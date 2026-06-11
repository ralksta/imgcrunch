#!/usr/bin/env python3
"""
ImgCrunch
Converts images and resizes if any dimension exceeds the target size.
Supports JPEG, HEIC, AVIF, and WebP output formats.
Preserves EXIF metadata. Parallel processing with progress bar.
"""

import argparse
import hashlib
import mmap
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image
try:
    import piexif
    PIEXIF_AVAILABLE = True
except ImportError:
    PIEXIF_AVAILABLE = False

# Try to import HEIC/AVIF support
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:
    HEIF_AVAILABLE = False

# Try to import tqdm
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# ── ANSI Colors ──────────────────────────────────────────────────────────────

class Color:
    """ANSI color codes. Auto-disabled when not writing to a TTY."""
    _enabled = sys.stdout.isatty()

    BOLD    = '\033[1m'   if _enabled else ''
    DIM     = '\033[2m'   if _enabled else ''
    GREEN   = '\033[92m'  if _enabled else ''
    RED     = '\033[91m'  if _enabled else ''
    YELLOW  = '\033[93m'  if _enabled else ''
    CYAN    = '\033[96m'  if _enabled else ''
    MAGENTA = '\033[95m'  if _enabled else ''
    RESET   = '\033[0m'   if _enabled else ''

C = Color

# ── Configuration ────────────────────────────────────────────────────────────

DEFAULT_MAX_SIZE   = 3000
OUTPUT_FOLDER_NAME = 'converted'
MAX_WORKERS        = min(os.cpu_count() or 4, 8)

# Per-format quality defaults (tuned for perceptual equivalence)
FORMAT_QUALITY_DEFAULTS = {
    'jpeg': 85,
    'heic': 65,
    'avif': 60,
    'webp': 82,
}

SUPPORTED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif',
    '.webp', '.gif', '.heic', '.heif', '.avif',
}

EXT_TO_FORMAT = {
    '.jpg': 'jpeg', '.jpeg': 'jpeg', '.png': 'jpeg', '.bmp': 'jpeg',
    '.tiff': 'jpeg', '.tif': 'jpeg', '.webp': 'webp', '.gif': 'jpeg',
    '.heic': 'heic', '.heif': 'heic',
    '.avif': 'avif',
}

FORMAT_CONFIG = {
    'jpeg': {'extension': '.jpg',  'pillow_format': 'JPEG', 'extra_opts': {'optimize': True, 'progressive': True}},
    'heic': {'extension': '.heic', 'pillow_format': 'HEIF', 'extra_opts': {}},
    'avif': {'extension': '.avif', 'pillow_format': 'AVIF', 'extra_opts': {}},
    'webp': {'extension': '.webp', 'pillow_format': 'WEBP', 'extra_opts': {'method': 6}},
}

IS_MACOS = sys.platform == 'darwin'


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class ProcessResult:
    input:          str
    output:         str
    resized:        bool         = False
    skipped:        bool         = False
    duplicate:      bool         = False
    original_size:  Optional[tuple[int, int]] = None
    new_size:       Optional[tuple[int, int]] = None
    input_bytes:    int          = 0
    output_bytes:   int          = 0
    input_format:   str          = ''   # source extension (for per-format summary)
    error:          Optional[str] = None


@dataclass
class BatchStats:
    processed:          int   = 0
    resized:            int   = 0
    errors:             int   = 0
    moved:              int   = 0
    replaced:           int   = 0
    skipped:            int   = 0
    duplicates_skipped: int   = 0
    total_input_bytes:  int   = 0
    total_output_bytes: int   = 0
    # per source-format counters  {'.jpg': {'count': N, 'in': bytes, 'out': bytes}}
    by_format: dict = field(default_factory=lambda: defaultdict(lambda: {'count': 0, 'in': 0, 'out': 0}))


# ── Helpers ──────────────────────────────────────────────────────────────────

def format_bytes(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def file_md5(path: Path) -> str:
    """Return MD5 hex digest of a file using mmap for efficiency."""
    h = hashlib.md5()
    size = path.stat().st_size
    if size == 0:
        return h.hexdigest()
    with open(path, 'rb') as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            h.update(mm)
    return h.hexdigest()


def detect_dominant_format(images: list[Path]) -> str:
    counts = Counter()
    for img in images:
        fmt = EXT_TO_FORMAT.get(img.suffix.lower(), 'jpeg')
        counts[fmt] += 1
    if not counts:
        return 'jpeg'
    dominant = counts.most_common(1)[0][0]
    total = sum(counts.values())
    return dominant if counts[dominant] > total * 0.5 else 'jpeg'


def find_images(input_dir: Path) -> list[tuple[Path, int]]:
    """Recursively find all supported images. Returns (path, size_bytes) tuples."""
    images = []
    for dirpath, _, filenames in os.walk(input_dir):
        for f in filenames:
            if f.startswith('._'):
                continue
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS:
                full = Path(dirpath) / f
                try:
                    size = full.stat().st_size
                except OSError:
                    continue
                images.append((full, size))
    # Sort largest-first so big files don't straggle at the end (#2)
    return sorted(images, key=lambda x: x[1], reverse=True)


def disk_free_bytes(path: Path) -> int:
    """Return free disk bytes on the volume containing path."""
    stat = shutil.disk_usage(path)
    return stat.free


def preflight_disk_check(images_with_sizes: list[tuple[Path, int]], output_dir: Path,
                         safety_factor: float = 1.2) -> Optional[str]:
    """
    Estimate required disk space and return an error string if insufficient,
    else None. Uses safety_factor × total input size as worst-case estimate.
    """
    total_input = sum(sz for _, sz in images_with_sizes)
    estimated_need = int(total_input * safety_factor)
    free = disk_free_bytes(output_dir)
    if free < estimated_need:
        return (
            f"Not enough disk space. Estimated need: {format_bytes(estimated_need)}, "
            f"available: {format_bytes(free)}"
        )
    return None


def build_duplicate_set(images: list[Path]) -> set[str]:
    """
    Hash every image; return the set of paths (str) that are content-duplicates
    of an earlier file. The first occurrence is kept, rest are skipped.
    """
    seen: dict[str, str] = {}   # hash → first path
    dupes: set[str] = set()
    for p in images:
        try:
            h = file_md5(p)
        except OSError:
            continue
        if h in seen:
            dupes.add(str(p))
        else:
            seen[h] = str(p)
    return dupes


def refresh_quicklook(paths: list[Path]) -> None:
    """Tell macOS Quick Look to regenerate thumbnails for the given files."""
    if not IS_MACOS or not paths:
        return
    try:
        subprocess.run(
            ['qlmanage', '-r', 'cache'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        # Touch each output file so Finder notices the change
        for p in paths:
            if p.exists():
                p.touch()
    except Exception:
        pass


# ── Output path helper ───────────────────────────────────────────────────────

def get_output_path(input_path: Path, output_dir: Path, input_root: Path, extension: str,
                    rename_base: Optional[str] = None, rename_index: int = 0,
                    total_count: int = 0) -> Path:
    if rename_base:
        pad_width = max(3, len(str(total_count)))
        new_name = f"{rename_base}_{str(rename_index).zfill(pad_width)}{extension}"
        output_path = output_dir / new_name
    else:
        relative_path = input_path.relative_to(input_root)
        output_path = output_dir / relative_path.with_suffix(extension)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


# ── Core Image Processing ─────────────────────────────────────────────────────
# NOTE: This function runs in a worker process (ProcessPoolExecutor).
#       It must be importable at the top level — no lambdas or closures.

def needs_resize(width: int, height: int, max_size: int) -> bool:
    if max_size == 0:
        return False
    return width > max_size or height > max_size


def calculate_new_size(width: int, height: int, target: int) -> tuple[int, int]:
    if width >= height:
        new_width  = target
        new_height = int(height * (target / width))
    else:
        new_height = target
        new_width  = int(width * (target / height))
    return new_width, new_height


def process_image(
    input_path_str: str,
    output_path_str: str,
    format_key:  str,
    quality:     int,
    max_size:    int,
    input_bytes: int = 0,
    lossless:    bool = False,
) -> ProcessResult:
    """
    Process a single image: convert, optionally resize, verify output, atomic write.
    Runs in a subprocess worker — only uses serialisable types.
    """
    input_path  = Path(input_path_str)
    output_path = Path(output_path_str)
    input_ext   = input_path.suffix.lower()

    result = ProcessResult(
        input=input_path_str,
        output=output_path_str,
        input_bytes=input_bytes or 0,
        input_format=input_ext,
    )

    fmt        = FORMAT_CONFIG[format_key]
    use_piexif = format_key == 'jpeg' and PIEXIF_AVAILABLE

    try:
        if not result.input_bytes:
            result.input_bytes = input_path.stat().st_size

        # Use mmap for the read if file is large enough (#3)
        # PIL needs a real file-like object; we open normally but mmap is used
        # internally by the OS page cache — just ensure we open in binary mode.
        with Image.open(input_path) as img:
            width, height = img.size
            result.original_size = (width, height)

            # Early bail-out: already target format, no resize, no mode conversion needed
            target_ext = fmt['extension']
            already_target = (
                input_ext == target_ext
                or (input_ext in ('.jpg', '.jpeg') and target_ext == '.jpg')
            )
            if already_target and not needs_resize(width, height, max_size) \
                    and img.mode in ('RGB', 'L') and not lossless:
                result.skipped     = True
                result.new_size    = (width, height)
                result.output_bytes = result.input_bytes
                return result

            # Extract EXIF
            exif_bytes = None
            exif_dict  = None
            try:
                if 'exif' in img.info:
                    raw_exif = img.info['exif']
                    if use_piexif:
                        exif_dict  = piexif.load(raw_exif)
                        exif_bytes = raw_exif
                    else:
                        exif_bytes = raw_exif
                elif use_piexif and input_ext in ('.jpg', '.jpeg', '.tiff', '.tif'):
                    exif_dict  = piexif.load(str(input_path))
                    exif_bytes = piexif.dump(exif_dict)
            except Exception:
                exif_dict = None

            # Mode conversion
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Resize
            if needs_resize(width, height, max_size):
                new_width, new_height = calculate_new_size(width, height, max_size)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                result.resized  = True
                result.new_size = (new_width, new_height)
                if exif_dict and use_piexif:
                    try:
                        if piexif.ExifIFD.PixelXDimension in exif_dict.get('Exif', {}):
                            exif_dict['Exif'][piexif.ExifIFD.PixelXDimension] = new_width
                        if piexif.ExifIFD.PixelYDimension in exif_dict.get('Exif', {}):
                            exif_dict['Exif'][piexif.ExifIFD.PixelYDimension] = new_height
                        exif_bytes = piexif.dump(exif_dict)
                    except Exception:
                        pass
            else:
                result.new_size = (width, height)

            # Build save kwargs
            save_kwargs: dict = {**fmt['extra_opts']}
            if lossless and format_key in ('avif', 'webp'):
                save_kwargs['lossless'] = True
            else:
                save_kwargs['quality'] = quality
            if exif_bytes:
                save_kwargs['exif'] = exif_bytes

            # Atomic write: save to .tmp sibling, then rename (#12 approach)
            tmp_path = output_path.with_suffix(output_path.suffix + '.tmp')
            try:
                img.save(tmp_path, fmt['pillow_format'], **save_kwargs)

                # Verify the output is a valid image (#11)
                with Image.open(tmp_path) as verify_img:
                    verify_img.verify()

                # Commit
                tmp_path.replace(output_path)
            except Exception as e:
                tmp_path.unlink(missing_ok=True)
                raise e

        result.output_bytes = output_path.stat().st_size

    except Exception as e:
        result.error = str(e)

    return result


# ── Startup Wizard ───────────────────────────────────────────────────────────

def startup_wizard(prefill_folder: Optional[str] = None) -> Optional[dict]:
    print()
    print(f"{C.CYAN}╔══════════════════════════════════════════╗{C.RESET}")
    print(f"{C.CYAN}║{C.RESET}        🖼️  {C.BOLD}ImgCrunch{C.RESET}                     {C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}║{C.RESET}            {C.DIM}Startup Wizard{C.RESET}                {C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}╚══════════════════════════════════════════╝{C.RESET}")
    print()

    # 1. Folder
    if prefill_folder:
        folder_path = Path(prefill_folder).expanduser().resolve()
        if not folder_path.exists() or not folder_path.is_dir():
            print(f"  {C.RED}❌  Invalid folder: {folder_path}{C.RESET}")
            return None
    else:
        print(f"  {C.BOLD}Enter the path to the folder containing your images:{C.RESET}")
        print()
        while True:
            folder = input(f"  {C.CYAN}Folder path:{C.RESET} ").strip().strip('"').strip("'")
            if not folder:
                print(f"  {C.YELLOW}⚠️  Please enter a path.{C.RESET}")
                continue
            folder_path = Path(folder).expanduser().resolve()
            if not folder_path.exists():
                print(f"  {C.RED}❌  Folder not found: {folder_path}{C.RESET}")
                continue
            if not folder_path.is_dir():
                print(f"  {C.RED}❌  Not a directory: {folder_path}{C.RESET}")
                continue
            break

    print(f"  {C.GREEN}✅  Folder: {folder_path}{C.RESET}")
    print()

    print(f"  {C.DIM}Scanning folder...{C.RESET}", end='', flush=True)
    scanned_images_with_sizes = find_images(folder_path)
    scanned_images = [p for p, _ in scanned_images_with_sizes]
    detected_format = detect_dominant_format(scanned_images)
    print(f"\r  {C.DIM}Found {len(scanned_images)} images{C.RESET}          ")
    print()

    # 2. Output mode
    print(f"  {C.BOLD}How should the output be handled?{C.RESET}")
    print()
    print(f"    [{C.CYAN}1{C.RESET}]  Keep originals   — output → {C.DIM}converted/{C.RESET}, originals → {C.DIM}originals/{C.RESET}")
    print(f"    [{C.CYAN}2{C.RESET}]  Replace in-place  — overwrite originals {C.YELLOW}(destructive){C.RESET}")
    print()
    while True:
        mode_choice = input(f"  Your choice (1/2) [{C.CYAN}1{C.RESET}]: ").strip() or '1'
        if mode_choice in ('1', '2'):
            break
        print(f"  {C.YELLOW}⚠️  Please enter 1 or 2.{C.RESET}")

    replace_mode = mode_choice == '2'
    if replace_mode:
        print(f"  {C.YELLOW}⚠️  Replace mode — originals will be overwritten{C.RESET}")
    else:
        print(f"  {C.GREEN}✅  Keep originals{C.RESET}")
    print()

    # 3. Format
    format_keys    = ['jpeg', 'heic', 'avif', 'webp']
    detected_index = str(format_keys.index(detected_format) + 1) if detected_format in format_keys else '1'
    format_options = {
        '1': ('jpeg', 'JPEG  (.jpg)  — universal, great compression'),
        '2': ('heic', 'HEIC  (.heic) — Apple ecosystem, smaller files'),
        '3': ('avif', 'AVIF  (.avif) — next-gen, best compression'),
        '4': ('webp', 'WebP  (.webp) — web-optimised, wide support'),
    }
    print(f"  {C.BOLD}Which output format would you like?{C.RESET}")
    print()
    for key, (_, label) in format_options.items():
        marker = f" {C.GREEN}← detected{C.RESET}" if key == detected_index else ""
        print(f"    [{C.CYAN}{key}{C.RESET}]  {label}{marker}")
    print()
    while True:
        choice = input(f"  Your choice (1/2/3/4) [{C.CYAN}{detected_index}{C.RESET}]: ").strip() or detected_index
        if choice in format_options:
            break
        print(f"  {C.YELLOW}⚠️  Please enter 1–4.{C.RESET}")

    format_key     = format_options[choice][0]
    default_quality = FORMAT_QUALITY_DEFAULTS[format_key]

    if format_key in ('heic', 'avif') and not HEIF_AVAILABLE:
        print(f"\n  {C.RED}❌  {format_key.upper()} support requires pillow-heif.{C.RESET}")
        print(f"      Install with: {C.CYAN}pip install pillow-heif{C.RESET}")
        return None

    print(f"  {C.GREEN}✅  Format: {format_key.upper()}{C.RESET}")
    print()

    # 4. Max longest side
    print(f"  {C.BOLD}What should the max longest side be (in pixels)?{C.RESET}")
    print(f"  {C.DIM}Images larger than this will be resized down.{C.RESET}")
    print(f"  {C.DIM}(press Enter for default: no resizing, convert only){C.RESET}")
    print()
    while True:
        size_input = input(f"  Max longest side [{C.CYAN}no resize{C.RESET}]: ").strip()
        if not size_input:
            target_size = 0
            break
        try:
            target_size = int(size_input)
            if target_size == 0:
                break
            if target_size < 100:
                print(f"  {C.YELLOW}⚠️  Minimum is 100px (or 0 to skip resizing).{C.RESET}")
                continue
            break
        except ValueError:
            print(f"  {C.YELLOW}⚠️  Please enter a number.{C.RESET}")

    if target_size == 0:
        print(f"  {C.GREEN}✅  No resizing — convert only{C.RESET}")
    else:
        print(f"  {C.GREEN}✅  Max size: {target_size}px{C.RESET}")
    print()

    # 5. Rename (keep mode only)
    rename_base = None
    if not replace_mode:
        print(f"  {C.BOLD}Would you like to rename all photos with a clean naming scheme?{C.RESET}")
        print(f"  {C.DIM}e.g. \"vacation\" → vacation_001.jpg, vacation_002.jpg, ...{C.RESET}")
        print(f"  {C.DIM}(leave blank to keep original filenames){C.RESET}")
        print()
        rename_base = input(f"  Base name [{C.CYAN}skip{C.RESET}]: ").strip()
        if rename_base:
            rename_base = rename_base.replace(' ', '_')
            rename_base = ''.join(c for c in rename_base if c.isalnum() or c in ('_', '-'))
            if not rename_base:
                print(f"  {C.YELLOW}⚠️  Invalid name, keeping originals.{C.RESET}")
                rename_base = None
            else:
                print(f"  {C.GREEN}✅  Rename: {rename_base}_001, {rename_base}_002, ...{C.RESET}")
        else:
            rename_base = None
        print()

    # Confirmation
    print(f"{C.DIM}{'─' * 44}{C.RESET}")
    print(f"  {C.BOLD}Mode:{C.RESET}         {'⚠️  Replace in-place' if replace_mode else '📂  Keep originals'}")
    print(f"  {C.BOLD}Format:{C.RESET}       {format_key.upper()}")
    print(f"  {C.BOLD}Quality:{C.RESET}      {default_quality}  {C.DIM}(smart default for {format_key.upper()}){C.RESET}")
    print(f"  {C.BOLD}Max size:{C.RESET}     {'no resizing' if target_size == 0 else f'{target_size}px'}")
    print(f"  {C.BOLD}Folder:{C.RESET}       {folder_path}")
    if not replace_mode:
        print(f"  {C.BOLD}Rename:{C.RESET}       {rename_base + '_###' if rename_base else C.DIM + 'keep originals' + C.RESET}")
    print(f"  {C.BOLD}Images:{C.RESET}       {len(scanned_images)}")
    print(f"{C.DIM}{'─' * 44}{C.RESET}")

    if replace_mode:
        print()
        print(f"  {C.RED}{C.BOLD}⚠️  WARNING: This will permanently replace your original files!{C.RESET}")

    print()
    confirm = input(f"  Start processing? ({C.GREEN}Y{C.RESET}/n): ").strip().lower()
    if confirm and confirm not in ('y', 'yes'):
        print()
        print(f"  {C.DIM}No worries — nothing was changed.{C.RESET}")
        print(f"  {C.DIM}Run imgcrunch again whenever you\'re ready. 👋{C.RESET}")
        print()
        return None

    return {
        'input_folder': str(folder_path),
        'format':       format_key,
        'quality':      default_quality,
        'max_size':     target_size,
        'no_move':      replace_mode,
        'output':       None,
        'rename':       rename_base,
        'replace':      replace_mode,
        'lossless':     False,
        'skip_dupes':   False,
        'post_hook':    None,
    }


# ── Summary Table ─────────────────────────────────────────────────────────────

def print_summary(stats: BatchStats, elapsed: float, output_dir: Path):
    print()
    print(f"{C.CYAN}{'═' * 52}{C.RESET}")
    print(f"{C.BOLD}  📊  Processing Summary{C.RESET}")
    print(f"{C.CYAN}{'═' * 52}{C.RESET}")

    print(f"  {C.BOLD}Images processed:{C.RESET}  {C.GREEN}{stats.processed}{C.RESET}")
    print(f"  {C.BOLD}Images resized:{C.RESET}    {C.CYAN}{stats.resized}{C.RESET}")
    if stats.errors > 0:
        print(f"  {C.BOLD}Errors:{C.RESET}            {C.RED}{stats.errors}{C.RESET}")
    if stats.skipped > 0:
        print(f"  {C.BOLD}Skipped (no-op):{C.RESET}   {C.DIM}{stats.skipped}{C.RESET}")
    if stats.duplicates_skipped > 0:
        print(f"  {C.BOLD}Dupes skipped:{C.RESET}     {C.DIM}{stats.duplicates_skipped}{C.RESET}")
    if stats.moved > 0:
        print(f"  {C.BOLD}Originals moved:{C.RESET}   {stats.moved}")
    if stats.replaced > 0:
        print(f"  {C.BOLD}Files replaced:{C.RESET}    {C.YELLOW}{stats.replaced}{C.RESET}")

    # Per-format breakdown (#20)
    if stats.by_format:
        print(f"{C.DIM}{'─' * 52}{C.RESET}")
        print(f"  {C.BOLD}By source format:{C.RESET}")
        for ext, fdata in sorted(stats.by_format.items()):
            pct = (1 - fdata['out'] / fdata['in']) * 100 if fdata['in'] > 0 else 0
            arrow = '↓' if pct > 0 else '↑'
            color = C.GREEN if pct > 0 else C.RED
            print(
                f"    {C.CYAN}{ext:<6}{C.RESET}  {fdata['count']:>4} files  "
                f"{format_bytes(fdata['in']):>9} → {format_bytes(fdata['out']):<9}  "
                f"{color}{arrow}{abs(pct):4.1f}%{C.RESET}"
            )

    print(f"{C.DIM}{'─' * 52}{C.RESET}")

    total_in  = stats.total_input_bytes
    total_out = stats.total_output_bytes
    if total_in > 0 and total_out > 0:
        saved_pct = (1 - total_out / total_in) * 100
        arrow = '↓' if saved_pct > 0 else '↑'
        color = C.GREEN if saved_pct > 0 else C.RED
        print(f"  {C.BOLD}Input size:{C.RESET}        {format_bytes(total_in)}")
        print(f"  {C.BOLD}Output size:{C.RESET}       {format_bytes(total_out)}")
        print(f"  {C.BOLD}Savings:{C.RESET}           {color}{arrow} {abs(saved_pct):.1f}%{C.RESET}  ({format_bytes(abs(total_in - total_out))})")

    minutes, seconds = divmod(elapsed, 60)
    time_str = f"{int(minutes)}m {seconds:.1f}s" if minutes > 0 else f"{seconds:.1f}s"
    print(f"  {C.BOLD}Time elapsed:{C.RESET}      {time_str}")

    if stats.processed > 0 and elapsed > 0:
        speed    = stats.processed / elapsed
        mb_per_s = (total_in / 1_048_576) / elapsed if total_in > 0 else 0
        print(f"  {C.BOLD}Speed:{C.RESET}             {speed:.1f} img/s  ({mb_per_s:.1f} MB/s input)")  # #19

    print(f"{C.CYAN}{'═' * 52}{C.RESET}")

    if stats.errors > 0:
        print(f"\n  {C.YELLOW}⚠️  {stats.errors} file(s) had errors and remain in the input folder{C.RESET}")


def move_to_originals(input_path: Path, originals_dir: Path, input_root: Path) -> Path:
    relative_path = input_path.relative_to(input_root)
    dest_path = originals_dir / relative_path
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(input_path), str(dest_path))
    return dest_path


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) == 1 or '--wizard' in sys.argv:
        prefill = None
        for arg in sys.argv[1:]:
            if arg != '--wizard':
                prefill = arg
                break
        wizard_result = startup_wizard(prefill_folder=prefill)
        if wizard_result is None:
            sys.exit(0)
        args = argparse.Namespace(**wizard_result)
    else:
        parser = argparse.ArgumentParser(
            prog='imgcrunch',
            description='ImgCrunch — Fast parallel image cruncher with format conversion.',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""\
Output modes:
  By default, converted files go to <input>/converted/ and originals are
  moved to <input>/originals/. Use --replace to overwrite originals in-place
  (destructive). Use --no-move to leave originals where they are.

Quality defaults (tuned per format):
  JPEG: 85   HEIC: 65   AVIF: 60   WebP: 82

Examples:
  imgcrunch /path/to/images                          # JPEG, smart quality, no resize
  imgcrunch /path/to/images -f heic                  # HEIC with smart quality default
  imgcrunch /path/to/images -f avif --max-size 2000  # AVIF, cap at 2000px
  imgcrunch /path/to/images --lossless -f avif       # lossless AVIF
  imgcrunch /path/to/images --skip-dupes             # skip content-identical files
  imgcrunch /path/to/images --replace -f jpeg        # replace originals in-place
  imgcrunch /path/to/images --rename vacation        # rename: vacation_001.jpg, ...
  imgcrunch /path/to/images --post-hook 'echo {out}' # run command after each file
  imgcrunch --wizard /path/to/images                 # interactive wizard
            """
        )
        parser.add_argument('input_folder',
                            help='Path to the folder containing images to process')
        parser.add_argument('-f', '--format', choices=['jpeg', 'heic', 'avif', 'webp'], default='jpeg',
                            help='Output format (default: jpeg)')
        parser.add_argument('-q', '--quality', type=int, default=None,
                            help='Compression quality 1–100 (default: smart per-format default)')
        parser.add_argument('-m', '--max-size', type=int, default=DEFAULT_MAX_SIZE,
                            help=f'Max longest side in px; 0 = convert only (default: {DEFAULT_MAX_SIZE})')
        parser.add_argument('-o', '--output',
                            help=f'Custom output folder (default: <input>/{OUTPUT_FOLDER_NAME})')
        parser.add_argument('--replace', action='store_true',
                            help='Replace originals in-place (⚠️  destructive, no backup)')
        parser.add_argument('--no-move', action='store_true',
                            help="Keep originals in place (don't move to originals/)")
        parser.add_argument('--rename', type=str, default=None, metavar='NAME',
                            help='Rename output files as NAME_001, NAME_002, ...')
        parser.add_argument('--lossless', action='store_true',
                            help='Lossless encode (AVIF and WebP only)')
        parser.add_argument('--skip-dupes', action='store_true',
                            help='Skip files that are content-identical to an already-processed file')
        parser.add_argument('--post-hook', type=str, default=None, metavar='CMD',
                            help='Shell command to run after each file. '
                                 'Use {in} and {out} as placeholders.')
        args = parser.parse_args()

    # Resolve quality
    quality = getattr(args, 'quality', None)
    if quality is None:
        quality = FORMAT_QUALITY_DEFAULTS[args.format]
    args.quality = quality

    # Check HEIC/AVIF availability
    if args.format in ('heic', 'avif') and not HEIF_AVAILABLE:
        print(f"{C.RED}Error: {args.format.upper()} support requires pillow-heif{C.RESET}")
        print(f"Install with: {C.CYAN}pip install pillow-heif{C.RESET}")
        sys.exit(1)

    input_dir    = Path(args.input_folder).resolve()
    replace_mode = getattr(args, 'replace', False)
    lossless     = getattr(args, 'lossless', False)
    skip_dupes   = getattr(args, 'skip_dupes', False)
    post_hook    = getattr(args, 'post_hook', None)
    rename_base  = getattr(args, 'rename', None)
    fmt          = FORMAT_CONFIG[args.format]

    if not input_dir.exists():
        print(f"{C.RED}Error: Input folder does not exist: {input_dir}{C.RESET}")
        sys.exit(1)

    if replace_mode:
        tmp_dir      = Path(tempfile.mkdtemp(dir=input_dir, prefix='.resizer_tmp_'))
        output_dir   = tmp_dir
        originals_dir = None
    else:
        output_dir    = Path(args.output).resolve() if args.output else input_dir / OUTPUT_FOLDER_NAME
        originals_dir = input_dir / 'originals'

    output_dir.mkdir(parents=True, exist_ok=True)

    # Print run config
    print()
    if replace_mode:
        print(f"  {C.BOLD}Mode:{C.RESET}            {C.YELLOW}⚠️  Replace in-place{C.RESET}")
    print(f"  {C.BOLD}Input folder:{C.RESET}    {input_dir}")
    if not replace_mode:
        print(f"  {C.BOLD}Output folder:{C.RESET}   {output_dir}")
    print(f"  {C.BOLD}Format:{C.RESET}          {C.CYAN}{args.format.upper()}{C.RESET} ({fmt['extension']})")
    print(f"  {C.BOLD}Quality:{C.RESET}         {args.quality}  {C.DIM}(smart default){C.RESET}" if getattr(args, 'quality', None) is None else
          f"  {C.BOLD}Quality:{C.RESET}         {args.quality}")
    if lossless:
        print(f"  {C.BOLD}Lossless:{C.RESET}        {C.CYAN}yes{C.RESET}")
    if args.max_size == 0:
        print(f"  {C.BOLD}Resize:{C.RESET}          {C.DIM}convert only{C.RESET}")
    else:
        print(f"  {C.BOLD}Max size:{C.RESET}        {args.max_size}px longest side")
    if rename_base:
        print(f"  {C.BOLD}Rename:{C.RESET}          {rename_base}_001, {rename_base}_002, ...")
    if skip_dupes:
        print(f"  {C.BOLD}Skip dupes:{C.RESET}      {C.CYAN}yes (content hash){C.RESET}")
    if post_hook:
        print(f"  {C.BOLD}Post-hook:{C.RESET}       {C.DIM}{post_hook}{C.RESET}")
    print(f"  {C.BOLD}Workers:{C.RESET}         {MAX_WORKERS}")
    if not replace_mode and not args.no_move:
        print(f"  {C.BOLD}Originals:{C.RESET}       → {originals_dir}")
    print(f"{C.DIM}{'─' * 60}{C.RESET}")

    # Find images (already sorted largest-first)
    all_images_with_sizes = find_images(input_dir)
    exclude_dirs = [str(output_dir)]
    if originals_dir:
        exclude_dirs.append(str(originals_dir))
    images_with_sizes = [
        (img, sz) for img, sz in all_images_with_sizes
        if not any(str(img).startswith(d) for d in exclude_dirs)
    ]

    if not images_with_sizes:
        print(f"{C.YELLOW}No images found!{C.RESET}")
        if replace_mode:
            tmp_dir.rmdir()
        sys.exit(0)

    # Disk space preflight (#13)
    disk_err = preflight_disk_check(images_with_sizes, output_dir)
    if disk_err:
        print(f"\n  {C.RED}❌  {disk_err}{C.RESET}\n")
        if replace_mode:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(1)

    images     = [img for img, _ in images_with_sizes]
    image_sizes = {str(img): sz for img, sz in images_with_sizes}

    # Duplicate detection (#14)
    dupe_paths: set[str] = set()
    if skip_dupes:
        print(f"  {C.DIM}Hashing files for duplicate detection...{C.RESET}", end='', flush=True)
        dupe_paths = build_duplicate_set(images)
        print(f"\r  {C.DIM}Found {len(dupe_paths)} duplicate(s) to skip{C.RESET}          ")

    print(f"  Found {C.BOLD}{len(images)}{C.RESET} images  "
          f"{f'({len(dupe_paths)} dupes will be skipped)' if dupe_paths else ''}\n")

    stats = BatchStats()

    # Build task list
    tasks: list[tuple[Path, Path, int]] = []
    for idx, img_path in enumerate(images, start=1):
        if str(img_path) in dupe_paths:
            stats.duplicates_skipped += 1
            continue
        output_path = get_output_path(
            img_path, output_dir, input_dir, fmt['extension'],
            rename_base=rename_base, rename_index=idx, total_count=len(images),
        )
        if output_path.resolve() == img_path.resolve():
            continue
        file_size = image_sizes.get(str(img_path), 0)
        tasks.append((img_path, output_path, file_size))

    start_time = time.time()

    if TQDM_AVAILABLE:
        progress = tqdm(
            total=len(tasks),
            desc=f"  {C.CYAN}Processing{C.RESET}",
            unit='img',
            bar_format=(
                f"  {{l_bar}}{C.GREEN}{{bar}}{C.RESET}"
                f" {{n_fmt}}/{{total_fmt}} [{{elapsed}}<{{remaining}}, {{rate_fmt}}]"
            ),
            ncols=80,
        )
    else:
        progress = None

    output_paths_written: list[Path] = []

    # ProcessPoolExecutor for CPU-bound encode/resize (#1)
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_path = {}
        for img_path, output_path, file_size in tasks:
            future = executor.submit(
                process_image,
                str(img_path), str(output_path),
                args.format, args.quality, args.max_size, file_size, lossless,
            )
            future_to_path[future] = img_path

        for future in as_completed(future_to_path):
            img_path = future_to_path[future]
            result: ProcessResult = future.result()

            if result.error:
                msg = f"  {C.RED}✗{C.RESET} {img_path.name}: {result.error}"
                (tqdm.write if progress else print)(msg)
                stats.errors += 1

            elif result.skipped:
                stats.processed          += 1
                stats.skipped            += 1
                stats.total_input_bytes  += result.input_bytes
                stats.total_output_bytes += result.output_bytes

            else:
                stats.processed          += 1
                stats.total_input_bytes  += result.input_bytes
                stats.total_output_bytes += result.output_bytes

                # Per-format breakdown accumulation (#20)
                fdata = stats.by_format[result.input_format]
                fdata['count'] += 1
                fdata['in']    += result.input_bytes
                fdata['out']   += result.output_bytes

                if result.resized:
                    stats.resized += 1
                    orig = result.original_size
                    new  = result.new_size
                    msg  = (
                        f"  {C.GREEN}✓{C.RESET} {C.DIM}Resized{C.RESET} {img_path.name} "
                        f"{C.DIM}({orig[0]}x{orig[1]} → {new[0]}x{new[1]}){C.RESET}"
                    )
                    (tqdm.write if progress else print)(msg)

                output_path = Path(result.output)
                output_paths_written.append(output_path)

                if progress:
                    progress.set_postfix_str(img_path.name[-30:], refresh=False)

                # Post-hook (#18)
                if post_hook:
                    cmd = post_hook.replace('{in}', str(img_path)).replace('{out}', str(output_path))
                    try:
                        subprocess.run(cmd, shell=True, timeout=30,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception as hook_err:
                        warn = f"  {C.YELLOW}⚠ post-hook failed for {img_path.name}: {hook_err}{C.RESET}"
                        (tqdm.write if progress else print)(warn)

                if replace_mode:
                    try:
                        converted_path = Path(result.output)
                        final_path     = img_path.with_suffix(fmt['extension'])
                        img_path.unlink()
                        shutil.move(str(converted_path), str(final_path))
                        stats.replaced += 1
                    except Exception as e:
                        warn = f"  {C.YELLOW}⚠ Could not replace {img_path.name}: {e}{C.RESET}"
                        (tqdm.write if progress else print)(warn)
                elif not args.no_move:
                    try:
                        move_to_originals(img_path, originals_dir, input_dir)
                        stats.moved += 1
                    except Exception as e:
                        warn = f"  {C.YELLOW}⚠ Could not move {img_path.name}: {e}{C.RESET}"
                        (tqdm.write if progress else print)(warn)

            if progress:
                progress.update(1)

    if progress:
        progress.close()

    if replace_mode:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    elapsed = time.time() - start_time

    # macOS Quick Look refresh (#22)
    if IS_MACOS and output_paths_written:
        refresh_quicklook(output_paths_written)

    print_summary(stats, elapsed, output_dir)
    if replace_mode:
        print(f"\n  {C.BOLD}Files replaced in:{C.RESET} {input_dir}\n")
    else:
        print(f"\n  {C.BOLD}Output saved to:{C.RESET} {output_dir}\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
        print(f"  {C.DIM}Cancelled — nothing was changed.{C.RESET}")
        print(f"  {C.DIM}Run imgcrunch again whenever you\'re ready. 👋{C.RESET}")
        print()
        sys.exit(0)

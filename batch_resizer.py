#!/usr/bin/env python3
"""
ImgCrunch
Converts images and resizes if any dimension exceeds the target size.
Supports JPEG, HEIC, and AVIF output formats.
Preserves EXIF metadata. Parallel processing with progress bar.
"""

import argparse
import os
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PIL import Image
import piexif

# Try to import HEIC/AVIF support
try:
    import pillow_heif
    pillow_heif.register_heif_opener()  # Handles both HEIC and AVIF
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

DEFAULT_MAX_SIZE = 3000         # Default max longest side in pixels
DEFAULT_QUALITY = 85            # Quality setting (works for all formats)
OUTPUT_FOLDER_NAME = 'converted'
MAX_WORKERS = min(os.cpu_count() or 4, 8)
SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp', '.gif', '.heic', '.heif', '.avif'}

# Extension → format key mapping for auto-detection
EXT_TO_FORMAT = {
    '.jpg': 'jpeg', '.jpeg': 'jpeg', '.png': 'jpeg', '.bmp': 'jpeg',
    '.tiff': 'jpeg', '.tif': 'jpeg', '.webp': 'jpeg', '.gif': 'jpeg',
    '.heic': 'heic', '.heif': 'heic',
    '.avif': 'avif',
}

# Format configurations
FORMAT_CONFIG = {
    'jpeg': {'extension': '.jpg', 'pillow_format': 'JPEG', 'extra_opts': {'optimize': True, 'progressive': True}},
    'heic': {'extension': '.heic', 'pillow_format': 'HEIF', 'extra_opts': {}},
    'avif': {'extension': '.avif', 'pillow_format': 'AVIF', 'extra_opts': {}},
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def format_bytes(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def detect_dominant_format(images: list[Path]) -> str:
    """Detect the most common input format and return the matching output format key."""
    counts = Counter()
    for img in images:
        ext = img.suffix.lower()
        fmt = EXT_TO_FORMAT.get(ext, 'jpeg')
        counts[fmt] += 1

    if not counts:
        return 'jpeg'

    dominant = counts.most_common(1)[0][0]
    # Only suggest non-jpeg if it's a clear majority (>50%)
    total = sum(counts.values())
    if counts[dominant] > total * 0.5:
        return dominant
    return 'jpeg'


def find_images(input_dir: Path) -> list[Path]:
    """Recursively find all supported image files."""
    images = []
    for ext in SUPPORTED_EXTENSIONS:
        images.extend(input_dir.rglob(f'*{ext}'))
        images.extend(input_dir.rglob(f'*{ext.upper()}'))
    return sorted(set(images))


# ── Startup Wizard ───────────────────────────────────────────────────────────

def startup_wizard(prefill_folder: str | None = None) -> dict | None:
    """Interactive startup wizard. If prefill_folder is given, skip the folder prompt."""
    print()
    print(f"{C.CYAN}╔══════════════════════════════════════════╗{C.RESET}")
    print(f"{C.CYAN}║{C.RESET}        🖼️  {C.BOLD}ImgCrunch{C.RESET}                     {C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}║{C.RESET}            {C.DIM}Startup Wizard{C.RESET}                {C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}╚══════════════════════════════════════════╝{C.RESET}")
    print()

    # --- 1. Folder path (skip if pre-filled, e.g. from Quick Action) ---
    if prefill_folder:
        folder_path = Path(prefill_folder).expanduser().resolve()
        if not folder_path.exists() or not folder_path.is_dir():
            print(f"  {C.RED}❌  Invalid folder: {folder_path}{C.RESET}")
            return None
    else:
        print(f"  {C.BOLD}Enter the path to the folder containing your images:{C.RESET}")
        print()

        while True:
            folder = input(f"  {C.CYAN}Folder path:{C.RESET} ").strip()
            folder = folder.strip('"').strip("'")
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

    # Scan folder to auto-detect format
    print(f"  {C.DIM}Scanning folder...{C.RESET}", end='', flush=True)
    scanned_images = find_images(folder_path)
    detected_format = detect_dominant_format(scanned_images)
    print(f"\r  {C.DIM}Found {len(scanned_images)} images{C.RESET}          ")
    print()

    # --- 2. Output mode ---
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

    # --- 3. Output format ---
    format_keys = ['jpeg', 'heic', 'avif']
    detected_index = str(format_keys.index(detected_format) + 1)

    format_options = {
        '1': ('jpeg', f'JPEG  (.jpg) — universal, great compression'),
        '2': ('heic', f'HEIC  (.heic) — Apple ecosystem, smaller files'),
        '3': ('avif', f'AVIF  (.avif) — next-gen, best compression'),
    }
    print(f"  {C.BOLD}Which output format would you like?{C.RESET}")
    print()
    for key, (_, label) in format_options.items():
        marker = f" {C.GREEN}← detected{C.RESET}" if key == detected_index else ""
        print(f"    [{C.CYAN}{key}{C.RESET}]  {label}{marker}")
    print()

    while True:
        choice = input(f"  Your choice (1/2/3) [{C.CYAN}{detected_index}{C.RESET}]: ").strip() or detected_index
        if choice in format_options:
            break
        print(f"  {C.YELLOW}⚠️  Please enter 1, 2, or 3.{C.RESET}")

    format_key = format_options[choice][0]

    if format_key in ('heic', 'avif') and not HEIF_AVAILABLE:
        print(f"\n  {C.RED}❌  {format_key.upper()} support requires pillow-heif.{C.RESET}")
        print(f"      Install with: {C.CYAN}pip install pillow-heif{C.RESET}")
        return None

    print(f"  {C.GREEN}✅  Format: {format_key.upper()}{C.RESET}")
    print()

    # --- 4. Max longest side ---
    print(f"  {C.BOLD}What should the max longest side be (in pixels)?{C.RESET}")
    print(f"  {C.DIM}Images larger than this will be resized down.{C.RESET}")
    print(f"  {C.DIM}Enter 0 to skip resizing (convert only).{C.RESET}")
    print(f"  {C.DIM}(press Enter for default: {DEFAULT_MAX_SIZE}px){C.RESET}")
    print()

    while True:
        size_input = input(f"  Max longest side [{C.CYAN}{DEFAULT_MAX_SIZE}{C.RESET}]: ").strip()
        if not size_input:
            target_size = DEFAULT_MAX_SIZE
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

    # --- 5. Rename option (only in keep mode) ---
    rename_base = None
    if not replace_mode:
        print(f"  {C.BOLD}Would you like to rename all photos with a clean naming scheme?{C.RESET}")
        print(f"  {C.DIM}e.g. \"vacation\" → vacation_001.jpg, vacation_002.jpg, ...{C.RESET}")
        print(f"  {C.DIM}(leave blank to keep original filenames){C.RESET}")
        print()

        rename_base = input(f"  Base name [{C.CYAN}skip{C.RESET}]: ").strip()
        if rename_base:
            # Sanitize: keep only alphanumeric, dashes, underscores, spaces→underscores
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

    # --- Confirmation ---
    print(f"{C.DIM}{'─' * 44}{C.RESET}")
    print(f"  {C.BOLD}Mode:{C.RESET}         {'⚠️  Replace in-place' if replace_mode else '📂  Keep originals'}")
    print(f"  {C.BOLD}Format:{C.RESET}       {format_key.upper()}")
    print(f"  {C.BOLD}Max size:{C.RESET}     {'no resizing' if target_size == 0 else f'{target_size}px'}")
    print(f"  {C.BOLD}Folder:{C.RESET}       {folder_path}")
    print(f"  {C.BOLD}Quality:{C.RESET}      {DEFAULT_QUALITY}")
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
        print(f"\n  {C.YELLOW}Aborted.{C.RESET}")
        return None

    return {
        'input_folder': str(folder_path),
        'format': format_key,
        'quality': DEFAULT_QUALITY,
        'max_size': target_size,
        'no_move': replace_mode,
        'output': None,
        'rename': rename_base,
        'replace': replace_mode,
    }


# ── Core Image Processing ───────────────────────────────────────────────────

def get_output_path(input_path: Path, output_dir: Path, input_root: Path, extension: str,
                    rename_base: str | None = None, rename_index: int = 0,
                    total_count: int = 0) -> Path:
    """Generate output path preserving subfolder structure, with optional rename."""
    if rename_base:
        # Determine zero-padding width from total count (minimum 3 digits)
        pad_width = max(3, len(str(total_count)))
        new_name = f"{rename_base}_{str(rename_index).zfill(pad_width)}{extension}"
        # Flatten into output_dir (no subfolder nesting when renaming)
        output_path = output_dir / new_name
    else:
        relative_path = input_path.relative_to(input_root)
        output_path = output_dir / relative_path.with_suffix(extension)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def needs_resize(width: int, height: int, max_size: int) -> bool:
    """Check if image exceeds the max size. Returns False when max_size is 0 (convert only)."""
    if max_size == 0:
        return False
    return width > max_size or height > max_size


def calculate_new_size(width: int, height: int, target: int) -> tuple[int, int]:
    """Calculate new dimensions keeping aspect ratio, longest side = target."""
    if width >= height:
        new_width = target
        new_height = int(height * (target / width))
    else:
        new_height = target
        new_width = int(width * (target / height))
    return new_width, new_height


def process_image(input_path: Path, output_path: Path, format_key: str, quality: int,
                  max_size: int) -> dict:
    """Process a single image: convert and optionally resize. Preserves metadata."""
    result = {
        'input': str(input_path),
        'output': str(output_path),
        'resized': False,
        'original_size': None,
        'new_size': None,
        'input_bytes': 0,
        'output_bytes': 0,
        'error': None
    }

    fmt = FORMAT_CONFIG[format_key]

    try:
        result['input_bytes'] = input_path.stat().st_size

        with Image.open(input_path) as img:
            # Extract EXIF data if present
            exif_bytes = None
            exif_dict = None
            try:
                if 'exif' in img.info:
                    exif_dict = piexif.load(img.info['exif'])
                    exif_bytes = img.info['exif']
                elif input_path.suffix.lower() in ('.jpg', '.jpeg', '.tiff', '.tif'):
                    exif_dict = piexif.load(str(input_path))
                    exif_bytes = piexif.dump(exif_dict)
            except Exception:
                exif_dict = None

            # Convert to RGB if necessary (for PNG with transparency, etc.)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            width, height = img.size
            result['original_size'] = (width, height)

            # Check if resize is needed
            if needs_resize(width, height, max_size):
                new_width, new_height = calculate_new_size(width, height, max_size)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                result['resized'] = True
                result['new_size'] = (new_width, new_height)

                # Update EXIF dimensions if present
                if exif_dict:
                    try:
                        if piexif.ExifIFD.PixelXDimension in exif_dict.get('Exif', {}):
                            exif_dict['Exif'][piexif.ExifIFD.PixelXDimension] = new_width
                        if piexif.ExifIFD.PixelYDimension in exif_dict.get('Exif', {}):
                            exif_dict['Exif'][piexif.ExifIFD.PixelYDimension] = new_height
                        exif_bytes = piexif.dump(exif_dict)
                    except Exception:
                        pass
            else:
                result['new_size'] = (width, height)

            # Build save options
            save_kwargs = {'quality': quality, **fmt['extra_opts']}

            # Preserve EXIF metadata (works for JPEG, HEIC, and AVIF)
            if exif_bytes:
                save_kwargs['exif'] = exif_bytes

            img.save(output_path, fmt['pillow_format'], **save_kwargs)

        result['output_bytes'] = output_path.stat().st_size

    except Exception as e:
        result['error'] = str(e)

    return result


def move_to_originals(input_path: Path, originals_dir: Path, input_root: Path) -> Path:
    """Move original file to originals folder, preserving subfolder structure."""
    relative_path = input_path.relative_to(input_root)
    dest_path = originals_dir / relative_path
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(input_path), str(dest_path))
    return dest_path


# ── Summary Table ────────────────────────────────────────────────────────────

def print_summary(stats: dict, elapsed: float):
    """Print a styled summary table after processing."""
    print()
    print(f"{C.CYAN}{'═' * 52}{C.RESET}")
    print(f"{C.BOLD}  📊  Processing Summary{C.RESET}")
    print(f"{C.CYAN}{'═' * 52}{C.RESET}")

    processed = stats['processed']
    resized = stats['resized']
    errors = stats['errors']
    moved = stats['moved']
    total_in = stats['total_input_bytes']
    total_out = stats['total_output_bytes']

    print(f"  {C.BOLD}Images processed:{C.RESET}  {C.GREEN}{processed}{C.RESET}")
    print(f"  {C.BOLD}Images resized:{C.RESET}    {C.CYAN}{resized}{C.RESET}")
    if errors > 0:
        print(f"  {C.BOLD}Errors:{C.RESET}            {C.RED}{errors}{C.RESET}")
    if moved > 0:
        print(f"  {C.BOLD}Originals moved:{C.RESET}   {moved}")
    replaced = stats.get('replaced', 0)
    if replaced > 0:
        print(f"  {C.BOLD}Files replaced:{C.RESET}    {C.YELLOW}{replaced}{C.RESET}")

    print(f"{C.DIM}{'─' * 52}{C.RESET}")

    if total_in > 0 and total_out > 0:
        saved_pct = (1 - total_out / total_in) * 100
        arrow = '↓' if saved_pct > 0 else '↑'
        color = C.GREEN if saved_pct > 0 else C.RED
        print(f"  {C.BOLD}Input size:{C.RESET}        {format_bytes(total_in)}")
        print(f"  {C.BOLD}Output size:{C.RESET}       {format_bytes(total_out)}")
        print(f"  {C.BOLD}Savings:{C.RESET}           {color}{arrow} {abs(saved_pct):.1f}%{C.RESET}  ({format_bytes(abs(total_in - total_out))})")

    minutes, seconds = divmod(elapsed, 60)
    if minutes > 0:
        time_str = f"{int(minutes)}m {seconds:.1f}s"
    else:
        time_str = f"{seconds:.1f}s"
    print(f"  {C.BOLD}Time elapsed:{C.RESET}      {time_str}")

    if processed > 0 and elapsed > 0:
        speed = processed / elapsed
        print(f"  {C.BOLD}Speed:{C.RESET}             {speed:.1f} images/sec")

    print(f"{C.CYAN}{'═' * 52}{C.RESET}")

    if errors > 0:
        print(f"\n  {C.YELLOW}⚠️  {errors} file(s) had errors and remain in the input folder{C.RESET}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # If no CLI arguments, or --wizard flag, launch the interactive wizard
    if len(sys.argv) == 1 or '--wizard' in sys.argv:
        # Extract folder path if passed alongside --wizard
        prefill = None
        for arg in sys.argv[1:]:
            if arg != '--wizard':
                prefill = arg
                break
        wizard_result = startup_wizard(prefill_folder=prefill)
        if wizard_result is None:
            sys.exit(0)
        # Convert wizard result to a namespace-like object
        args = argparse.Namespace(**wizard_result)
    else:
        parser = argparse.ArgumentParser(
            description='Batch convert and resize images.',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  python batch_resizer.py /path/to/images
  python batch_resizer.py /path/to/images --format heic
  python batch_resizer.py /path/to/images --format avif --quality 80
  python batch_resizer.py /path/to/images -o /path/to/output --max-size 2000
            """
        )
        parser.add_argument('input_folder', help='Input folder containing images')
        parser.add_argument('-o', '--output', help=f'Output folder (default: <input>/{OUTPUT_FOLDER_NAME})')
        parser.add_argument('-f', '--format', choices=['jpeg', 'heic', 'avif'], default='jpeg',
                            help='Output format (default: jpeg)')
        parser.add_argument('-q', '--quality', type=int, default=DEFAULT_QUALITY,
                            help=f'Quality 1-100 (default: {DEFAULT_QUALITY})')
        parser.add_argument('-m', '--max-size', type=int, default=DEFAULT_MAX_SIZE,
                            help=f'Max longest side in px, larger images get resized (default: {DEFAULT_MAX_SIZE})')
        parser.add_argument('--no-move', action='store_true',
                            help='Do not move originals to "originals" folder')
        parser.add_argument('--replace', action='store_true',
                            help='Replace originals in-place (destructive)')
        parser.add_argument('--rename', type=str, default=None, metavar='NAME',
                            help='Rename output files with NAME_001, NAME_002, ... scheme')

        args = parser.parse_args()

    # Check HEIC/AVIF availability
    if args.format in ('heic', 'avif') and not HEIF_AVAILABLE:
        print(f"{C.RED}Error: {args.format.upper()} support requires pillow-heif{C.RESET}")
        print(f"Install with: {C.CYAN}pip install pillow-heif{C.RESET}")
        sys.exit(1)

    input_dir = Path(args.input_folder).resolve()

    if not input_dir.exists():
        print(f"{C.RED}Error: Input folder does not exist: {input_dir}{C.RESET}")
        sys.exit(1)

    replace_mode = getattr(args, 'replace', False)
    fmt = FORMAT_CONFIG[args.format]
    rename_base = getattr(args, 'rename', None)

    if replace_mode:
        # In replace mode, output to a temp dir within the input folder
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(dir=input_dir, prefix='.resizer_tmp_'))
        output_dir = tmp_dir
        originals_dir = None
    else:
        output_dir = Path(args.output).resolve() if args.output else input_dir / OUTPUT_FOLDER_NAME
        originals_dir = input_dir / 'originals'

    output_dir.mkdir(parents=True, exist_ok=True)

    print()
    if replace_mode:
        print(f"  {C.BOLD}Mode:{C.RESET}            {C.YELLOW}⚠️  Replace in-place{C.RESET}")
    print(f"  {C.BOLD}Input folder:{C.RESET}    {input_dir}")
    if not replace_mode:
        print(f"  {C.BOLD}Output folder:{C.RESET}   {output_dir}")
    print(f"  {C.BOLD}Format:{C.RESET}          {C.CYAN}{args.format.upper()}{C.RESET} ({fmt['extension']})")
    print(f"  {C.BOLD}Quality:{C.RESET}         {args.quality}")
    if args.max_size == 0:
        print(f"  {C.BOLD}Resize:{C.RESET}          {C.DIM}convert only{C.RESET}")
    else:
        print(f"  {C.BOLD}Max size:{C.RESET}        {args.max_size}px longest side")
    if rename_base:
        print(f"  {C.BOLD}Rename:{C.RESET}         {rename_base}_001, {rename_base}_002, ...")
    print(f"  {C.BOLD}Workers:{C.RESET}         {MAX_WORKERS}")
    if not replace_mode and not args.no_move:
        print(f"  {C.BOLD}Originals:{C.RESET}      → {originals_dir}")
    print(f"{C.DIM}{'─' * 60}{C.RESET}")

    # Find all images (exclude output and originals folders)
    all_images = find_images(input_dir)
    exclude_dirs = [str(output_dir)]
    if originals_dir:
        exclude_dirs.append(str(originals_dir))
    images = [img for img in all_images
              if not any(str(img).startswith(d) for d in exclude_dirs)]

    if not images:
        print(f"{C.YELLOW}No images found!{C.RESET}")
        if replace_mode:
            tmp_dir.rmdir()
        sys.exit(0)

    print(f"  Found {C.BOLD}{len(images)}{C.RESET} images\n")

    stats = {
        'processed': 0, 'resized': 0, 'errors': 0, 'moved': 0,
        'replaced': 0,
        'total_input_bytes': 0, 'total_output_bytes': 0,
    }

    # Pre-create output directories and build task list
    tasks = []
    for idx, img_path in enumerate(images, start=1):
        output_path = get_output_path(
            img_path, output_dir, input_dir, fmt['extension'],
            rename_base=rename_base, rename_index=idx, total_count=len(images),
        )
        if output_path.resolve() == img_path.resolve():
            continue
        tasks.append((img_path, output_path))

    start_time = time.time()

    # Process images in parallel with progress bar
    if TQDM_AVAILABLE:
        progress = tqdm(
            total=len(tasks),
            desc=f"  {C.CYAN}Processing{C.RESET}",
            unit='img',
            bar_format=f"  {{l_bar}}{C.GREEN}{{bar}}{C.RESET} {{n_fmt}}/{{total_fmt}} [{{elapsed}}<{{remaining}}, {{rate_fmt}}]",
            ncols=80,
        )
    else:
        progress = None

    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_path = {}
        for img_path, output_path in tasks:
            future = executor.submit(
                process_image, img_path, output_path,
                args.format, args.quality, args.max_size,
            )
            future_to_path[future] = img_path

        # Collect results as they complete
        for future in as_completed(future_to_path):
            img_path = future_to_path[future]
            result = future.result()

            if result['error']:
                msg = f"  {C.RED}✗{C.RESET} {img_path.name}: {result['error']}"
                if progress:
                    tqdm.write(msg)
                else:
                    print(msg)
                stats['errors'] += 1
            else:
                stats['processed'] += 1
                stats['total_input_bytes'] += result['input_bytes']
                stats['total_output_bytes'] += result['output_bytes']

                if result['resized']:
                    stats['resized'] += 1
                    orig = result['original_size']
                    new = result['new_size']
                    msg = f"  {C.GREEN}✓{C.RESET} {C.DIM}Resized{C.RESET} {img_path.name} {C.DIM}({orig[0]}x{orig[1]} → {new[0]}x{new[1]}){C.RESET}"
                else:
                    msg = f"  {C.GREEN}✓{C.RESET} {img_path.name}"

                if progress:
                    progress.set_postfix_str(img_path.name[-30:], refresh=False)
                    tqdm.write(msg)
                else:
                    print(msg)

                if replace_mode:
                    # Replace original: move converted file to original location
                    try:
                        converted_path = Path(result['output'])
                        # Determine final path (same dir as original, with new extension)
                        final_path = img_path.with_suffix(fmt['extension'])
                        # Remove original file
                        img_path.unlink()
                        # Move converted file to final location
                        shutil.move(str(converted_path), str(final_path))
                        # If extension changed, the old file is already gone (unlinked above)
                        stats['replaced'] += 1
                    except Exception as e:
                        warn = f"  {C.YELLOW}⚠ Could not replace {img_path.name}: {e}{C.RESET}"
                        if progress:
                            tqdm.write(warn)
                        else:
                            print(warn)
                elif not args.no_move:
                    # Move originals (sequential, safe for filesystem)
                    try:
                        move_to_originals(img_path, originals_dir, input_dir)
                        stats['moved'] += 1
                    except Exception as e:
                        warn = f"  {C.YELLOW}⚠ Could not move {img_path.name}: {e}{C.RESET}"
                        if progress:
                            tqdm.write(warn)
                        else:
                            print(warn)

            if progress:
                progress.update(1)

    if progress:
        progress.close()

    # Clean up temp directory in replace mode
    if replace_mode:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    elapsed = time.time() - start_time

    # Print summary table
    print_summary(stats, elapsed)
    if replace_mode:
        print(f"\n  {C.BOLD}Files replaced in:{C.RESET} {input_dir}\n")
    else:
        print(f"\n  {C.BOLD}Output saved to:{C.RESET} {output_dir}\n")


if __name__ == '__main__':
    main()

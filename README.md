# 🖼️ ImgCrunch

ImgCrunch is an extremely fast, parallel image processing command-line tool (CLI) and macOS Finder Quick Action. It allows you to convert, resize, rename, and clean entire image folders simultaneously using all available CPU cores of your system.

---

## ⚡ Core Features

### 📦 Multi-Format Power
- **Modern Formates**: Convert to **JPEG**, **HEIC** (Apple standard), **AVIF** (next-gen), **WebP** (web-optimized), and **JPEG XL (JXL)**.
- **Transparency Preservation**: Keeps the alpha channel (RGBA) intact when converting to formats that support transparency (WebP, AVIF, JXL).
- **Lossless Mode**: `--lossless` flag for lossless AVIF and WebP outputs.
- **Smart Quality**: Auto-tuned quality levels per output format to achieve the perfect balance between file size and visual fidelity.
- **Target Size (`--target-size`)**: Force every output below a byte budget (`500k`, `1.5m`), on the command line or as a wizard step. Quality is lowered first; if that isn't enough, the image is scaled down until it fits. Files that can't reach the target are reported as errors instead of being written oversized. Cannot be combined with `--lossless` (no quality to trade) or `--format original` (no re-encoding). Does not apply to animated images (GIF→WebP/AVIF); those are written at normal quality with a warning. Note: When dimensions are reduced during the target-size search, EXIF `PixelXDimension` and `PixelYDimension` tags still describe the pre-shrink size (affects JPEG and other formats that preserve EXIF).
- **Copy Mode (`original`)**: Merge and rename images without recompressing them (1:1 binary copies).
- **Rename-Only Mode (`--rename-only`)**: Renames files where they lie — no conversion, no resizing, no copies. Instant even for thousands of files.

### 🚀 High-Speed Performance
- **True Parallelism**: CPU-intensive resizing and encoding run in parallel across all available CPU cores using Python's `ProcessPoolExecutor`.
- **mmap-Accelerated Hashing**: Duplicate detection memory-maps files instead of reading them in chunks.
- **Smart Skipping**: Automatically skips images that are already in the target format and do not exceed the maximum dimension.
- **Duplicate Detection (`--skip-dupes`)**: Groups by file size first and hashes only the collisions, then skips content-identical duplicates. Off unless you ask for it.

### 🍎 macOS Integration
- **Finder Quick Action**: Select images and folders directly in Finder, right-click → *Quick Actions* → *ImgCrunch*. Immediately starts the interactive wizard.
- **Automatic Refresh**: Triggers the macOS Quick Look thumbnail cache to refresh previews instantly after processing.
- **Finder-Safe**: Ignores macOS system files like `._` resource forks automatically.

### 🛡️ Privacy & Safety
- **Privacy Mode (`--strip` / `--no-exif`)**: Strips all EXIF metadata (GPS coordinates, camera model, etc.) completely before saving.
- **Atomic Writes**: Writes to a temporary file first and renames it only after successful output verification. `--replace` stages next to the source and moves the result into place *before* dropping the original, so a failed write never costs you the file.
- **Preflight Disk Check**: Estimates required disk space before processing starts and aborts if the disk is at risk of running full.
- **Encoder Preflight**: Verifies the output format can actually be encoded on this machine before the batch starts — a missing AVIF or JXL encoder fails immediately with an install hint instead of on image 200.

---

## 🚀 Installation & Quick Start

### 1. Install

**Recommended — [pipx](https://pipx.pypa.io)**, which puts `imgcrunch` on your `PATH` in its own environment:
```bash
git clone https://github.com/ralksta/imgcrunch.git
pipx install './imgcrunch[all]'
imgcrunch --version
```

Pillow is the only hard requirement and already covers JPEG, WebP and AVIF. The extras add the rest; `all` installs every one of them:

| Extra | Adds |
| :--- | :--- |
| `heic` | HEIC output (`pillow-heif`) |
| `jxl` | JPEG XL output (`pillow-jxl-plugin`) |
| `exif` | Keeps EXIF dimension tags accurate after a JPEG resize (`piexif`) |
| `progress` | Progress bar (`tqdm`) |

Choose a format whose extra is missing and ImgCrunch stops before the first image and names the package to install.

**Alternative — a venv inside the clone**, which is what `resize.sh` uses:
```bash
cd imgcrunch
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt     # installs the project with all extras
```
Requires Python 3.11 or newer.

### 2. Install macOS Finder Quick Action
To process images directly from Finder:
```bash
bash install_macos_quick_action.sh
```
The action starts the `imgcrunch` command if pipx installed it, and this clone's `resize.sh` otherwise. With pipx you can move or delete the clone freely; without it, run the installer again after moving the clone — the action tells you so if you forget.

*To uninstall, delete `~/Library/Services/ImgCrunch.workflow` and `~/Library/Application Support/ImgCrunch`.*

---

## 🔥 Performance Tuning (Pillow-SIMD for Intel/AMD)

For maximum processing speed on **Intel/AMD (x86_64) CPUs** (especially when resizing large batches of high-resolution images), you can install **Pillow-SIMD**. It leverages SSE4 and AVX2 to speed up image resizing operations by **4x to 6x**:

```bash
# Uninstall standard Pillow
pip uninstall pillow

# Install Pillow-SIMD with AVX2 optimizations (Intel/AMD only)
CC="clang -mavx2" pip install pillow-simd
```

> [!NOTE]
> **Apple Silicon (M-Series ARM Macs):** Do not install Pillow-SIMD on Apple Silicon. Pillow-SIMD requires x86-specific SIMD instructions (SSE/AVX) and will fail to compile on arm64. The standard `Pillow` package is already natively compiled and highly optimized for Apple Silicon (utilizing macOS Accelerate and ARM NEON) out of the box.

---

## 🎮 Usage Guide

### 1. Interactive Wizard (Recommended)
Launch the wizard without arguments. It guides you step-by-step through formatting, resizing, max file size, renaming, and privacy options:
```bash
bash resize.sh
```
The wizard asks its own questions, so it takes no flags — `--wizard` combined with any flag is rejected rather than silently ignored. Use the flags directly (below) when you want a non-interactive run.

Instead of walking through every setting, the wizard first offers presets:

```
  How should the images be encoded?

    [1]  Last run     — AVIF q55, 2400px, max 800k, EXIF stripped
    [2]  Web          — JPEG q85, 2000px, max 500k, EXIF stripped
    [3]  Archive      — JXL q90, original size, EXIF kept
    [4]  Save space   — AVIF q60, 3000px, EXIF kept
    [5]  Choose each setting …
```

*Last run* appears once you have finished a conversion; its settings live in `~/.config/imgcrunch/config.toml` (or under `$XDG_CONFIG_HOME`) and the file is safe to delete. A preset only ever sets how images are encoded — never replace, rename or merge — so picking one cannot be what overwrites your files.

### 2. CLI Mode (Automation)
Ideal for scripting and automation:
```bash
# Convert to JPEG with no resizing
bash resize.sh /path/to/images

# Convert to HEIC with quality 80
bash resize.sh /path/to/images --format heic --quality 80

# Resize images to a max longest side of 2000px and rename (vacation_001.jpg etc.)
bash resize.sh /path/to/images --max-size 2000 --rename vacation

# Only rename, in-place — no recompression, no copies (vacation_001.jpg, ...)
bash resize.sh /path/to/images --rename-only --rename vacation

# Overwrite original files directly (Warning: Destructive!)
bash resize.sh /path/to/images --replace --format avif

# Strip metadata (Privacy Mode) and convert to JXL
bash resize.sh /path/to/images --strip --format jxl

# Force every output under 500 KB (lower quality first, then scale down if needed)
bash resize.sh /path/to/images --target-size 500k

# Convert to WebP with target size 200 KB and max dimension 2000px
bash resize.sh /path/to/images -f webp --target-size 200k -m 2000

# Run a custom shell command after processing each file
bash resize.sh /path/to/images --post-hook 'echo Processed: {out}'
```

---

## ⚙️ CLI Options & Reference

| Flag | Short | Description | Default |
| :--- | :--- | :--- | :--- |
| `--format` | `-f` | Output format: `jpeg`, `heic`, `avif`, `webp`, `jxl`, `original` | `jpeg` |
| `--quality` | `-q` | Compression quality (1–100) | Smart default per format |
| `--max-size` | `-m` | Max longest side in pixels (`0` = no resize) | `3000` |
| `--target-size` | | Force every output below SIZE (e.g. `500k`, `1.5m`). Lowers quality first, then dimensions. Cannot combine with `--lossless` or `--format original`. Skipped for animated images. | off |
| `--output` | `-o` | Custom output folder path | `<input>/converted/` |
| `--replace` | | Replace originals in-place (**Warning: Destructive!**) | off |
| `--no-move` | | Do not move originals to the `originals/` backup folder | off |
| `--rename NAME`| | Rename output files to `NAME_001`, `NAME_002` ... | Keep original names |
| `--rename-only` | | Rename in-place only — no conversion, resize or copies. Requires `--rename`. Numbering follows filename order. | off |
| `--lossless` | | Lossless encoding (AVIF and WebP only) | off |
| `--strip` | | Strip all EXIF metadata from output images (Privacy Mode) | off |
| `--no-strip` | | Keep EXIF metadata even when `--preset` would strip it | off |
| `--merge` | | Merge all input folders/files into a single output folder | off |
| `--post-hook CMD`| | Shell command to run after each file (placeholders: `{in}`, `{out}`) | off |
| `--skip-dupes` | | Skip files that are content-identical to an already-processed file | off |
| `--dry-run` | | Preview what would be processed without writing anything | off |
| `--yes` | `-y` | Skip the confirmation prompt for `--replace` and `--rename-only` | off |
| `--preset NAME` | | Start from a recipe: `web`, `archive`, `compact`, or `last` (the settings of your previous run). Flags you type explicitly still win; a preset's byte budget quietly steps aside for `--lossless`, `-f original` or `--rename-only`. | off |
| `--workers N` | | Number of parallel encoder processes. Lower it to keep the machine responsive during a big batch. | one per core |
| `--quiet` | | Print only errors — no config table, progress bar or summary | off |
| `--args-file` | | *Internal.* Reads one argument per line from a file, then deletes it. The macOS Quick Action uses this to hand over a Finder selection. | off |

---

### Exit Codes

| Code | Meaning |
| :--- | :--- |
| `0` | Everything succeeded. Warnings and skipped duplicates do not count as failures; a `--dry-run` always exits 0. |
| `1` | At least one image failed, or a replace, move or `--post-hook` after it did — or a `--replace`/`--rename-only` run was not confirmed. The other images are still processed. |
| `2` | Usage error: an invalid flag or value, or an unreadable `--args-file`. |
| `130` | Cancelled with Ctrl+C during the batch. |

---

## 📁 Output Folder Modes

### Mode 1: Backup (Default)
Originals are preserved and moved to `originals/`, while optimized images land in `converted/`:
```
input-folder/
├── converted/          ← Resized, optimized & stripped images
├── originals/          ← Untouched original files (Backup)
└── ...
```

### Mode 2: In-place Overwrite (`--replace`)
Replaces the original files directly. Great for quickly freeing up disk space:
```
input-folder/
├── photo1.jpg          ← Overwritten with optimized version
├── photo2.png          ← Overwritten and converted to target format
└── ...
```

---

## 📅 Changelog

### Unreleased
*Everything below has landed on `main` since the v1.0.0 tag.*

**Installation**

- **`pipx install './imgcrunch[all]'`** puts an `imgcrunch` command on your PATH; `imgcrunch --version` reports the version. Pillow is the only hard dependency — HEIC, JPEG XL, piexif and tqdm are extras — and AVIF needs no plugin at all.
- **The Quick Action survives moving the clone** when imgcrunch is installed with pipx, and explains itself instead of failing silently when it is not. Its temp file moved out of the shared `/tmp`, and installing it no longer resets the system-wide LaunchServices database (`lsregister -kill`); it refreshes only the Services menu.
- **`resize.sh` explains a missing venv** instead of printing a bare shell error.

**Robustness and tests**

- **A worker process that dies no longer takes the batch down.** If the OS kills one — usually for memory — its images are reported as failed with a hint to lower `--workers`, originals stay put, and everything else still finishes and is summarised.
- **The suite covers what it used to skip:** HEIC, AVIF and JPEG XL round trips, animated GIF frames, timing and loop count, `--merge`, `--skip-dupes`, moving originals, the Quick Action installer and launcher, and a worker crash. 97 tests at v1.0.0, 227 now.

**Performance**

- **Large JPEGs are decoded at a reduced scale when they are about to be shrunk.** libjpeg can scale by ½, ¼ or ⅛ while decoding; the decode keeps 1.5× headroom above the target so LANCZOS still does the final step (≥ 44 dB PSNR against a full decode, even on fine texture). On 60 × 12 MP photos: `-m 800` 0.84 s → 0.63 s, `-m 1200` 1.23 s → 1.02 s. Mild shrinks, including the default `-m 3000` on typical camera files, are unchanged.
- **Preparation no longer resolves every path five times.** Before the progress bar appears on 10,000 files: 1.04 s → 0.28 s.
- **`--strip` no longer copies upright images** just to not rotate them: 45 MB less peak memory per worker on a 12 MP photo.
- **`--workers N`** caps the encoder pool. On a 10 performance + 4 efficiency core Mac, 10 workers cost about 4 % against the default.

**Wizard**

- **Presets.** The wizard opens with *Last run*, *Web*, *Archive* and *Save space*; picking one answers the format, quality, size, byte-budget and metadata questions in one keystroke. The same recipes are available as `--preset NAME`, with explicitly typed flags taking precedence. Presets never carry a mode, so one can never switch on `--replace`.
- **Transparency is no longer flattened in silence.** A folder of PNGs used to default to JPEG, painting every transparent pixel white. PNG now suggests WebP, and flattening real transparency into JPEG or HEIC produces a warning.
- **Every option is reachable from the wizard.** *Choose each setting* now asks for quality, offers lossless for WebP and AVIF (skipping quality and byte budget, which it makes meaningless), and can skip duplicates. Answering `d` at the final prompt does a dry run on any path — presets and replace included.
- **Same default everywhere.** Enter on the longest-side question now means 3000px, like the command line and this README; `0` still disables resizing.
- **Vanished Finder selections are named** instead of silently shrinking the input list.

**Safety and honest reporting**

- **`--replace` no longer risks the original.** It used to `unlink()` the source and only then move the new file into place; a failing move — a full disk, a read-only parent — destroyed the image outright, and on a format change there was nothing to fall back on. The replacement now goes in first and the original is dropped afterwards. The staging directory also moved from `/var/folders` to right beside the input, which turns every replace on an external disk from a full cross-volume copy into a rename.
- **Destructive runs ask first.** `--replace` and `--rename-only` prompt on a terminal and refuse to run without one unless you pass `--yes`. The wizard's final prompt no longer defaults to *yes* on the replace path.
- **Ctrl+C tells the truth.** The old handler printed “nothing was changed” however far the batch had got. It now names how many images were processed and how many originals were already replaced or moved.
- **Failures are counted and named.** A replace, move or post-hook that blew up printed a yellow warning and was then forgotten, so the closing count under-reported. Those now have their own counter, the summary lists which files failed and why, and raw encoder text like `cannot identify image file` is translated into something actionable.
- **A failing `--post-hook` is visible.** Its exit code was ignored entirely; a non-zero exit now reports the code and the first line of stderr.
- **`--args-file` fails honestly.** An unreadable file used to print a note and carry on with the flag still in `argv`, which then produced the baffling “`--args-file` cannot be combined with `--wizard`”. It now exits with the real reason.
- **Unreadable EXIF is reported** instead of being dropped in silence, and the Quick Look refresh no longer runs `qlmanage -r cache`, which threw away Quick Look thumbnails for every file on the machine.
- **`--quiet`** prints errors and nothing else.
- **Transparent AVIF, WebP and JPEG XL files are no longer re-encoded into their own format.** The copy-through rule only admitted images without an alpha channel — a rule meant for JPEG and HEIC — so converting a folder of transparent AVIFs to AVIF recompressed every one of them. They are now copied byte for byte like any other file that needs no change.
- **The exit code reports failures.** It was 0 even when images failed; it is now 1 whenever an image, or a replace, move or post-hook after it, failed — which is what makes `--quiet` usable in scripts.

- **Target Size (`--target-size`)** – Force every output below a byte budget (`500k`, `1.5m`). Quality is binary-searched first, capped at the requested `--quality`; if no quality fits, dimensions are reduced until one does, preserving aspect ratio and never upscaling. Files that cannot reach the target are reported as errors rather than written oversized. Available on the command line and as a wizard step.
- **Encoder Preflight** – Encodes a 1×1 image before the batch starts to verify the output format is genuinely encodable on this machine, aborting with a `pip install` hint instead of failing on the first image. Replaces the previous check, which only tested whether the optional plugin imported.
- **Rename-Only Mode (`--rename-only`)** – Renames files where they lie: no decode, no encode, no copies. Numbering follows filename order, and a two-phase rename via temporary names makes a base name that collides with existing files safe. Also reachable from the wizard.
- **Wizard: no more silently swallowed flags** – Any flag passed beside `--wizard` used to be discarded without a word (everything but `--wizard` became a path prefill, and non-paths were dropped). It now aborts with a message naming the flag.
- **Correctness fixes** – Clamp the short side to ≥1 px so extreme aspect ratios cannot round to zero and crash the resize; bake EXIF orientation into the pixels before `--strip` drops metadata, so stripped images no longer appear rotated; copy already-optimal files through to the output folder instead of silently omitting them; stage `--replace` in the temp dir so it stops leaving an empty `converted/` behind; number renamed files after duplicate filtering so the sequence has no gaps.
- **`--dry-run`** – Preview the plan without writing anything.
- **Hardening** – Faster duplicate detection (group by size, hash only on collision), `--quality` range validation, and shell-quoted `{in}`/`{out}` in `--post-hook`.
- **Internals** – Sizing and search arithmetic extracted into a Pillow-free `sizing.py`, testable without encoding real images; worker parameters bundled into a picklable `JobSettings` dataclass whose `forces_reencode()` centralises the byte-copy decision. Test suite grown from 27 to 96 tests.

### v1.0.0 (2026-07-05) - Initial Stable Release
- **JPEG XL (.jxl) Integration** – Native JXL output support (requires `pillow-jxl-plugin`).
- **Privacy Mode (`--strip`)** – Complete EXIF metadata stripping.
- **GIF Animation Preservation** – Converts animated GIFs to WebP/AVIF while preserving precise, variable frame timings.
- **Alpha Channel Preservation** – Transparency is kept intact when converting to WebP, AVIF, and JXL.
- **Performance Upgrade** – Removed the CPU worker pool limit of 8 threads, fully utilizing all available cores on multi-core processors (e.g., Apple Silicon).
- **WebP Encoding Optimization** – Adjusted libwebp compression method from level 6 to level 4 for up to 100x faster animated WebP rendering.
- **Terminal Progress Updates** – Dynamically displays the current progress percentage in the terminal title bar.
- **Bugfixes** – Fixed argument scanning errors for single file inputs, resolved wizard detection fallback markers, and defaulted GIFs to WebP conversion.

---

## 🧪 Development

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements-dev.txt   # project + all extras + pytest
./venv/bin/python -m pytest
```

The suite never touches your real `~/.config/imgcrunch` or `~/Library`: config lookups are redirected to a temp directory, and the Quick Action tests install into temp directories with `osascript` stubbed out. HEIC and JPEG XL tests skip when their plugin is missing.

To run the tests before every push:
```bash
ln -s ../../hooks/pre-push .git/hooks/pre-push
```
Skip it for a single push with `git push --no-verify`; remove it by deleting `.git/hooks/pre-push`.

---

## 📄 License
MIT License. Free usage for everyone.

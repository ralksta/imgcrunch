# 🖼️ ImgCrunch

ImgCrunch is an extremely fast, parallel image processing command-line tool (CLI) and macOS Finder Quick Action. It allows you to convert, resize, rename, and clean entire image folders simultaneously using all available CPU cores of your system.

---

## ⚡ Core Features

### 📦 Multi-Format Power
- **Modern Formates**: Convert to **JPEG**, **HEIC** (Apple standard), **AVIF** (next-gen), **WebP** (web-optimized), and **JPEG XL (JXL)**.
- **Transparency Preservation**: Keeps the alpha channel (RGBA) intact when converting to formats that support transparency (WebP, AVIF, JXL).
- **Lossless Mode**: `--lossless` flag for lossless AVIF and WebP outputs.
- **Smart Quality**: Auto-tuned quality levels per output format to achieve the perfect balance between file size and visual fidelity.
- **Copy Mode (`original`)**: Merge and rename images without recompressing them (1:1 binary copies).

### 🚀 High-Speed Performance
- **True Parallelism**: CPU-intensive resizing and encoding run in parallel across all available CPU cores using Python's `ProcessPoolExecutor`.
- **mmap-Accelerated Reads**: Memory-mapped file I/O for faster reading of large source images.
- **Smart Skipping**: Automatically skips images that are already in the target format and do not exceed the maximum dimension.
- **Duplicate Detection**: Hashes files using MD5 and skips content-identical duplicates automatically.

### 🍎 macOS Integration
- **Finder Quick Action**: Select images and folders directly in Finder, right-click → *Quick Actions* → *ImgCrunch*. Immediately starts the interactive wizard.
- **Automatic Refresh**: Triggers the macOS Quick Look thumbnail cache to refresh previews instantly after processing.
- **Finder-Safe**: Ignores macOS system files like `._` resource forks automatically.

### 🛡️ Privacy & Safety
- **Privacy Mode (`--strip` / `--no-exif`)**: Strips all EXIF metadata (GPS coordinates, camera model, etc.) completely before saving.
- **Atomic Writes**: Writes to a temporary file first and renames it only after successful output verification. Prevents corrupted outputs.
- **Preflight Disk Check**: Estimates required disk space before processing starts and aborts if the disk is at risk of running full.

---

## 🚀 Installation & Quick Start

### 1. Clone & Set Up the Environment
```bash
git clone https://github.com/ralksta/imgcrunch.git
cd imgcrunch
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Install macOS Finder Quick Action
To process images directly from Finder:
```bash
bash install_macos_quick_action.sh
```
*To uninstall, simply delete `~/Library/Services/ImgCrunch.workflow`.*

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
Launch the wizard without arguments. It guides you step-by-step through formatting, resizing, renaming, and privacy options:
```bash
bash resize.sh
```

### 2. CLI Mode (Automation)
Ideal for scripting and automation:
```bash
# Convert to JPEG with no resizing
bash resize.sh /path/to/images

# Convert to HEIC with quality 80
bash resize.sh /path/to/images --format heic --quality 80

# Resize images to a max longest side of 2000px and rename (vacation_001.jpg etc.)
bash resize.sh /path/to/images --max-size 2000 --rename vacation

# Overwrite original files directly (Warning: Destructive!)
bash resize.sh /path/to/images --replace --format avif

# Strip metadata (Privacy Mode) and convert to JXL
bash resize.sh /path/to/images --strip --format jxl

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
| `--output` | `-o` | Custom output folder path | `<input>/converted/` |
| `--replace` | | Replace originals in-place (**Warning: Destructive!**) | off |
| `--no-move` | | Do not move originals to the `originals/` backup folder | off |
| `--rename NAME`| | Rename output files to `NAME_001`, `NAME_002` ... | Keep original names |
| `--lossless` | | Lossless encoding (AVIF and WebP only) | off |
| `--strip` | | Strip all EXIF metadata from output images (Privacy Mode) | off |
| `--merge` | | Merge all input folders/files into a single output folder | off |
| `--post-hook CMD`| | Shell command to run after each file (placeholders: `{in}`, `{out}`) | off |

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

## 📄 License
MIT License. Free usage for everyone.

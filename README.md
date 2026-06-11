# 🖼️ ImgCrunch

A fast, parallel image cruncher with format conversion. Processes entire folders of images — resize, convert, and optionally rename — all with EXIF metadata preserved.

## ✨ Features

- **Multi-format output** — JPEG, HEIC, AVIF, or WebP
- **Smart resize** — only downsizes images exceeding a configurable max dimension (or skip with `0`)
- **Smart quality defaults** — tuned per format (JPEG 85 · HEIC 65 · AVIF 60 · WebP 82)
- **Lossless mode** — `--lossless` flag for AVIF and WebP
- **Two output modes** — keep originals safe, or replace them in-place
- **ProcessPool parallelism** — CPU-bound encode/resize runs in a process pool for true multi-core throughput
- **mmap-accelerated reads** — large files are memory-mapped for faster I/O
- **Disk preflight check** — estimates required space before starting; aborts early if disk is too full
- **Duplicate detection** — MD5-hashes all input files and skips content-identical duplicates automatically
- **Output verification** — each output file is opened and verified after writing
- **Atomic writes** — images are written to a temp file first and renamed on success to avoid partial outputs
- **Post-process hook** — `--post-hook 'cmd {in} {out}'` runs a shell command after each file
- **Throughput stats** — summary shows img/s and MB/s input throughput
- **Per-format summary** — breakdown of how many files were processed per source format
- **EXIF preservation** — metadata is carried over to converted files
- **Interactive wizard** — zero-config start, just run and answer prompts (defaults to convert-only, no resize)
- **CLI mode** — full flag support for scripting and automation
- **Batch rename** — optional clean naming scheme (`vacation_001.jpg`, `vacation_002.jpg`, …)
- **Smart skipping** — automatically skips images already in the target format and size
- **macOS Finder integration** — right-click a folder to launch via Quick Action (see below)
- **macOS safe** — ignores `._` resource fork files; triggers Quick Look thumbnail refresh after processing

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USER/batchresizer-quick.git
cd batchresizer-quick
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run

**Interactive wizard** (no arguments):

```bash
bash resize.sh
```

**CLI mode** (scriptable):

```bash
bash resize.sh /path/to/images
bash resize.sh /path/to/images --format heic --quality 80
bash resize.sh /path/to/images --max-size 2000 --rename vacation
bash resize.sh /path/to/images --replace --format avif
bash resize.sh /path/to/images --max-size 0 --format jpeg        # convert only, no resizing
bash resize.sh /path/to/images --lossless --format avif           # lossless AVIF
bash resize.sh /path/to/images --post-hook 'echo done: {out}'    # run command after each file
```

## 🍎 macOS Finder Integration

Add a **right-click Quick Action** so you can launch the resizer directly from Finder:

```bash
bash install_macos_quick_action.sh
```

Then: **right-click any folder** → **Quick Actions** → **ImgCrunch**

A Terminal window opens with the interactive wizard for that folder. After processing, Quick Look thumbnails are automatically refreshed.

> To uninstall: delete `~/Library/Services/ImgCrunch.workflow`

## ⚙️ CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `-f`, `--format` | Output format: `jpeg`, `heic`, `avif`, `webp` | `jpeg` |
| `-q`, `--quality` | Quality 1–100 | smart per-format default |
| `-m`, `--max-size` | Max longest side in pixels (`0` = no resize) | `0` |
| `-o`, `--output` | Custom output folder | `<input>/converted` |
| `--replace` | Replace originals in-place (**destructive**) | off |
| `--rename NAME` | Rename files as `NAME_001`, `NAME_002`, … | keep originals |
| `--no-move` | Don't move originals to `originals/` folder | move by default |
| `--lossless` | Lossless encoding (AVIF and WebP only) | off |
| `--post-hook CMD` | Shell command to run after each file (`{in}`, `{out}` placeholders) | none |

## 📁 Output Modes

### Keep Originals (default)

```
your-folder/
├── converted/          ← resized & converted images
├── originals/          ← original files moved here
└── ...
```

### Replace in-place (`--replace`)

```
your-folder/
├── photo1.jpg          ← replaced with converted version
├── photo2.jpg          ← replaced with converted version
└── ...
```

> ⚠️ Replace mode is **destructive** — original files are permanently overwritten.

## 📋 Requirements

- Python 3.10+
- [Pillow](https://pillow.readthedocs.io/) ≥ 10.0
- [piexif](https://pypi.org/project/piexif/) ≥ 1.1.3
- [pillow-heif](https://pypi.org/project/pillow-heif/) ≥ 0.16.0 (for HEIC/AVIF support)
- [tqdm](https://pypi.org/project/tqdm/) ≥ 4.60.0 (progress bar)

## 📅 Changelog

### 2026-06-11
- **ProcessPool parallelism** — encode/resize now runs across all CPU cores via `ProcessPoolExecutor`
- **mmap-accelerated reads** — large image files are memory-mapped for faster loading
- **Smart quality defaults** — tuned per-format defaults instead of a single global value
- **Lossless mode** — `--lossless` flag for AVIF and WebP output
- **Output verification** — each output file is verified after writing to catch corrupt encodes
- **Disk preflight check** — estimates required disk space and aborts early if insufficient
- **Duplicate detection** — MD5 hashing skips content-identical input files automatically
- **Dataclass internals** — `ImageResult` and `ProcessStats` refactored to typed dataclasses
- **Post-process hook** — `--post-hook` runs an arbitrary shell command after each converted file
- **Throughput stats** — run summary now shows MB/s input throughput alongside img/s
- **Per-format summary** — breakdown of source formats in the final report
- **Quick Look refresh** — macOS thumbnail cache is refreshed automatically after a run
- **Graceful abort** — clean `KeyboardInterrupt` handler with a friendly exit message

### Earlier
- WebP added as a fourth output format
- Interactive wizard defaults to convert-only (no resize)
- 6 performance optimisations: worker tuning, early-exit skip logic, reduced IPC overhead, macOS resource fork filtering, and more
- Renamed `batch_resizer.py` → `imgcrunch.py`
- macOS Finder Quick Action installer
- Initial release

## 📄 License

MIT

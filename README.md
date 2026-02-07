# 🖼️ ImgCrunch

A fast, parallel image cruncher with format conversion. Processes entire folders of images — resize, convert, and optionally rename — all with EXIF metadata preserved.

## ✨ Features

- **Multi-format output** — JPEG, HEIC, or AVIF
- **Smart resize** — only downsizes images exceeding a configurable max dimension (or skip with `0`)
- **Two output modes** — keep originals safe, or replace them in-place
- **Parallel processing** — uses all available CPU cores with progress bar
- **EXIF preservation** — metadata is carried over to converted files
- **Interactive wizard** — zero-config start, just run and answer prompts
- **CLI mode** — full flag support for scripting and automation
- **Batch rename** — optional clean naming scheme (`vacation_001.jpg`, `vacation_002.jpg`, …)
- **macOS Finder integration** — right-click a folder to launch (see below)

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
bash resize.sh /path/to/images --max-size 0 --format jpeg   # convert only, no resizing
```

## 🍎 macOS Finder Integration

Add a **right-click Quick Action** so you can launch the resizer directly from Finder:

```bash
bash install_macos_quick_action.sh
```

Then: **right-click any folder** → **Quick Actions** → **ImgCrunch**

A Terminal window opens with the interactive wizard for that folder.

> To uninstall: delete `~/Library/Services/ImgCrunch.workflow`

## ⚙️ CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `-f`, `--format` | Output format: `jpeg`, `heic`, `avif` | `jpeg` |
| `-q`, `--quality` | Quality 1–100 | `85` |
| `-m`, `--max-size` | Max longest side in pixels (`0` = no resize) | `3000` |
| `-o`, `--output` | Custom output folder | `<input>/converted` |
| `--replace` | Replace originals in-place (**destructive**) | off |
| `--rename NAME` | Rename files as `NAME_001`, `NAME_002`, … | keep originals |
| `--no-move` | Don't move originals to `originals/` folder | move by default |

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

## 📄 License

MIT

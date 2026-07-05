# 🖼️ ImgCrunch

ImgCrunch ist ein extrem schnelles, paralleles Bildverarbeitungstool für die Befehlszeile (CLI) und den macOS Finder. Es ermöglicht das blitzschnelle Konvertieren, Skalieren, Umbenennen und Bereinigen ganzer Bildersammlungen über alle CPU-Kerne deines Systems.

---

## ⚡ Core Features

### 📦 Multi-Format Power
- **Moderne Formate**: Konvertierung nach **JPEG**, **HEIC** (Apple Standard), **AVIF** (Next-Gen), **WebP** (Web-optimiert) und **JPEG XL (JXL)**.
- **Transparenz-Erhalt**: Beibehält den Alpha-Kanal (RGBA) bei Formaten, die Transparenz unterstützen (WebP, AVIF, JXL).
- **Verlustfreier Modus**: `--lossless` Flag für verlustfreie AVIF- und WebP-Bilder.
- **Smart Quality**: Automatisch optimierte Qualitätsstufen pro Ausgabeformat für die perfekte Balance aus Bildgröße und Qualität.
- **Kopiermodus (`original`)**: Bilder mergen und umbenennen ohne Neukompression (1:1 binäre Kopien).

### 🚀 High-Speed Performance
- **Echte Parallelität**: CPU-intensives Skalieren und Kodieren läuft parallel über alle verfügbaren Kerne via Pythons `ProcessPoolExecutor`.
- **mmap-Beschleunigung**: Schnelle, speicherabgebildete Lesezugriffe (Memory Mapping) bei großen Quellbildern.
- **Smart Skipping**: Überspringt Bilder, die bereits im Zielformat vorliegen und die Maximalgröße nicht überschreiten.
- **Duplikat-Erkennung**: Hashed Dateien via MD5 und überspringt Inhalts-Duplikate vollautomatisch.

### 🍎 macOS Integration
- **Finder Quick Action**: Bilder und Ordner direkt im Finder auswählen, Rechtsklick → *Schnellaktionen* → *ImgCrunch*. Startet sofort die interaktive Konsole.
- **Automatische Aktualisierung**: Triggered den macOS Quick Look Thumbnail-Cache, damit die Finder-Vorschauen nach dem Crunch sofort aktualisiert sind.
- **Finder-Safe**: Ignoriert macOS-Systemdateien wie `._` automatisch.

### 🛡️ Privacy & Safety
- **Privacy Mode (`--strip` / `--no-exif`)**: Entfernt EXIF-Metadaten (GPS-Koordinaten, Kamerainformationen, etc.) vollständig vor dem Speichern.
- **Atomares Schreiben**: Bilder werden in eine temporäre Datei geschrieben und erst bei erfolgreichem Validieren umbenannt. Kein Datenverlust bei Abbruch.
- **Preflight Speicher-Check**: Schätzt den benötigten Speicherplatz im Voraus und bricht ab, falls die Festplatte vollzulaufen droht.

---

## 🚀 Installation & Quick Start

### 1. Repository klonen und einrichten
```bash
git clone https://github.com/ralksta/imgcrunch.git
cd imgcrunch
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. macOS Finder Quick Action installieren
Um Bilder direkt aus dem macOS Finder per Rechtsklick zu verarbeiten:
```bash
bash install_macos_quick_action.sh
```
*Zur Deinstallation einfach den Ordner `~/Library/Services/ImgCrunch.workflow` löschen.*

---

## 🔥 Performance Tuning (Pillow-SIMD)

Für maximale Verarbeitungsgeschwindigkeit (besonders beim Skalieren großer Mengen hochauflösender Fotos) kannst du **Pillow-SIMD** installieren. Es nutzt SSE4, AVX2 oder NEON (auf Apple Silicon Macs) und beschleunigt Resizing-Operationen um das **4- bis 6-fache**:

```bash
# Deinstalliere das normale Pillow
pip uninstall pillow

# Installiere Pillow-SIMD mit AVX2/NEON Optimierung
CC="clang -mavx2" pip install pillow-simd
```

---

## 🎮 Usage Guide

### 1. Interaktiver Wizard (Empfohlen)
Startet ohne Argumente die interaktive Konsole, die dich Schritt für Schritt durch die Optionen führt. Perfekt für den Finder-Rechtsklick:
```bash
bash resize.sh
```

### 2. CLI-Modus (Automatisierung)
Ideal für Skripte und Entwickler:
```bash
# JPEG-Konvertierung ohne Größenänderung
bash resize.sh /path/to/images

# Nach HEIC konvertieren mit Qualität 80
bash resize.sh /path/to/images --format heic --quality 80

# Bildgröße deckeln auf max. 2000px Kantenlänge und umbenennen (vacation_001.jpg etc.)
bash resize.sh /path/to/images --max-size 2000 --rename vacation

# Bestehende Bilder direkt überschreiben (Destruktiv!)
bash resize.sh /path/to/images --replace --format avif

# Metadaten entfernen (Privacy Mode) und konvertieren
bash resize.sh /path/to/images --strip --format jxl

# Nach jedem Bild ein Skript oder Command ausführen
bash resize.sh /path/to/images --post-hook 'echo Verarbeitet: {out}'
```

---

## ⚙️ CLI Options & Reference

| Flag | Kurzform | Beschreibung | Standard |
| :--- | :--- | :--- | :--- |
| `--format` | `-f` | Ausgabeformat: `jpeg`, `heic`, `avif`, `webp`, `jxl`, `original` | `jpeg` |
| `--quality` | `-q` | Bildqualität (1–100) | Smart-Default pro Format |
| `--max-size` | `-m` | Maximale Kantenlänge in Pixeln (`0` = kein Resize) | `3000` |
| `--output` | `-o` | Zielverzeichnis für die konvertierten Bilder | `<input>/converted/` |
| `--replace` | | Überschreibt die Originaldateien direkt (**Achtung: Destruktiv!**) | aus |
| `--no-move` | | Verschiebt die Originale nicht in das `originals/` Backup-Verzeichnis | aus |
| `--rename NAME`| | Benennt Bilder um in `NAME_001`, `NAME_002` ... | Originalnamen |
| `--lossless` | | Verlustfreie Kompression (nur für AVIF & WebP) | aus |
| `--strip` | | EXIF-Metadaten (GPS etc.) restlos löschen (Privacy Mode) | aus |
| `--merge` | | Führt alle übergebenen Ordner/Dateien in einem Zielordner zusammen | aus |
| `--post-hook CMD`| | Führt Shell-Kommando nach jedem Bild aus (Platzhalter: `{in}`, `{out}`) | aus |

---

## 📁 Output Folder Modes

### Modus 1: Backup (Standard)
Originale bleiben erhalten und werden in den Ordner `originals/` verschoben, während die bereinigten/konvertierten Bilder in `converted/` landen:
```
input-folder/
├── converted/          ← Resized, optimiert & bereinigt
├── originals/          ← Unberührte Originaldateien (Backup)
└── ...
```

### Modus 2: In-Place Ersetzen (`--replace`)
Ersetzt die Originaldateien direkt an Ort und Stelle. Hilfreich, um schnell Speicherplatz auf der Festplatte freizugeben:
```
input-folder/
├── photo1.jpg          ← Direkt überschrieben mit optimierter Version
├── photo2.png          ← Direkt überschrieben und konvertiert
└── ...
```

---

## 📅 Changelog

### v1.0.0 (2026-07-05) - Initial Stable Release
- **JPEG XL (.jxl) Integration** – Native Unterstützung des Formats (erfordert `pillow-jxl-plugin`).
- **Privacy Mode (`--strip`)** – EXIF-Metadaten können nun restlos entfernt werden.
- **GIF-Animationen erhalten** – WebP/AVIF-Animationen werden nun frame-genau mit exakten, variablen Framelatenzen des Original-GIFs geschrieben.
- **Alpha-Kanal Erhalt** – Transparenz (Alpha-Kanal) wird beim Konvertieren nach WebP, AVIF und JXL vollständig beibehalten.
- **Performance Upgrade** – Aufhebung des CPU-Worker-Limits auf 8 Threads, um Multi-Core-Prozessoren (z.B. Apple Silicon M-Series) zu 100% auszulasten.
- **WebP-Performance Hotfix** – Anpassung der libwebp Kompressionsmethode von Stufe 6 auf Stufe 4 (Standard) für bis zu 100-fach schnellere Batch-Animationen.
- **Fenstertitel-Fortschritt** – Zeigt den aktuellen Fortschrittsprozentsatz direkt im Titel des Terminal-Fensters an.
- **Bugfixes** – Korrektur der Ausschluss-Logik für einzeln übergebene Argumente und Reparatur der Fallback-Formaterkennung im Wizard.

---

## 📄 License
Mit-Lizenz. Freie Nutzung für alle Landratten und Kapitäne.

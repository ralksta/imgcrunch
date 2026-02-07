#!/bin/bash
# ImgCrunch — launcher script
# Activates venv and runs the resizer. Pass CLI args or run without for wizard mode.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/venv/bin/activate"
python "$SCRIPT_DIR/batch_resizer.py" "$@"

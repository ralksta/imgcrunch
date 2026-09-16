#!/bin/bash
# ImgCrunch — launcher for the venv inside this clone.
# Pass CLI args, or run without any for the wizard.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -f "$SCRIPT_DIR/venv/bin/activate" ]]; then
    {
        echo "ImgCrunch: no virtual environment in $SCRIPT_DIR/venv."
        echo ""
        echo "Set it up once with:"
        echo "  cd \"$SCRIPT_DIR\" && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
        echo ""
        echo "or install the imgcrunch command for your user with:"
        echo "  pipx install \"$SCRIPT_DIR[all]\""
    } >&2
    exit 1
fi

source "$SCRIPT_DIR/venv/bin/activate"
exec python "$SCRIPT_DIR/imgcrunch.py" "$@"

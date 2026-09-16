#!/usr/bin/env python3
"""
Presets for ImgCrunch: a few built-in encoding recipes plus the last run.

Like sizing.py this imports no Pillow, so it is testable in milliseconds.

A preset only ever describes *how to encode* - format, quality, longest side,
byte budget, metadata. It never carries a mode (replace, rename, merge), so
picking one can never be the thing that destroys a file.
"""

import json
import os
import tomllib
from pathlib import Path
from typing import Optional

import sizing


# Mirrors imgcrunch.FORMAT_CONFIG; a test keeps the two in step. Duplicated
# rather than imported so this module stays free of Pillow.
VALID_FORMATS = ('jpeg', 'heic', 'avif', 'webp', 'jxl')

# The only keys a preset may hold, with the type each must have.
_FIELDS = {
    'format':      str,
    'quality':     int,
    'max_size':    int,
    'target_size': str,   # optional; absent means no byte budget
    'strip':       bool,
    'lossless':    bool,
}

BUILTIN_PRESETS = {
    'web': {
        'label': 'Web',
        'format': 'jpeg', 'quality': 85, 'max_size': 2000,
        'target_size': '500k', 'strip': True, 'lossless': False,
    },
    'archive': {
        'label': 'Archive',
        'format': 'jxl', 'quality': 90, 'max_size': 0,
        'target_size': None, 'strip': False, 'lossless': False,
    },
    'compact': {
        'label': 'Save space',
        'format': 'avif', 'quality': 60, 'max_size': 3000,
        'target_size': None, 'strip': False, 'lossless': False,
    },
}


def config_path() -> Path:
    """~/.config/imgcrunch/config.toml, honouring XDG_CONFIG_HOME."""
    base = os.environ.get('XDG_CONFIG_HOME')
    root = Path(base) if base else Path(os.environ.get('HOME', '~')).expanduser() / '.config'
    return root / 'imgcrunch' / 'config.toml'


def validate(settings: dict) -> Optional[dict]:
    """
    Return the encoding settings in canonical form, or None if they are unusable.

    Anything read from disk goes through here: a hand-edited or half-written
    config must fall back to the built-ins, never crash the wizard.
    """
    out = {}
    for key, kind in _FIELDS.items():
        value = settings.get(key)
        if key == 'target_size' and value is None:
            out[key] = None
            continue
        # bool is a subclass of int; `quality = true` must not pass as 1.
        if type(value) is not kind:
            return None
        out[key] = value

    if out['format'] not in VALID_FORMATS:
        return None
    if not 1 <= out['quality'] <= 100:
        return None
    if out['max_size'] < 0:
        return None
    if out['target_size'] is not None:
        try:
            sizing.parse_size(out['target_size'])
        except ValueError:
            return None
        if out['lossless']:
            return None
    return out


def describe(settings: dict) -> str:
    """One menu line: 'JPEG q85, 2000px, max 500k, EXIF stripped'."""
    parts = [f"{settings['format'].upper()} "
             f"{'lossless' if settings.get('lossless') else 'q' + str(settings['quality'])}"]
    parts.append(f"{settings['max_size']}px" if settings['max_size'] else "original size")
    if settings.get('target_size'):
        parts.append(f"max {settings['target_size']}")
    parts.append("EXIF stripped" if settings.get('strip') else "EXIF kept")
    return ", ".join(parts)


def load_last_run() -> Optional[dict]:
    """The remembered last run, or None if there is none or it is unusable."""
    try:
        with open(config_path(), 'rb') as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    last = data.get('last')
    if not isinstance(last, dict):
        return None
    return validate(last)


def save_last_run(settings: dict) -> None:
    """
    Remember the encoding settings of a run. Mode keys are dropped on purpose.

    Written by hand: the structure is one flat table, and tomllib only reads.
    Strings go through json.dumps, whose escaping is valid TOML basic-string
    escaping. Raises OSError; callers treat a failure as non-fatal.
    """
    clean = validate(settings)
    if clean is None:
        return

    lines = ['# Written by imgcrunch after each run. Safe to delete.', '[last]']
    for key in _FIELDS:
        value = clean[key]
        if value is None:
            continue                     # TOML has no null: absent means "none"
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        else:
            lines.append(f"{key} = {json.dumps(value)}")

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.toml.tmp')
    tmp.write_text("\n".join(lines) + "\n", encoding='utf-8')
    tmp.replace(path)

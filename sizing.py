#!/usr/bin/env python3
"""
Pure sizing and search arithmetic for ImgCrunch.

This module deliberately imports neither PIL nor anything that touches the
filesystem: every function here is a pure computation over numbers, so the
tricky parts (the target-size search in particular) can be tested against a
simulated encoder in milliseconds instead of against real AVIF encodes.
"""

import math
from typing import Callable, Optional


def needs_resize(width: int, height: int, max_size: int) -> bool:
    if max_size == 0:
        return False
    return width > max_size or height > max_size


def calculate_new_size(width: int, height: int, target: int) -> tuple[int, int]:
    # Clamp the short side to >=1: extreme aspect ratios (e.g. 100000x30)
    # can otherwise round to 0 and make Pillow's resize() raise.
    if width >= height:
        new_width  = target
        new_height = max(1, int(height * (target / width)))
    else:
        new_height = target
        new_width  = max(1, int(width * (target / height)))
    return new_width, new_height

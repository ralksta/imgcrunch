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


def search_quality(
    encode: Callable[[int], bytes],
    target_bytes: int,
    lo: int = 1,
    hi: int = 100,
) -> Optional[tuple[int, bytes]]:
    """
    Binary search the highest quality whose encode still fits target_bytes.

    `encode(quality) -> bytes` is injected so this stays testable without a
    real encoder. Runs at most 7 encodes (log2(100) is about 6.64), which is
    what keeps --target-size affordable on a large batch.

    Returns (quality, data), or None when even `lo` overshoots the target.
    """
    best: Optional[tuple[int, bytes]] = None

    for _ in range(7):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        data = encode(mid)
        if len(data) <= target_bytes:
            best = (mid, data)
            lo = mid + 1
        else:
            hi = mid - 1

    return best


def search_scale(
    probe: Callable[[int, int], tuple[Optional[bytes], int]],
    target_bytes: int,
    width: int,
    height: int,
    min_edge: int = 16,
    max_attempts: int = 16,
) -> Optional[bytes]:
    """
    Shrink the pixel dimensions until an encode fits target_bytes.

    `probe(w, h) -> (fit, floor)` does the quality search at one pixel size:
    `fit` is the data that fits (or None), `floor` is the size of the
    smallest possible encode there. Injecting it keeps every branch below
    testable without an encoder.

    Returns the best data found, or None if even min_edge overshoots.
    """
    fit, floor = probe(width, height)
    if fit is not None:
        return fit
    if floor <= 0:
        return None

    # Encoded size scales roughly with pixel count, so the edge scale needed
    # is about sqrt(target / current). Clamped: 0.95 because we already know
    # full size doesn't fit, 0.002 to stay off zero.
    scale = min(max(math.sqrt(target_bytes / floor), 0.002), 0.95)

    best: Optional[bytes] = None
    last: Optional[tuple[int, int]] = None
    grew = False

    for _ in range(max_attempts):
        w = max(min_edge, int(width * scale))
        h = max(min_edge, int(height * scale))

        # Integer rounding (or the min_edge floor) can produce the same pixel
        # size twice — without this the loop would spin without progress.
        if (w, h) == last:
            if scale <= 0.002:
                break
            scale = max(scale * 0.6, 0.002)
            continue
        last = (w, h)

        fit, floor_at = probe(w, h)

        if fit is not None:
            best = fit
            # Landing far under the budget means we threw away pixels we could
            # have kept. Try one size up — but only once, otherwise a borderline
            # image oscillates between two sizes until max_attempts runs out.
            if not grew and len(fit) < target_bytes * 0.85:
                new_scale = scale * 1.15
                if new_scale < 1.0:
                    grew = True
                    scale = new_scale
                    continue
            break

        # Still too big. floor_at > target_bytes here (otherwise probe would
        # have returned a fit), so the factor is always < 1 and the loop
        # strictly shrinks. The 0.6 cap stops a single wild estimate from
        # collapsing straight to min_edge.
        if floor_at > 0:
            scale = max(scale * max(math.sqrt(target_bytes / floor_at), 0.6), 0.002)
        else:
            scale = max(scale * 0.6, 0.002)

    return best

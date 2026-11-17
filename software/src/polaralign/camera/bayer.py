"""Bayer-mosaic bookkeeping for the colour IMX296 (Waveshare IMX296 Global Camera (A), SKU 32501)."""
from __future__ import annotations

import re

_FMT = re.compile(r"S?(RGGB|BGGR|GRBG|GBRG)\d+", re.IGNORECASE)


def pattern_from_format(fmt: str) -> str | None:
    """Tile pattern from a libcamera/V4L2 raw format name: ``"SBGGR10"`` -> ``"BGGR"``; mono formats
    (``"R10"``, ``"Y10"``) -> ``None``."""
    m = _FMT.search(fmt or "")
    return m.group(1).upper() if m else None


def flip_pattern(pattern: str | None, horizontal: bool = False, vertical: bool = False) -> str | None:
    """Tile pattern after flipping the *array* (even width/height assumed: the flip then swaps the parity).

    A horizontal flip turns RGGB into GRBG, a vertical one into GBRG, both into BGGR.
    """
    if not pattern:
        return pattern
    p = pattern.upper()
    if horizontal:
        p = p[1] + p[0] + p[3] + p[2]
    if vertical:
        p = p[2] + p[3] + p[0] + p[1]
    return p

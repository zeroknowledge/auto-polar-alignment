"""Development cameras: replay files, or call a function."""
from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..config import CameraConfig
from .base import Frame


class FakeCamera:
    """Returns frames from a callable ``source(exposure_s, gain) -> ndarray`` or from files.

    Files may be ``.npy`` (any 2-D array, e.g. a saved raw Bayer frame: pass ``bayer``) or anything Pillow
    reads (16-bit PNG/TIFF raw dumps are kept as they are; 8-bit colour images are converted to luminance); they are
    served in a loop.  With no source it produces a flat noise frame (nothing to solve).
    """

    name = "fake"

    def __init__(self, cfg: CameraConfig | None = None,
                 source: Callable[[float, float], np.ndarray] | list[str | Path] | None = None,
                 bayer: str | None = None) -> None:
        self.cfg = cfg or CameraConfig()
        self.bayer = bayer                 # tile pattern if the replayed arrays are raw mosaics (e.g. "RGGB")
        self._fn: Callable[[float, float], np.ndarray] | None = None
        self._files: itertools.cycle | None = None
        if callable(source):
            self._fn = source
        elif source:
            self._files = itertools.cycle([Path(p) for p in source])
        self._rng = np.random.default_rng(0)

    def capture(self, exposure_s: float | None = None, gain: float | None = None) -> Frame:
        exposure_s = self.cfg.exposure_s if exposure_s is None else exposure_s
        gain = self.cfg.gain if gain is None else gain
        if self._fn is not None:
            pix = self._fn(exposure_s, gain)
        elif self._files is not None:
            pix = self._load(next(self._files))
        else:
            pix = (self._rng.normal(60.0, 3.0, (self.cfg.height, self.cfg.width))).clip(0, 1023).astype(np.uint16)
        return Frame(pix, exposure_s, gain, datetime.now(timezone.utc), {"camera": "fake", "bayer": self.bayer})

    @staticmethod
    def _load(path: Path) -> np.ndarray:
        if path.suffix == ".npy":
            return np.load(path)
        from PIL import Image
        img = Image.open(path)
        if img.mode not in ("L", "I;16", "I"):
            img = img.convert("L")
        return np.asarray(img)

    def close(self) -> None:
        pass

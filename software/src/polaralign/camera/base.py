"""Camera interface."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass
class Frame:
    pixels: np.ndarray            # 2-D, uint16 (or uint8), linear: monochrome, or a raw Bayer mosaic (meta['bayer'])
    exposure_s: float
    gain: float
    timestamp: datetime
    meta: dict = field(default_factory=dict)      # 'bayer': tile pattern of the raw mosaic (e.g. 'RGGB'), None if mono

    @property
    def shape(self) -> tuple[int, int]:
        return self.pixels.shape[0], self.pixels.shape[1]


@runtime_checkable
class Camera(Protocol):
    name: str

    def capture(self, exposure_s: float | None = None, gain: float | None = None) -> Frame: ...
    def close(self) -> None: ...

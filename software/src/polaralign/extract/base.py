"""Star-extractor interface.

The aligner only ever talks to :class:`StarExtractor`; the implementation is chosen by
``config.extractor.backend`` through :func:`polaralign.extract.get_extractor`.  A third party (or a
later, faster implementation) can be dropped in by registering a new backend name.

Input is always a 2-D array: a monochrome frame, or a raw Bayer mosaic with its tile pattern passed as ``bayer``
(e.g. "RGGB").  Output coordinates are full-resolution either way.

Coordinate convention for every extractor: ``x`` is the column and ``y`` the row of the star
centre, with the *centre of the top-left pixel at (0.0, 0.0)*.  (tetra3 wants (0.5, 0.5); the solver
wrapper adds the half pixel.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

# quality flags (bit mask)
FLAG_SATURATED = 1
FLAG_BLENDED = 2
FLAG_ELONGATED = 4


@dataclass
class ExtractionResult:
    """Detected stars as parallel arrays, brightest first."""

    x: np.ndarray
    y: np.ndarray
    flux: np.ndarray            # background-subtracted aperture sum, ADU
    peak: np.ndarray            # background-subtracted peak pixel, ADU
    fwhm: np.ndarray            # estimated FWHM, pixels
    snr: np.ndarray             # background-limited signal-to-noise of the aperture sum
    flags: np.ndarray           # bit mask, see FLAG_*
    image_shape: tuple[int, int]
    background: float = 0.0     # median sky level per pixel, ADU
    noise: float = 0.0          # per-pixel noise, ADU
    n_candidates: int = 0
    timings_ms: dict[str, float] = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.x.shape[0])

    def good(self, allow_saturated: bool = True) -> "ExtractionResult":
        """Subset suitable for plate solving (no blends / streaks, optionally no saturated stars)."""
        bad = FLAG_BLENDED | FLAG_ELONGATED | (0 if allow_saturated else FLAG_SATURATED)
        keep = (self.flags & bad) == 0
        return self.select(keep)

    def select(self, mask: np.ndarray) -> "ExtractionResult":
        return ExtractionResult(
            x=self.x[mask], y=self.y[mask], flux=self.flux[mask], peak=self.peak[mask],
            fwhm=self.fwhm[mask], snr=self.snr[mask], flags=self.flags[mask],
            image_shape=self.image_shape, background=self.background, noise=self.noise,
            n_candidates=self.n_candidates, timings_ms=dict(self.timings_ms))

    def centroids_yx(self) -> np.ndarray:
        """(N, 2) array of (row, col), pixel centre of the top-left pixel at (0, 0)."""
        return np.column_stack([self.y, self.x])

    @staticmethod
    def empty(shape: tuple[int, int]) -> "ExtractionResult":
        z = np.zeros(0)
        return ExtractionResult(z, z, z, z, z, z, np.zeros(0, dtype=np.int32), shape)


@runtime_checkable
class StarExtractor(Protocol):
    """Anything that turns a 2-D image (mono or raw Bayer) into a brightness-ordered star list."""

    name: str

    def extract(self, image: np.ndarray, bayer: str | None = None) -> ExtractionResult: ...

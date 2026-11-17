"""Adapter that exposes tetra3's own (Apache-2.0) centroider behind the StarExtractor interface.

Not the default: it exists as a second backend so the swappable interface is exercised, and so the
benchmark can compare our extractor with a freely licensed alternative on identical frames.
"""
from __future__ import annotations

import time

import numpy as np

from ..config import ExtractorConfig
from .base import ExtractionResult


class Tetra3Extractor:
    name = "tetra3"

    def __init__(self, cfg: ExtractorConfig | None = None) -> None:
        self.cfg = cfg or ExtractorConfig()

    def extract(self, image: np.ndarray, bayer: str | None = None) -> ExtractionResult:
        import tetra3  # imported lazily: only needed when this backend is selected

        t0 = time.perf_counter()
        img = np.asarray(image, dtype=np.float32)
        scale = 1
        if bayer or self.cfg.bayer_pattern:       # no mosaic support in tetra3's centroider: sum each 2x2 cell
            h2, w2 = img.shape[0] // 2, img.shape[1] // 2
            img = (img[0:2 * h2:2, 0:2 * w2:2] + img[0:2 * h2:2, 1:2 * w2:2] + img[1:2 * h2:2, 0:2 * w2:2]
                   + img[1:2 * h2:2, 1:2 * w2:2])
            scale = 2
        out = tetra3.get_centroids_from_image(
            img, sigma=self.cfg.threshold_sigma, filtsize=31, bg_sub_mode="local_mean",
            sigma_mode="global_root_square", binary_open=True, min_area=4, max_area=150,
            max_returned=self.cfg.max_stars, return_moments=True)
        cents = np.asarray(out[0]) if isinstance(out, tuple) else np.asarray(out)
        n = cents.shape[0]
        if n == 0:
            return ExtractionResult.empty(img.shape)
        # with return_moments=True tetra3 returns (centroids, [sums, areas, moments, axis_ratios])
        sums = np.asarray(out[1][0]) if isinstance(out, tuple) and len(out) > 1 else np.ones(n)
        # tetra3: (y, x) with the top-left pixel centre at (0.5, 0.5)  ->  centre at (0, 0)
        y = cents[:, 0] - 0.5
        x = cents[:, 1] - 0.5
        if scale == 2:                            # binned pixel centre (i, j) is at full-resolution (2i + 0.5, 2j + 0.5)
            x, y = 2.0 * x + 0.5, 2.0 * y + 0.5
        z = np.zeros(n)
        return ExtractionResult(x=x, y=y, flux=np.asarray(sums, dtype=float), peak=z, fwhm=z + 3.0, snr=z + 10.0,
                                flags=np.zeros(n, dtype=np.int32), image_shape=(img.shape[0] * scale, img.shape[1] * scale),
                                timings_ms={"total": (time.perf_counter() - t0) * 1e3})

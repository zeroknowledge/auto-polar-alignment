"""Our own star extractor (numpy + scipy only; no Cedar Detect, no OpenCV).

Works on monochrome frames and on raw Bayer mosaics (the colour IMX296 camera): detection sums 2x2 cells, which is
colour-agnostic for any Bayer pattern; measurement removes the per-channel sky offsets and centroids either every
pixel (default) or the green pixels only (``extractor.bayer_mode``).

Pipeline, designed so that the expensive passes touch as few pixels as possible (target: a
Pi Zero 2 W, 4 x Cortex-A53 @ 1 GHz, 512 MB):

1. **2x2 binning** straight from the uint16 frame into float32 (a quarter of the pixels, and a
   ~2x signal-to-noise gain for star-sized objects).  The full-resolution image is never converted.
2. **Background mesh**: per-cell median and MAD from a sub-sample of each 32x32 px cell, bilinear
   interpolation back to the binned grid.
3. **Candidates**: pixels of the background-subtracted binned image above ``k`` sigma that are
   3x3 local maxima (found by gathering neighbours of the few thousand over-threshold pixels, not by
   filtering the whole image).
4. **Measurement at full resolution** on (2r+1)^2 windows gathered with fancy indexing: local
   background from the window ring, iterated Gaussian-weighted centroid (sub-pixel), aperture flux,
   FWHM from flux/peak, elongation from weighted second moments.
5. Reject hot pixels (too sharp), blobs, and mark blends, saturated and elongated objects.

All per-candidate work is vectorised over the candidate axis, so cost scales with the number of
stars, not with the frame size, apart from the cheap binning/mesh passes.
"""
from __future__ import annotations

import time

import numpy as np

from ..config import ExtractorConfig
from .base import (FLAG_BLENDED, FLAG_ELONGATED, FLAG_SATURATED, ExtractionResult, StarExtractor)


class NumpyStarExtractor:
    name = "numpy"

    def __init__(self, cfg: ExtractorConfig | None = None, hot_pixel_mask: np.ndarray | None = None) -> None:
        self.cfg = cfg or ExtractorConfig()
        self.hot_pixel_mask = hot_pixel_mask       # optional static mask (True = bad pixel)
        r = self.cfg.window_radius_px
        self._w = 2 * r + 1
        yy, xx = np.mgrid[0:self._w, 0:self._w].astype(np.float32)
        self._xg = xx
        self._yg = yy
        ring = np.zeros((self._w, self._w), dtype=bool)
        ring[0, :] = ring[-1, :] = ring[:, 0] = ring[:, -1] = True
        self._ring = ring
        rr = np.hypot(xx - r, yy - r)
        self._aperture = (rr <= r + 0.5).astype(np.float32)   # circular aperture inside the window
        self._napix = float(self._aperture.sum())

    # ------------------------------------------------------------------
    @staticmethod
    def _channel_of_parity(pattern: str) -> np.ndarray:
        """0/1/2 = R/G/B for the four (row&1, col&1) positions of a row-major Bayer tile such as "RGGB"."""
        pattern = pattern.upper()
        if len(pattern) != 4 or set(pattern) - set("RGB") or pattern.count("G") != 2:
            raise ValueError(f"bad Bayer pattern {pattern!r} (expected e.g. 'RGGB')")
        return np.array(["RGB".index(c) for c in pattern], dtype=np.int8)

    def extract(self, image: np.ndarray, bayer: str | None = None) -> ExtractionResult:
        """``image`` is a 2-D array: a monochrome frame, or a raw Bayer mosaic when ``bayer`` (e.g. "RGGB",
        the tile read row-major from the top-left pixel) is given or ``cfg.bayer_pattern`` is set."""
        cfg = self.cfg
        t0 = time.perf_counter()
        img = np.asarray(image)
        pattern = (bayer if bayer is not None else cfg.bayer_pattern) or ""
        if img.ndim != 2:
            raise ValueError("expected a 2-D image (monochrome, or a raw Bayer mosaic)")
        h, w = img.shape
        b = cfg.bin_factor
        if b != 2:
            raise ValueError("only bin_factor=2 is implemented")
        h2, w2 = h // 2, w // 2

        # 1. bin 2x2 (sum), straight into float32 --------------------------------------
        binned = np.add(img[0:2 * h2:2, 0:2 * w2:2], img[0:2 * h2:2, 1:2 * w2:2], dtype=np.float32)
        binned += img[1:2 * h2:2, 0:2 * w2:2]
        binned += img[1:2 * h2:2, 1:2 * w2:2]
        t1 = time.perf_counter()

        # 2. background mesh --------------------------------------------------------------
        bb = max(8, cfg.bg_block_px // 2)
        mh, mw = h2 // bb, w2 // bb
        crop = binned[:mh * bb, :mw * bb]
        cells = crop.reshape(mh, bb, mw, bb)[:, ::2, :, ::2]                 # sub-sample 1/4
        cells = cells.transpose(0, 2, 1, 3).reshape(mh, mw, -1)
        bg_grid = np.median(cells, axis=2)
        mad = np.median(np.abs(cells - bg_grid[:, :, None]), axis=2)
        sig_grid = np.maximum(1.4826 * mad, 1e-3)
        cy = (np.arange(mh) + 0.5) * bb - 0.5
        cx = (np.arange(mw) + 0.5) * bb - 0.5
        bg_full = self._bilinear_grid(bg_grid, cy, cx, h2, w2)
        sigma_bin = float(np.median(sig_grid))
        t2 = time.perf_counter()

        # 3. candidates ----------------------------------------------------------------------
        binned -= bg_full
        k = cfg.threshold_sigma
        ys, xs = np.nonzero(binned > 0.8 * k * sigma_bin)           # loose pre-threshold
        res_shape = (h, w)
        if ys.size == 0:
            res = ExtractionResult.empty(res_shape)
            res.background = float(np.median(bg_grid)) / 4.0
            res.noise = sigma_bin / 2.0
            res.timings_ms = {"bin": (t1 - t0) * 1e3, "background": (t2 - t1) * 1e3, "total": (time.perf_counter() - t0) * 1e3}
            return res
        padded = np.pad(binned, 1, mode="constant", constant_values=-1e30)
        center = padded[ys + 1, xs + 1]
        is_max = np.ones(ys.shape, dtype=bool)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                nb = padded[ys + 1 + dy, xs + 1 + dx]
                # ties: strictly greater than the "earlier" neighbours, >= the later ones
                is_max &= (center > nb) if (dy, dx) < (0, 0) else (center >= nb)
        ys, xs, center = ys[is_max], xs[is_max], center[is_max]
        # local sigma at the candidate (bilinear sample of the noise mesh)
        sig_loc = self._sample_grid(sig_grid, cy, cx, ys, xs)
        keep = center > k * sig_loc
        ys, xs = ys[keep], xs[keep]
        n_cand = int(ys.size)
        edge = cfg.border_px
        # full-resolution start position: centre of the 2x2 cell
        y0 = 2 * ys + 0.5
        x0 = 2 * xs + 0.5
        keep = (y0 > edge) & (y0 < h - 1 - edge) & (x0 > edge) & (x0 < w - 1 - edge)
        y0, x0 = y0[keep], x0[keep]
        # sky level per pixel at each candidate from the (smooth, low-variance) background mesh.  A
        # background taken from the 32-pixel window ring has +-0.5 ADU noise per pixel, which over a
        # 60-pixel aperture is a +-30 ADU flux error: as large as a faint star.
        bg_pix = bg_full[ys[keep], xs[keep]] * 0.25
        t3 = time.perf_counter()
        if y0.size == 0:
            res = ExtractionResult.empty(res_shape)
            res.n_candidates = n_cand
            res.background = float(np.median(bg_grid)) / 4.0
            res.noise = sigma_bin / 2.0
            return res

        # 4. measurement at full resolution -----------------------------------------------------
        r = cfg.window_radius_px
        w_ = self._w
        oy = np.floor(y0).astype(np.int64) - r        # window origin (top-left pixel of window)
        ox = np.floor(x0).astype(np.int64) - r
        offs = np.arange(w_)
        rows = (oy[:, None] + offs[None, :])          # (N, w)
        cols = (ox[:, None] + offs[None, :])
        cube = img[rows[:, :, None], cols[:, None, :]].astype(np.float32)   # (N, w, w)
        if self.hot_pixel_mask is not None:
            bad = self.hot_pixel_mask[rows[:, :, None], cols[:, None, :]]
            if bad.any():
                med = np.median(cube, axis=(1, 2), keepdims=True)
                cube = np.where(bad, med, cube)
        sat = (cube >= cfg.saturation_adu).any(axis=(1, 2))
        gmask = None
        if pattern:
            # Bayer mosaic: each pixel position has its own channel, hence its own sky level; the mesh (cell sums)
            # gives the mean, a few per-plane medians give the offsets.
            chan_par = self._channel_of_parity(pattern)
            plane_med = np.array([np.median(img[r_::2, c_::2][::8, ::8]) for r_ in (0, 1) for c_ in (0, 1)], dtype=np.float32)
            plane_off = plane_med - plane_med.mean()
            par = (rows[:, :, None] & 1) * 2 + (cols[:, None, :] & 1)                # (N, w, w) in 0..3
            cube -= bg_pix.astype(np.float32)[:, None, None] + plane_off[par]
            if cfg.bayer_mode == "green":
                gmask = (chan_par[par] == 1).astype(np.float32)
        else:
            cube -= bg_pix.astype(np.float32)[:, None, None]

        # iterated Gaussian-weighted centroid (window coordinates)
        sig_w = cfg.centroid_sigma_px
        cxw = (x0 - ox).astype(np.float32)
        cyw = (y0 - oy).astype(np.float32)
        # start from the brightest pixel of the 3x3-smoothed window to get inside the PSF core
        for _ in range(5):
            wgt = np.exp(-((self._xg[None] - cxw[:, None, None]) ** 2 + (self._yg[None] - cyw[:, None, None]) ** 2)
                         / (2.0 * sig_w * sig_w))
            if gmask is not None:
                wgt = wgt * gmask
            m = cube * wgt
            s = m.sum(axis=(1, 2))
            s = np.where(np.abs(s) < 1e-6, 1e-6, s)
            ncx = (m * self._xg[None]).sum(axis=(1, 2)) / s
            ncy = (m * self._yg[None]).sum(axis=(1, 2)) / s
            # keep the estimate inside the window core
            ncx = np.clip(ncx, 1.0, w_ - 2.0)
            ncy = np.clip(ncy, 1.0, w_ - 2.0)
            cxw, cyw = ncx.astype(np.float32), ncy.astype(np.float32)

        noise_pix = sigma_bin / 2.0
        if gmask is not None:                    # green samples only: scale to the whole aperture (x2) for ranking
            flux = 2.0 * (cube * self._aperture[None] * gmask).sum(axis=(1, 2))
            peak = np.where(gmask > 0, cube, -1e30).reshape(cube.shape[0], -1).max(axis=1)
            snr = flux / (2.0 * noise_pix * np.sqrt(self._napix / 2.0) + 1e-9)
        else:
            flux = (cube * self._aperture[None]).sum(axis=(1, 2))
            peak = cube.reshape(cube.shape[0], -1).max(axis=1)
            snr = flux / (noise_pix * np.sqrt(self._napix) + 1e-9)
        with np.errstate(divide="ignore", invalid="ignore"):
            sigma_est = np.sqrt(np.maximum(flux, 1e-9) / (2.0 * np.pi * np.maximum(peak, 1e-9)))
        fwhm = 2.3548 * sigma_est

        # weighted second moments -> elongation
        wgt = np.exp(-((self._xg[None] - cxw[:, None, None]) ** 2 + (self._yg[None] - cyw[:, None, None]) ** 2)
                     / (2.0 * (1.3 * sig_w) ** 2))
        m = np.maximum(cube, 0.0) * wgt
        if gmask is not None:
            m = m * gmask
        s = np.maximum(m.sum(axis=(1, 2)), 1e-9)
        dx = self._xg[None] - cxw[:, None, None]
        dy = self._yg[None] - cyw[:, None, None]
        sxx = (m * dx * dx).sum(axis=(1, 2)) / s
        syy = (m * dy * dy).sum(axis=(1, 2)) / s
        sxy = (m * dx * dy).sum(axis=(1, 2)) / s
        tr = sxx + syy
        det = np.sqrt(np.maximum((sxx - syy) ** 2 + 4 * sxy * sxy, 0.0))
        l1 = 0.5 * (tr + det)
        l2 = np.maximum(0.5 * (tr - det), 1e-9)
        elong = 1.0 - np.sqrt(l2 / np.maximum(l1, 1e-9))
        if pattern:
            # flux/peak is meaningless on a mosaic (the peak is one colour channel); use the second moment, undoing
            # the Gaussian window:  1/sigma_m^2 = 1/sigma_psf^2 + 1/sigma_w^2
            inv = 1.0 / np.maximum(0.5 * (sxx + syy), 1e-6) - 1.0 / (1.3 * sig_w) ** 2
            fwhm = 2.3548 * np.sqrt(np.where(inv > 1e-6, 1.0 / np.maximum(inv, 1e-6), 1e3))

        xs_f = ox + cxw.astype(np.float64)
        ys_f = oy + cyw.astype(np.float64)

        ok = (snr >= 0.8 * k) & (flux > 0) & (peak > 0)
        ok &= fwhm >= 1.25                              # a single hot pixel gives ~0.9
        ok &= fwhm <= 12.0
        ok &= (xs_f > edge) & (xs_f < w - 1 - edge) & (ys_f > edge) & (ys_f < h - 1 - edge)
        xs_f, ys_f, flux, peak, fwhm, snr, sat, elong = (a[ok] for a in (xs_f, ys_f, flux, peak, fwhm, snr, sat, elong))

        flags = np.zeros(xs_f.shape[0], dtype=np.int32)
        flags[sat] |= FLAG_SATURATED
        flags[elong > 0.55] |= FLAG_ELONGATED

        # 5. de-duplicate and flag blends ------------------------------------------------------
        order = np.argsort(-flux)
        xs_f, ys_f, flux, peak, fwhm, snr, flags = (a[order] for a in (xs_f, ys_f, flux, peak, fwhm, snr, flags))
        xs_f, ys_f, flux, peak, fwhm, snr, flags = self._merge(xs_f, ys_f, flux, peak, fwhm, snr, flags)
        n = min(len(xs_f), cfg.max_stars)
        t4 = time.perf_counter()
        res = ExtractionResult(
            x=xs_f[:n], y=ys_f[:n], flux=flux[:n].astype(np.float64), peak=peak[:n].astype(np.float64),
            fwhm=fwhm[:n].astype(np.float64), snr=snr[:n].astype(np.float64), flags=flags[:n],
            image_shape=res_shape, background=float(np.median(bg_grid)) / 4.0, noise=noise_pix,
            n_candidates=n_cand,
            timings_ms={"bin": (t1 - t0) * 1e3, "background": (t2 - t1) * 1e3,
                        "candidates": (t3 - t2) * 1e3, "measure": (t4 - t3) * 1e3, "total": (t4 - t0) * 1e3})
        return res

    # ------------------------------------------------------------------
    @staticmethod
    def _bilinear_grid(grid: np.ndarray, cy: np.ndarray, cx: np.ndarray, h: int, w: int) -> np.ndarray:
        """Bilinear interpolation of a coarse mesh to (h, w); edges clamp to the outer cells."""
        mh, mw = grid.shape
        xq = np.arange(w, dtype=np.float32)
        rows = np.empty((mh, w), dtype=np.float32)
        for i in range(mh):
            rows[i] = np.interp(xq, cx, grid[i])
        yq = np.arange(h, dtype=np.float32)
        pos = np.clip((yq - cy[0]) / (cy[1] - cy[0]) if mh > 1 else np.zeros_like(yq), 0, mh - 1 - 1e-6)
        i0 = pos.astype(np.int64)
        f = (pos - i0).astype(np.float32)[:, None]
        i1 = np.minimum(i0 + 1, mh - 1)
        out = rows[i0] * (1.0 - f)
        out += rows[i1] * f
        return out

    @staticmethod
    def _sample_grid(grid: np.ndarray, cy: np.ndarray, cx: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
        mh, mw = grid.shape
        py = np.clip((ys - cy[0]) / (cy[1] - cy[0]) if mh > 1 else np.zeros(ys.shape), 0, mh - 1 - 1e-6)
        px = np.clip((xs - cx[0]) / (cx[1] - cx[0]) if mw > 1 else np.zeros(xs.shape), 0, mw - 1 - 1e-6)
        iy, ix = py.astype(np.int64), px.astype(np.int64)
        fy, fx = py - iy, px - ix
        iy1, ix1 = np.minimum(iy + 1, mh - 1), np.minimum(ix + 1, mw - 1)
        return (grid[iy, ix] * (1 - fy) * (1 - fx) + grid[iy1, ix] * fy * (1 - fx)
                + grid[iy, ix1] * (1 - fy) * fx + grid[iy1, ix1] * fy * fx)

    def _merge(self, x, y, flux, peak, fwhm, snr, flags):
        """Drop duplicate detections of one star (flat-topped saturated stars give several local
        maxima) and flag close pairs as blended.  Input is sorted brightest first."""
        n = len(x)
        if n < 2:
            return x, y, flux, peak, fwhm, snr, flags
        dx = x[:, None] - x[None, :]
        dy = y[:, None] - y[None, :]
        d = np.hypot(dx, dy)
        np.fill_diagonal(d, np.inf)
        keep = np.ones(n, dtype=bool)
        for i in range(n):
            if not keep[i]:
                continue
            dup = np.nonzero((d[i] < 2.2) & keep)[0]
            dup = dup[dup > i]                       # fainter ones only
            keep[dup] = False
        # a neighbour inside ~the centroid window (or 2.5 FWHM) biases the centroid: flag both stars
        blend = ((d < np.maximum(6.0, 2.5 * fwhm[:, None])) & keep[None, :] & keep[:, None]).any(axis=1)
        flags = flags.copy()
        flags[blend] |= FLAG_BLENDED
        return (x[keep], y[keep], flux[keep], peak[keep], fwhm[keep], snr[keep], flags[keep])


assert isinstance(NumpyStarExtractor(), StarExtractor)

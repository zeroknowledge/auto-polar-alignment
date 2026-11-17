"""Synthetic star-field frames with a physically motivated noise model.

Stars become pixel-integrated Gaussians (error-function integrals, so sub-pixel positions are
exact), flux follows ``mag0_e_per_s * 10**(-0.4 mag) * exposure``.  Noise: Poisson (stars + sky +
dark), Gaussian read noise, quantisation, black level and saturation at the ADC limit, plus a few hot
pixels and an optional sky gradient.  Seeing is modelled as a per-frame tip/tilt plus small
per-star jitter.  Default numbers are chosen so that a 0.5 s frame of a 16 mm f/1.4 lens reaches about
magnitude 8; the README says plainly that this is not a measurement of real optics.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.special import erf

from .camera_model import CameraModel


@dataclass
class SensorParams:
    mag0_e_per_s: float = 2.5e5          # electrons per second in the PSF from a magnitude-0 star
    sky_e_per_s_px: float = 2.0          # sky background, electrons / s / pixel
    dark_e_per_s_px: float = 0.2
    read_noise_e: float = 2.5
    gain_e_per_adu: float = 2.0
    black_level_adu: float = 40.0
    max_adu: int = 1023                  # 10 bit
    psf_fwhm_px: float = 2.8
    tip_tilt_px: float = 0.08            # per-frame common shift (seeing / vibration), sigma
    seeing_px: float = 0.05              # independent per-star jitter, sigma
    n_hot_pixels: int = 40
    hot_pixel_adu_s: float = 150.0       # mean hot-pixel dark level, ADU/s
    sky_gradient: float = 0.3            # fractional sky brightness change across the frame
    hot_seed: int = 7
    # Colour sensor (Waveshare IMX296 Global Camera (A), SKU 32501: Bayer mosaic + integrated IR-cut filter).
    cfa: str = ""                        # "" = monochrome; "RGGB", "BGGR", "GRBG", "GBRG" = Bayer tile, row-major
    cfa_transmission: tuple[float, float, float] = (0.35, 0.50, 0.30)   # R, G, B response relative to the mono sensor
    star_colour_spread: float = 0.6      # per-star red/blue imbalance: R x (1+s*t), B x (1-s*t), t in [-1, 1]


class FrameRenderer:
    def __init__(self, camera: CameraModel, params: SensorParams | None = None) -> None:
        self.camera = camera
        self.p = params or SensorParams()
        rng = np.random.default_rng(self.p.hot_seed)
        n = self.p.n_hot_pixels
        self._hot_y = rng.integers(8, camera.height - 8, n)
        self._hot_x = rng.integers(8, camera.width - 8, n)
        self._hot_level = rng.exponential(self.p.hot_pixel_adu_s, n) * self.p.gain_e_per_adu
        self._chan: np.ndarray | None = None
        self._resp: np.ndarray | None = None
        if self.p.cfa:
            idx = {"R": 0, "G": 1, "B": 2}
            tile = np.array([[idx[self.p.cfa[0]], idx[self.p.cfa[1]]], [idx[self.p.cfa[2]], idx[self.p.cfa[3]]]], dtype=np.uint8)
            yy, xx = np.indices((camera.height, camera.width))
            self._chan = tile[yy & 1, xx & 1]
            self._resp = np.asarray(self.p.cfa_transmission, dtype=np.float32)[self._chan]
        gy, gx = np.mgrid[0:camera.height, 0:camera.width].astype(np.float32)
        gradient = 1.0 + self.p.sky_gradient * ((gx / camera.width - 0.5) + 0.5 * (gy / camera.height - 0.5))
        self._sky_shape = gradient.astype(np.float32)

    # ------------------------------------------------------------------
    @staticmethod
    def star_redness(ids: np.ndarray) -> np.ndarray:
        """Deterministic pseudo-colour in [-1, 1] per catalogue index (the catalogue has no colour index)."""
        frac = np.abs(np.modf(np.sin(np.asarray(ids, dtype=np.float64) * 12.9898) * 43758.5453)[0])
        return 2.0 * frac - 1.0

    def render(self, v_cam: np.ndarray, mag: np.ndarray, exposure_s: float, rng: np.random.Generator,
               gain: float = 1.0, return_truth: bool = False, star_ids: np.ndarray | None = None):
        """Render stars given as camera-frame unit vectors (N, 3) and magnitudes.

        With ``params.cfa`` set the frame is a Bayer mosaic: each pixel sees the star through its colour filter,
        so a red star lights the R pixels more than the B ones (the effect the extractor must cope with).
        """
        cam, p = self.camera, self.p
        sigma = p.psf_fwhm_px / 2.3548
        col, row, front = cam.project(v_cam)
        col = col + rng.normal(0, p.tip_tilt_px) + rng.normal(0, p.seeing_px, col.shape)
        row = row + rng.normal(0, p.tip_tilt_px) + rng.normal(0, p.seeing_px, row.shape)
        ok = front & cam.in_frame(col, row, margin=6.0)
        ids = np.arange(len(ok)) if star_ids is None else np.asarray(star_ids)
        col, row, m, ids = col[ok], row[ok], np.asarray(mag)[ok], ids[ok]
        t_col = self.star_redness(ids)
        flux = p.mag0_e_per_s * 10.0 ** (-0.4 * m) * exposure_s

        sky = (p.sky_e_per_s_px + p.dark_e_per_s_px) * exposure_s * self._sky_shape
        if self._resp is not None:
            sky = sky * self._resp
        img = sky.copy()
        rw = int(np.ceil(4.0 * sigma)) + 1
        offs = np.arange(-rw, rw + 1)
        s2 = sigma * np.sqrt(2.0)
        for cx, cy, f, tc in zip(col, row, flux, t_col):
            ix, iy = int(round(cx)), int(round(cy))
            xs = ix + offs
            ys = iy + offs
            gx = 0.5 * (erf((xs + 0.5 - cx) / s2) - erf((xs - 0.5 - cx) / s2))
            gy = 0.5 * (erf((ys + 0.5 - cy) / s2) - erf((ys - 0.5 - cy) / s2))
            x0, x1 = max(xs[0], 0), min(xs[-1] + 1, cam.width)
            y0, y1 = max(ys[0], 0), min(ys[-1] + 1, cam.height)
            if x0 >= x1 or y0 >= y1:
                continue
            patch = (f * np.outer(gy[y0 - ys[0]:y1 - ys[0]], gx[x0 - xs[0]:x1 - xs[0]])).astype(np.float32)
            if self._resp is not None:
                wch = np.array([1.0 + p.star_colour_spread * tc, 1.0, 1.0 - p.star_colour_spread * tc], dtype=np.float32)
                patch *= self._resp[y0:y1, x0:x1] * wch[self._chan[y0:y1, x0:x1]]
            img[y0:y1, x0:x1] += patch
        img[self._hot_y, self._hot_x] += self._hot_level * exposure_s          # hot pixels are not colour dependent

        electrons = rng.poisson(img).astype(np.float32)
        electrons += rng.normal(0.0, p.read_noise_e, img.shape).astype(np.float32)
        adu = electrons * (gain / p.gain_e_per_adu) + p.black_level_adu
        np.rint(adu, out=adu)
        np.clip(adu, 0, p.max_adu, out=adu)
        frame = adu.astype(np.uint16)
        if return_truth:
            return frame, {"col": col, "row": row, "mag": m, "flux_e": flux}
        return frame

"""Pinhole + radial-distortion camera model, identical in convention to tetra3's.

Pixel coordinates here use the *pixel-centre* convention of the rest of polaralign (the centre
of the top-left pixel is (0, 0)); tetra3 uses (0.5, 0.5), the solver wrapper converts.
Distortion follows tetra3: ``r_u = r_d (1 - k r_d^2) / (1 - k)`` with radii normalised to half the
image width (k < 0 barrel, k > 0 pincushion).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class CameraModel:
    width: int = 1456
    height: int = 1088
    focal_px: float = 16.0e3 / 3.45          # 16 mm lens, 3.45 um pixels
    distortion: float = 0.0                  # tetra3 'k'

    @property
    def fov_h_deg(self) -> float:
        return math.degrees(2 * math.atan(self.width / 2 / self.focal_px))

    @property
    def fov_v_deg(self) -> float:
        return math.degrees(2 * math.atan(self.height / 2 / self.focal_px))

    @property
    def diag_half_angle_rad(self) -> float:
        return math.atan(math.hypot(self.width, self.height) / 2 / self.focal_px)

    # ------------------------------------------------------------------
    def project(self, v_cam: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Camera-frame unit vectors (N, 3) -> (x, y, in_front) in pixel-centre coordinates."""
        x_c, y_c, z_c = v_cam[:, 0], v_cam[:, 1], v_cam[:, 2]
        front = x_c > 1e-6
        safe = np.where(front, x_c, 1.0)
        # pixel edges at integers: column = w/2 - f*y/x ; row = h/2 - f*z/x
        col_u = -self.focal_px * y_c / safe
        row_u = -self.focal_px * z_c / safe
        if self.distortion != 0.0:
            col_u, row_u = self._distort(col_u, row_u)
        col = self.width / 2.0 + col_u - 0.5
        row = self.height / 2.0 + row_u - 0.5
        return col, row, front

    def _distort(self, cu: np.ndarray, ru: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        k = self.distortion
        r_u = np.hypot(cu, ru) / self.width * 2.0
        r_d = r_u.copy()
        for _ in range(30):
            est = r_d * (1 - k * r_d ** 2) / (1 - k)
            slope = (1 - 3 * k * r_d ** 2) / (1 - k)
            err = r_u - est
            r_d += err / slope
            if np.all(np.abs(err) < 1e-9):
                break
        scale = np.divide(r_d, r_u, out=np.ones_like(r_u), where=r_u > 0)
        return cu * scale, ru * scale

    def in_frame(self, col: np.ndarray, row: np.ndarray, margin: float = 0.0) -> np.ndarray:
        return (col > -margin) & (col < self.width - 1 + margin) & (row > -margin) & (row < self.height - 1 + margin)

    def pixel_to_vector(self, col: np.ndarray, row: np.ndarray) -> np.ndarray:
        """Inverse projection for undistorted frames (used in tests)."""
        col_e = np.asarray(col) + 0.5 - self.width / 2.0
        row_e = np.asarray(row) + 0.5 - self.height / 2.0
        v = np.stack([np.ones_like(col_e, dtype=float), -col_e / self.focal_px, -row_e / self.focal_px], axis=-1)
        return v / np.linalg.norm(v, axis=-1, keepdims=True)

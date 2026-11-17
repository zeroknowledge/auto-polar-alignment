"""Robust pose refinement after the pattern match has identified the field.

tetra3 accepts a star as matched if it lies within ``match_radius`` (1 % of the image width,
about 14 px) of its predicted position, and fits rotation, FOV and distortion to *all* of those,
so one false match inflates the reported RMSE and pulls the pose.  We therefore re-do the last step
ourselves, starting from tetra3's answer:

1. project every catalogue star in the field with the current (rotation, focal length, distortion),
2. match to *all* extracted stars (nearest neighbour, one to one) with a radius shrinking 6 -> 3 -> 2 px,
3. fit rotation (3), focal length (1) and radial distortion (1) with a soft-L1 loss in pixel space,
4. repeat with the improved model (picks up fainter stars and tolerates a start a few pixels off).

The camera model is the same pinhole + one-parameter radial distortion that tetra3 uses, so the
results are directly comparable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from ..sim.camera_model import CameraModel


@dataclass
class RefinedPose:
    rotation: np.ndarray      # 3x3 celestial -> camera
    focal_px: float
    fov_deg: float
    distortion: float
    rms_px: float
    rmse_arcsec: float
    n_inliers: int
    n_stars: int
    ok: bool


def refine_pose(rotation: np.ndarray, fov_deg: float, distortion: float | None, width: int, height: int,
                cat_vec: np.ndarray, star_xy: np.ndarray, match_px: float = 2.0, iterations: int = 3,
                inlier_px: float = 1.0) -> RefinedPose:
    """``star_xy``: (N, 2) extracted centroids (col, row) with the pixel-centre convention."""
    k = 0.0 if distortion is None else float(distortion)
    f = (width / 2.0) / math.tan(math.radians(fov_deg) / 2.0)
    rot = np.array(rotation, dtype=float)
    cam = CameraModel(width, height, f, k)
    half_diag = cam.diag_half_angle_rad * 1.05
    n_in = 0
    rms = float("nan")
    pairs_cat = pairs_xy = np.zeros((0, 3))
    # coarse to fine: a wide first match tolerates a start a few pixels off, the last pass is tight
    radii = ([3.0 * match_px, 1.5 * match_px, match_px] if iterations >= 3 else [1.5 * match_px, match_px])[-max(1, iterations):]
    for match_px in radii:
        cam = CameraModel(width, height, f, k)
        sel = np.nonzero(cat_vec @ rot[0] > math.cos(half_diag))[0]
        vc = (rot @ cat_vec[sel].T).T
        col, row, front = cam.project(vc)
        ok = front & cam.in_frame(col, row, margin=2.0)
        sel, col, row = sel[ok], col[ok], row[ok]
        if sel.size < 6:
            break
        tree = cKDTree(np.column_stack([col, row]))
        dist, idx = tree.query(star_xy, distance_upper_bound=match_px)
        got = np.isfinite(dist)
        if got.sum() < 6:
            break
        si = np.nonzero(got)[0]
        ci = idx[got]
        # one-to-one: for each catalogue star keep the nearest extracted star
        order = np.argsort(dist[got])
        seen: set[int] = set()
        keep_s, keep_c = [], []
        for o in order:
            c = int(ci[o])
            if c in seen:
                continue
            seen.add(c)
            keep_s.append(int(si[o]))
            keep_c.append(c)
        pairs_xy = star_xy[keep_s]
        pairs_cat = cat_vec[sel[keep_c]]
        x0 = np.array([0.0, 0.0, 0.0, 0.0, k])

        def residual(p: np.ndarray) -> np.ndarray:
            r = Rotation.from_rotvec(p[:3]).as_matrix() @ rot
            c2 = CameraModel(width, height, f * (1.0 + p[3]), p[4])
            cc, rr, _ = c2.project((r @ pairs_cat.T).T)
            return np.concatenate([cc - pairs_xy[:, 0], rr - pairs_xy[:, 1]])

        sol = least_squares(residual, x0, loss="soft_l1", f_scale=0.5,
                            x_scale=np.array([1e-3, 1e-3, 1e-3, 1e-3, 1e-2]), max_nfev=60)
        rot = Rotation.from_rotvec(sol.x[:3]).as_matrix() @ rot
        f = f * (1.0 + sol.x[3])
        k = float(sol.x[4])
        cam = CameraModel(width, height, f, k)
        cc, rr, _ = cam.project((rot @ pairs_cat.T).T)
        d = np.hypot(cc - pairs_xy[:, 0], rr - pairs_xy[:, 1])
        inl = d < inlier_px
        n_in = int(inl.sum())
        rms = float(np.sqrt(np.mean(d[inl] ** 2))) if n_in else float("nan")
    arcsec_per_px = math.degrees(1.0 / f) * 3600.0
    fov = math.degrees(2.0 * math.atan(width / 2.0 / f))
    return RefinedPose(rotation=rot, focal_px=f, fov_deg=fov, distortion=k, rms_px=rms,
                       rmse_arcsec=rms * arcsec_per_px if n_in else float("inf"), n_inliers=n_in,
                       n_stars=int(star_xy.shape[0]), ok=n_in >= 6)

"""Small vector / rotation helpers shared by the astronomy, solver and simulator code.

Conventions
-----------
* Celestial vectors are unit 3-vectors in the equatorial frame (x to RA 0h/Dec 0, z to the pole).
* The *camera frame* is the one used by tetra3 / Cedar Solve: x = boresight (out of the lens),
  y = image LEFT, z = image UP (towards row 0).  A pinhole image of a star at camera vector
  (x, y, z) lands at column ``w/2 - f*y/x`` and row ``h/2 - f*z/x`` (pixel edges at integers).
* ``R_cam`` always maps celestial -> camera:  ``v_cam = R_cam @ v_sky``; its rows are the camera
  axes expressed in the sky frame.
"""
from __future__ import annotations

import math

import numpy as np

ARCSEC = math.radians(1.0 / 3600.0)
ARCMIN = math.radians(1.0 / 60.0)


def unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / n


def radec_to_vec(ra_deg: float | np.ndarray, dec_deg: float | np.ndarray) -> np.ndarray:
    ra = np.radians(ra_deg)
    dec = np.radians(dec_deg)
    return np.stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)], axis=-1)


def vec_to_radec(v: np.ndarray) -> tuple[float, float]:
    v = unit(v)
    return (math.degrees(math.atan2(v[1], v[0])) % 360.0,
            math.degrees(math.asin(max(-1.0, min(1.0, v[2])))))


def angle_between(a: np.ndarray, b: np.ndarray) -> float:
    """Angle in radians, accurate for tiny angles (atan2 of cross and dot)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return float(math.atan2(np.linalg.norm(np.cross(a, b)), float(np.dot(a, b))))


def rot_axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    """Active rotation matrix about ``axis`` by ``angle`` (radians, right-handed)."""
    k = unit(axis)
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(angle) * kx + (1.0 - math.cos(angle)) * (kx @ kx)


def rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Smallest active rotation taking unit vector ``a`` onto ``b``."""
    a = unit(a)
    b = unit(b)
    axis = np.cross(a, b)
    s = float(np.linalg.norm(axis))
    c = float(np.dot(a, b))
    if s < 1e-14:
        if c > 0:
            return np.eye(3)
        # opposite vectors: rotate pi about any perpendicular axis
        perp = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(perp) < 1e-6:
            perp = np.cross(a, [0.0, 1.0, 0.0])
        return rot_axis_angle(perp, math.pi)
    return rot_axis_angle(axis, math.atan2(s, c))


def rotation_from_radec_roll(ra_deg: float, dec_deg: float, roll_deg: float) -> np.ndarray:
    """Rebuild tetra3's celestial->camera rotation from its (RA, Dec, Roll) output.

    Derived from ``tetra3.solve_from_centroids``: RA = atan2(R[0,1], R[0,0]),
    Dec = atan2(R[0,2], |R[1:3,2]|), Roll = atan2(R[1,2], R[2,2]), rows = (boresight, left, up).
    Verified against a full least-squares fit in tests/test_solver.py.
    """
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    rho = math.radians(roll_deg)
    bore = np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])
    east = np.array([-math.sin(ra), math.cos(ra), 0.0])
    north = np.array([-math.sin(dec) * math.cos(ra), -math.sin(dec) * math.sin(ra), math.cos(dec)])
    up = math.cos(rho) * north - math.sin(rho) * east
    left = math.sin(rho) * north + math.cos(rho) * east
    return np.vstack([bore, left, up])


def tangent_offset(v: np.ndarray, center: np.ndarray, e1: np.ndarray, e2: np.ndarray) -> tuple[float, float]:
    """Gnomonic offset (radians) of unit vector ``v`` from ``center`` along tangent axes e1, e2."""
    v = unit(v)
    c = float(np.dot(v, center))
    d = v / c - center          # lies in the tangent plane at ``center``
    return float(np.dot(d, e1)), float(np.dot(d, e2))

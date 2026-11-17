"""Atmospheric refraction (visual band, standard-atmosphere scaling).

Two classic formulae, one for each direction:

* Saemundsson (1986): refraction from the *true* altitude  h:   R = 1.02 / tan(h + 10.3/(h + 5.11))  arcmin
* Bennett (1982):     refraction from the *apparent* altitude:  R = 1 / tan(h + 7.31/(h + 4.4))      arcmin

both multiplied by (P / 1010 hPa) * (283 / (273 + T)).  Accuracy is ~0.1' above 15 deg altitude and
degrades below 5 deg (where the real value also depends on the temperature profile).  Typical size:
2.1' at 25 deg (0.035 deg), 1.0' at 45 deg, 5.4' at 10 deg.

How the aligner uses it (see :mod:`polaralign.astro.pole`): the physical axis is aligned to the
*apparent* pole -- the true pole displaced toward the zenith by R(latitude) -- because that is the
point the refracted sky appears to rotate about (the same choice SharpCap's "refraction
compensation" makes).  The camera boresight, which may be 20-30 deg off the axis and therefore at a
different altitude, is un-refracted with its own R so the difference between the two does not leak
into the result.
"""
from __future__ import annotations

import math

import numpy as np

from .frames import rot_axis_angle, unit

_MIN_ALT_DEG = 0.5   # formulae are meaningless below the horizon; clamp


def _pt_factor(pressure_hpa: float, temperature_c: float) -> float:
    return (pressure_hpa / 1010.0) * (283.0 / (273.0 + temperature_c))


def refraction_from_true_alt(h_true_deg: float, pressure_hpa: float = 1010.0, temperature_c: float = 10.0) -> float:
    """Saemundsson: refraction in radians for a given true altitude."""
    h = max(h_true_deg, _MIN_ALT_DEG)
    r_arcmin = 1.02 / math.tan(math.radians(h + 10.3 / (h + 5.11)))
    return math.radians(r_arcmin / 60.0) * _pt_factor(pressure_hpa, temperature_c)


def refraction_from_apparent_alt(h_app_deg: float, pressure_hpa: float = 1010.0, temperature_c: float = 10.0) -> float:
    """Bennett: refraction in radians for a given apparent altitude."""
    h = max(h_app_deg, _MIN_ALT_DEG)
    r_arcmin = 1.0 / math.tan(math.radians(h + 7.31 / (h + 4.4)))
    return math.radians(r_arcmin / 60.0) * _pt_factor(pressure_hpa, temperature_c)


def shift_toward(v: np.ndarray, target: np.ndarray, angle: float) -> np.ndarray:
    """Rotate ``v`` along the great circle through ``target`` by ``angle`` (positive = toward it)."""
    v = unit(v)
    axis = np.cross(v, target)
    if np.linalg.norm(axis) < 1e-12:
        return v
    return rot_axis_angle(axis, angle) @ v


class RefractionModel:
    """Refraction about a known zenith direction (J2000-labelled unit vector)."""

    def __init__(self, zenith: np.ndarray | None, pressure_hpa: float = 1010.0,
                 temperature_c: float = 10.0, enabled: bool = True) -> None:
        self.zenith = None if zenith is None else unit(zenith)
        self.pressure_hpa = pressure_hpa
        self.temperature_c = temperature_c
        self.enabled = bool(enabled and self.zenith is not None)

    def altitude_deg(self, v: np.ndarray) -> float:
        assert self.zenith is not None
        return math.degrees(math.asin(max(-1.0, min(1.0, float(np.dot(unit(v), self.zenith))))))

    def apparent(self, v_true: np.ndarray) -> np.ndarray:
        """True direction -> where the refracted sky shows it."""
        if not self.enabled:
            return unit(v_true)
        r = refraction_from_true_alt(self.altitude_deg(v_true), self.pressure_hpa, self.temperature_c)
        return shift_toward(v_true, self.zenith, r)

    def true(self, v_app: np.ndarray) -> np.ndarray:
        """Apparent direction -> true direction."""
        if not self.enabled:
            return unit(v_app)
        r = refraction_from_apparent_alt(self.altitude_deg(v_app), self.pressure_hpa, self.temperature_c)
        return shift_toward(v_app, self.zenith, -r)

    def apparent_array(self, v_true: np.ndarray) -> np.ndarray:
        """Vectorised :meth:`apparent` for an (N, 3) array (used by the simulator)."""
        v = unit(v_true)
        if not self.enabled:
            return v
        assert self.zenith is not None
        alt = np.degrees(np.arcsin(np.clip(v @ self.zenith, -1.0, 1.0)))
        h = np.maximum(alt, _MIN_ALT_DEG)
        r = np.radians(1.02 / np.tan(np.radians(h + 10.3 / (h + 5.11))) / 60.0) \
            * _pt_factor(self.pressure_hpa, self.temperature_c)
        # rotate each vector toward the zenith by r (Rodrigues, vectorised)
        axis = np.cross(v, self.zenith)
        norm = np.linalg.norm(axis, axis=1, keepdims=True)
        k = np.where(norm > 1e-12, axis / np.maximum(norm, 1e-300), 0.0)
        c = np.cos(r)[:, None]
        s = np.sin(r)[:, None]
        out = v * c + np.cross(k, v) * s + k * np.sum(k * v, axis=1, keepdims=True) * (1.0 - c)
        return out / np.linalg.norm(out, axis=1, keepdims=True)

"""IAU 2006 precession (Fukushima-Williams angles) and low-order nutation.

The plate solver (Cedar Solve / tetra3) works in the J2000 / ICRS frame.  The Earth's rotation
axis is, at any date, a different point on that sphere: the pole of date.  In November 2026 it is
about 0.150 deg (539") from the J2000 pole -- three times the 0.05 deg convergence target and
more than the 0.1 deg design target.  The aligner must therefore compare the telescope axis with
the *pole of date expressed in J2000 coordinates*, which is what :func:`pole_of_date_j2000` returns.

Accuracy: precession is the full IAU 2006 model (cross-checked against ERFA in the tests, < 0.01").
Nutation uses the four leading terms of Meeus ch. 22 (about 0.5" accuracy, a 17" effect).
Annual aberration (<= 20.5") and polar motion (~0.3") are neglected: both are small against the
3' (180") convergence threshold and, for aberration, nearly common-mode between camera and pole.
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from .timescales import centuries_tt

ASEC2RAD = math.radians(1.0 / 3600.0)


def _rx(a: float) -> np.ndarray:  # passive rotation about x (ERFA convention)
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, s], [0, -s, c]])


def _rz(a: float) -> np.ndarray:  # passive rotation about z
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])


def fw_angles(t: float) -> tuple[float, float, float, float]:
    """Fukushima-Williams angles gamma_bar, phi_bar, psi_bar, eps_A (radians), t = TT centuries."""
    gamb = (-0.052928 + (10.556378 + (0.4932044 + (-0.00031238 + (-0.000002788 + 0.0000000260 * t) * t) * t) * t) * t)
    phib = (84381.412819 + (-46.811016 + (0.0511268 + (0.00053289 + (-0.000000440 - 0.0000000176 * t) * t) * t) * t) * t)
    psib = (-0.041775 + (5038.481484 + (1.5584175 + (-0.00018522 + (-0.000026452 - 0.0000000148 * t) * t) * t) * t) * t)
    epsa = (84381.406 + (-46.836769 + (-0.0001831 + (0.00200340 + (-0.000000576 - 0.0000000434 * t) * t) * t) * t) * t)
    return gamb * ASEC2RAD, phib * ASEC2RAD, psib * ASEC2RAD, epsa * ASEC2RAD


def fw_to_matrix(gamb: float, phib: float, psi: float, eps: float) -> np.ndarray:
    return _rx(-eps) @ _rz(-psi) @ _rx(phib) @ _rz(gamb)


def nutation(t: float) -> tuple[float, float]:
    """(d_psi, d_eps) in radians, leading terms only (Meeus 22, ~0.5" / 0.1")."""
    om = math.radians(125.04452 - 1934.136261 * t)
    ls = math.radians(280.4665 + 36000.7698 * t)
    lm = math.radians(218.3165 + 481267.8813 * t)
    dpsi = (-17.20 * math.sin(om) - 1.32 * math.sin(2 * ls) - 0.23 * math.sin(2 * lm) + 0.21 * math.sin(2 * om))
    deps = (9.20 * math.cos(om) + 0.57 * math.cos(2 * ls) + 0.10 * math.cos(2 * lm) - 0.09 * math.cos(2 * om))
    return dpsi * ASEC2RAD, deps * ASEC2RAD


def bias_precession_matrix(dt: datetime) -> np.ndarray:
    """GCRS (~J2000) -> mean equator and equinox of date."""
    t = centuries_tt(dt)
    gamb, phib, psib, epsa = fw_angles(t)
    return fw_to_matrix(gamb, phib, psib, epsa)


def bias_precession_nutation_matrix(dt: datetime, nutation_on: bool = True) -> np.ndarray:
    """GCRS (~J2000) -> true equator and equinox of date (``v_date = M @ v_j2000``)."""
    t = centuries_tt(dt)
    gamb, phib, psib, epsa = fw_angles(t)
    dpsi, deps = nutation(t) if nutation_on else (0.0, 0.0)
    return fw_to_matrix(gamb, phib, psib + dpsi, epsa + deps)


def pole_of_date_j2000(dt: datetime, hemisphere: int = +1, nutation_on: bool = True) -> np.ndarray:
    """Unit vector, in J2000 coordinates, of the celestial pole of date.

    ``hemisphere`` +1 = north celestial pole, -1 = south celestial pole.
    """
    m = bias_precession_nutation_matrix(dt, nutation_on)
    return float(np.sign(hemisphere) or 1.0) * m[2, :]   # third row = date z-axis in J2000 coords


def precession_offset_arcsec(dt: datetime) -> float:
    """Angular distance between the J2000 pole and the pole of date (for display and tests)."""
    p = pole_of_date_j2000(dt)
    return math.degrees(math.atan2(np.linalg.norm(np.cross(p, [0, 0, 1])), p[2])) * 3600.0

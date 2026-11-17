"""Where the telescope axis should point, and how far it is from there.

Everything here is expressed in the J2000-labelled celestial frame, which is the frame the plate
solver reports in.  Two corrections that the design document does not make are applied here:

1. **Precession/nutation.**  The target is the pole *of date* (:func:`pole_of_date_j2000`), 0.150 deg
   (542") away from the J2000 pole in November 2026.
2. **Refraction.**  With ``refraction="model"`` the physical axis is aligned to the *apparent* pole
   (true pole displaced toward the zenith by R(|latitude|)); the camera boresight is un-refracted with
   its own R.  With ``"off"`` the solver's frame is used as is, which leaves the axis about R(lat)
   (2.1' = 0.035 deg at 25 deg latitude, 5' at 10 deg) low relative to the apparent pole.
   Either way the stored camera-to-axis calibration absorbs whatever convention the telescope's own
   alignment routine uses, as long as calibration and use happen at similar latitudes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from .frames import ARCSEC, rotation_between, unit
from .precession import bias_precession_nutation_matrix, pole_of_date_j2000
from .refraction import RefractionModel
from .timescales import local_sidereal_deg


@dataclass(frozen=True)
class Site:
    latitude_deg: float
    longitude_deg: float
    pressure_hpa: float = 1010.0
    temperature_c: float = 10.0


@dataclass
class PoleTarget:
    """The point the physical axis must reach, plus the frame used to report errors."""

    hemisphere: int                     # +1 north, -1 south
    time: datetime
    true_pole: np.ndarray               # pole of date, J2000 coordinates
    target: np.ndarray                  # apparent pole (== true_pole when refraction is off / unknown)
    precession_arcsec: float            # |pole of date - J2000 pole|
    refraction_arcsec: float            # |target - true_pole|
    refraction: RefractionModel
    site: Site | None
    up: np.ndarray                      # tangent unit vector toward the zenith ("altitude" direction)
    east: np.ndarray                    # tangent unit vector toward the east ("azimuth" direction)
    frame_is_horizontal: bool
    notes: list[str] = field(default_factory=list)

    @property
    def pole_altitude_deg(self) -> float | None:
        if self.site is None:
            return None
        return abs(self.site.latitude_deg)


@dataclass(frozen=True)
class PoleError:
    d_alt_rad: float      # axis minus target, along "up" (positive = axis too high)
    d_east_rad: float     # axis minus target, along "east" (sky angle; positive = axis too far east)
    total_rad: float
    cos_alt: float        # cos(altitude of the pole), to convert sky angle into dial angle

    @property
    def total_arcmin(self) -> float:
        return math.degrees(self.total_rad) * 60.0

    @property
    def alt_arcmin(self) -> float:
        return math.degrees(self.d_alt_rad) * 60.0

    @property
    def east_arcmin(self) -> float:
        return math.degrees(self.d_east_rad) * 60.0

    @property
    def az_dial_arcmin(self) -> float:
        return self.east_arcmin / max(self.cos_alt, 1e-3)

    def vector_rad(self) -> np.ndarray:
        return np.array([self.d_alt_rad, self.d_east_rad])


def zenith_j2000(dt: datetime, site: Site) -> np.ndarray:
    """Zenith direction in J2000 coordinates (true equator of date -> J2000)."""
    theta = math.radians(local_sidereal_deg(dt, site.longitude_deg))
    phi = math.radians(site.latitude_deg)
    z_date = np.array([math.cos(phi) * math.cos(theta), math.cos(phi) * math.sin(theta), math.sin(phi)])
    return bias_precession_nutation_matrix(dt).T @ z_date


def east_j2000(dt: datetime, site: Site) -> np.ndarray:
    theta = math.radians(local_sidereal_deg(dt, site.longitude_deg))
    e_date = np.array([-math.sin(theta), math.cos(theta), 0.0])
    return bias_precession_nutation_matrix(dt).T @ e_date


def detect_hemisphere(axis_j2000: np.ndarray, dt: datetime) -> tuple[int, float]:
    """Which pole is the axis closest to?  Returns (+1 | -1, angular distance in degrees)."""
    n = pole_of_date_j2000(dt, +1)
    ang_n = math.degrees(math.atan2(np.linalg.norm(np.cross(axis_j2000, n)), float(np.dot(axis_j2000, n))))
    ang_s = 180.0 - ang_n
    return (+1, ang_n) if ang_n <= ang_s else (-1, ang_s)


def make_target(dt: datetime, hemisphere: int, site: Site | None, refraction: str = "model") -> PoleTarget:
    """Build the aligned-axis target for time ``dt`` (UTC)."""
    notes: list[str] = []
    true_pole = pole_of_date_j2000(dt, hemisphere)
    j2000_pole = np.array([0.0, 0.0, float(hemisphere)])
    prec = math.atan2(np.linalg.norm(np.cross(true_pole, j2000_pole)), float(np.dot(true_pole, j2000_pole)))

    model = RefractionModel(None, enabled=False)
    target = true_pole
    if site is not None:
        zen = zenith_j2000(dt, site)
        enabled = refraction == "model"
        model = RefractionModel(zen, site.pressure_hpa, site.temperature_c, enabled=enabled)
        if enabled:
            target = model.apparent(true_pole)
            if abs(site.latitude_deg) < 10.0:
                notes.append("pole altitude < 10 deg: refraction model is unreliable here")
        else:
            notes.append("refraction model off: axis is aligned to the true pole of date")
        up_raw = zen - float(np.dot(zen, target)) * target
        up = unit(up_raw)
        east_raw = east_j2000(dt, site)
        east = unit(east_raw - float(np.dot(east_raw, target)) * target)
        horizontal = True
    else:
        notes.append("no site location: refraction not applied, errors reported in a sky frame (not alt/az)")
        ref = np.array([1.0, 0.0, 0.0])
        up = unit(ref - float(np.dot(ref, target)) * target)
        east = unit(np.cross(target, up))
        horizontal = False

    refr = math.atan2(np.linalg.norm(np.cross(target, true_pole)), float(np.dot(target, true_pole)))
    return PoleTarget(hemisphere=hemisphere, time=dt, true_pole=true_pole, target=target,
                      precession_arcsec=prec / ARCSEC, refraction_arcsec=refr / ARCSEC,
                      refraction=model, site=site, up=up, east=east, frame_is_horizontal=horizontal,
                      notes=notes)


# --------------------------------------------------------------------------------------
# camera <-> physical axis
# --------------------------------------------------------------------------------------
def boresight_unrefraction(r_cam: np.ndarray, target: PoleTarget) -> np.ndarray:
    """Rotation taking the *solved* boresight (true-pattern direction) to its physical direction.

    The solver labels the pattern under the boresight with true positions; the telescope really
    points at the apparent position, which is shifted toward the zenith by R(boresight altitude).
    """
    if not target.refraction.enabled:
        return np.eye(3)
    b_sky = r_cam[0, :]
    b_phys = target.refraction.apparent(b_sky)
    return rotation_between(b_sky, b_phys)


def physical_axis(r_cam: np.ndarray, a_cam: np.ndarray, target: PoleTarget) -> np.ndarray:
    """Physical direction (J2000-labelled) of the telescope axis given a solve and the calibration."""
    a_sky = r_cam.T @ unit(a_cam)
    return unit(boresight_unrefraction(r_cam, target) @ a_sky)


def axis_in_camera(r_cam: np.ndarray, a_phys: np.ndarray, target: PoleTarget) -> np.ndarray:
    """Inverse of :func:`physical_axis`: the axis direction in the camera frame."""
    rr = boresight_unrefraction(r_cam, target)
    return unit(r_cam @ (rr.T @ unit(a_phys)))


def pole_error(a_phys: np.ndarray, target: PoleTarget) -> PoleError:
    a = unit(a_phys)
    p = target.target
    dvec = a / float(np.dot(a, p)) - p            # gnomonic offset in the tangent plane at p
    total = math.atan2(np.linalg.norm(np.cross(a, p)), float(np.dot(a, p)))
    cos_alt = 1.0
    if target.site is not None:
        cos_alt = math.cos(math.radians(abs(target.site.latitude_deg)))
    return PoleError(d_alt_rad=float(np.dot(dvec, target.up)), d_east_rad=float(np.dot(dvec, target.east)),
                     total_rad=total, cos_alt=cos_alt)

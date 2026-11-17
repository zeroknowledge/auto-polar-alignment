"""The simulated world: sky truth chain + mount + camera, and a builder that wires it all to the
real motion / camera / clock interfaces.

Truth chain for every catalogue star (all independent of the aligner's own code where ERFA is
available): J2000 vector -> annual aberration -> bias-precession-nutation of date (ERFA ``pnm06a`` if
installed, else our own model) -> horizontal frame (sidereal time + site latitude) -> refraction
(ERFA's A tan z + B tan^3 z model if installed, else Saemundsson) -> camera frame (mount pose) -> pixels.
The aligner assumes none of aberration and uses Saemundsson/Bennett refraction, so those differences
are genuine model error that the end-to-end test has to absorb.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from ..astro.frames import rot_axis_angle, unit
from ..astro.pole import Site
from ..astro.precession import bias_precession_nutation_matrix, pole_of_date_j2000
from ..astro.refraction import RefractionModel
from ..astro.timescales import centuries_tt, julian_date_utc, local_sidereal_deg
from ..camera.base import Frame
from ..catalog import StarCatalog, load_from_database
from ..clock import SimClock, TimeSource
from ..config import Config
from ..motion.controller import MotionController
from ..motion.gpio import FakeGPIO
from ..motion.tmc2209 import FakeTmcBus
from .camera_model import CameraModel
from .mount import MountParams, SimMount
from .render import FrameRenderer, SensorParams

try:  # independent truth, only if ERFA happens to be installed (dev extra)
    import erfa as _erfa
except ImportError:  # pragma: no cover
    _erfa = None


def _pnm(dt: datetime) -> np.ndarray:
    if _erfa is not None:
        d1, d2 = _erfa.dtf2d("UTC", dt.year, dt.month, dt.day, dt.hour, dt.minute,
                             dt.second + dt.microsecond * 1e-6)
        tt = _erfa.taitt(*_erfa.utctai(d1, d2))
        return np.asarray(_erfa.pnm06a(*tt))
    return bias_precession_nutation_matrix(dt)


def earth_velocity_over_c(dt: datetime) -> np.ndarray:
    """Earth's barycentric-ish velocity / c in J2000 equatorial axes (accurate to a few percent)."""
    d = julian_date_utc(dt) - 2451545.0
    g = math.radians(357.528 + 0.9856003 * d)
    sun_lon = math.radians(280.460 + 0.9856474 * d + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.4393)
    k = 9.936e-5
    return k * np.array([math.sin(sun_lon), -math.cos(sun_lon) * math.cos(eps), -math.cos(sun_lon) * math.sin(eps)])


@dataclass
class SimWorld:
    site: Site
    clock: SimClock
    mount: SimMount
    catalog: StarCatalog
    camera_model: CameraModel
    sensor: SensorParams = field(default_factory=SensorParams)
    seed: int = 5
    aberration: bool = True
    refraction_truth: str = "auto"       # "auto" (ERFA if present) | "model" | "off"
    exposures: int = 0

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.renderer = FrameRenderer(self.camera_model, self.sensor)

    # ---------------------------------------------------------------- sky -> horizontal
    def _enu_matrix(self, dt: datetime) -> np.ndarray:
        th = math.radians(local_sidereal_deg(dt, self.site.longitude_deg))
        ph = math.radians(self.site.latitude_deg)
        e = [-math.sin(th), math.cos(th), 0.0]
        n = [-math.sin(ph) * math.cos(th), -math.sin(ph) * math.sin(th), math.cos(ph)]
        u = [math.cos(ph) * math.cos(th), math.cos(ph) * math.sin(th), math.sin(ph)]
        return np.array([e, n, u])

    def _refract_enu(self, v: np.ndarray) -> np.ndarray:
        mode = self.refraction_truth
        if mode == "off":
            return v
        if mode in ("auto", "erfa") and _erfa is not None:
            a, b = _erfa.refco(self.site.pressure_hpa, self.site.temperature_c, 0.5, 0.55)
            zd = np.minimum(np.arccos(np.clip(v[:, 2], -1, 1)), math.radians(89.0))     # true zenith distance
            zo = zd.copy()
            for _ in range(3):                                      # refco's model is in observed ZD: invert it
                zo = zd - (a * np.tan(zo) + b * np.tan(zo) ** 3)
            dz = zd - zo
            az_vec = np.column_stack([v[:, 0], v[:, 1]])
            hn = np.linalg.norm(az_vec, axis=1, keepdims=True)
            hn[hn == 0] = 1.0
            znew = zd - dz
            out = np.column_stack([np.sin(znew)[:, None] * az_vec / hn, np.cos(znew)])
            return out
        return RefractionModel(np.array([0.0, 0.0, 1.0]), self.site.pressure_hpa, self.site.temperature_c
                               ).apparent_array(v)

    def sky_to_enu(self, v_j2000: np.ndarray, dt: datetime | None = None) -> np.ndarray:
        """Apparent (aberrated, refracted) horizontal-frame directions of J2000 unit vectors."""
        dt = dt or self.clock.now()
        v = np.atleast_2d(v_j2000)
        if self.aberration:
            beta = earth_velocity_over_c(dt)
            v = v + beta - (v @ beta)[:, None] * v
            v = v / np.linalg.norm(v, axis=1, keepdims=True)
        v_date = v @ _pnm(dt).T
        v_enu = v_date @ self._enu_matrix(dt).T
        return self._refract_enu(v_enu)

    # ---------------------------------------------------------------- truth
    def apparent_pole_enu(self, hemisphere: int | None = None) -> np.ndarray:
        """Where the true pole of date appears (the aligner's target), in the horizontal frame."""
        hemi = hemisphere if hemisphere is not None else (1 if self.site.latitude_deg >= 0 else -1)
        pole = pole_of_date_j2000(self.clock.now(), hemi, nutation_on=True)
        return self.sky_to_enu(pole[None, :])[0]

    def true_axis_error_deg(self, hemisphere: int | None = None) -> float:
        """Angle between the physical polar axis and the apparent pole (the quantity to drive to 0)."""
        a = self.mount.axis_enu()
        p = self.apparent_pole_enu(hemisphere)
        return math.degrees(math.atan2(np.linalg.norm(np.cross(a, p)), float(a @ p)))

    def true_axis_error_vs_true_pole_deg(self, hemisphere: int | None = None) -> float:
        """Angle to the *unrefracted* pole of date (differs from the above by the refraction R)."""
        hemi = hemisphere if hemisphere is not None else (1 if self.site.latitude_deg >= 0 else -1)
        dt = self.clock.now()
        pole = pole_of_date_j2000(dt, hemi, nutation_on=True)
        p = self._enu_matrix(dt) @ (_pnm(dt) @ pole)
        a = self.mount.axis_enu()
        return math.degrees(math.atan2(np.linalg.norm(np.cross(a, p)), float(a @ p)))

    def set_coarse(self, error_deg: float = 0.0, direction_deg: float = 0.0, hemisphere: int | None = None) -> None:
        """Set the coarse tilt/heading (by hand, in the real world) so the polar axis sits ``error_deg`` from
        the apparent pole, towards ``direction_deg`` (0 = up/zenith side, 90 = east), at the *current*
        fine-stage positions.  Independent of anything the controller believes."""
        target = self.apparent_pole_enu(hemisphere)
        if error_deg:
            side = unit(np.cross(target, [0, 0, 1.0]))
            up = unit(np.cross(side, target))
            off = math.cos(math.radians(direction_deg)) * up + math.sin(math.radians(direction_deg)) * side
            target = rot_axis_angle(np.cross(target, off), math.radians(error_deg)) @ target
        self.mount.set_axis_direction(target)

    # ---------------------------------------------------------------- imaging
    def render_frame(self, exposure_s: float, gain: float = 1.0) -> np.ndarray:
        dt = self.clock.now()
        c_h = self.mount.camera_axes_enu()
        bore_enu = c_h[:, 0]
        # find stars near the boresight: transform cone-selected stars (cheap pre-selection in J2000)
        enu = self._enu_matrix(dt)
        bore_j2000 = _pnm(dt).T @ (enu.T @ bore_enu)
        idx = self.catalog.cone(bore_j2000, self.camera_model.diag_half_angle_rad + math.radians(1.5), max_mag=9.5)
        v_enu = self.sky_to_enu(self.catalog.vec[idx], dt)
        up = v_enu[:, 2] > math.sin(math.radians(0.5))              # nothing below the horizon
        v_cam = v_enu[up] @ c_h
        self.exposures += 1
        return self.renderer.render(v_cam, self.catalog.mag[idx][up], exposure_s, self.rng, gain=gain, star_ids=idx[up])


class SimCamera:
    name = "sim"

    def __init__(self, world: SimWorld, cfg_exposure: float = 0.5, cfg_gain: float = 1.0) -> None:
        self.world = world
        self.cfg_exposure = cfg_exposure
        self.cfg_gain = cfg_gain

    def capture(self, exposure_s: float | None = None, gain: float | None = None) -> Frame:
        exposure_s = self.cfg_exposure if exposure_s is None else exposure_s
        gain = self.cfg_gain if gain is None else gain
        pix = self.world.render_frame(exposure_s, gain)
        ts = self.world.clock.now()
        self.world.clock.advance(exposure_s + 0.3)         # exposure + readout/processing latency
        return Frame(pix, exposure_s, gain, ts, {"camera": "sim", "bayer": self.world.sensor.cfa or None})

    def close(self) -> None:
        pass


@dataclass
class SimHardware:
    config: Config
    world: SimWorld
    gpio: FakeGPIO
    uart: FakeTmcBus
    motion: MotionController
    camera: SimCamera
    time_source: TimeSource


def build_sim_hardware(config: Config | None = None, site: Site | None = None, when: datetime | None = None,
                       mount: MountParams | None = None, sensor: SensorParams | None = None,
                       distortion: float = -0.012, seed: int = 5, aberration: bool = True,
                       catalog: StarCatalog | None = None, state_file=None) -> SimHardware:
    """Everything needed to run the real alignment code against a virtual base."""
    from ..config import sim_config
    cfg = config or sim_config()
    site = site or Site(latitude_deg=25.2, longitude_deg=55.3)
    when = when or datetime(2026, 11, 17, 20, 30, tzinfo=timezone.utc)
    cat = catalog or load_from_database()
    sim_mount = SimMount(cfg.motion, mount or MountParams(axis_alt_deg=abs(site.latitude_deg) + 3.0,
                                                         axis_az_deg=(4.0 if site.latitude_deg >= 0 else 184.0)))
    clock = SimClock(when)
    cam_model = CameraModel(cfg.camera.width, cfg.camera.height, cfg.camera.focal_px, distortion)
    world = SimWorld(site=site, clock=clock, mount=sim_mount, catalog=cat, camera_model=cam_model,
                     sensor=sensor or SensorParams(cfa=cfg.camera.bayer_pattern if cfg.camera.colour else ""),
                     seed=seed, aberration=aberration)
    gpio = FakeGPIO()
    uart = FakeTmcBus((cfg.motion.az.uart_address, cfg.motion.alt.uart_address))
    motion = MotionController(cfg.motion, gpio, uart, state_file=state_file)
    sim_mount.attach(gpio)
    motion.configure_drivers()
    time_source = TimeSource(clock)
    time_source.source = "simulated clock"
    return SimHardware(cfg, world, gpio, uart, motion, SimCamera(world, cfg.camera.exposure_s, 1.0), time_source)

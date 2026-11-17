"""Physical model of the base: two screw-driven stages with backlash, scale errors, lost steps and a
shift when the motors are released.  It is driven by STEP edges on a :class:`FakeGPIO`, so the real
motion-layer code runs against it.

Geometry (horizontal frame, x = East, y = North, z = Up): the azimuth stage turns everything about the
vertical; the altitude hinge sits on top of it and turns the polar axis about a (nearly) horizontal
axis perpendicular to the axis's vertical plane, ``skew_deg`` off true horizontal so the two axes are
not perfectly independent.  The camera is rigidly fixed to the top plate, looking
``offaxis_deg`` away from the axis.  None of these numbers are known to the controller: it has to
learn the step-to-sky matrix from jogs, as in section 10.2 of the design document.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..astro.frames import rot_axis_angle, unit
from ..config import MotionConfig
from ..motion.gpio import FakeGPIO


@dataclass
class MountParams:
    axis_alt_deg: float = 28.0              # initial (rough set-up) pointing of the polar axis
    axis_az_deg: float = 4.0                # azimuth from north through east
    skew_deg: float = 0.8
    az_sign: int = +1
    alt_sign: int = +1
    az_scale_error: float = 0.015           # true deg/step relative to the configured value
    alt_scale_error: float = 0.08
    backlash_az_deg: float = 0.05
    backlash_alt_deg: float = 0.06
    stall_prob_per_move: float = 0.03       # chance that a move loses a burst of steps
    stall_max_full_steps: int = 5
    release_shift_deg: float = 0.004        # random shift (sigma) when the motor current is cut
    offaxis_deg: float = 25.0
    cam_roll_deg: float = 17.0
    stop_az_deg: tuple[float, float] = (8.05, 8.05)     # end-stop trigger angles from the mechanical centre (min, max)
    stop_alt_deg: tuple[float, float] = (7.35, 7.15)    # hardware/README.md: 8.05 az, 7.35 / 7.15 alt
    swap_endstops: tuple[bool, bool] = (False, False)   # (az, alt): the MIN connector is wired to the positive-end switch
    start_fraction_az: float = 0.62         # where in its travel the plate is at power-up
    start_fraction_alt: float = 0.35
    seed: int = 1


class _Stage:
    """One screw: motor position -> plate position through a symmetric backlash dead band."""

    def __init__(self, name: str, deg_per_ustep: float, travel_usteps: float, backlash_usteps: float,
                 start_fraction: float, stall_prob: float, stall_max_ustep: int, rng: np.random.Generator,
                 centre_usteps: float | None = None) -> None:
        self.name = name
        self.deg_per_ustep = deg_per_ustep
        self.travel = travel_usteps                 # stop-to-stop, in microsteps (true)
        self.centre = travel_usteps / 2.0 if centre_usteps is None else centre_usteps   # mechanical centre, from the MIN stop
        self.gap = backlash_usteps
        self.p = start_fraction * travel_usteps     # plate, from the MIN stop
        self.m = self.p                             # motor
        self.enabled = False
        self.dir_forward = True
        self._lose = 0
        self._stall_prob = stall_prob
        self._stall_max = stall_max_ustep
        self._rng = rng
        self.lost_total = 0
        self.steps_total = 0

    def set_enabled(self, enabled: bool) -> None:
        if enabled and not self.enabled and self._rng.random() < self._stall_prob:
            self._lose = int(self._rng.integers(1, self._stall_max + 1))
        self.enabled = enabled

    def step(self) -> None:
        if not self.enabled:
            return
        if self._lose > 0:
            self._lose -= 1
            self.lost_total += 1
            return
        self.steps_total += 1
        self.m += 1.0 if self.dir_forward else -1.0
        half = self.gap / 2.0
        if self.m - self.p > half:
            self.p = self.m - half
        elif self.p - self.m > half:
            self.p = self.m + half
        if self.p < 0.0:                      # mechanical stop: the motor stalls against it
            self.p = 0.0
            self.m = -half
        elif self.p > self.travel:
            self.p = self.travel
            self.m = self.travel + half

    @property
    def at_min(self) -> bool:
        return self.p <= 0.0 + 1e-9

    @property
    def at_max(self) -> bool:
        return self.p >= self.travel - 1e-9


class SimMount:
    def __init__(self, motion: MotionConfig, params: MountParams | None = None) -> None:
        self.p = params or MountParams()
        self.rng = np.random.default_rng(self.p.seed)
        up = motion.microsteps * motion.az.full_steps_per_rev

        def stage(cfg, scale_err: float, backlash_deg: float, start_frac: float, stops: tuple[float, float]) -> _Stage:
            deg_per_ustep = cfg.deg_per_rev * (1.0 + scale_err) / (cfg.full_steps_per_rev * motion.microsteps)
            return _Stage(cfg.name, deg_per_ustep, (stops[0] + stops[1]) / deg_per_ustep, backlash_deg / deg_per_ustep,
                          start_frac, self.p.stall_prob_per_move, motion.microsteps * self.p.stall_max_full_steps,
                          self.rng, centre_usteps=stops[0] / deg_per_ustep)

        self.stages = {
            "az": stage(motion.az, self.p.az_scale_error, self.p.backlash_az_deg, self.p.start_fraction_az, self.p.stop_az_deg),
            "alt": stage(motion.alt, self.p.alt_scale_error, self.p.backlash_alt_deg, self.p.start_fraction_alt, self.p.stop_alt_deg),
        }
        self._motion = motion
        # initial geometry (rough set-up of the coarse tilt / heading)
        alt0, az0 = math.radians(self.p.axis_alt_deg), math.radians(self.p.axis_az_deg)
        self._build_geometry(np.array([math.sin(az0) * math.cos(alt0), math.cos(az0) * math.cos(alt0), math.sin(alt0)]))

    def _build_geometry(self, a0: np.ndarray) -> None:
        """Rigid assembly for stage angles (0, 0): polar axis ``a0``, hinge axis, camera axes."""
        self.a0 = unit(a0)
        d = unit([self.a0[0], self.a0[1], 0.0])
        hinge = np.cross(d, [0.0, 0.0, 1.0])                      # raises the axis for positive rotation
        self.hinge0 = rot_axis_angle(self.a0, math.radians(self.p.skew_deg)) @ hinge
        # The camera is fixed to the assembly, so define it from the assembly's own vectors (the polar axis and the
        # hinge axis), never from "up": a camera looking at the zenith would make an "up"-referenced roll degenerate
        # and the camera-to-axis relation would change between calls.
        b0 = rot_axis_angle(hinge, math.radians(self.p.offaxis_deg)) @ self.a0           # tilted away from the axis
        z_c = rot_axis_angle(b0, math.radians(self.p.cam_roll_deg)) @ hinge             # hinge axis is perpendicular to b0
        y_c = np.cross(z_c, b0)
        self.c0 = np.column_stack([b0, y_c, z_c])                 # camera axes (x boresight, y left, z up) in ENU
        self.a_cam_true = self.c0.T @ self.a0                     # the quantity the calibration must recover

    def set_axis_direction(self, a_target: np.ndarray, iterations: int = 8) -> None:
        """Re-set the *coarse* tilt/heading so that, at the present plate positions, the polar axis points
        along ``a_target`` (what the user does by hand).  The camera stays rigidly fixed to the axis."""
        a_target = unit(a_target)
        guess = self.rotation().T @ a_target
        for _ in range(iterations):
            self._build_geometry(guess)
            guess = self.rotation().T @ a_target
        self._build_geometry(guess)

    # ------------------------------------------------------------------ wiring to the controller
    def attach(self, gpio: FakeGPIO) -> None:
        for name, cfg in (("az", self._motion.az), ("alt", self._motion.alt)):
            st = self.stages[name]
            fwd_level = 0 if cfg.invert_dir else 1
            st.dir_forward = gpio.levels.get(cfg.dir_pin, 0) == fwd_level      # pin may already sit at its level
            st.enabled = gpio.levels.get(cfg.enable_pin, 1) == 0
            gpio.on_write(cfg.dir_pin, lambda old, new, st=st, fl=fwd_level: setattr(st, "dir_forward", new == fl))
            gpio.on_write(cfg.step_pin, lambda old, new, st=st: st.step() if new == 1 else None)
            gpio.on_write(cfg.enable_pin, lambda old, new, st=st: self._enable_edge(st, new))
            trip, idle = cfg.endstop_trip_level, 1 - cfg.endstop_trip_level
            swap = self.p.swap_endstops[0 if name == "az" else 1]
            lo_pin, hi_pin = (cfg.endstop_max_pin, cfg.endstop_min_pin) if swap else (cfg.endstop_min_pin, cfg.endstop_max_pin)
            gpio.set_input_source(lo_pin, lambda st=st, t=trip, i=idle: t if st.at_min else i)
            gpio.set_input_source(hi_pin, lambda st=st, t=trip, i=idle: t if st.at_max else i)

    def _enable_edge(self, st: _Stage, level: int) -> None:
        enabled = level == 0
        if st.enabled and not enabled and self.p.release_shift_deg > 0:
            # releasing the motor lets the preloaded plate (and the rotor, snapping to a detent) shift a little;
            # the backlash state (contact side) is kept
            shift = self.rng.normal(0.0, self.p.release_shift_deg) / st.deg_per_ustep
            st.p += shift
            st.m += shift
        st.set_enabled(enabled)

    # ------------------------------------------------------------------ geometry
    def stage_angles_deg(self) -> tuple[float, float]:
        """(azimuth-stage angle, altitude-hinge angle) in degrees from the mechanical centre."""
        out = []
        for name, sign in (("az", self.p.az_sign), ("alt", self.p.alt_sign)):
            st = self.stages[name]
            out.append(sign * (st.p - st.centre) * st.deg_per_ustep)
        return out[0], out[1]

    def rotation(self) -> np.ndarray:
        th_az, ph_alt = (math.radians(a) for a in self.stage_angles_deg())
        return rot_axis_angle([0, 0, 1], th_az) @ rot_axis_angle(self.hinge0, ph_alt)

    def axis_enu(self) -> np.ndarray:
        return self.rotation() @ self.a0

    def camera_axes_enu(self) -> np.ndarray:
        return self.rotation() @ self.c0

"""The closed-loop alignment sequence of design document section 10.2.

1. first solve -> where does the telescope axis point, compared with the pole *of date*;
2. learn the 2x2 step->sky matrix by jogging each axis (also estimates the backlash);
3. apply ~80 % of the inverted correction on both axes, finishing every move in the preload direction;
4. cut motor current, wait 1-2 s for the structure to settle, solve again; repeat until the error is
   below the threshold (default 3', at most 8 iterations);
5. cut motor current, report the residual.

The loop uses only interfaces (camera, extractor, solver, motion, clock), so the same code runs on the
Pi and against the simulator.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from ..astro import (ARCSEC, PoleError, PoleTarget, Site, axis_in_camera, detect_hemisphere, make_target,
                     physical_axis, pole_error)
from ..calibration import CalibrationEntry, CalibrationStore
from ..clock import TimeSource
from ..config import Config
from ..motion.controller import MotionController
from ..motion.stepper import LimitError, MotionFault
from .pipeline import Measurement, Measurer

log = logging.getLogger(__name__)

AXES = ("az", "alt")


class AlignError(RuntimeError):
    """A failure with a message fit for the user."""


class AlignCancelled(AlignError):
    pass


@dataclass
class ErrorSample:
    """Where the axis is relative to the target at one instant."""
    vec_arcsec: np.ndarray            # [alt (up), east] components of (axis - target), sky angle
    error: PoleError
    target: PoleTarget
    a_phys: np.ndarray
    measurement: Measurement
    time: datetime

    @property
    def total_arcmin(self) -> float:
        return self.error.total_arcmin

    def to_dict(self) -> dict:
        e = self.error
        return {"total_arcmin": round(e.total_arcmin, 3), "alt_arcmin": round(e.alt_arcmin, 3),
                "east_arcmin": round(e.east_arcmin, 3), "az_dial_arcmin": round(e.az_dial_arcmin, 3),
                "horizontal_frame": self.target.frame_is_horizontal,
                "precession_arcsec": round(self.target.precession_arcsec, 1),
                "refraction_arcsec": round(self.target.refraction_arcsec, 1),
                "hemisphere": self.target.hemisphere, "notes": self.target.notes,
                "time": self.time.isoformat(timespec="seconds")}


@dataclass
class AlignReport:
    success: bool = False
    converged: bool = False
    message: str = ""
    iterations: int = 0
    initial_error_arcmin: float | None = None
    residual_arcmin: float | None = None
    residual_alt_arcmin: float | None = None
    residual_east_arcmin: float | None = None
    uncalibrated: bool = False
    matrix_arcsec_per_ustep: list[list[float]] | None = None
    backlash_deg: dict[str, float] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    solves: int = 0
    duration_s: float = 0.0
    motor_current_cut: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class AlignEngine:
    def __init__(self, cfg: Config, measurer: Measurer, motion: MotionController, calibration: CalibrationStore,
                 time_source: TimeSource, site_provider: Callable[[], Site | None],
                 knock_source: Callable[[], bool] | None = None,
                 on_event: Callable[[dict], None] | None = None, allow_uncalibrated: bool = False) -> None:
        self.cfg = cfg
        self.measurer = measurer
        self.motion = motion
        self.calibration = calibration
        self.time_source = time_source
        self.site_provider = site_provider
        self.knock_source = knock_source
        self.on_event = on_event or (lambda e: None)
        self.allow_uncalibrated = allow_uncalibrated
        self.hemisphere: int | None = None
        self.n_solves = 0
        self._cancel = threading.Event()

    # ------------------------------------------------------------------ plumbing
    def cancel(self) -> None:
        self._cancel.set()
        self.motion.abort()

    def _emit(self, phase: str, message: str, **kw) -> None:
        log.info("[%s] %s", phase, message)
        self.on_event({"phase": phase, "message": message, **kw})

    def _more_light(self) -> float:
        """After a failed solve: raise the exposure for the retry (restored when the run ends).  Returns it."""
        cur = self.measurer.exposure_s or self.cfg.camera.exposure_s
        longer = min(cur * self.cfg.align.retry_exposure_factor, self.cfg.align.max_exposure_s)
        if longer > cur * 1.01:
            self.measurer.exposure_s = longer
        return self.measurer.exposure_s or cur

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise AlignCancelled("cancelled")

    def _settle(self, seconds: float | None = None) -> None:
        self.time_source.sleep(self.cfg.align.settle_s if seconds is None else seconds)

    # ------------------------------------------------------------------ measuring
    def _axis_in_camera(self) -> np.ndarray:
        a = self.calibration.a_cam
        if a is None:
            if not self.allow_uncalibrated:
                raise AlignError("No camera-to-axis calibration yet. Align once by hand with the telescope's own "
                                 "routine, then press 'Declare aligned'.")
            return np.array([1.0, 0.0, 0.0])        # camera boresight stands in for the axis
        return a

    def _site(self) -> Site | None:
        return self.site_provider()

    def sample(self, a_cam: np.ndarray | None = None, retries: int | None = None, quiet: bool = False) -> ErrorSample:
        """Solve and turn the pose into an error relative to the pole of date."""
        a_cam = self._axis_in_camera() if a_cam is None else a_cam
        retries = self.cfg.align.solve_retries if retries is None else retries
        last = "no attempt"
        frames: list[Measurement] = []
        want = max(1, self.cfg.align.frames_per_measurement)
        attempts = 0
        while len(frames) < want and attempts < retries * want:
            attempts += 1
            self._check_cancel()
            if self.knock_source and self.knock_source():
                self._emit("measure", "knock detected: waiting for the structure to settle")
                self._settle()
            m = self.measurer.measure()
            self.n_solves += 1
            if self.knock_source and self.knock_source():     # bumped during the exposure
                self._emit("measure", "knock during exposure: discarding frame")
                continue
            if m.ok:
                frames.append(m)
            else:
                last = f"{m.status}: {m.outcome.detail if m.outcome else ''} ({len(m.stars) if m.stars else 0} stars)"
                longer = self._more_light()
                if not quiet:
                    self._emit("measure", f"solve failed ({last}); retrying with {longer:.1f} s exposure")
        if not frames:
            raise AlignError(f"Could not plate-solve the sky ({last}). Check clouds, focus, lens cap, exposure time.")
        return self._error_from(frames, a_cam)

    def _error_from(self, frames: list[Measurement], a_cam: np.ndarray) -> ErrorSample:
        now = self.time_source.now()
        site = self._site()
        # hemisphere: from latitude if known, otherwise whichever pole the axis is nearest to
        if self.hemisphere is None:
            if site is not None:
                self.hemisphere = 1 if site.latitude_deg >= 0 else -1
            else:
                probe = make_target(now, +1, None)
                a0 = physical_axis(frames[0].rotation, a_cam, probe)
                self.hemisphere, ang = detect_hemisphere(a0, now)
                self._emit("measure", f"hemisphere auto-detected: {'north' if self.hemisphere > 0 else 'south'} "
                                      f"(axis is {ang:.1f} deg from that pole)")
        target = make_target(now, self.hemisphere, site, self.cfg.align.refraction)
        axes = np.array([physical_axis(f.rotation, a_cam, target) for f in frames])
        a_phys = axes.mean(axis=0)
        a_phys = a_phys / np.linalg.norm(a_phys)
        err = pole_error(a_phys, target)
        return ErrorSample(vec_arcsec=err.vector_rad() / ARCSEC, error=err, target=target, a_phys=a_phys,
                           measurement=frames[-1], time=now)

    # ------------------------------------------------------------------ calibration
    def declare_aligned(self, frames: int = 3) -> CalibrationEntry:
        """Record the camera-to-axis relation *now*, taking the axis to be at the (apparent) pole."""
        site = self._site()
        a_list, ms = [], []
        exposure0 = self.measurer.exposure_s
        attempts, last = 0, "no attempt"
        while len(ms) < frames and attempts < frames * max(1, self.cfg.align.solve_retries):
            attempts += 1
            self._check_cancel()
            m = self.measurer.measure()
            if m.ok:
                ms.append(m)
            else:
                last = m.status                       # a faint colour frame can fail to solve: more light, take another
                self._more_light()
        self.measurer.exposure_s = exposure0
        if len(ms) < frames:
            raise AlignError(f"Could not plate-solve the sky ({last}); calibration not recorded.")
        now = self.time_source.now()
        if self.hemisphere is None:
            if site is not None:
                hemi = 1 if site.latitude_deg >= 0 else -1
            else:
                # no location: use the boresight to pick the nearer pole (the axis is within ~30 deg of it)
                hemi, _ = detect_hemisphere(ms[0].rotation[0], now)
        else:
            hemi = self.hemisphere
        target = make_target(now, hemi, site, self.cfg.align.refraction)
        for m in ms:
            a_list.append(axis_in_camera(m.rotation, target.target, target))
        a_cam = np.mean(a_list, axis=0)
        a_cam /= np.linalg.norm(a_cam)
        sol = ms[-1].solution
        assert sol is not None
        entry = self.calibration.add_entry(
            a_cam, latitude_deg=None if site is None else site.latitude_deg,
            longitude_deg=None if site is None else site.longitude_deg, n_matches=sol.n_matches,
            rmse_arcsec=sol.rmse_arcsec, refraction=self.cfg.align.refraction if site else "off (no site)",
            note="; ".join(target.notes))
        self._emit("calibrate", f"axis recorded in camera frame ({len(self.calibration.data.entries)} entries)")
        return entry

    # ------------------------------------------------------------------ learning
    def _jog(self, axis: str, usteps: int, preload: bool = False) -> int:
        res = self.motion.move_relative_usteps(axis, usteps, preload_finish=preload)
        if res.aborted:
            raise AlignCancelled("cancelled")
        return res.done

    def _learn(self, s0: ErrorSample, report: AlignReport) -> np.ndarray:
        """Jog each axis, return M (2x2, arcsec of error per microstep; columns az, alt)."""
        cfg = self.cfg
        cols: dict[str, np.ndarray] = {}
        s = s0
        for axis in AXES:
            self._check_cancel()
            a = self.motion.axes[axis]
            jog = max(a.deg_to_usteps(cfg.align.learn_jog_deg), 4 * cfg.motion.microsteps)
            cond = int(a.deg_to_usteps(a.cfg.backlash_overshoot_deg) * 1.5) + cfg.motion.microsteps
            # move towards the middle of the travel so neither end stop is approached
            sign = 1 if a.pos < a.total_usteps / 2 else -1
            if a.pos + sign * (jog + cond) > a.soft_max or a.pos + sign * (jog + cond) < a.soft_min:
                sign = -sign
            self._emit("learn", f"learning {axis}: conditioning, then jogging {sign * jog} microsteps")
            self._jog(axis, sign * cond)                       # take up the slack in the jog direction
            self._settle()
            sA = self.sample(quiet=True)
            done = self._jog(axis, sign * jog)
            self._settle()
            sB = self.sample(quiet=True)
            if done == 0:
                raise AlignError(f"The {axis} motor did not move (check EN pin, driver power, current setting).")
            col = (sB.vec_arcsec - sA.vec_arcsec) / done
            cols[axis] = col
            if a.cfg.preload_sky == "clockwise" and sA.target.frame_is_horizontal:
                # the azimuth spring pulls the plate clockwise seen from above; that moves a north-pointing axis tip
                # east (a south-pointing one west).  Which way +steps go is wiring, so read it off the sky motion.
                want = 1 if col[1] * sA.target.hemisphere > 0 else -1
                if want != a.cfg.preload_dir:
                    self._emit("learn", f"{axis}: positive steps turn the plate "
                                        f"{'clockwise' if want > 0 else 'counter-clockwise'}; finishing moves in the "
                                        f"{'positive' if want > 0 else 'negative'} direction (spring side)")
                a.cfg.preload_dir = want
            elif a.cfg.preload_sky == "clockwise":
                report.warnings.append(f"{axis}: spring direction not determined (no site, so no east); "
                                       f"using preload_dir = {a.cfg.preload_dir:+d} from the config")
            expected = a.cfg.arcsec_per_full_step / cfg.motion.microsteps
            mag = float(np.linalg.norm(col))
            self._emit("learn", f"{axis}: {mag:.3f} arcsec per microstep ({mag / expected:.2f} x nominal), "
                                f"direction ({col[0]:+.2f}, {col[1]:+.2f})")
            if mag < 0.25 * expected:
                raise AlignError(f"The {axis} jog produced almost no motion on the sky ({mag:.3f} arcsec/step vs "
                                 f"{expected:.3f} expected): motor not turning, screw slipping or camera not rigid.")
            if mag > 4.0 * expected and a.cfg.mechanics_confirmed:
                report.warnings.append(f"{axis}: measured step size is {mag / expected:.1f} x the configured mechanics")
            if cfg.align.learn_backlash:
                back = self._jog(axis, -done)                   # raw reversal: the slack shows up as a shortfall
                self._settle()
                sC = self.sample(quiet=True)
                short = float(((sC.vec_arcsec - sA.vec_arcsec) @ col) / (col @ col))     # microsteps not travelled
                bl_deg = abs(short) / a.usteps_per_deg
                report.backlash_deg[axis] = round(bl_deg, 4)
                self._emit("learn", f"{axis}: backlash about {bl_deg:.3f} deg")
                if bl_deg > a.cfg.backlash_overshoot_deg * 1.0:
                    a.cfg.backlash_overshoot_deg = min(1.0, 1.5 * bl_deg)
                    self._emit("learn", f"{axis}: raising the approach overshoot to {a.cfg.backlash_overshoot_deg:.3f} deg")
                s = sC
            else:
                s = sB
        m = np.column_stack([cols["az"], cols["alt"]])
        det = float(np.linalg.det(m))
        n1, n2 = np.linalg.norm(m[:, 0]), np.linalg.norm(m[:, 1])
        sin_angle = abs(det) / (n1 * n2) if n1 * n2 > 0 else 0.0
        if sin_angle < 0.2:
            raise AlignError("The two axes move the sky almost along the same line; the step-to-sky matrix is "
                             "ill-conditioned (is the camera looking at the sky? is one axis not moving?).")
        report.matrix_arcsec_per_ustep = m.tolist()
        return m

    # ------------------------------------------------------------------ main loop
    def run(self) -> AlignReport:
        self._cancel.clear()
        cfg = self.cfg.align
        t_start = time.perf_counter()
        rep = AlignReport()
        self.n_solves = 0
        self.hemisphere = None
        exposure0 = self.measurer.exposure_s
        try:
            a_cam = self._axis_in_camera()
            rep.uncalibrated = self.calibration.a_cam is None
            if rep.uncalibrated:
                rep.warnings.append("no calibration: the camera boresight was used as the axis")
            for name, a in self.motion.axes.items():
                if not a.cfg.mechanics_confirmed:
                    rep.warnings.append(f"{name}: arm length / screw pitch are design values, not measured "
                                        "(the loop learns the real scale, but soft limits in degrees are approximate)")
            if not self.motion.axes["az"].homed or not self.motion.axes["alt"].homed:
                rep.warnings.append("axes not homed: positions are assumed from the last session; end stops protect the travel")
            self._emit("measure", "first solve")
            s = self.sample(a_cam)
            rep.initial_error_arcmin = s.total_arcmin
            self._emit("measure", f"axis is {s.total_arcmin:.1f}' from the target pole "
                                  f"(alt {s.error.alt_arcmin:+.1f}', az {s.error.az_dial_arcmin:+.1f}')",
                       error=s.to_dict())
            if s.total_arcmin > cfg.max_start_error_deg * 60.0:
                raise AlignError(f"The axis is {s.total_arcmin / 60:.1f} deg from the pole, outside the fine range. "
                                 "Set the coarse tilt to your latitude and point the base roughly at the pole first.")
            m = self._learn(s, rep)
            s = self.sample(a_cam)
            rep.history.append({"iteration": 0, **s.to_dict()})
            prev: tuple[np.ndarray, np.ndarray] | None = None
            increases = 0
            stop_arcmin = min(cfg.target_arcmin, cfg.polish_arcmin) if cfg.polish_arcmin > 0 else cfg.target_arcmin
            for it in range(1, cfg.max_iterations + 1):
                self._check_cancel()
                if s.total_arcmin < stop_arcmin:
                    break
                ds = -cfg.gain * np.linalg.solve(m, s.vec_arcsec)            # [az, alt] microsteps
                limited = False
                moved = np.zeros(2)
                for k, axis in enumerate(AXES):
                    a = self.motion.axes[axis]
                    target = a.pos + ds[k]
                    if target < a.soft_min or target > a.soft_max:
                        limited = True
                        clipped = min(max(target, a.soft_min), a.soft_max)
                        short_deg = (target - clipped) / a.usteps_per_deg
                        self._emit("move", f"{axis} would need {short_deg:+.2f} deg beyond its travel limit; clipping")
                        ds[k] = clipped - a.pos
                    if abs(ds[k]) >= 1:
                        try:
                            moved[k] = self._jog(axis, int(round(ds[k])), preload=True)
                        except LimitError as exc:
                            rep.warnings.append(f"fine travel exhausted: {exc}")
                            self.motion.release_all()
                            s = self.sample(a_cam)
                            rep.history.append({"iteration": it, "moved_usteps": moved.tolist(), "limited": True, **s.to_dict()})
                            raise AlignError(f"{exc}.  Residual {s.total_arcmin:.1f}'. The base needs a coarse re-set, or the "
                                             "stored calibration is wrong (was the telescope really aligned when you pressed 'Declare aligned'?).") from exc
                self.motion.release_all()
                rep.motor_current_cut = True
                self._settle()
                s_new = self.sample(a_cam)
                self._emit("iterate", f"iteration {it}: {s.total_arcmin:.2f}' -> {s_new.total_arcmin:.2f}'",
                           iteration=it, error=s_new.to_dict())
                rep.history.append({"iteration": it, "moved_usteps": moved.tolist(), "limited": limited, **s_new.to_dict()})
                # refine the matrix from what actually happened (Broyden rank-1 update)
                if cfg.broyden_update and np.linalg.norm(moved) > 0.2 * a_jog_size(self, cfg):
                    de = s_new.vec_arcsec - s.vec_arcsec
                    m = m + 0.5 * np.outer(de - m @ moved, moved) / float(moved @ moved)
                if s_new.total_arcmin > 1.5 * s.total_arcmin + 1.0:
                    increases += 1
                    if increases >= 2:
                        raise AlignError("The error is growing, not shrinking: motor direction or matrix is wrong. Stopping.")
                else:
                    increases = 0
                if limited and s_new.total_arcmin >= s.total_arcmin * 0.9:
                    rep.warnings.append("fine travel exhausted: the base needs a coarse re-set")
                    s = s_new
                    rep.iterations = it
                    break
                s = s_new
                rep.iterations = it
            rep.converged = s.total_arcmin < cfg.target_arcmin
            rep.success = rep.converged
            rep.residual_arcmin = s.total_arcmin
            rep.residual_alt_arcmin = s.error.alt_arcmin
            rep.residual_east_arcmin = s.error.east_arcmin
            rep.message = (f"Aligned: residual {s.total_arcmin:.2f}' ({s.total_arcmin / 60:.3f} deg) after {rep.iterations} iterations."
                           if rep.converged else
                           f"Stopped: residual {s.total_arcmin:.2f}' did not reach {cfg.target_arcmin}' in {rep.iterations} iterations.")
            self._emit("done", rep.message, error=s.to_dict(), report=True)
        except AlignCancelled:
            rep.message = "Cancelled."
            self._emit("done", rep.message)
        except (AlignError, MotionFault) as exc:
            rep.message = str(exc)
            self._emit("error", rep.message)
        finally:
            self.measurer.exposure_s = exposure0
            self.motion.release_all()
            rep.motor_current_cut = True
            rep.solves = self.n_solves
            rep.duration_s = time.perf_counter() - t_start
        return rep


def a_jog_size(engine: AlignEngine, cfg) -> float:
    """Smallest move (microsteps) worth using for a matrix update: 20 % of the learning jog."""
    a = engine.motion.axes["az"]
    return float(a.deg_to_usteps(cfg.learn_jog_deg))

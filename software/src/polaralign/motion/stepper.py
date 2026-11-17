"""One motorised axis: trapezoidal step generation, soft/hard limits, homing, backlash handling.

Positions are integers in *microsteps* measured from the MIN end stop (``pos = 0`` there);
increasing position = towards MAX.  The axis keeps the driver disabled (outputs off) except while
moving, because the self-locking screw holds the plate.

Real-time caveat (untested on a Pi): steps are emitted from a Python loop with absolute deadlines
(``time.perf_counter_ns``), a coarse ``sleep`` and a short spin.  At the default 1 rev/s (3200
microsteps/s) that is a 312 us period; jitter of tens of microseconds is harmless for a stepper at
this speed, but the loop competes with the web server for the GIL, so the move thread asks for
``SCHED_FIFO`` when it is permitted to.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from ..config import AxisConfig, MotionConfig
from .gpio import GPIOBackend

log = logging.getLogger(__name__)


class MotionFault(RuntimeError):
    """Hard-stop hit, abort, or a move that cannot be done safely."""


class LimitError(MotionFault):
    """Requested position is outside the soft limits."""


@dataclass
class MoveResult:
    requested: int
    done: int                  # signed microsteps actually emitted (both phases)
    position: int
    aborted: bool = False
    used_overshoot: bool = False
    clamped: bool = False
    duration_s: float = 0.0
    notes: list[str] = field(default_factory=list)


class StepperAxis:
    def __init__(self, cfg: AxisConfig, motion: MotionConfig, gpio: GPIOBackend) -> None:
        self.cfg = cfg
        self.m = motion
        self.gpio = gpio
        self.usteps_per_rev = cfg.full_steps_per_rev * motion.microsteps
        self.usteps_per_deg = self.usteps_per_rev / cfg.deg_per_rev
        self.total_usteps = int(round(2.0 * cfg.end_stop_deg * self.usteps_per_deg))     # stop to stop
        self.margin = int(round(cfg.home_backoff_deg * self.usteps_per_deg))
        soft = max(int(round((cfg.end_stop_deg - cfg.travel_deg) * self.usteps_per_deg)), self.margin)
        self.soft_min = soft                                    # the +/-travel_deg working range, inside the stops
        self.soft_max = self.total_usteps - soft
        self.swapped = False        # homing found the "MIN" connector at the positive end: roles exchanged
        self.pos = self.total_usteps // 2           # assumed until homed
        self.homed = False
        self.enabled = False
        self.fault: str | None = None
        self.moving = False
        self._abort = threading.Event()
        self._lock = threading.RLock()
        self._fwd_level = 0 if cfg.invert_dir else 1
        self._setup_pins()

    # ------------------------------------------------------------------ pins
    def _setup_pins(self) -> None:
        c = self.cfg
        self.gpio.setup_output(c.enable_pin, 1)      # disabled first (active low, pulled up externally)
        self.gpio.setup_output(c.step_pin, 0)
        self.gpio.setup_output(c.dir_pin, 0)
        deb = int(c.endstop_debounce_ms * 1000)
        self.gpio.setup_input(c.endstop_min_pin, True, deb)
        self.gpio.setup_input(c.endstop_max_pin, True, deb)

    def _pin(self, which: str) -> int:
        """Pin of the *logical* min/max switch (homing may have found the connectors the other way round)."""
        c = self.cfg
        mn, mx = (c.endstop_max_pin, c.endstop_min_pin) if self.swapped else (c.endstop_min_pin, c.endstop_max_pin)
        return mn if which == "min" else mx

    def endstop(self, which: str) -> bool:
        """True when the logical min/max switch is tripped (see ``endstop_trip_level``)."""
        return self.gpio.read(self._pin(which)) == self.cfg.endstop_trip_level

    def enable(self) -> None:
        if not self.enabled:
            self.gpio.write(self.cfg.enable_pin, 0)
            self.enabled = True
            self._sleep(self.m.enable_settle_ms / 1000.0)

    def release(self) -> None:
        """Cut motor current (EN high).  The screw is self-locking and holds the plate."""
        self.gpio.write(self.cfg.enable_pin, 1)
        self.enabled = False

    def abort(self) -> None:
        self._abort.set()

    # ------------------------------------------------------------------ geometry helpers
    def deg_to_usteps(self, deg: float) -> int:
        return int(round(deg * self.usteps_per_deg))

    def usteps_to_deg(self, usteps: float) -> float:
        return usteps / self.usteps_per_deg

    @property
    def position_deg(self) -> float:
        """Plate angle relative to the centre of travel."""
        return self.usteps_to_deg(self.pos - self.total_usteps / 2.0)

    # ------------------------------------------------------------------ timing
    def _sleep(self, s: float) -> None:
        if self.m.realtime and s > 0:
            time.sleep(s)

    def _intervals_ns(self, n: int, vmax_ratio: float = 1.0) -> np.ndarray:
        """Per-step intervals (ns) for a trapezoidal profile of ``n`` steps."""
        upr = self.usteps_per_rev
        vmax = self.m.max_speed_rev_s * upr * vmax_ratio
        v0 = min(self.m.start_speed_rev_s * upr, vmax)
        acc = self.m.accel_rev_s2 * upr
        i = np.arange(n, dtype=np.float64)
        v = np.minimum(np.sqrt(v0 * v0 + 2.0 * acc * (i + 0.5)), np.sqrt(v0 * v0 + 2.0 * acc * (n - 1 - i + 0.5)))
        v = np.minimum(v, vmax)
        return (1e9 / v).astype(np.int64)

    @staticmethod
    def _spin_until(deadline_ns: int) -> None:
        now = time.perf_counter_ns
        remaining = deadline_ns - now()
        if remaining > 400_000:
            time.sleep((remaining - 250_000) / 1e9)
        while now() < deadline_ns:
            pass

    # ------------------------------------------------------------------ the pulse loop
    def _emit(self, n: int, forward: bool, vmax_ratio: float = 1.0, watch: str | None = "auto") -> tuple[int, str | None]:
        """Emit ``n`` steps.  Returns (steps_done, reason) with reason in {None, 'abort', 'min', 'max'}."""
        if n <= 0:
            return 0, None
        g = self.gpio
        c = self.cfg
        g.write(c.dir_pin, self._fwd_level if forward else 1 - self._fwd_level)
        self._sleep(self.m.dir_setup_us / 1e6)
        sgn = 1 if forward else -1
        intervals = self._intervals_ns(n, vmax_ratio)
        check_every = max(1, self.m.microsteps)
        watch_which = ("max" if forward else "min") if watch == "auto" else watch
        confirm = 0
        confirm_which = None
        realtime = self.m.realtime
        pulse_ns = int(self.m.step_pulse_us * 1000)
        step_pin = c.step_pin
        write = g.write
        now = time.perf_counter_ns
        deadline = now()
        done = 0
        base = self.pos
        reason: str | None = None
        self.moving = True
        rt = try_realtime_priority() if realtime else False
        try:
            for i in range(n):
                write(step_pin, 1)
                if realtime and pulse_ns > 2000:
                    end = now() + pulse_ns
                    while now() < end:
                        pass
                write(step_pin, 0)
                done += 1
                if done % check_every == 0:
                    self.pos = base + sgn * done            # live position for the UI and the end-stop logic
                    if self._abort.is_set():
                        reason = "abort"
                        break
                    if watch_which:
                        hit = (("min" if self.endstop("min") else "max" if self.endstop("max") else None)
                               if watch_which == "both" else (watch_which if self.endstop(watch_which) else None))
                        if hit:
                            confirm = confirm + 1 if hit == confirm_which else 1
                            confirm_which = hit
                            if confirm >= 2:
                                reason = hit
                                break
                        else:
                            confirm, confirm_which = 0, None
                if realtime:
                    deadline += int(intervals[i])
                    self._spin_until(deadline)
        finally:
            self.moving = False
            self.pos = base + sgn * done
            if rt:
                drop_realtime_priority()
        return done, reason

    # ------------------------------------------------------------------ moves
    def move_relative(self, delta_usteps: int, *, preload_finish: bool = True, release: bool = True,
                      clamp: bool = False, vmax_ratio: float = 1.0) -> MoveResult:
        with self._lock:
            return self._move_to(self.pos + int(delta_usteps), preload_finish, release, clamp, vmax_ratio)

    def move_to(self, target_usteps: int, *, preload_finish: bool = True, release: bool = True,
                clamp: bool = False, vmax_ratio: float = 1.0) -> MoveResult:
        with self._lock:
            return self._move_to(int(target_usteps), preload_finish, release, clamp, vmax_ratio)

    def _move_to(self, target: int, preload_finish: bool, release: bool, clamp: bool, vmax_ratio: float) -> MoveResult:
        c = self.cfg
        res = MoveResult(requested=target - self.pos, done=0, position=self.pos)
        if self.fault:
            raise MotionFault(f"{c.name}: axis in fault state: {self.fault}")
        # Targets outside the working range are refused, except moves that head back *toward* it (right after homing the
        # axis sits at the MIN stop, which is outside the +/-6 deg range).
        beyond_low = target < self.soft_min and target <= self.pos
        beyond_high = target > self.soft_max and target >= self.pos
        if beyond_low or beyond_high:
            if not clamp:
                raise LimitError(f"{c.name}: target {self.usteps_to_deg(target - self.total_usteps / 2):+.3f} deg is outside "
                                 f"+/-{self.usteps_to_deg(self.soft_max - self.total_usteps / 2):.2f} deg soft limits")
            target = min(max(target, self.soft_min), self.soft_max)
            res.clamped = True
        self._abort.clear()
        t0 = time.perf_counter()
        start = self.pos
        try:
            self.enable()
            delta = target - self.pos
            ov = self.deg_to_usteps(c.backlash_overshoot_deg)
            if preload_finish and delta != 0 and ov > 0 and (1 if delta > 0 else -1) != c.preload_dir:
                # go past the target on the non-preload side, then finish in the preload direction
                t1 = target - c.preload_dir * ov
                t1 = min(max(t1, self.soft_min), self.soft_max)
                if (t1 - target) * c.preload_dir < 0:      # there is room on the far side
                    res.used_overshoot = True
                    self._go(t1, vmax_ratio, res)
                    if not res.aborted:
                        self._go(target, vmax_ratio, res)
                else:
                    res.notes.append("no room for backlash overshoot; approached against preload")
                    self._go(target, vmax_ratio, res)
            else:
                self._go(target, vmax_ratio, res)
        finally:
            if release:
                self.release()
            res.done = self.pos - start
            res.position = self.pos
            res.duration_s = time.perf_counter() - t0
        return res

    def _go(self, target: int, vmax_ratio: float, res: MoveResult) -> None:
        delta = target - self.pos
        if delta == 0:
            return
        done, reason = self._emit(abs(delta), delta > 0, vmax_ratio)
        if reason == "abort":
            res.aborted = True
        elif reason in ("min", "max"):
            self._hit_hard_stop(reason)

    def _hit_hard_stop(self, which: str) -> None:
        """A hard stop in normal travel means the configured mechanics (or our position count) were off.

        It is not a fault: the switch tells us exactly where the travel ends, so learn that, back off the
        switch, and refuse the move with a :class:`LimitError` the caller can report.
        """
        c = self.cfg
        if which == "min":
            if self.homed:
                self.pos = 0
            self.soft_min = max(self.soft_min, self.pos + self.margin)
            where = "MIN"
        else:
            if self.homed:                         # MIN is the reference, so the MAX stop gives the true span
                self.total_usteps = self.pos
            self.soft_max = min(self.soft_max, self.pos - self.margin)
            where = "MAX"
        log.warning("%s: hit the %s end stop; soft travel is now %.2f..%.2f deg", c.name, where,
                    self.usteps_to_deg(self.soft_min - self.total_usteps / 2), self.usteps_to_deg(self.soft_max - self.total_usteps / 2))
        # step back off the switch (slowly, not watching the switch we are leaving)
        self._emit(self.margin, which == "min", c.home_speed_ratio, watch=None)
        self.release()
        raise LimitError(f"{c.name}: reached the {where} end stop; the usable travel is now "
                         f"{self.usteps_to_deg(self.soft_min - self.total_usteps / 2):+.2f} .. "
                         f"{self.usteps_to_deg(self.soft_max - self.total_usteps / 2):+.2f} deg (check arm length/pitch in the config)")

    def clear_fault(self) -> None:
        self.fault = None
        self.homed = False

    # ------------------------------------------------------------------ homing
    def home(self, release: bool = True, go_to_centre: bool = False, measure_span: bool = False) -> int:
        """Drive to the MIN stop, set pos = 0 there and back off.  Returns the steps travelled.

        ``measure_span`` also drives to the MAX stop and replaces the configured travel with the measured one
        (independent of arm length / pitch in the config, which for the altitude axis are placeholders).
        """
        with self._lock:
            c = self.cfg
            self._abort.clear()
            self.fault = None
            travelled = 0
            try:
                self.enable()
                if self.endstop("min") or self.endstop("max"):
                    # Starting on a switch: we do not know which end of the screw that is (the connectors may be wired
                    # either way round).  A short move in the positive direction is safe at either end (the jackscrew's
                    # hard limit is 1.5-3 deg past the switch) and frees the switch if it was the negative end.
                    done, _ = self._emit(self.margin * 2 + 1, True, c.home_speed_ratio, watch=None)
                    travelled += done
                limit = int(1.4 * self.total_usteps) + 2 * self.margin
                # watch BOTH switches: the connector labelled MIN may be at the other end of the screw (motor
                # wiring), and the hardware's jackscrew hard limit is only ~1-2 deg past the switch
                done, reason = self._emit(limit, False, c.home_speed_ratio, watch="both")
                travelled += done
                if reason == "abort":
                    raise MotionFault(f"{c.name}: homing aborted")
                if reason == "max":
                    self.swapped = not self.swapped
                    log.warning("%s: the switch wired as MIN is at the positive end; roles exchanged", c.name)
                    reason = "min"
                if reason != "min":
                    raise MotionFault(f"{c.name}: no end stop found after {self.usteps_to_deg(done):.1f} deg "
                                      "(switch wiring? trip level? motor direction?)")
                self.pos = 0
                self.homed = True
                done, _ = self._emit(self.margin, True, c.home_speed_ratio, watch=None)   # back off
                travelled += done
                if measure_span:
                    limit = int(1.6 * self.total_usteps)
                    done, reason = self._emit(limit, True, c.home_speed_ratio, watch="max")
                    travelled += done
                    if reason != "max":
                        raise MotionFault(f"{c.name}: MAX end stop not found within {self.usteps_to_deg(done):.1f} deg")
                    self.total_usteps = self.pos
                    soft = max(int(self.total_usteps / 2 - c.travel_deg * self.usteps_per_deg), self.margin)
                    self.soft_min, self.soft_max = soft, self.total_usteps - soft
                    done, _ = self._emit(self.margin, False, c.home_speed_ratio, watch=None)     # back off the MAX switch
                    travelled += done
                    log.info("%s: measured travel %.2f deg", c.name, self.usteps_to_deg(self.total_usteps))
                if go_to_centre:
                    self._go(self.total_usteps // 2, c.home_speed_ratio, MoveResult(0, 0, self.pos))
            finally:
                if release:
                    self.release()
            return travelled

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        return {"name": self.cfg.name, "position_usteps": self.pos, "position_deg": round(self.position_deg, 4),
                "homed": self.homed, "switches_swapped": self.swapped, "enabled": self.enabled, "moving": self.moving, "fault": self.fault,
                "limit_deg": round(self.usteps_to_deg(self.soft_max - self.total_usteps / 2), 3),
                "travel_deg": round(self.usteps_to_deg(self.total_usteps), 3),
                "min_switch": self.endstop("min"), "max_switch": self.endstop("max"),
                "mechanics_confirmed": self.cfg.mechanics_confirmed,
                "arcsec_per_full_step": round(self.cfg.arcsec_per_full_step, 3)}


def try_realtime_priority(priority: int = 20) -> bool:
    """Ask for SCHED_FIFO for the calling thread (needs CAP_SYS_NICE or a RLIMIT_RTPRIO grant).

    Held only for the duration of a step burst (see :func:`drop_realtime_priority`): a FIFO thread that ran
    Python solves for seconds could starve the web server.
    """
    try:
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(priority))  # type: ignore[attr-defined]
        return True
    except (AttributeError, PermissionError, OSError):
        return False


def drop_realtime_priority() -> None:
    try:
        os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))  # type: ignore[attr-defined]
    except (AttributeError, PermissionError, OSError):  # pragma: no cover
        pass

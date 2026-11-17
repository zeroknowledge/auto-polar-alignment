"""Motion layer against FakeGPIO: step counts, directions, current cut, limits, backlash, homing."""
import copy

import numpy as np
import pytest

from polaralign.config import MotionConfig, sim_config
from polaralign.motion.controller import MotionController
from polaralign.motion.gpio import FakeGPIO
from polaralign.motion.stepper import LimitError, MotionFault, StepperAxis
from polaralign.sim.mount import MountParams, SimMount


def make_axis(**axis_kw):
    cfg = sim_config().motion
    for k, v in axis_kw.items():
        setattr(cfg.az, k, v)
    gpio = FakeGPIO()
    ax = StepperAxis(cfg.az, cfg, gpio)
    for pin in (cfg.az.endstop_min_pin, cfg.az.endstop_max_pin):          # switches idle (normally-closed wiring: idle = LOW)
        gpio.set_input_source(pin, lambda: IDLE)
    return ax, gpio, cfg


IDLE, TRIP = 0, 1          # hardware/README.md: common + normally-closed, so a pressed or broken switch reads HIGH


def connect_idle_switches(gpio, cfg):
    """A disconnected NC switch reads HIGH (= tripped, the safe way round), so tests must 'connect' them."""
    for ax in (cfg.az, cfg.alt):
        for pin in (ax.endstop_min_pin, ax.endstop_max_pin):
            gpio.set_input_source(pin, lambda: IDLE)


class Recorder:
    """Counts rising STEP edges and remembers the DIR level at each, and EN transitions."""

    def __init__(self, gpio, cfg):
        self.steps, self.dirs, self.en_log = 0, [], []
        gpio.on_write(cfg.step_pin, lambda o, n: self._step(gpio, cfg) if n else None)
        gpio.on_write(cfg.enable_pin, lambda o, n: self.en_log.append(n))

    def _step(self, gpio, cfg):
        self.steps += 1
        self.dirs.append(gpio.levels[cfg.dir_pin])


def test_microstep_resolution_numbers():
    ax, _, cfg = make_axis()
    assert ax.usteps_per_rev == 200 * 16
    assert ax.usteps_per_deg == pytest.approx(3200 / 0.7162, rel=1e-3)
    assert ax.usteps_to_deg(ax.deg_to_usteps(0.01)) == pytest.approx(0.01, abs=2e-4)   # 0.01 deg resolution (doc requirement)


def test_move_emits_exact_steps_in_the_right_direction_and_cuts_current():
    ax, gpio, cfg = make_axis()
    rec = Recorder(gpio, cfg.az)
    assert gpio.levels[cfg.az.enable_pin] == 1                       # disabled at start
    start = ax.pos
    res = ax.move_relative(+500, preload_finish=False)
    assert rec.steps == 500 and ax.pos == start + 500 and res.done == 500
    assert set(rec.dirs) == {1}
    assert rec.en_log == [0, 1]                                      # enabled for the move, released after
    assert gpio.levels[cfg.az.enable_pin] == 1
    ax.move_relative(-200, preload_finish=False)
    assert ax.pos == start + 300 and rec.dirs[-1] == 0


def test_invert_dir_flips_the_pin_level():
    ax, gpio, cfg = make_axis(invert_dir=True)
    rec = Recorder(gpio, cfg.az)
    ax.move_relative(+50, preload_finish=False)
    assert set(rec.dirs) == {0}


def test_finish_in_preload_direction():
    """A negative move overshoots on the non-preload side then approaches in the preload direction."""
    ax, gpio, cfg = make_axis(backlash_overshoot_deg=0.1)
    rec = Recorder(gpio, cfg.az)
    start = ax.pos
    res = ax.move_relative(-300)                                      # preload_dir = +1
    assert res.used_overshoot and ax.pos == start - 300
    assert rec.dirs[0] == 0 and rec.dirs[-1] == 1                     # went negative, finished positive
    assert rec.steps == 300 + 2 * ax.deg_to_usteps(0.1)
    # a positive move needs no overshoot
    rec.steps, rec.dirs = 0, []
    res = ax.move_relative(+300)
    assert not res.used_overshoot and rec.steps == 300 and set(rec.dirs) == {1}


def test_soft_limits_raise_or_clamp():
    ax, _, _ = make_axis()
    with pytest.raises(LimitError):
        ax.move_relative(ax.total_usteps)
    res = ax.move_relative(ax.total_usteps, clamp=True, preload_finish=False)
    assert res.clamped and ax.pos == ax.soft_max
    assert ax.position_deg == pytest.approx(6.0, abs=0.01)            # the +/-6 deg working range (the stops are at 8.05)


def test_trapezoid_profile_ramps_up_and_down():
    ax, _, cfg = make_axis()
    iv = ax._intervals_ns(4000)
    assert iv[0] > iv[len(iv) // 2] < iv[-1]                          # slow at both ends, fastest in the middle
    assert iv.min() == pytest.approx(1e9 / (cfg.max_speed_rev_s * ax.usteps_per_rev), rel=0.02)
    assert np.all(np.diff(iv[: len(iv) // 3]) <= 0) and np.all(np.diff(iv[-len(iv) // 3:]) >= 0)


def test_abort_stops_mid_move():
    ax, gpio, cfg = make_axis()
    rec = Recorder(gpio, cfg.az)

    def abort_after_100(o, n):
        if n and rec.steps >= 100:
            ax.abort()
    gpio.on_write(cfg.az.step_pin, abort_after_100)
    res = ax.move_relative(1000, preload_finish=False)
    assert res.aborted and 100 <= res.done < 200
    assert gpio.levels[cfg.az.enable_pin] == 1                        # still released


def test_hard_stop_in_normal_travel_teaches_the_limit_instead_of_faulting():
    ax, gpio, cfg = make_axis()
    hit_at = ax.total_usteps // 2 + 200                                  # the real MAX stop is nearer than configured
    gpio.set_input_source(cfg.az.endstop_max_pin, lambda: TRIP if ax.pos >= hit_at else IDLE)
    with pytest.raises(LimitError, match="reached the MAX end stop"):
        ax.move_relative(800, preload_finish=False)
    assert ax.fault is None and gpio.levels[cfg.az.enable_pin] == 1       # not a fault: motors released, axis usable
    assert abs(ax.soft_max - (hit_at - ax.margin)) < 40                    # the limit was learned from the switch (+ debounce)
    assert ax.pos < hit_at                                                 # and it backed off the switch
    ax.move_relative(-100, preload_finish=False)                           # still usable inside the new limits
    with pytest.raises(LimitError):
        ax.move_relative(+1000)                                            # but not beyond them


def test_endstop_needs_two_consecutive_reads_no_glitch():
    ax, gpio, cfg = make_axis()
    calls = {"n": 0}

    def glitch():
        calls["n"] += 1
        return TRIP if calls["n"] == 3 else IDLE    # a single spurious read (EMI, contact bounce)
    gpio.set_input_source(cfg.az.endstop_max_pin, glitch)
    res = ax.move_relative(400, preload_finish=False)
    assert res.done == 400 and not ax.fault


def test_homing_against_the_simulated_mount():
    cfg = sim_config().motion
    gpio = FakeGPIO()
    mc = MotionController(cfg, gpio)
    mount = SimMount(cfg, MountParams(stall_prob_per_move=0.0))
    mount.attach(gpio)
    assert not any(a.homed for a in mc.axes.values())
    mc.home(go_to_centre=False)
    for name, a in mc.axes.items():
        st = mount.stages[name]
        assert a.homed and not a.enabled
        # the plate is just off its MIN stop; the controller counts motor steps, so it is off by about the backlash
        assert 0 < st.p < a.margin + 60 and abs(st.p - a.margin) <= st.gap + 60
        assert a.position_deg == pytest.approx(a.usteps_to_deg(a.pos - a.total_usteps / 2), abs=1e-6)
    # after homing, a +1 deg move really moves the simulated plate by about 1 deg (mechanical scale error 1.5 %)
    a = mc.axes["az"]
    before = mount.stages["az"].p
    mc.move_relative_deg("az", 1.0, preload_finish=False)
    assert (mount.stages["az"].p - before) * mount.stages["az"].deg_per_ustep == pytest.approx(1.0, rel=0.03)


def test_homing_reports_a_dead_switch():
    ax, gpio, cfg = make_axis()
    gpio.set_input_source(cfg.az.endstop_min_pin, lambda: IDLE)        # never trips
    with pytest.raises(MotionFault, match="no end stop found"):
        ax.home()
    assert gpio.levels[cfg.az.enable_pin] == 1


def test_position_hint_persisted_between_sessions(tmp_path):
    cfg = sim_config().motion
    f = tmp_path / "motion.json"
    gpio = FakeGPIO()
    mc = MotionController(cfg, gpio, state_file=f)
    connect_idle_switches(gpio, cfg)
    mc.move_relative_usteps("az", 777, preload_finish=False)
    mc2 = MotionController(cfg, FakeGPIO(), state_file=f)
    assert mc2.axes["az"].pos == mc.axes["az"].pos and not mc2.axes["az"].homed


def test_controller_programs_drivers_and_reports_missing_uart():
    from polaralign.motion.tmc2209 import FakeTmcBus
    cfg = sim_config().motion
    mc = MotionController(cfg, FakeGPIO(), FakeTmcBus((0, 1)))
    mc.configure_drivers()
    assert mc.driver_error is None and set(mc.drivers) == {"az", "alt"}
    mc = MotionController(cfg, FakeGPIO(), FakeTmcBus((0, 1), echo=False))
    mc.configure_drivers()
    assert mc.driver_error and "echo" in mc.driver_error


def test_measure_span_replaces_the_configured_travel_with_the_real_one():
    cfg = sim_config().motion
    gpio = FakeGPIO()
    mc = MotionController(cfg, gpio)
    # the real altitude mechanics are 8 % coarser than the (placeholder) config says -> less travel in microsteps
    mount = SimMount(cfg, MountParams(stall_prob_per_move=0.0, alt_scale_error=0.08, release_shift_deg=0.0))
    mount.attach(gpio)
    alt = mc.axes["alt"]
    configured = alt.total_usteps
    mc.home(axes=("alt",), measure_span=True, go_to_centre=False)
    true_span = mount.stages["alt"].travel
    assert alt.total_usteps < configured * 0.99
    assert alt.total_usteps == pytest.approx(true_span, abs=700)           # within the backlash gap and the debounce
    assert alt.soft_max == alt.total_usteps - alt.soft_min and alt.homed and alt.fault is None
    assert alt.status()["travel_deg"] == pytest.approx(alt.usteps_to_deg(alt.total_usteps), abs=1e-3)


def test_normally_closed_switches_read_tripped_when_high_or_broken():
    ax, gpio, cfg = make_axis()
    assert cfg.az.endstop_trip_level == 1                     # NC wiring is the default (hardware/README.md)
    assert not ax.endstop("min") and not ax.endstop("max")
    gpio.set_input_source(cfg.az.endstop_min_pin, lambda: 1)  # pressed, or the wire came off the pull-up
    assert ax.endstop("min") and not ax.endstop("max")
    # normally-open wiring (switch to GND when pressed) is a setting away
    cfg2 = sim_config().motion
    cfg2.az.endstop_trip_level = 0
    gpio2 = FakeGPIO()
    ax2 = StepperAxis(cfg2.az, cfg2, gpio2)
    gpio2.set_input_source(cfg2.az.endstop_min_pin, lambda: 0)
    assert ax2.endstop("min")


def test_working_range_sits_inside_the_end_stops():
    cfg = sim_config().motion
    az, alt = StepperAxis(cfg.az, cfg, FakeGPIO()), StepperAxis(cfg.alt, cfg, FakeGPIO())
    for ax in (az, alt):
        assert ax.usteps_to_deg(ax.soft_max - ax.total_usteps / 2) == pytest.approx(6.0, abs=0.01)
        assert ax.usteps_to_deg(ax.soft_min) > 1.0                           # clear of the switch (8.05 / 7.25 deg from centre)
    assert az.usteps_to_deg(az.total_usteps) == pytest.approx(16.1, abs=0.01)
    assert alt.cfg.arm_mm == 150.0 and alt.cfg.arcsec_per_full_step == pytest.approx(6.9, abs=0.05)     # hardware/README.md


@pytest.mark.parametrize("swap", [False, True])
def test_homing_finds_which_connector_is_which(swap):
    """The connector labelled MIN may be wired to the switch at the positive end; homing must stop at whichever
    trips first (never run on into the jackscrew's hard limit) and relabel."""
    cfg = sim_config().motion
    gpio = FakeGPIO()
    mc = MotionController(cfg, gpio)
    mount = SimMount(cfg, MountParams(stall_prob_per_move=0.0, swap_endstops=(swap, swap)))
    mount.attach(gpio)
    mc.home(go_to_centre=False)
    for name, a in mc.axes.items():
        st = mount.stages[name]
        assert a.homed and a.swapped is swap and a.fault is None
        assert 0 < st.p < a.margin + 60 or st.p > 0            # stopped at the switch: never driven into the hard stop
        assert st.p < st.travel - 1.0 and st.p > 0.0
    mc.home(go_to_centre=True)                                 # and it works the second time, starting off the stop
    assert abs(mc.axes["az"].position_deg) < 0.01


def test_homing_from_a_switch_that_is_already_tripped():
    cfg = sim_config().motion
    gpio = FakeGPIO()
    mc = MotionController(cfg, gpio)
    mount = SimMount(cfg, MountParams(stall_prob_per_move=0.0, start_fraction_az=0.0, start_fraction_alt=1.0))
    mount.attach(gpio)
    assert mc.axes["az"].endstop("min") and mc.axes["alt"].endstop("max")      # parked on a stop at each end
    mc.home(go_to_centre=False)
    assert all(a.homed and a.fault is None for a in mc.axes.values())

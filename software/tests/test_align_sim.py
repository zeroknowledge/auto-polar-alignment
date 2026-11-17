"""End-to-end: the real extractor, solver, motion layer and alignment loop against the simulator.

Acceptance criterion (from the task): from a 5 degree initial error, with realistic noise, backlash,
scale errors, lost steps and a shift when the motors release, converge to under 0.05 degrees *true* error
within 8 iterations -- measured against the simulator's ground truth, not against the loop's own estimate.
"""
import math

import numpy as np
import pytest

from polaralign.align.engine import AlignEngine
from polaralign.align.pipeline import Measurer
from polaralign.astro import Site
from polaralign.calibration import CalibrationStore
from polaralign.config import sim_config
from polaralign.extract import get_extractor
from polaralign.sim import MountParams, SensorParams, build_sim_hardware
from polaralign.sim.scenario import run_scenario

pytestmark = pytest.mark.slow

# NB: at latitude phi the azimuth stage's +/-6 deg moves the axis only +/-6*cos(phi) deg across the sky (3.8 deg at
# 48 N, 2.8 deg at 62 N), so a 5 deg error is only correctable when its east-west part fits; the directions below
# keep that part reachable.  test_exhausted_fine_travel_is_reported covers the case where it does not fit.
SCENARIOS = [
    # id,            lat,   lon,   seed, error, direction, mount overrides, sensor overrides
    ("dubai",         25.2,  55.3,  1,    5.0,   130.0, {}, {}),
    ("germany",       48.1,  11.6,  2,    5.0,   330.0, {"az_sign": -1, "alt_sign": +1}, {}),
    ("scotland",      57.5,  -4.2,  3,    5.0,    15.0, {"az_sign": +1, "alt_sign": -1, "backlash_az_deg": 0.1}, {}),
    ("sydney_south", -33.9, 151.2,  4,    5.0,   200.0, {}, {}),
    ("chile_south",  -29.0, -70.7,  5,    4.0,    75.0, {"az_sign": -1, "alt_sign": -1}, {}),
    ("faint_sky",     35.0, -106.0, 6,    5.0,   200.0, {}, {"mag0_e_per_s": 5.5e4, "sky_e_per_s_px": 6.0}),
    ("near_equator",   9.0, 101.7,  7,    5.0,    40.0, {}, {"cfa": ""}),       # the monochrome sensor still works
]


@pytest.mark.parametrize("name,lat,lon,seed,err,direction,mount_kw,sensor_kw", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_converges_from_five_degrees(solver, name, lat, lon, seed, err, direction, mount_kw, sensor_kw):
    site = Site(lat, lon)
    mp = MountParams(axis_alt_deg=abs(lat) + 3.0, axis_az_deg=4.0 if lat >= 0 else 184.0, seed=seed + 100, **mount_kw)
    res = run_scenario(seed=seed, site=site, initial_error_deg=err, direction_deg=direction, mount=mp,
                       sensor=SensorParams(**{"cfa": "RGGB", **sensor_kw}), solver=solver)   # colour IMX296 unless overridden
    r = res.report
    assert r.success, r.message
    assert res.initial_true_error_deg == pytest.approx(err, abs=0.05)
    assert res.final_true_error_deg < 0.05, f"{name}: true error {res.final_true_error_deg:.4f} deg"   # the acceptance criterion
    assert r.iterations <= 8
    # the loop's own residual agrees with the truth to within the calibration error plus noise
    assert abs(r.residual_arcmin / 60.0 - res.final_true_error_deg) < res.calibration_error_deg + 0.02
    assert r.motor_current_cut
    for ax in res.hw.motion.axes.values():
        assert not ax.enabled
    assert res.hw.gpio.levels[res.hw.config.motion.az.enable_pin] == 1
    assert res.hw.gpio.levels[res.hw.config.motion.alt.enable_pin] == 1
    # learned something sensible about the mechanics (true backlash was configured in the mount)
    assert set(r.backlash_deg) == {"az", "alt"}
    assert r.backlash_deg["alt"] == pytest.approx(res.hw.world.mount.p.backlash_alt_deg, abs=0.04)
    assert r.duration_s < 60


def test_time_to_align_in_simulated_seconds(solver):
    """Doc target: under two minutes from a rough set-up.  Simulated time includes exposures and settle delays."""
    cfg = sim_config()
    cfg.align.settle_s = 1.5
    res = run_scenario(seed=11, config=cfg, solver=solver)
    elapsed = (res.hw.world.clock.now() - res.hw.world.clock.now().replace(hour=20, minute=30, second=0, microsecond=0)).total_seconds()
    assert res.report.success
    assert elapsed < 120, f"{elapsed:.0f} simulated seconds"


def test_refraction_model_matters_when_the_base_travels(solver):
    """Calibrate where the pole is at 10 deg altitude (R = 5.4'), then use the base at 55 deg (R = 0.7').
    Without the refraction model the 4.7' (0.078 deg) difference lands in the result."""
    errs = {}
    for mode in ("model", "off"):
        cfg = sim_config()
        cfg.align.refraction = mode
        site_a, site_b = Site(10.0, 100.0), Site(55.0, 10.0)
        hw = build_sim_hardware(cfg, site=site_a, seed=21, aberration=False,
                                mount=MountParams(axis_alt_deg=13.0, axis_az_deg=4.0, seed=121, stall_prob_per_move=0.0))
        hw.motion.home()
        cal = CalibrationStore(None)
        current = {"site": site_a}
        eng = AlignEngine(cfg, Measurer(hw.camera, get_extractor(cfg.extractor), solver), hw.motion, cal,
                          hw.time_source, lambda: current["site"])
        hw.world.set_coarse(0.0)
        eng.declare_aligned()
        # move the whole base to another site
        hw.world.site = current["site"] = site_b
        hw.world.set_coarse(4.0, 25.0)       # mostly an altitude error: the azimuth stage only moves the axis cos(lat) per degree
        eng.hemisphere = None
        rep = eng.run()
        assert rep.success, rep.message
        errs[mode] = hw.world.true_axis_error_deg()
    assert errs["model"] < 0.03
    assert errs["off"] > 0.05 and errs["off"] > 2 * errs["model"]


def test_uncalibrated_bench_mode_points_the_camera_at_the_pole(solver):
    cfg = sim_config()
    hw = build_sim_hardware(cfg, seed=31, mount=MountParams(seed=131, stall_prob_per_move=0.0))
    hw.motion.home()
    site = hw.world.site
    eng = AlignEngine(cfg, Measurer(hw.camera, get_extractor(cfg.extractor), solver), hw.motion, CalibrationStore(None),
                      hw.time_source, lambda: site)
    rep = eng.run()                                                    # refused without a calibration ...
    assert not rep.success and "calibration" in rep.message.lower()
    # bench mode treats the camera boresight as the axis, so aim the *boresight* about 4 deg from the pole
    pole = hw.world.apparent_pole_enu()
    side = np.cross(pole, [0, 0, 1.0])
    goal = pole + math.radians(4.0) * side / np.linalg.norm(side)
    a = hw.world.mount.axis_enu()
    for _ in range(8):
        hw.world.mount.set_axis_direction(a)
        a = a + (goal - hw.world.mount.camera_axes_enu()[:, 0])
    hw.world.mount.set_axis_direction(a)
    eng.allow_uncalibrated = True
    rep = eng.run()
    assert rep.success and rep.uncalibrated and any("no calibration" in w for w in rep.warnings)
    bore = hw.world.mount.camera_axes_enu()[:, 0]
    p = hw.world.apparent_pole_enu()
    assert math.degrees(math.atan2(np.linalg.norm(np.cross(bore, p)), bore @ p)) < 0.06       # camera boresight on the pole


@pytest.fixture()
def rig(solver):
    cfg = sim_config()
    hw = build_sim_hardware(cfg, seed=41, mount=MountParams(seed=141, stall_prob_per_move=0.0))
    hw.motion.home()
    cal = CalibrationStore(None)
    events = []
    site = hw.world.site
    eng = AlignEngine(cfg, Measurer(hw.camera, get_extractor(cfg.extractor), solver), hw.motion, cal, hw.time_source,
                      lambda: site, on_event=events.append)
    hw.world.set_coarse(0.01, 40)
    eng.declare_aligned()
    return hw, eng, events


def test_refuses_to_start_when_the_axis_is_far_outside_the_fine_range(rig):
    hw, eng, _ = rig
    hw.world.set_coarse(20.0, 130.0)
    moved_before = sum(st.steps_total for st in hw.world.mount.stages.values())
    rep = eng.run()
    assert not rep.success and "fine range" in rep.message and rep.motor_current_cut
    assert sum(st.steps_total for st in hw.world.mount.stages.values()) == moved_before     # nothing moved


def test_dead_motor_is_diagnosed(rig):
    hw, eng, _ = rig
    hw.world.set_coarse(3.0, 10.0)
    hw.world.mount.stages["alt"].set_enabled = lambda e: None           # driver unpowered / EN stuck
    hw.world.mount.stages["az"].set_enabled = lambda e: None
    rep = eng.run()
    assert not rep.success and ("did not move" in rep.message or "almost no motion" in rep.message)


def test_blind_camera_is_diagnosed(rig):
    hw, eng, _ = rig
    from polaralign.camera import FakeCamera
    eng.measurer.camera = FakeCamera()                                   # lens cap on: noise only
    rep = eng.run()
    assert not rep.success and "plate-solve" in rep.message and rep.motor_current_cut


def test_cancel_stops_the_loop_and_cuts_current(rig):
    hw, eng, events = rig
    hw.world.set_coarse(4.0, 50.0)
    eng.on_event = lambda e: (events.append(e), eng.cancel() if e.get("phase") == "learn" else None)
    rep = eng.run()
    assert not rep.success and rep.message == "Cancelled." and rep.motor_current_cut
    assert all(not a.enabled for a in hw.motion.axes.values())


def test_knock_during_a_measurement_forces_a_resolve(rig):
    hw, eng, events = rig
    hw.world.set_coarse(2.0, 10.0)
    flags = iter([True, False] + [False] * 200)
    eng.knock_source = lambda: next(flags)
    s = eng.sample()
    assert any("knock" in e["message"] for e in events)
    assert eng.n_solves >= 1 and s.total_arcmin > 60


def test_exhausted_fine_travel_is_reported_not_crashed(solver):
    cfg = sim_config()
    # the base has been left far off AND near the end of its travel: the fine stages cannot reach the pole
    hw = build_sim_hardware(cfg, seed=51, mount=MountParams(seed=151, stall_prob_per_move=0.0, start_fraction_az=0.5))
    hw.motion.home()
    site = hw.world.site
    cal = CalibrationStore(None)
    eng = AlignEngine(cfg, Measurer(hw.camera, get_extractor(cfg.extractor), solver), hw.motion, cal, hw.time_source,
                      lambda: site)
    hw.world.set_coarse(0.01, 40)
    eng.declare_aligned()
    hw.world.set_coarse(9.5, 90.0)                                       # pure azimuth error beyond +/-5.75 deg of travel
    rep = eng.run()
    assert not rep.success and rep.motor_current_cut
    assert all(a.fault is None for a in hw.motion.axes.values())         # it stopped at the soft limit; no hard stop hit
    assert any("travel" in w for w in rep.warnings) or "travel" in rep.message or rep.residual_arcmin > 3


def test_wrong_calibration_ends_gracefully_with_a_useful_message(solver):
    """Regression (found by driving the web UI): 'Declare aligned' pressed while the base was NOT aligned makes the loop
    chase a wrong pole until a hard stop.  That must end as a clear message, not a fault that bricks the axis."""
    cfg = sim_config()
    hw = build_sim_hardware(cfg, seed=71, mount=MountParams(seed=171, stall_prob_per_move=0.0, alt_scale_error=0.08))
    hw.motion.home()                                      # configured alt mechanics are 8 % off the real ones
    site = hw.world.site
    cal = CalibrationStore(None)
    eng = AlignEngine(cfg, Measurer(hw.camera, get_extractor(cfg.extractor), solver), hw.motion, cal, hw.time_source, lambda: site)
    hw.world.set_coarse(5.0, 100.0)                       # base is 5 deg off ...
    eng.declare_aligned()                                 # ... but the user declared "aligned" anyway
    hw.world.set_coarse(5.0, 100.0 + 180.0)               # then re-set it somewhere else: the stored axis is now wrong by ~10 deg
    rep = eng.run()
    assert not rep.success and rep.motor_current_cut
    assert all(a.fault is None for a in hw.motion.axes.values())
    assert rep.message                                      # something readable, whatever stopped it


@pytest.mark.parametrize("lat,az_sign", [(25.2, +1), (25.2, -1), (-33.9, +1), (-33.9, -1)])
def test_azimuth_spring_direction_is_read_off_the_sky(solver, lat, az_sign):
    """hardware/README.md: the azimuth spring pulls the plate clockwise seen from above, so moves must finish clockwise.
    Which sign of step count that is depends on motor wiring: the loop reads it off the learned sky motion.  In the
    simulator a positive stage angle is a rotation about +up (counter-clockwise from above), so clockwise means the
    stage angle decreasing: +steps are clockwise exactly when az_sign = -1."""
    site = Site(lat, 55.3)
    mp = MountParams(axis_alt_deg=abs(lat) + 3.0, axis_az_deg=4.0 if lat >= 0 else 184.0, az_sign=az_sign, seed=7)
    res = run_scenario(seed=5, site=site, initial_error_deg=3.0, direction_deg=20.0, mount=mp, solver=solver)
    assert res.report.success, res.report.message
    assert res.hw.config.motion.az.preload_dir == -az_sign
    assert res.hw.config.motion.alt.preload_dir == +1                 # altitude has no preload_sky: left as configured


def test_without_a_site_the_spring_direction_stays_as_configured(solver):
    """Hemisphere is auto-detected when no site is known, but 'east' is not: say so instead of guessing."""
    cfg = sim_config()
    hw = build_sim_hardware(cfg, seed=81, mount=MountParams(seed=181, stall_prob_per_move=0.0))
    hw.motion.home()
    cal = CalibrationStore(None)
    eng = AlignEngine(cfg, Measurer(hw.camera, get_extractor(cfg.extractor), solver), hw.motion, cal, hw.time_source, lambda: None)
    hw.world.set_coarse(0.01, 40)
    eng.declare_aligned()
    hw.world.set_coarse(3.0, 20)
    rep = eng.run()
    assert rep.success, rep.message
    assert any("spring direction not determined" in w for w in rep.warnings)


def test_faint_sky_is_handled_by_exposing_longer_and_the_exposure_is_restored(solver):
    """Colour sensor + haze: at 1 s there are too few stars to solve (measured: ~30 stars is not enough in this setup,
    1.6 s is); a failed solve retries with more exposure, and the user's setting comes back afterwards."""
    cfg = sim_config()
    faint = SensorParams(cfa="RGGB", mag0_e_per_s=3.0e4, sky_e_per_s_px=6.0)
    hw = build_sim_hardware(cfg, seed=91, sensor=faint, mount=MountParams(seed=191, stall_prob_per_move=0.0))
    hw.motion.home()
    site = hw.world.site
    events = []
    meas = Measurer(hw.camera, get_extractor(cfg.extractor), solver)
    eng = AlignEngine(cfg, meas, hw.motion, CalibrationStore(None), hw.time_source, lambda: site, on_event=events.append)
    assert not meas.measure().ok                                          # at 1 s this sky does not solve
    hw.world.set_coarse(0.01, 40)
    eng.declare_aligned()
    assert meas.exposure_s is None                                        # restored
    hw.world.set_coarse(3.0, 20)
    rep = eng.run()
    assert rep.success, rep.message
    assert any("retrying with 1.6 s" in e["message"] for e in events)
    assert meas.exposure_s is None
    assert hw.world.true_axis_error_deg() < 0.05

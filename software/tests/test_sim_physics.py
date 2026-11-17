"""The simulator itself: if its physics were wrong, a passing end-to-end test would mean nothing."""
import math

import numpy as np
import pytest

from polaralign.astro import Site
from polaralign.astro.frames import radec_to_vec, rotation_from_radec_roll
from polaralign.astro.refraction import refraction_from_true_alt
from polaralign.config import sim_config
from polaralign.motion.gpio import FakeGPIO
from polaralign.motion.controller import MotionController
from polaralign.sim import CameraModel, FrameRenderer, MountParams, SensorParams, SimMount, build_sim_hardware


def test_projection_roundtrip_and_pixel_scale():
    cam = CameraModel()
    col, row, front = cam.project(np.array([[1.0, 0.0, 0.0]]))
    assert front[0] and col[0] == pytest.approx(cam.width / 2 - 0.5) and row[0] == pytest.approx(cam.height / 2 - 0.5)
    v = cam.pixel_to_vector(np.array([100.0, 1300.0]), np.array([50.0, 1000.0]))
    c2, r2, _ = cam.project(v)
    assert c2 == pytest.approx([100.0, 1300.0], abs=1e-6) and r2 == pytest.approx([50.0, 1000.0], abs=1e-6)
    # one pixel = 44.5 arcsec at the centre
    a = cam.pixel_to_vector(np.array([700.0]), np.array([500.0]))[0]
    b = cam.pixel_to_vector(np.array([701.0]), np.array([500.0]))[0]
    assert math.degrees(math.acos(a @ b)) * 3600 == pytest.approx(44.5, abs=0.2)
    # image axes: +y_left maps to smaller column, +z_up to smaller row
    left = np.array([[1.0, 0.01, 0.0]])
    up = np.array([[1.0, 0.0, 0.01]])
    assert cam.project(left)[0][0] < col[0] and cam.project(up)[1][0] < row[0]


def test_distortion_matches_tetra3s_model():
    from tetra3.tetra3 import _distort_centroids, _undistort_centroids
    k = -0.03
    cam = CameraModel(distortion=k)
    flat = CameraModel(distortion=0.0)
    rng = np.random.default_rng(0)
    v = np.column_stack([np.ones(30), rng.uniform(-0.15, 0.15, 30), rng.uniform(-0.1, 0.1, 30)])
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    cu, ru, _ = flat.project(v)
    cd, rd, _ = cam.project(v)
    # tetra3 coordinates: (y, x) with the pixel centre at 0.5
    und = _undistort_centroids(np.column_stack([rd + 0.5, cd + 0.5]), (cam.height, cam.width), k)
    assert np.abs(und[:, 1] - 0.5 - cu).max() < 0.05 and np.abs(und[:, 0] - 0.5 - ru).max() < 0.05


def test_renderer_flux_scaling_saturation_and_noise():
    cam = CameraModel()
    p = SensorParams(n_hot_pixels=0, sky_gradient=0.0, tip_tilt_px=0.0, seeing_px=0.0)
    rend = FrameRenderer(cam, p)
    rng = np.random.default_rng(0)
    v = cam.pixel_to_vector(np.array([700.0, 300.0]), np.array([500.0, 300.0]))
    img = rend.render(v, np.array([5.0, 7.5]), 2.0, rng).astype(float)
    sky = img[800:1000, 100:300].mean()          # mean, not median: the sky is only ~1 electron per pixel (Poisson)
    expect_sky = p.black_level_adu + (p.sky_e_per_s_px + p.dark_e_per_s_px) * 2.0 / p.gain_e_per_adu
    assert sky == pytest.approx(expect_sky, abs=0.5)
    flux5 = (img[490:511, 690:711] - sky).sum() * p.gain_e_per_adu
    assert flux5 == pytest.approx(p.mag0_e_per_s * 10 ** (-0.4 * 5.0) * 2.0, rel=0.05)
    ratio = (img[290:311, 290:311] - sky).sum() / (img[490:511, 690:711] - sky).sum()
    assert ratio == pytest.approx(10 ** (-0.4 * 2.5), rel=0.15)            # 2.5 mag fainter = 10x fainter
    bright = rend.render(v[:1], np.array([-1.0]), 0.5, rng)
    assert bright.max() == p.max_adu                                       # saturates at the ADC limit
    bg = img[800:1000, 100:300]
    assert bg.std() == pytest.approx(math.sqrt(p.read_noise_e ** 2 + expect_sky_e(p) * 4) / p.gain_e_per_adu, rel=0.25)


def expect_sky_e(p):
    return (p.sky_e_per_s_px + p.dark_e_per_s_px) * 0.5


def make_mount(**kw):
    cfg = sim_config().motion
    gpio = FakeGPIO()
    mc = MotionController(cfg, gpio)
    m = SimMount(cfg, MountParams(stall_prob_per_move=0.0, release_shift_deg=0.0, skew_deg=0.0, **kw))
    m.attach(gpio)
    return mc, m


def alt_az(v):
    return math.degrees(math.asin(v[2])), math.degrees(math.atan2(v[0], v[1])) % 360


def test_altitude_stage_raises_the_axis_one_for_one():
    mc, m = make_mount(axis_alt_deg=30.0, axis_az_deg=10.0, alt_sign=+1, alt_scale_error=0.0)
    a0 = alt_az(m.axis_enu())
    mc.move_relative_deg("alt", 1.0, preload_finish=False)
    a1 = alt_az(m.axis_enu())
    assert a1[0] - a0[0] == pytest.approx(1.0, rel=0.05)                 # backlash eats a little of the first move
    assert a1[1] == pytest.approx(a0[1], abs=0.05)


def test_azimuth_stage_moves_the_axis_by_cos_altitude():
    mc, m = make_mount(axis_alt_deg=60.0, axis_az_deg=0.0, az_sign=+1, az_scale_error=0.0)
    v0 = m.axis_enu()
    mc.move_relative_deg("az", 2.0, preload_finish=False)
    v1 = m.axis_enu()
    moved = math.degrees(math.acos(float(v0 @ v1)))
    alt_now = alt_az(v0)[0]                                   # the altitude hinge starts a little off its centre
    assert moved == pytest.approx(2.0 * math.cos(math.radians(alt_now)), rel=0.02)


def test_backlash_dead_band_and_preload():
    mc, m = make_mount(backlash_az_deg=0.1, az_scale_error=0.0)
    st = m.stages["az"]
    mc.move_relative_deg("az", 1.0, preload_finish=False)
    p_fwd = st.p
    gap = st.gap
    mc.move_relative_usteps("az", -int(gap * 0.6), preload_finish=False)    # reverse by less than the gap: plate must not move
    assert st.p == pytest.approx(p_fwd, abs=1.0)
    mc.move_relative_usteps("az", -int(gap * 0.6), preload_finish=False)    # now the slack is taken up
    assert st.p < p_fwd - 0.1 * gap
    # finishing in the preload direction gives the same plate position whichever side we came from
    mc.move_to_deg("az", 0.5, preload_finish=True)
    a = st.p
    mc.move_to_deg("az", 2.0, preload_finish=True)
    mc.move_to_deg("az", 0.5, preload_finish=True)
    assert st.p == pytest.approx(a, abs=gap * 0.05)


def test_lost_steps_and_end_stop_stall():
    cfg = sim_config().motion
    gpio = FakeGPIO()
    mc = MotionController(cfg, gpio)
    m = SimMount(cfg, MountParams(stall_prob_per_move=1.0, release_shift_deg=0.0))
    m.attach(gpio)
    st = m.stages["az"]
    mc.move_relative_deg("az", 0.5, preload_finish=False)
    assert 1 <= st.lost_total <= 5 * cfg.microsteps                       # a burst of lost steps on the first move
    st.set_enabled(True)
    for _ in range(int(st.travel) * 2):                                   # drive into the MIN stop: stage clamps, motor stalls
        st.dir_forward = False
        st.step()
    assert st.p == 0.0 and st.at_min


def test_set_coarse_hits_the_requested_error_and_keeps_camera_rigid():
    hw = build_sim_hardware(seed=3, mount=MountParams(seed=3))
    acam0 = hw.world.mount.a_cam_true.copy()
    for err, direction in ((0.0, 0.0), (0.02, 40.0), (5.0, 130.0), (3.0, 280.0)):
        hw.world.set_coarse(err, direction)
        assert hw.world.true_axis_error_deg() == pytest.approx(err, abs=2e-4)
    assert np.allclose(hw.world.mount.a_cam_true, acam0, atol=1e-6)       # camera-to-axis relation is a physical constant


def test_truth_chain_refraction_precession_and_zenith():
    site = Site(40.0, 10.0)
    hw = build_sim_hardware(site=site, mount=MountParams(axis_alt_deg=43.0, seed=2), seed=2, aberration=False)
    hw.world.set_coarse(0.0)
    vs_apparent = hw.world.true_axis_error_deg()
    vs_true = hw.world.true_axis_error_vs_true_pole_deg()
    assert vs_apparent < 1e-3
    assert vs_true * 60 == pytest.approx(math.degrees(refraction_from_true_alt(40.0)) * 60, abs=0.15)   # refraction at 40 deg
    p = hw.world.apparent_pole_enu()
    assert math.degrees(math.asin(p[2])) == pytest.approx(40.0 + math.degrees(refraction_from_true_alt(40.0)) + 0.0, abs=0.12)


def test_aberration_is_a_small_common_shift():
    hw = build_sim_hardware(seed=2, aberration=True)
    hw_off = build_sim_hardware(seed=2, aberration=False)
    v = radec_to_vec(np.array([10.0, 100.0, 200.0]), np.array([20.0, -30.0, 60.0]))
    d = hw.world.sky_to_enu(v) - hw_off.world.sky_to_enu(v)
    ang = np.degrees(np.linalg.norm(d, axis=1)) * 3600
    assert np.all(ang < 21.5) and np.all(ang > 0.1)                       # <= 20.5" annual aberration


def test_camera_stays_rigid_when_it_looks_straight_at_the_zenith():
    """Regression: with the axis 29.5 deg from the zenith and the camera 29.8 deg off-axis the boresight is within a
    fraction of a degree of the zenith; the camera-to-axis relation must still not depend on how the base was set."""
    hw = build_sim_hardware(site=Site(57.5, -4.2), seed=1,
                            mount=MountParams(axis_alt_deg=60.5, offaxis_deg=29.8, cam_roll_deg=77.0, seed=1))
    ref = hw.world.mount.a_cam_true.copy()
    bore = hw.world.mount.camera_axes_enu()[:, 0]
    assert bore[2] > 0.999                                                     # boresight really is at the zenith
    for err, direction in ((0.0, 0), (5.1, 12), (4.0, 200), (2.0, 90)):
        hw.world.set_coarse(err, direction)
        assert np.allclose(hw.world.mount.a_cam_true, ref, atol=1e-6)
        c = hw.world.mount.camera_axes_enu()
        assert np.allclose(c.T @ c, np.eye(3), atol=1e-9) and np.linalg.det(c) == pytest.approx(1.0)

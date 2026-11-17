import math

import pytest

from polaralign.config import Config, load_config, sim_config


def test_mechanics_match_the_design_document():
    az = Config().motion.az
    assert az.deg_per_rev == pytest.approx(0.716, abs=0.001)                 # M6x1 on an 80 mm arm
    assert az.arcsec_per_full_step == pytest.approx(12.9, abs=0.05)
    assert az.travel_deg == 6.0


def test_camera_numbers_for_16mm_lens_on_imx296():
    c = Config().camera
    assert c.fov_h_deg == pytest.approx(17.9, abs=0.1)        # doc: about 18 x 13 deg
    assert c.fov_v_deg == pytest.approx(13.4, abs=0.1)
    assert c.arcsec_per_px == pytest.approx(44.5, abs=0.5)    # doc: 45 arcsec per pixel
    assert c.focal_px == pytest.approx(16000 / 3.45)


def test_altitude_mechanics_follow_hardware_readme_but_are_flagged_unconfirmed():
    m = Config().motion
    assert m.az.mechanics_confirmed and not m.alt.mechanics_confirmed
    assert m.alt.arm_mm == 150.0 and m.alt.arcsec_per_full_step == pytest.approx(6.9, abs=0.05)
    assert m.az.end_stop_deg == 8.05 and m.alt.end_stop_deg == pytest.approx(7.25)


def test_toml_overlay_and_unknown_key(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[motion.alt]\narm_mm = 95.0\npitch_mm = 1.25\nmechanics_confirmed = true\n[align]\nmax_iterations = 6\n')
    cfg = load_config(p)
    assert cfg.motion.alt.arm_mm == 95.0 and cfg.motion.alt.deg_per_rev == pytest.approx(math.degrees(1.25 / 95.0))
    assert cfg.align.max_iterations == 6 and cfg.motion.az.arm_mm == 80.0
    bad = tmp_path / "bad.toml"
    bad.write_text("[align]\nmax_iteration = 6\n")
    with pytest.raises(ValueError, match="unknown config key"):
        load_config(bad)


def test_sim_config_does_not_sleep():
    c = sim_config()
    assert c.hardware == "sim" and not c.motion.realtime and c.align.settle_s == 0


def test_example_config_file_loads_and_matches_the_defaults():
    from pathlib import Path
    example = Path(__file__).resolve().parents[1] / "config" / "polaralign.example.toml"
    cfg = load_config(example)
    d = Config()
    assert cfg.motion.az.step_pin == d.motion.az.step_pin and cfg.motion.alt.endstop_max_pin == d.motion.alt.endstop_max_pin
    assert cfg.sensors.imu_address == 0x68 and cfg.sensors.imu_axis_in_sensor == (0.0, 0.0, 1.0)
    assert cfg.motion.alt.arm_mm == d.motion.alt.arm_mm == 150.0 and cfg.motion.alt.end_stop_deg == d.motion.alt.end_stop_deg
    assert cfg.motion.az.preload_sky == d.motion.az.preload_sky == "clockwise" and cfg.motion.az.endstop_trip_level == 1
    assert cfg.align.target_arcmin == d.align.target_arcmin and cfg.motion.alt.mechanics_confirmed is False
    assert cfg.camera.fov_h_deg == d.camera.fov_h_deg and cfg.site.latitude_deg is None

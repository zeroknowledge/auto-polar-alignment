import json
import math

import numpy as np
import pytest

from polaralign.calibration import CalibrationStore

ARCSEC = math.radians(1 / 3600)


def vec(az_deg, el_deg):
    a, e = math.radians(az_deg), math.radians(el_deg)
    return np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])


def test_empty_store_is_uncalibrated():
    s = CalibrationStore(None)
    assert not s.calibrated and s.a_cam is None and s.rotation_cam_to_mount is None and s.spread_arcsec() is None


def test_entries_are_averaged_and_spread_reported():
    s = CalibrationStore(None)
    base = vec(20, 40)
    for dx in (+30, -30, 0):
        s.add_entry(base + np.array([dx * ARCSEC, 0, 0]))
    assert math.acos(min(1.0, float(s.a_cam @ base))) < 2 * ARCSEC
    assert 20 < s.spread_arcsec() < 40


def test_rotation_maps_axis_to_mount_z():
    s = CalibrationStore(None)
    s.add_entry(vec(70, 25))
    r = s.rotation_cam_to_mount
    assert np.allclose(r @ s.a_cam, [0, 0, 1], atol=1e-12)
    assert np.allclose(r @ r.T, np.eye(3), atol=1e-12) and np.linalg.det(r) == pytest.approx(1.0)


def test_trim_moves_the_axis_and_is_clamped():
    s = CalibrationStore(None)
    base = vec(10, 10)
    s.add_entry(base)
    s.trim(np.array([0, 0, 20 * ARCSEC]), source="test")
    assert 18 < math.degrees(math.acos(min(1, float(s.a_cam @ base)))) * 3600 < 22
    s.trim(np.array([0.5, 0, 0]), max_deg=0.1)                          # absurd request: limited to 0.1 deg
    assert math.degrees(math.acos(float(s.a_cam @ base))) < 0.13
    assert len(s.data.trims) == 2


def test_persistence_roundtrip_and_backup(tmp_path):
    p = tmp_path / "cal" / "calibration.json"
    s = CalibrationStore(p)
    s.add_entry(vec(1, 2), latitude_deg=25.2, longitude_deg=55.3, n_matches=40, rmse_arcsec=8.0)
    s.add_entry(vec(1.001, 2))
    s.trim(np.array([1e-6, 0, 0]), source="seestar")
    s2 = CalibrationStore(p)
    assert s2.calibrated and len(s2.data.entries) == 2 and len(s2.data.trims) == 1
    assert np.allclose(s2.a_cam, s.a_cam)
    assert p.with_suffix(".bak").exists()                                # previous generation kept
    s2.clear()
    assert not CalibrationStore(p).calibrated
    assert json.loads(p.with_suffix(".bak").read_text())["entries"]      # the cleared data is recoverable


def test_corrupt_file_starts_empty_instead_of_crashing(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json")
    assert not CalibrationStore(p).calibrated

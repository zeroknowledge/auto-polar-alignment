"""Pole-of-date, precession, sidereal time and refraction maths, cross-checked against ERFA."""
import math
from datetime import datetime, timezone

import numpy as np
import pytest

from polaralign.astro import (RefractionModel, Site, axis_in_camera, detect_hemisphere, make_target,
                              physical_axis, pole_error, pole_of_date_j2000, precession_offset_arcsec,
                              refraction_from_apparent_alt, refraction_from_true_alt,
                              rotation_from_radec_roll, unit, zenith_j2000)
from polaralign.astro.frames import ARCSEC, radec_to_vec, rot_axis_angle
from polaralign.astro.precession import ASEC2RAD, bias_precession_matrix, bias_precession_nutation_matrix
from polaralign.astro.timescales import gmst_deg, julian_date_utc

erfa = pytest.importorskip("erfa")

NOV_2026 = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)


def _erfa_tt(dt):
    d1, d2 = erfa.dtf2d("UTC", dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second + dt.microsecond * 1e-6)
    tai = erfa.utctai(d1, d2)
    return d1, d2, erfa.taitt(*tai)


@pytest.mark.parametrize("dt", [datetime(2000, 1, 1, 12, tzinfo=timezone.utc), NOV_2026,
                                datetime(2040, 6, 30, 3, 15, tzinfo=timezone.utc),
                                datetime(1990, 3, 1, tzinfo=timezone.utc)])
def test_precession_matrix_matches_erfa(dt):
    _, _, tt = _erfa_tt(dt)
    ref = erfa.pmat06(*tt)
    # 1 mas: the leap-second count (TT-UTC) differs between ERFA and the 2017+ constant used here
    assert np.abs(ref - bias_precession_matrix(dt)).max() / ASEC2RAD < 1e-3


def test_nutation_approximation_within_one_arcsec():
    for dt in (NOV_2026, datetime(2031, 2, 3, tzinfo=timezone.utc), datetime(2012, 9, 9, tzinfo=timezone.utc)):
        _, _, tt = _erfa_tt(dt)
        ref = erfa.pnm06a(*tt)
        mine = bias_precession_nutation_matrix(dt)
        assert np.abs(ref - mine).max() / ASEC2RAD < 1.0


def test_pole_of_date_offset_is_about_539_arcsec_in_november_2026():
    # The task statement quotes 539" (0.150 deg): that is the *precession* part (no nutation).
    p_mean = bias_precession_matrix(NOV_2026)[2, :]
    off = math.degrees(math.acos(np.clip(p_mean[2], -1, 1))) * 3600
    assert off == pytest.approx(539.0, abs=1.0)
    assert off / 3600 == pytest.approx(0.150, abs=0.001)
    # with nutation (~17" amplitude) the true pole is a few arcsec further; still well above 0.1 deg
    assert 535 < precession_offset_arcsec(NOV_2026) < 548
    assert precession_offset_arcsec(NOV_2026) / 3600 > 0.1


def test_pole_of_date_direction_matches_erfa_pole():
    _, _, tt = _erfa_tt(NOV_2026)
    ref = erfa.pnm06a(*tt)[2, :]
    assert np.degrees(np.arccos(np.clip(ref @ pole_of_date_j2000(NOV_2026), -1, 1))) * 3600 < 0.5
    south = pole_of_date_j2000(NOV_2026, -1)
    assert np.allclose(south, -pole_of_date_j2000(NOV_2026, +1))


def test_gmst_matches_erfa_within_a_second_of_time():
    for dt in (NOV_2026, datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc)):
        d1, d2, tt = _erfa_tt(dt)
        ref = math.degrees(erfa.gmst06(d1, d2, *tt)) % 360
        diff = (gmst_deg(dt) - ref + 180) % 360 - 180
        assert abs(diff) * 240 < 0.5       # < 0.5 s of time


def test_julian_date():
    assert julian_date_utc(datetime(2000, 1, 1, 12, tzinfo=timezone.utc)) == pytest.approx(2451545.0)
    assert julian_date_utc(datetime(2026, 11, 17, 21, tzinfo=timezone.utc)) == pytest.approx(2461362.375)


def test_refraction_values_and_inverse():
    # textbook values: ~1' at 45 deg, ~2.1' at 25 deg (doc: 0.035 deg), ~5.4' at 10 deg
    for h, expect in ((45.0, 0.99), (25.0, 2.09), (10.0, 5.4)):
        r = math.degrees(refraction_from_true_alt(h)) * 60
        assert r == pytest.approx(expect, abs=0.2), (h, r)
    # Saemundsson (true alt) and Bennett (apparent alt) are inverse of each other to ~0.1'
    for h in (8.0, 15.0, 30.0, 60.0):
        r = refraction_from_true_alt(h)
        r_back = refraction_from_apparent_alt(h + math.degrees(r))
        assert abs(r - r_back) / ARCSEC < 8.0
    # pressure / temperature scaling
    assert refraction_from_true_alt(30, 800, 10) < refraction_from_true_alt(30, 1010, 10)
    assert refraction_from_true_alt(30, 1010, -10) > refraction_from_true_alt(30, 1010, 30)


def test_refraction_model_vectors_roundtrip_and_direction():
    site = Site(25.0, 55.0)
    zen = zenith_j2000(NOV_2026, site)
    model = RefractionModel(zen)
    v = unit(zen + 0.7 * unit(np.cross(zen, [0, 0, 1])))      # ~35 deg altitude
    app = model.apparent(v)
    assert np.dot(app, zen) > np.dot(v, zen)                    # moved toward the zenith
    assert model.true(app) @ v == pytest.approx(1.0, abs=1e-8 + 1e-7)
    batch = model.apparent_array(np.vstack([v, v]))
    assert np.allclose(batch[0], app, atol=1e-9)


def test_target_precession_and_refraction_sizes():
    site = Site(25.0, 55.0)
    t = make_target(NOV_2026, +1, site, "model")
    assert 535 < t.precession_arcsec < 548
    assert t.refraction_arcsec == pytest.approx(math.degrees(refraction_from_true_alt(25.0)) * 3600, rel=0.02)
    assert t.up @ t.east == pytest.approx(0, abs=1e-9)
    assert abs(t.up @ t.target) < 1e-9 and abs(t.east @ t.target) < 1e-9
    t_off = make_target(NOV_2026, +1, site, "off")
    assert t_off.refraction_arcsec == 0.0 and np.allclose(t_off.target, t_off.true_pole)
    t_south = make_target(NOV_2026, -1, Site(-33.0, 151.0))
    assert t_south.target @ np.array([0, 0, -1.0]) > 0.99999


def test_apparent_pole_is_raised_in_altitude_by_refraction():
    site = Site(40.0, 10.0)
    t = make_target(NOV_2026, +1, site, "model")
    alt_true = math.degrees(math.asin(t.true_pole @ t.refraction.zenith))
    alt_app = math.degrees(math.asin(t.target @ t.refraction.zenith))
    assert alt_true == pytest.approx(40.0, abs=0.01)           # pole altitude = latitude (+ the 0.15 deg frame offset is horizontal)
    assert (alt_app - alt_true) * 60 == pytest.approx(math.degrees(refraction_from_true_alt(40.0)) * 60, abs=0.05)


def test_axis_calibration_roundtrip_and_error_signs():
    site = Site(48.0, 8.0)
    target = make_target(NOV_2026, +1, site, "model")
    # an arbitrary camera pointing ~25 deg from the pole, arbitrary roll
    bore = rot_axis_angle([1, 0.3, 0.2], math.radians(25)) @ target.target
    r_cam = rotation_from_radec_roll(*_radec(bore), 33.0)
    a_cam = axis_in_camera(r_cam, target.target, target)
    assert np.linalg.norm(a_cam) == pytest.approx(1.0)
    # physical_axis must invert axis_in_camera exactly
    assert physical_axis(r_cam, a_cam, target) @ target.target == pytest.approx(1.0, abs=1e-12)
    # tilt the camera (= the telescope) so the axis ends up 0.1 deg above the target
    err = pole_error(physical_axis(r_cam, a_cam, target), target)
    assert err.total_rad < 1e-9
    a_high = unit(target.target + math.radians(0.1) * target.up)
    e = pole_error(a_high, target)
    assert math.degrees(e.d_alt_rad) == pytest.approx(0.1, abs=1e-4)
    assert abs(e.d_east_rad) < 1e-9
    a_east = unit(target.target + math.radians(0.2) * target.east)
    e = pole_error(a_east, target)
    assert math.degrees(e.d_east_rad) == pytest.approx(0.2, abs=1e-4)
    assert e.az_dial_arcmin > e.east_arcmin       # dial angle is larger than the sky angle at lat 48


def test_hemisphere_detection():
    n = pole_of_date_j2000(NOV_2026, +1)
    off = rot_axis_angle([1, 0, 0], math.radians(6)) @ n
    assert detect_hemisphere(off, NOV_2026)[0] == +1
    assert detect_hemisphere(-off, NOV_2026)[0] == -1
    assert detect_hemisphere(off, NOV_2026)[1] == pytest.approx(6.0, abs=0.01)


def _radec(v):
    from polaralign.astro import vec_to_radec
    return vec_to_radec(v)

"""Plate solving with the real Cedar Solve / tetra3 on simulated frames."""
import math

import numpy as np
import pytest

from polaralign.astro.frames import angle_between, radec_to_vec, rotation_from_radec_roll
from polaralign.config import CameraConfig, ExtractorConfig, SolverConfig
from polaralign.extract import NumpyStarExtractor
from polaralign.extract.base import ExtractionResult
from polaralign.sim import CameraModel, FrameRenderer, SensorParams
from polaralign.solve import get_solver
from polaralign.solve.astrometry import AstrometrySolver, parse_wcs_header, rotation_from_wcs, write_xyls
from polaralign.solve.refine import refine_pose

ARCSEC = 3600.0


def render(catalog, ra, dec, roll, seed, distortion=-0.01, mag0=2.5e5):
    cam = CameraModel(distortion=distortion)
    r = rotation_from_radec_roll(ra, dec, roll)
    idx = catalog.cone(r[0], cam.diag_half_angle_rad + 0.02, max_mag=9)
    rend = FrameRenderer(cam, SensorParams(mag0_e_per_s=mag0))
    img, truth = rend.render((r @ catalog.vec[idx].T).T, catalog.mag[idx], 0.5, np.random.default_rng(seed), return_truth=True)
    return r, cam, img, truth


@pytest.mark.parametrize("ra,dec,roll", [(10.0, 89.8, 20.0), (200.0, -89.2, 100.0), (45.0, 60.0, 5.0),
                                         (300.0, -30.0, 250.0), (130.0, 0.0, 180.0), (0.5, 12.0, 359.0)])
def test_solves_anywhere_on_the_sky_with_arcsecond_accuracy(catalog, solver, ra, dec, roll):
    r, cam, img, _ = render(catalog, ra, dec, roll, seed=int(ra))
    out = solver.solve(NumpyStarExtractor(ExtractorConfig(max_stars=60)).extract(img))
    assert out.ok, (out.status, out.detail)
    s = out.solution
    assert math.degrees(angle_between(r[0], s.rotation[0])) * ARCSEC < 25          # boresight
    assert max(math.degrees(angle_between(r[k], s.rotation[k])) for k in (1, 2)) * ARCSEC < 60   # roll too
    assert s.fov_deg == pytest.approx(cam.fov_h_deg, abs=0.01)
    assert s.distortion == pytest.approx(-0.01, abs=0.004)
    assert s.n_matches >= 25 and s.rmse_arcsec < 15


def test_rotation_matrix_reproduces_the_stars_in_the_image(catalog, solver):
    """Convention check: projecting catalogue stars with the returned rotation lands on the measured centroids."""
    r, cam, img, truth = render(catalog, 80.0, 20.0, 33.0, seed=3)
    ext = NumpyStarExtractor(ExtractorConfig(max_stars=300)).extract(img)
    out = solver.solve(ext)
    s = out.solution
    fitted = CameraModel(cam.width, cam.height, (cam.width / 2) / math.tan(math.radians(s.fov_deg) / 2), s.distortion)
    idx = catalog.cone(s.rotation[0], cam.diag_half_angle_rad, max_mag=6.5)
    col, row, front = fitted.project((s.rotation @ catalog.vec[idx].T).T)
    ok = front & fitted.in_frame(col, row, margin=-10)
    d = [np.hypot(ext.x - c, ext.y - rr).min() for c, rr in zip(col[ok], row[ok])]
    assert np.median(d) < 0.3 and np.percentile(d, 90) < 0.8


def test_rotation_from_radec_roll_is_proper_and_matches_tetra3_definition():
    for ra, dec, roll in [(10, 20, 30), (200, -70, 300), (359.9, 89.5, 1)]:
        r = rotation_from_radec_roll(ra, dec, roll)
        assert np.allclose(r @ r.T, np.eye(3), atol=1e-12) and np.linalg.det(r) == pytest.approx(1.0)
        assert np.allclose(np.cross(r[0], r[1]), r[2])                     # x_bore cross y_left = z_up
        assert math.degrees(math.atan2(r[0, 1], r[0, 0])) % 360 == pytest.approx(ra % 360, abs=1e-9)
        assert math.degrees(math.atan2(r[1, 2], r[2, 2])) % 360 == pytest.approx(roll, abs=1e-9)


def test_refit_rejects_a_false_match_that_ruins_tetra3_rmse(catalog, solver):
    r, cam, img, truth = render(catalog, 45.0, 50.9, 77.0, seed=7)
    ext = NumpyStarExtractor().extract(img)
    good = solver.solve(ext)
    assert good.ok
    # add a decoy "star" 12 px from a real star's predicted place: inside tetra3's 14.5 px match radius
    decoy = ExtractionResult(x=np.append(ext.x, ext.x[5] + 12.0), y=np.append(ext.y, ext.y[5]),
                             flux=np.append(ext.flux, ext.flux[5] * 1.01), peak=np.append(ext.peak, 1.0),
                             fwhm=np.append(ext.fwhm, 3.0), snr=np.append(ext.snr, 50.0),
                             flags=np.append(ext.flags, 0), image_shape=ext.image_shape)
    out = solver.solve(decoy)
    assert out.ok
    assert math.degrees(angle_between(good.solution.rotation[0], out.solution.rotation[0])) * ARCSEC < 6
    assert out.solution.rmse_arcsec < 20


def test_refine_pose_recovers_from_a_perturbed_start(catalog):
    r, cam, img, truth = render(catalog, 150.0, -20.0, 10.0, seed=4)
    ext = NumpyStarExtractor().extract(img)
    from scipy.spatial.transform import Rotation
    start = Rotation.from_rotvec([6e-4, -4e-4, 3e-4]).as_matrix() @ r           # ~0.05 deg = 4-5 px off
    rp = refine_pose(start, cam.fov_h_deg * 1.002, -0.008, cam.width, cam.height, catalog.vec, np.column_stack([ext.x, ext.y]))
    assert rp.ok and rp.n_inliers > 25
    assert math.degrees(angle_between(r[0], rp.rotation[0])) * ARCSEC < 10


def test_too_few_stars_and_blank_frame(solver):
    blank = ExtractionResult.empty((1088, 1456))
    assert solver.solve(blank).status == "too_few"
    rng = np.random.default_rng(0)
    junk = ExtractionResult(x=rng.uniform(10, 1400, 20), y=rng.uniform(10, 1000, 20), flux=np.linspace(900, 100, 20),
                            peak=np.ones(20), fwhm=np.full(20, 3.0), snr=np.full(20, 20.0), flags=np.zeros(20, dtype=int),
                            image_shape=(1088, 1456))
    out = solver.solve(junk)
    assert not out.ok and out.status in ("no_match", "timeout", "poor_fit")


def test_wrong_fov_is_still_solved_inside_the_search_window(catalog):
    solver = get_solver(SolverConfig(), CameraConfig(lens_focal_mm=16.8))        # configured lens is 5 % off
    r, cam, img, _ = render(catalog, 250.0, 40.0, 60.0, seed=9)
    out = solver.solve(NumpyStarExtractor().extract(img))
    assert out.ok and out.solution.fov_deg == pytest.approx(cam.fov_h_deg, abs=0.02)


def test_database_builder_makes_a_working_small_database(tmp_path, catalog):
    from polaralign.solve.database import build_database
    db = build_database(tmp_path / "small", min_fov_deg=16.5, max_fov_deg=19.5, star_max_magnitude=7.5,
                        verification_stars_per_fov=80, lattice_field_oversampling=20, patterns_per_lattice_field=50)
    assert db.exists() and db.stat().st_size < 8_000_000
    solver = get_solver(SolverConfig(database=str(db)), CameraConfig())
    assert solver.database_properties["max_fov"] == pytest.approx(19.5)
    ok = 0
    for i, (ra, dec) in enumerate([(30, 40), (200, -50), (100, 10), (280, 70), (320, -10)]):
        r, cam, img, _ = render(catalog, ra, dec, 15.0 * i, seed=i)
        out = solver.solve(NumpyStarExtractor().extract(img))
        ok += int(out.ok and math.degrees(angle_between(r[0], out.solution.rotation[0])) * ARCSEC < 30)
    assert ok >= 4


# ---------------------------------------------------------------- astrometry.net fallback (plumbing only)
def test_astrometry_wcs_geometry_recovers_the_rotation():
    """Build a TAN WCS from a known rotation + camera model, read it back with our parser, get the rotation."""
    cam = CameraModel()
    r = rotation_from_radec_roll(33.0, 41.0, 72.0)
    ra, dec = math.degrees(math.atan2(r[0, 1], r[0, 0])), math.degrees(math.asin(r[0, 2]))
    scale = math.degrees(1.0 / cam.focal_px)
    # image columns increase to the right = +y_left decreasing; rows increase downward = -z_up
    # sky offsets (xi east, eta north) per pixel step follow from the camera axes
    east = np.array([-math.sin(math.radians(ra)), math.cos(math.radians(ra)), 0.0])
    north = np.array([-math.sin(math.radians(dec)) * math.cos(math.radians(ra)),
                      -math.sin(math.radians(dec)) * math.sin(math.radians(ra)), math.cos(math.radians(dec))])
    right, down = -r[1], -r[2]
    cd = scale * np.array([[right @ east, down @ east], [right @ north, down @ north]])
    hdr = b"".join(f"{k:<8}= {v:>20}".ljust(80).encode() for k, v in
                   {"CRVAL1": ra, "CRVAL2": dec, "CRPIX1": (cam.width + 1) / 2, "CRPIX2": (cam.height + 1) / 2,
                    "CD1_1": cd[0, 0], "CD1_2": cd[0, 1], "CD2_1": cd[1, 0], "CD2_2": cd[1, 1]}.items()) + b"END".ljust(80)
    w = parse_wcs_header(hdr)
    got = rotation_from_wcs(w, cam.width, cam.height)
    for k in range(3):
        assert math.degrees(angle_between(got[k], r[k])) * ARCSEC < 1.0


def test_astrometry_xyls_is_valid_fits_and_missing_binary_is_reported(tmp_path):
    p = tmp_path / "s.xyls"
    write_xyls(p, np.array([1.0, 2.0]), np.array([3.0, 4.0]), np.array([10.0, 5.0]), 1456, 1088)
    raw = p.read_bytes()
    assert len(raw) % 2880 == 0 and raw.startswith(b"SIMPLE  =") and b"XTENSION= 'BINTABLE'" in raw
    s = AstrometrySolver(SolverConfig(astrometry_binary="definitely-not-installed"), CameraConfig())
    stars = ExtractionResult(x=np.arange(10.0), y=np.arange(10.0), flux=np.arange(10.0), peak=np.ones(10),
                             fwhm=np.full(10, 3.0), snr=np.full(10, 20.0), flags=np.zeros(10, dtype=int), image_shape=(1088, 1456))
    out = s.solve(stars)
    assert out.status == "error" and "not found" in out.detail

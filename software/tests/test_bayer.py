"""The colour path: the user's camera is the Waveshare IMX296 Global Camera (A) (SKU 32501), a Bayer colour sensor
with an IR-cut filter, so raw frames are mosaics and there is 2-3x less starlight than on a mono sensor."""
import math

import numpy as np
import pytest

from polaralign.align.pipeline import Measurer
from polaralign.camera import FakeCamera, flip_pattern, make_camera, pattern_from_format, register_camera
from polaralign.config import CameraConfig, ExtractorConfig
from polaralign.extract import NumpyStarExtractor
from polaralign.extract.base import ExtractionResult
from polaralign.sim import CameraModel, FrameRenderer, SensorParams

H, W = 1088, 1456


def star_frame(pattern="RGGB", stars=((700.3, 500.6, 6.0),), colour=0.9, exposure=1.0, seed=0, **sensor_kw):
    """Mosaic frame with stars at exact positions; ``colour`` is the star colour spread (extreme by default)."""
    cam = CameraModel()
    p = SensorParams(cfa=pattern, star_colour_spread=colour, n_hot_pixels=0, tip_tilt_px=0.0, seeing_px=0.0,
                     sky_gradient=0.0, **sensor_kw)
    rend = FrameRenderer(cam, p)
    cols = np.array([s[0] for s in stars])
    rows = np.array([s[1] for s in stars])
    v = cam.pixel_to_vector(cols, rows)
    img, truth = rend.render(v, np.array([s[2] for s in stars]), exposure, np.random.default_rng(seed),
                             return_truth=True, star_ids=np.arange(len(stars)) + 3)
    return img, truth, rend


# ---------------------------------------------------------------- helpers
def test_pattern_from_libcamera_format_names():
    assert pattern_from_format("SBGGR10") == "BGGR"
    assert pattern_from_format("SRGGB10_CSI2P") == "RGGB"
    assert pattern_from_format("sgrbg12") == "GRBG"
    assert pattern_from_format("SGBRG10") == "GBRG"
    assert pattern_from_format("R10") is None and pattern_from_format("Y10") is None and pattern_from_format("") is None


def test_flipping_the_array_changes_the_pattern_consistently():
    assert flip_pattern("RGGB", horizontal=True) == "GRBG"
    assert flip_pattern("RGGB", vertical=True) == "GBRG"
    assert flip_pattern("RGGB", True, True) == "BGGR"
    assert flip_pattern(None, True, True) is None
    # and it really is what happens to a mosaic: flip a frame, re-read the colours at the new positions
    tile = np.array([["R", "G"], ["G", "B"]])
    big = np.tile(tile, (4, 4))
    for h, v, want in ((True, False, "GRBG"), (False, True, "GBRG"), (True, True, "BGGR")):
        f = big[:, ::-1] if h else big
        f = f[::-1, :] if v else f
        assert "".join(f[:2, :2].ravel()) == want == flip_pattern("RGGB", h, v)


def test_bad_patterns_are_rejected():
    img, _, _ = star_frame()
    for bad in ("RGB", "RRGB", "XGGB", "RGGBB"):
        with pytest.raises(ValueError, match="Bayer"):
            NumpyStarExtractor().extract(img, bayer=bad)


def test_camera_registry_allows_replacing_the_board():
    class Other:
        name = "other"

        def capture(self, exposure_s=None, gain=None):
            raise NotImplementedError

        def close(self):
            pass
    register_camera("other-board", lambda cfg: Other())
    assert make_camera(CameraConfig(backend="other-board")).name == "other"
    with pytest.raises(ValueError, match="unknown camera backend"):
        make_camera(CameraConfig(backend="nope"))
    assert make_camera(CameraConfig(backend="fake")).capture().meta["bayer"] == "RGGB"
    assert make_camera(CameraConfig(backend="fake", colour=False)).capture().meta["bayer"] is None


# ---------------------------------------------------------------- the simulated colour sensor
def test_simulated_colour_sensor_is_2_to_3_times_less_sensitive_and_shows_star_colour():
    cam = CameraModel()
    kw = dict(n_hot_pixels=0, tip_tilt_px=0.0, seeing_px=0.0, sky_gradient=0.0)
    v = cam.pixel_to_vector(np.array([600.0]), np.array([400.0]))
    mono = FrameRenderer(cam, SensorParams(**kw)).render(v, np.array([5.0]), 1.0, np.random.default_rng(1)).astype(float)
    col = FrameRenderer(cam, SensorParams(cfa="RGGB", star_colour_spread=0.0, **kw)).render(
        v, np.array([5.0]), 1.0, np.random.default_rng(1)).astype(float)
    base = 40.0
    f_mono = (mono[385:416, 585:616] - base).sum()
    f_col = (col[385:416, 585:616] - base).sum()
    assert 2.0 < f_mono / f_col < 3.0                                   # "roughly 2-3x less starlight"
    # a strongly red star lights the R pixels (even row, even column) much more than the B ones
    red = FrameRenderer(cam, SensorParams(cfa="RGGB", star_colour_spread=0.95, **kw))
    ids = np.arange(200)
    t = red.star_redness(ids)
    i_red, i_blue = int(ids[t.argmax()]), int(ids[t.argmin()])
    img = red.render(v, np.array([4.0]), 1.0, np.random.default_rng(1), star_ids=np.array([i_red])).astype(float) - base
    win = img[390:411, 590:611]
    r_sum, b_sum = win[0::2, 0::2].sum(), win[1::2, 1::2].sum()          # RGGB tile starting at an even row/column
    assert r_sum > 5 * b_sum
    img = red.render(v, np.array([4.0]), 1.0, np.random.default_rng(1), star_ids=np.array([i_blue])).astype(float) - base
    win = img[390:411, 590:611]
    assert win[1::2, 1::2].sum() > 5 * win[0::2, 0::2].sum()


@pytest.mark.parametrize("pattern", ["RGGB", "BGGR", "GRBG", "GBRG"])
def test_all_four_patterns_render_distinct_channel_layouts(pattern):
    img, truth, rend = star_frame(pattern, colour=0.0)
    chan = rend._chan
    assert "".join("RGB"[c] for c in chan[:2, :2].ravel()) == pattern


# ---------------------------------------------------------------- the extractor on mosaics
@pytest.mark.parametrize("mode", ["all", "green"])
@pytest.mark.parametrize("pattern", ["RGGB", "BGGR", "GRBG", "GBRG"])
def test_mosaic_centroids_are_subpixel_even_for_extreme_star_colours(pattern, mode):
    rng = np.random.default_rng(4)
    stars = [(float(rng.uniform(50, W - 50)), float(rng.uniform(50, H - 50)), 5.5) for _ in range(30)]
    stars = [s for i, s in enumerate(stars) if all(math.hypot(s[0] - t[0], s[1] - t[1]) > 40 for t in stars[:i])]
    img, truth, _ = star_frame(pattern, stars, colour=0.95, mag0_e_per_s=2.5e5)
    res = NumpyStarExtractor(ExtractorConfig(bayer_mode=mode, max_stars=200)).extract(img, bayer=pattern)
    assert len(res) >= 0.9 * len(stars)
    err = []
    for x, y in zip(res.x, res.y):
        j = np.argmin(np.hypot(truth["col"] - x, truth["row"] - y))
        err.append((x - truth["col"][j], y - truth["row"][j]))
    err = np.array(err)
    assert np.abs(err).max() < 0.35
    assert np.sqrt((err ** 2).sum(1).mean()) < 0.2                      # px; measured about 0.16 (all) / 0.19 (green)
    assert np.abs(err.mean(axis=0)).max() < 0.03                        # star colour does not pull the centroids one way


def test_mosaic_detection_matches_monochrome_depth_at_the_longer_exposure():
    """1 s on the colour sensor finds about as many stars as 0.5 s on mono (the doc's 'allow longer exposures')."""
    cam = CameraModel()
    from polaralign.astro.frames import rotation_from_radec_roll
    from polaralign.catalog import load_from_database
    cat = load_from_database()
    r = rotation_from_radec_roll(150.0, 30.0, 20.0)
    idx = cat.cone(r[0], cam.diag_half_angle_rad + 0.02, max_mag=9)
    v = (r @ cat.vec[idx].T).T
    mono = FrameRenderer(cam, SensorParams()).render(v, cat.mag[idx], 0.5, np.random.default_rng(1))
    col = FrameRenderer(cam, SensorParams(cfa="RGGB")).render(v, cat.mag[idx], 1.0, np.random.default_rng(1), star_ids=idx)
    ext = NumpyStarExtractor(ExtractorConfig(max_stars=400))
    n_mono, n_col = len(ext.extract(mono)), len(ext.extract(col, bayer="RGGB"))
    col_short = len(ext.extract(FrameRenderer(cam, SensorParams(cfa="RGGB")).render(
        v, cat.mag[idx], 0.5, np.random.default_rng(1), star_ids=idx), bayer="RGGB"))
    assert n_col > 0.8 * n_mono
    assert col_short < n_col                                             # and the longer exposure is what buys that


def test_mosaic_rejects_hot_pixels_in_every_colour_plane():
    img, truth, _ = star_frame("RGGB", [(700.0, 500.0, 5.0)], colour=0.5)
    img = img.astype(np.int32)
    for (x, y) in ((100, 100), (101, 301), (300, 501), (900, 701)):      # one hot pixel in each of R, G1, G2, B positions
        img[y, x] += 400
    for mode in ("all", "green"):
        res = NumpyStarExtractor(ExtractorConfig(bayer_mode=mode)).extract(np.clip(img, 0, 1023).astype(np.uint16), bayer="RGGB")
        assert len(res) == 1 and abs(res.x[0] - 700) < 0.5, mode


def test_mosaic_flux_ordering_snr_and_flags():
    stars = [(300.0, 300.0, 6.5), (600.0, 500.0, 4.5), (900.0, 700.0, 5.5)]
    img, _, _ = star_frame("RGGB", stars, colour=0.6)
    res = NumpyStarExtractor().extract(img, bayer="RGGB")
    assert [round(v / 100) for v in res.x] == [6, 9, 3] and np.all(np.diff(res.snr) <= 0)
    assert np.all((res.fwhm > 1.8) & (res.fwhm < 4.5))                   # moment-based FWHM on a mosaic ~ the 2.8 px truth


def test_pattern_comes_from_the_frame_meta_through_the_measurer():
    seen = {}

    class Spy:
        name = "spy"

        def extract(self, image, bayer=None):
            seen["bayer"] = bayer
            return ExtractionResult.empty(image.shape)

    class Solver:
        name = "none"

        def solve(self, stars, image=None):
            from polaralign.solve.base import SolveOutcome
            return SolveOutcome("too_few")

    img, _, _ = star_frame("BGGR")
    m = Measurer(FakeCamera(source=lambda e, g: img, bayer="BGGR"), Spy(), Solver())
    m.measure()
    assert seen["bayer"] == "BGGR"
    m = Measurer(FakeCamera(source=lambda e, g: img), Spy(), Solver())
    m.measure()
    assert seen["bayer"] is None


def test_wrong_but_same_green_layout_pattern_still_centroids():
    """BGGR and RGGB have the same green positions, so green mode is insensitive to confusing them."""
    img, truth, _ = star_frame("RGGB", [(700.3, 500.6, 5.0)], colour=0.5)
    a = NumpyStarExtractor(ExtractorConfig(bayer_mode="green")).extract(img, bayer="RGGB")
    b = NumpyStarExtractor(ExtractorConfig(bayer_mode="green")).extract(img, bayer="BGGR")
    assert abs(a.x[0] - b.x[0]) < 0.02 and abs(a.y[0] - b.y[0]) < 0.02


# ---------------------------------------------------------------- end to end on colour frames
def test_colour_frames_solve_with_real_tetra3(catalog, solver):
    from polaralign.astro.frames import angle_between, rotation_from_radec_roll
    cam = CameraModel(distortion=-0.01)
    for i, (ra, dec) in enumerate([(30, 40), (210, -55), (95, 10), (330, 70), (0, -85)]):
        r = rotation_from_radec_roll(ra, dec, 12.0 * i)
        idx = catalog.cone(r[0], cam.diag_half_angle_rad + 0.02, max_mag=9)
        img = FrameRenderer(cam, SensorParams(cfa="RGGB")).render((r @ catalog.vec[idx].T).T, catalog.mag[idx], 1.0,
                                                                  np.random.default_rng(i), star_ids=idx)
        ext = NumpyStarExtractor(ExtractorConfig(max_stars=80)).extract(img, bayer="RGGB")
        out = solver.solve(ext)
        assert out.ok, (ra, dec, out.status, len(ext))
        assert math.degrees(angle_between(r[0], out.solution.rotation[0])) * 3600 < 25

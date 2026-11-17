"""The star extractor: sub-pixel accuracy, rejection of junk, flags, and the swappable interface."""
import numpy as np
import pytest
from scipy.special import erf

from polaralign.config import ExtractorConfig
from polaralign.extract import (NumpyStarExtractor, StarExtractor, get_extractor, register_extractor)
from polaralign.extract.base import FLAG_BLENDED, FLAG_SATURATED, ExtractionResult

H, W = 1088, 1456


def gaussian_star(img, x, y, flux, fwhm=2.8):
    s = fwhm / 2.3548
    r = int(np.ceil(5 * s))
    xs, ys = np.arange(int(x) - r, int(x) + r + 1), np.arange(int(y) - r, int(y) + r + 1)
    xs, ys = xs[(xs >= 0) & (xs < W)], ys[(ys >= 0) & (ys < H)]
    gx = 0.5 * (erf((xs + .5 - x) / (s * 2 ** .5)) - erf((xs - .5 - x) / (s * 2 ** .5)))
    gy = 0.5 * (erf((ys + .5 - y) / (s * 2 ** .5)) - erf((ys - .5 - y) / (s * 2 ** .5)))
    img[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1] += flux * np.outer(gy, gx)


def frame(stars, bg=60.0, noise=2.0, seed=0, hot=()):
    rng = np.random.default_rng(seed)
    img = np.full((H, W), bg, dtype=np.float64)
    for (x, y, f) in stars:
        gaussian_star(img, x, y, f)
    img += rng.normal(0, noise, img.shape)
    for (x, y, v) in hot:
        img[y, x] += v
    return np.clip(np.rint(img), 0, 1023).astype(np.uint16)


def test_subpixel_centroid_accuracy_on_bright_stars():
    rng = np.random.default_rng(1)
    truth = [(rng.uniform(40, W - 40), rng.uniform(40, H - 40), 900.0) for _ in range(40)]
    # keep them apart so none is flagged as a blend
    truth = [t for i, t in enumerate(truth) if all(np.hypot(t[0] - u[0], t[1] - u[1]) > 30 for u in truth[:i])]
    res = NumpyStarExtractor(ExtractorConfig(max_stars=200)).extract(frame(truth))
    assert len(res) == len(truth)
    err = []
    for x, y, _ in truth:
        j = np.argmin(np.hypot(res.x - x, res.y - y))
        err.append((res.x[j] - x, res.y[j] - y))
    err = np.array(err)
    assert np.abs(err).max() < 0.15                       # sub-pixel: well under a fifth of a pixel
    assert err.std() < 0.05
    assert abs(err.mean()) < 0.02                         # no systematic half-pixel offset (pixel-centre convention)


def test_pixel_centre_convention():
    """A star exactly on the centre of pixel (row 100, col 200) must be reported at (200.0, 100.0)."""
    res = NumpyStarExtractor().extract(frame([(200.0, 100.0, 1500.0)], noise=0.5))
    assert res.x[0] == pytest.approx(200.0, abs=0.03) and res.y[0] == pytest.approx(100.0, abs=0.03)


def test_flux_ordering_and_snr():
    stars = [(300, 300, 400.0), (600, 500, 1200.0), (900, 700, 800.0)]
    res = NumpyStarExtractor().extract(frame(stars))
    assert [round(v) for v in res.x] == [600, 900, 300]                # brightest first
    assert res.flux[0] == pytest.approx(1200, rel=0.1) and np.all(np.diff(res.snr) <= 0)


def test_faint_star_detection_limit():
    bg_noise = 2.0
    res = NumpyStarExtractor().extract(frame([(500, 500, 120.0), (900, 400, 25.0)], noise=bg_noise))
    got = {round(x / 100) for x in res.x}
    assert 5 in got                 # 120 ADU total over ~7 px: easily found
    assert 9 not in got             # 25 ADU: below 5 sigma, must not be reported


def test_hot_pixels_are_rejected():
    res = NumpyStarExtractor().extract(frame([(700, 600, 800.0)], hot=[(100, 100, 400), (1200, 900, 600), (300, 800, 300)]))
    assert len(res) == 1 and abs(res.x[0] - 700) < 0.3


def test_static_hot_pixel_mask_removes_a_neighbouring_defect():
    mask = np.zeros((H, W), dtype=bool)
    mask[601, 703] = True
    img = frame([(700.0, 600.0, 800.0)], hot=[(703, 601, 500)])
    biased = NumpyStarExtractor().extract(img)
    masked = NumpyStarExtractor(hot_pixel_mask=mask).extract(img)
    assert abs(masked.x[0] - 700) <= abs(biased.x[0] - 700) + 1e-6 and abs(masked.x[0] - 700) < 0.1


def test_saturated_star_is_flagged_but_still_centred():
    res = NumpyStarExtractor().extract(frame([(640.3, 480.7, 30000.0)]))
    assert res.flags[0] & FLAG_SATURATED
    assert abs(res.x[0] - 640.3) < 0.2 and abs(res.y[0] - 480.7) < 0.2
    assert len(res.good()) == 1 and len(res.good(allow_saturated=False)) == 0


def test_close_pair_is_flagged_as_blend_and_excluded_from_solver_list():
    res = NumpyStarExtractor().extract(frame([(500, 500, 900.0), (505, 500, 700.0), (900, 800, 900.0)]))
    blended = [(round(x), bool(f & FLAG_BLENDED)) for x, f in zip(res.x, res.flags)]
    assert (500, True) in blended and (900, False) in blended
    assert len(res.good()) == 1


def test_border_stars_ignored_and_empty_frame_ok():
    res = NumpyStarExtractor().extract(frame([(3, 500, 900.0), (W - 2, 500, 900.0), (500, H - 2, 900.0)]))
    assert len(res) == 0
    flat = NumpyStarExtractor().extract(frame([]))
    assert len(flat) == 0 and flat.noise > 0 and flat.background == pytest.approx(60, abs=2)


def test_sky_gradient_does_not_create_or_hide_stars():
    img = frame([(400, 300, 700.0), (1000, 800, 700.0)]).astype(np.float64)
    ramp = np.linspace(0, 80, W)[None, :] * np.ones((H, 1))
    img = np.clip(img + ramp, 0, 1023).astype(np.uint16)
    res = NumpyStarExtractor().extract(img)
    assert len(res) == 2


def test_accepts_uint8_and_float_input():
    base = frame([(400, 300, 900.0)])
    for arr in (np.clip(base // 4, 0, 255).astype(np.uint8), base.astype(np.float32)):
        res = NumpyStarExtractor(ExtractorConfig(saturation_adu=10000)).extract(arr)
        assert len(res) == 1 and abs(res.x[0] - 400) < 0.3
    with pytest.raises(ValueError):
        NumpyStarExtractor().extract(np.zeros((4, 4, 3)))


def test_odd_frame_sizes():
    img = frame([(300, 200, 900.0)])[:1085, :1451]
    res = NumpyStarExtractor().extract(img)
    assert len(res) == 1 and res.image_shape == (1085, 1451)


def test_result_helpers():
    res = NumpyStarExtractor().extract(frame([(300, 200, 900.0), (900, 700, 700.0)]))
    yx = res.centroids_yx()
    assert yx.shape == (2, 2) and yx[0, 0] == pytest.approx(res.y[0])
    assert len(res.select(res.flux > 1e9)) == 0 and len(ExtractionResult.empty((4, 4))) == 0


def test_backend_registry_is_swappable():
    assert isinstance(get_extractor(ExtractorConfig()), StarExtractor)

    class Fixed:
        name = "fixed"

        def extract(self, image):
            r = ExtractionResult.empty(image.shape)
            r.x = np.array([1.0])
            return r

    register_extractor("fixed", lambda cfg: Fixed())
    ext = get_extractor(ExtractorConfig(backend="fixed"))
    assert ext.name == "fixed" and len(ext.extract(np.zeros((8, 8)))) == 1
    with pytest.raises(ValueError, match="unknown extractor"):
        get_extractor(ExtractorConfig(backend="nope"))


def test_tetra3_adapter_runs_behind_the_same_interface():
    res = get_extractor(ExtractorConfig(backend="tetra3")).extract(frame([(700, 500, 900.0), (300, 300, 900.0)]))
    assert len(res) >= 2
    j = np.argmin(np.hypot(res.x - 700, res.y - 500))
    assert abs(res.x[j] - 700) < 0.5 and abs(res.y[j] - 500) < 0.5      # same pixel-centre convention after conversion


def test_extractor_on_simulated_sky_recalls_bright_stars(catalog):
    from polaralign.astro.frames import rotation_from_radec_roll
    from polaralign.sim import CameraModel, FrameRenderer, SensorParams
    cam = CameraModel()
    r = rotation_from_radec_roll(120.0, 35.0, 10.0)
    idx = catalog.cone(r[0], cam.diag_half_angle_rad + 0.02, max_mag=9)
    img, truth = FrameRenderer(cam, SensorParams()).render((r @ catalog.vec[idx].T).T, catalog.mag[idx], 0.5,
                                                           np.random.default_rng(2), return_truth=True)
    res = NumpyStarExtractor(ExtractorConfig(max_stars=300)).extract(img)
    bright = np.nonzero(truth["mag"] < 6.8)[0]
    found = sum(1 for i in bright if np.hypot(res.x - truth["col"][i], res.y - truth["row"][i]).min() < 1.0)
    assert found >= 0.9 * len(bright)
    # nothing spurious among the strong detections
    strong = res.snr > 12
    far = [np.hypot(truth["col"] - x, truth["row"] - y).min() for x, y in zip(res.x[strong], res.y[strong])]
    assert max(far) < 1.5

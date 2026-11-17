"""Benchmark of the star extractor on a realistic 1456 x 1088 frame.  ``polaralign bench``.

Frames come from the simulator (real optics and a real sky are exactly what a Pi test would add), so
the numbers are timings of *this code on this machine*.  Run it on the Pi Zero 2 W to get the number
that matters; nothing here has been run on one.
"""
from __future__ import annotations

import json
import math
import platform
import statistics
import time

import numpy as np

from .astro.frames import rotation_from_radec_roll
from .catalog import load_from_database
from .config import ExtractorConfig
from .extract import NumpyStarExtractor
from .sim.camera_model import CameraModel
from .sim.render import FrameRenderer, SensorParams


def make_frames(n_pointings: int = 6, exposure_s: float = 0.5, seed: int = 4, cfa: str = ""):
    """Synthetic frames: ``cfa=""`` monochrome, ``"RGGB"`` etc. a Bayer mosaic (the colour IMX296)."""
    cat = load_from_database()
    cam = CameraModel()
    rend = FrameRenderer(cam, SensorParams(cfa=cfa))
    rng = np.random.default_rng(seed)
    frames = []
    for i in range(n_pointings):
        ra, dec, roll = rng.uniform(0, 360), math.degrees(math.asin(rng.uniform(-0.9, 0.9))), rng.uniform(0, 360)
        r = rotation_from_radec_roll(ra, dec, roll)
        idx = cat.cone(r[0], cam.diag_half_angle_rad + 0.02, max_mag=9.5)
        frame, truth = rend.render((r @ cat.vec[idx].T).T, cat.mag[idx], exposure_s, rng, return_truth=True, star_ids=idx)
        frames.append((frame, truth))
    return frames


def bench(runs: int = 30, cfa: str = "RGGB", exposure_s: float | None = None, bayer_mode: str = "all") -> dict:
    exposure_s = exposure_s or (1.0 if cfa else 0.5)
    frames = make_frames(exposure_s=exposure_s, cfa=cfa)
    ext = NumpyStarExtractor(ExtractorConfig(max_stars=200, bayer_mode=bayer_mode))
    bay = cfa or None
    ext.extract(frames[0][0], bayer=bay)             # warm up (page faults, numpy lazy init)
    times, stage = [], {}
    n_found = []
    for i in range(runs):
        frame = frames[i % len(frames)][0]
        t = time.perf_counter()
        res = ext.extract(frame, bayer=bay)
        times.append((time.perf_counter() - t) * 1e3)
        n_found.append(len(res))
        for k, v in res.timings_ms.items():
            stage.setdefault(k, []).append(v)
    # accuracy against the renderer's truth
    errs, matched, total = [], 0, 0
    for frame, truth in frames:
        res = ext.extract(frame, bayer=bay)
        tx, ty, tm = truth["col"], truth["row"], truth["mag"]
        for x, y in zip(res.x, res.y):
            d = np.hypot(tx - x, ty - y)
            j = int(d.argmin())
            if d[j] < 1.5:
                errs.append((x - tx[j], y - ty[j]))
        total += int((tm < 7.5).sum())
        matched += sum(1 for i in np.nonzero(tm < 7.5)[0] if len(res) and np.hypot(res.x - tx[i], res.y - ty[i]).min() < 1.5)
    e = np.array(errs)
    return {
        "machine": f"{platform.machine()} / {platform.system()} {platform.release()} / Python {platform.python_version()}",
        "numpy": np.__version__,
        "frame": f"1456x1088 uint16 (10-bit), {exposure_s} s synthetic sky, " + (f"Bayer {cfa}, bayer_mode={bayer_mode}" if cfa else "monochrome"),
        "runs": runs, "ms_median": round(statistics.median(times), 2), "ms_min": round(min(times), 2),
        "ms_p95": round(float(np.percentile(times, 95)), 2), "ms_max": round(max(times), 2),
        "stage_ms_median": {k: round(statistics.median(v), 2) for k, v in stage.items()},
        "stars_detected_median": int(statistics.median(n_found)),
        "recall_mag_lt_7.5": round(matched / max(total, 1), 3),
        "centroid_rms_px": {"x": round(float(e[:, 0].std()), 3), "y": round(float(e[:, 1].std()), 3)},
        "centroid_median_abs_px": round(float(np.median(np.hypot(e[:, 0], e[:, 1]))), 3),
    }


def main(runs: int = 30) -> int:
    out = {"colour_bayer_RGGB_1.0s": bench(runs, "RGGB"), "colour_bayer_green_only": bench(runs, "RGGB", bayer_mode="green"),
           "monochrome_0.5s": bench(runs, "")}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

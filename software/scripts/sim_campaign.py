"""Monte-Carlo campaign over simulated sessions: sites in both hemispheres, random 4-5.5 deg initial errors in
reachable directions, random motor-direction wiring, backlash 0.03-0.12 deg, scale errors, lost steps,
a sloppy hand alignment (<= 0.03 deg) and varied sky brightness, on the simulated COLOUR sensor (Bayer RGGB, IR cut).  Prints the numbers quoted in the README.

    .venv/bin/python scripts/sim_campaign.py [N [ONLY]]   (default 48; ~2 s per session; ONLY = run just that index)
"""
import json
import math
import statistics
import sys
import time

import numpy as np

from polaralign.astro import Site
from polaralign.config import CameraConfig, SolverConfig, sim_config
from polaralign.sim import MountParams, SensorParams
from polaralign.sim.scenario import run_scenario
from polaralign.solve import get_solver

SITES = [(25.2, 55.3), (48.1, 11.6), (57.5, -4.2), (35.0, -106.0), (9.0, 101.7), (-33.9, 151.2), (-29.0, -70.7), (-45.9, 170.5)]


def main(n: int = 48, only: int | None = None) -> None:
    solver = get_solver(SolverConfig(), CameraConfig())
    rng = np.random.default_rng(2026)
    rows = []
    t0 = time.time()
    for i in range(n):
        lat, lon = SITES[i % len(SITES)]
        # the azimuth stage moves the axis cos(lat) per degree: keep the east-west part of the error reachable
        cos_lat = math.cos(math.radians(abs(lat)))
        err = float(rng.uniform(4.0, 5.5))
        max_east = 5.0 * cos_lat
        while True:
            direction = float(rng.uniform(0, 360))
            if abs(err * math.sin(math.radians(direction))) <= max_east and abs(err * math.cos(math.radians(direction))) <= 5.2:
                break
        mp = MountParams(axis_alt_deg=abs(lat) + 3.0, axis_az_deg=4.0 if lat >= 0 else 184.0, seed=1000 + i,
                         az_sign=int(rng.choice([-1, 1])), alt_sign=int(rng.choice([-1, 1])),
                         backlash_az_deg=float(rng.uniform(0.03, 0.12)), backlash_alt_deg=float(rng.uniform(0.03, 0.12)),
                         az_scale_error=float(rng.uniform(-0.04, 0.04)), alt_scale_error=float(rng.uniform(-0.12, 0.12)),
                         offaxis_deg=float(rng.uniform(15, 35)), cam_roll_deg=float(rng.uniform(0, 360)))
        # the colour IMX296 (Bayer RGGB + IR-cut): the CFA already costs 2-3x of light; 1 s default exposure
        sensor = SensorParams(cfa="RGGB", mag0_e_per_s=float(rng.uniform(5e4, 2.5e5)), sky_e_per_s_px=float(rng.uniform(1.0, 8.0)))
        cal_err = float(rng.uniform(0.0, 0.03))
        if only is not None and i != only:
            continue                          # keep the random stream identical, run just one session
        res = run_scenario(seed=i, site=Site(lat, lon), initial_error_deg=err, direction_deg=direction,
                           calibration_error_deg=cal_err, mount=mp, sensor=sensor, solver=solver)
        r = res.report
        rows.append({"i": i, "lat": lat, "initial": round(res.initial_true_error_deg, 2), "ok": r.success,
                     "iterations": r.iterations, "final_deg": res.final_true_error_deg, "measured_arcmin": r.residual_arcmin,
                     "solves": r.solves, "cal_err_deg": res.calibration_error_deg, "msg": "" if r.success else r.message})
        print(f"{i:3d} lat {lat:6.1f} err {res.initial_true_error_deg:.2f} -> {res.final_true_error_deg:.4f} deg "
              f"in {r.iterations} it, {r.solves} solves {'OK' if r.success else 'FAIL ' + r.message}", flush=True)
    if only is not None:
        return
    fin = [r["final_deg"] for r in rows]
    its = [r["iterations"] for r in rows if r["ok"]]
    summary = {
        "sessions": n, "converged": sum(r["ok"] for r in rows), "under_0.05_deg_true": sum(f < 0.05 for f in fin),
        "iterations_median": statistics.median(its), "iterations_max": max(its),
        "iterations_histogram": {k: its.count(k) for k in sorted(set(its))},
        "final_true_error_deg": {"median": round(statistics.median(fin), 4), "p90": round(float(np.percentile(fin, 90)), 4),
                                 "max": round(max(fin), 4)},
        "solves_median": statistics.median(r["solves"] for r in rows), "wall_s": round(time.time() - t0, 1),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 48, int(sys.argv[2]) if len(sys.argv) > 2 else None)

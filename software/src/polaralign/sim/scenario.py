"""A complete simulated session: home, hand-align and declare, knock the base 5 degrees off, run the loop.

Shared by the tests, ``polaralign sim-align`` and the README numbers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from ..align.engine import AlignEngine, AlignReport
from ..align.pipeline import Measurer
from ..astro import Site
from ..calibration import CalibrationStore
from ..config import Config, sim_config
from ..extract import get_extractor
from ..solve import get_solver
from .mount import MountParams
from .render import SensorParams
from .world import SimHardware, build_sim_hardware


@dataclass
class ScenarioResult:
    report: AlignReport
    hw: SimHardware
    initial_true_error_deg: float
    final_true_error_deg: float              # physical axis vs the apparent pole (the quantity being driven to 0)
    final_vs_true_pole_deg: float            # vs the unrefracted pole of date
    calibration_error_deg: float             # error of the stored camera-to-axis vector
    declare_true_error_deg: float            # how far from the pole the 'hand alignment' really was
    iterations: int


def run_scenario(seed: int = 0, site: Site | None = None, initial_error_deg: float = 5.0,
                 direction_deg: float = 130.0, calibration_error_deg: float = 0.015,
                 mount: MountParams | None = None, sensor: SensorParams | None = None, config: Config | None = None,
                 when: datetime | None = None, distortion: float = -0.012, solver=None, aberration: bool = True,
                 refraction: str = "model", exposure_s: float | None = None) -> ScenarioResult:
    cfg = config or sim_config()
    cfg.align.refraction = refraction
    if exposure_s:
        cfg.camera.exposure_s = exposure_s
    site = site or Site(25.2, 55.3)
    mp = mount or MountParams(axis_alt_deg=abs(site.latitude_deg) + 3.0, axis_az_deg=4.0 if site.latitude_deg >= 0 else 184.0,
                              seed=seed + 100)
    hw = build_sim_hardware(cfg, site=site, when=when, mount=mp, sensor=sensor, distortion=distortion, seed=seed,
                            aberration=aberration)
    hw.motion.home()
    solver = solver or get_solver(cfg.solver, cfg.camera)
    measurer = Measurer(hw.camera, get_extractor(cfg.extractor), solver)
    cal = CalibrationStore(None)
    engine = AlignEngine(cfg, measurer, hw.motion, cal, hw.time_source, lambda: site)

    # 1. the user aligns by hand with the telescope's own routine, to within `calibration_error_deg`
    hw.world.set_coarse(calibration_error_deg, 40.0)
    declare_err = hw.world.true_axis_error_deg()
    engine.declare_aligned()
    a_true = hw.world.mount.a_cam_true
    cal_err = math.degrees(math.acos(min(1.0, float(cal.a_cam @ a_true))))
    # 2. the base is then re-set (or knocked) by `initial_error_deg`
    hw.world.set_coarse(initial_error_deg, direction_deg)
    initial = hw.world.true_axis_error_deg()
    # 3. one press of the button
    report = engine.run()
    return ScenarioResult(report, hw, initial, hw.world.true_axis_error_deg(), hw.world.true_axis_error_vs_true_pole_deg(),
                          cal_err, declare_err, report.iterations)

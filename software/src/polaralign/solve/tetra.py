"""Cedar Solve / tetra3 wrapper (Apache-2.0).

We use only the *solver* half of the package.  Star extraction is our own
(:mod:`polaralign.extract`); Cedar Detect (Functional Source License) is never imported.
"""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path

import numpy as np

from ..astro.frames import rotation_from_radec_roll
from ..config import CameraConfig, SolverConfig
from ..extract.base import ExtractionResult
from .base import Solution, SolveOutcome
from .refine import refine_pose

log = logging.getLogger(__name__)


def find_database(setting: str, state_dir: Path | None = None) -> Path | None:
    """Resolve ``solver.database``.  Returns None for the bundled default.

    "default" -> bundled; a path -> that file; "auto" -> $POLARALIGN_DB, <state_dir>/polaralign_db.npz,
    ``software/data/polaralign_db.npz`` next to the source tree, else the bundled default.
    """
    import os
    if setting == "default":
        return None
    if setting != "auto":
        return Path(setting).expanduser()
    candidates = []
    if os.environ.get("POLARALIGN_DB"):
        candidates.append(Path(os.environ["POLARALIGN_DB"]))
    if state_dir is not None:
        candidates.append(state_dir / "polaralign_db.npz")
    candidates.append(Path(__file__).resolve().parents[3] / "data" / "polaralign_db.npz")
    for c in candidates:
        if c.exists():
            return c
    return None


class TetraSolver:
    name = "tetra3"

    def __init__(self, cfg: SolverConfig | None = None, camera: CameraConfig | None = None,
                 database: str | Path | None = None) -> None:
        import tetra3  # Cedar Solve ships the module under this name

        if int(np.__version__.split(".")[0]) >= 2:
            raise RuntimeError(f"numpy {np.__version__} is too new for cedar-solve 0.5.1 (solves fail with numpy 2.x); "
                               "install numpy<2")

        self.cfg = cfg or SolverConfig()
        self.camera = camera or CameraConfig()
        self._tetra3 = tetra3
        db = database if database is not None else find_database(self.cfg.database)
        t0 = time.perf_counter()
        # tetra3: a *str* is looked up in its data dir, a Path is used as is
        if db is None or str(db) == "default":
            self._t3 = tetra3.Tetra3(load_database="default_database")
            self.database_path: Path | None = None
        else:
            self.database_path = Path(db).expanduser()
            self._t3 = tetra3.Tetra3(load_database=self.database_path)
        self.load_time_s = time.perf_counter() - t0

    @property
    def database_properties(self) -> dict:
        return dict(self._t3.database_properties)

    def solve(self, stars: ExtractionResult, image: np.ndarray | None = None) -> SolveOutcome:
        cfg = self.cfg
        good = stars.good()
        n = min(len(good), cfg.max_stars)
        if n < cfg.min_stars:
            return SolveOutcome("too_few", n_input=n, detail=f"{n} usable stars (< {cfg.min_stars})")
        h, w = stars.image_shape
        # brightest first; tetra3 wants (y, x) with the top-left pixel *centre* at (0.5, 0.5)
        order = np.argsort(-good.flux)[:n]
        cents = np.column_stack([good.y[order] + 0.5, good.x[order] + 0.5])
        t0 = time.perf_counter()
        try:
            res = self._t3.solve_from_centroids(
                cents, (h, w), fov_estimate=self.camera.fov_h_deg, fov_max_error=cfg.fov_max_error_deg,
                match_radius=cfg.match_radius, match_threshold=cfg.match_threshold,
                solve_timeout=cfg.solve_timeout_ms, distortion=tuple(cfg.distortion_range))
        except Exception as exc:                       # pragma: no cover - defensive
            log.exception("tetra3 raised")
            return SolveOutcome("error", n_input=n, detail=str(exc), t_ms=(time.perf_counter() - t0) * 1e3)
        t_ms = (time.perf_counter() - t0) * 1e3
        status = res.get("status")
        if status != self._tetra3.tetra3.MATCH_FOUND:
            name = {self._tetra3.tetra3.NO_MATCH: "no_match", self._tetra3.tetra3.TIMEOUT: "timeout",
                    self._tetra3.tetra3.TOO_FEW: "too_few"}.get(status, "error")
            return SolveOutcome(name, n_input=n, detail=f"tetra3 status {status}", t_ms=t_ms)
        sol = Solution(
            ra_deg=float(res["RA"]), dec_deg=float(res["Dec"]), roll_deg=float(res["Roll"]),
            fov_deg=float(res["FOV"]), distortion=None if res.get("distortion") is None else float(res["distortion"]),
            rmse_arcsec=float(res["RMSE"]), n_matches=int(res["Matches"]), prob=float(res["Prob"]),
            t_solve_ms=float(res["T_solve"]),
            rotation=rotation_from_radec_roll(float(res["RA"]), float(res["Dec"]), float(res["Roll"])))
        extra: dict = {"tetra3_rmse_arcsec": sol.rmse_arcsec, "tetra3_matches": sol.n_matches}
        if cfg.refine:
            # tetra3's final fit includes every star within 1 % of the image width (one false match
            # ruins the RMSE); redo it with a 2 px match radius and a robust loss.
            xy_all = np.column_stack([good.x, good.y])[np.argsort(-good.flux)[:cfg.refine_max_stars]]
            t1 = time.perf_counter()
            rp = refine_pose(sol.rotation, sol.fov_deg, sol.distortion, w, h,
                             np.asarray(self._t3.star_table[:, 2:5], dtype=float), xy_all)
            extra["refine_ms"] = (time.perf_counter() - t1) * 1e3
            if rp.ok and rp.n_inliers >= 0.6 * sol.n_matches:
                sol.rotation = rp.rotation
                sol.fov_deg, sol.distortion = rp.fov_deg, rp.distortion
                sol.rmse_arcsec, sol.n_matches = rp.rmse_arcsec, rp.n_inliers
                ra = math.degrees(math.atan2(rp.rotation[0, 1], rp.rotation[0, 0])) % 360.0
                dec = math.degrees(math.asin(max(-1.0, min(1.0, float(rp.rotation[0, 2])))))
                sol.ra_deg, sol.dec_deg = ra, dec
                sol.roll_deg = math.degrees(math.atan2(rp.rotation[1, 2], rp.rotation[2, 2])) % 360.0
            else:
                extra["refine"] = "rejected"
        t_ms = (time.perf_counter() - t0) * 1e3
        if sol.rmse_arcsec > cfg.max_rmse_arcsec or sol.n_matches < cfg.min_matches:
            return SolveOutcome("poor_fit", sol, n_input=n, t_ms=t_ms, extra=extra,
                                detail=f"{sol.n_matches} matches, rmse {sol.rmse_arcsec:.1f}\"")
        return SolveOutcome("ok", sol, n_input=n, t_ms=t_ms, extra=extra)

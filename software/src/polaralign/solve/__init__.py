"""Plate solving.  ``solver.backend = "tetra3"`` (Cedar Solve, Apache-2.0) is the default."""
from __future__ import annotations

from pathlib import Path

from ..config import CameraConfig, SolverConfig
from .base import Solution, Solver, SolveOutcome


def get_solver(cfg: SolverConfig, camera: CameraConfig, state_dir: Path | None = None) -> Solver:
    if cfg.backend == "tetra3":
        from .tetra import TetraSolver, find_database
        return TetraSolver(cfg, camera, database=find_database(cfg.database, state_dir))
    if cfg.backend == "astrometry":
        from .astrometry import AstrometrySolver
        return AstrometrySolver(cfg, camera)
    raise ValueError(f"unknown solver backend {cfg.backend!r}")


__all__ = ["Solution", "Solver", "SolveOutcome", "get_solver"]

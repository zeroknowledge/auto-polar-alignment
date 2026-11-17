"""Plate-solver interface and result types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

from ..extract.base import ExtractionResult


@dataclass
class Solution:
    ra_deg: float                  # boresight, J2000 / ICRS
    dec_deg: float
    roll_deg: float                # tetra3 convention
    fov_deg: float                 # fitted horizontal field of view
    distortion: float | None       # fitted radial distortion (tetra3 'k')
    rmse_arcsec: float             # RMS residual of matched stars
    n_matches: int
    prob: float                    # false-positive probability reported by the solver
    t_solve_ms: float
    rotation: np.ndarray           # 3x3, celestial (J2000) -> camera (x boresight, y left, z up)

    @property
    def boresight(self) -> np.ndarray:
        return self.rotation[0]


@dataclass
class SolveOutcome:
    status: str                    # "ok" | "too_few" | "no_match" | "timeout" | "poor_fit" | "error"
    solution: Solution | None = None
    n_input: int = 0               # stars handed to the solver
    detail: str = ""
    t_ms: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.solution is not None


@runtime_checkable
class Solver(Protocol):
    name: str

    def solve(self, stars: ExtractionResult, image: np.ndarray | None = None) -> SolveOutcome: ...

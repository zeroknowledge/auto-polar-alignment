"""capture -> extract -> solve, with the bookkeeping the UI and the loop need."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from ..camera.base import Camera, Frame
from ..extract.base import ExtractionResult, StarExtractor
from ..solve.base import Solution, Solver, SolveOutcome

log = logging.getLogger(__name__)


@dataclass
class Measurement:
    ok: bool
    status: str
    time: datetime
    outcome: SolveOutcome | None = None
    stars: ExtractionResult | None = None
    frame: Frame | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)

    @property
    def rotation(self) -> np.ndarray | None:
        return self.outcome.solution.rotation if self.outcome and self.outcome.solution else None

    @property
    def solution(self) -> Solution | None:
        return self.outcome.solution if self.outcome else None


class Measurer:
    """One pose measurement of the camera relative to the stars."""

    def __init__(self, camera: Camera, extractor: StarExtractor, solver: Solver) -> None:
        self.camera = camera
        self.extractor = extractor
        self.solver = solver
        self.last: Measurement | None = None
        self.exposure_s: float | None = None
        self.gain: float | None = None

    def measure(self) -> Measurement:
        t0 = time.perf_counter()
        frame = self.camera.capture(self.exposure_s, self.gain)
        t1 = time.perf_counter()
        stars = self.extractor.extract(frame.pixels, bayer=frame.meta.get("bayer"))
        t2 = time.perf_counter()
        outcome = self.solver.solve(stars, frame.pixels)
        t3 = time.perf_counter()
        m = Measurement(ok=outcome.ok, status=outcome.status, time=frame.timestamp, outcome=outcome, stars=stars,
                        frame=frame, timings_ms={"capture": (t1 - t0) * 1e3, "extract": (t2 - t1) * 1e3,
                                                 "solve": (t3 - t2) * 1e3, "total": (t3 - t0) * 1e3})
        self.last = m
        return m

"""Camera-to-axis calibration store (design document section 10.3).

The camera is bolted to the tilting plate; the thing that has to point at the pole is the telescope's
rotation axis.  The fixed relation between the two is a *rotation*: here, the unit vector ``a_cam`` of
the axis in the camera frame, plus the minimal rotation ``R_cam_to_mount`` that takes it to the mount
frame's +z (roll about the axis cannot matter for polar alignment, so it is left at the minimal
choice).  It is recorded when the user declares the telescope aligned, i.e. when the telescope's own
polar-alignment routine has done the best it can; entries from several nights are averaged, and a
Seestar (or other) report of a residual can later *trim* it (``trim``).

Persistence: JSON in the state directory, written atomically with a one-generation backup.
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .astro.frames import rotation_between, unit

log = logging.getLogger(__name__)


@dataclass
class CalibrationEntry:
    time_utc: str
    a_cam: list[float]
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    n_matches: int = 0
    rmse_arcsec: float = 0.0
    refraction: str = "model"
    note: str = ""


@dataclass
class Trim:
    time_utc: str
    delta_cam: list[float]       # small vector added to a_cam before renormalising
    source: str = ""


@dataclass
class CalibrationData:
    version: int = 1
    entries: list[CalibrationEntry] = field(default_factory=list)
    trims: list[Trim] = field(default_factory=list)


class CalibrationStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.data = CalibrationData()
        if path and path.exists():
            self.load()

    # ------------------------------------------------------------------ values
    @property
    def calibrated(self) -> bool:
        return bool(self.data.entries)

    @property
    def a_cam(self) -> np.ndarray | None:
        """Unit vector of the telescope axis in the camera frame (entries averaged, then trimmed)."""
        if not self.data.entries:
            return None
        v = np.mean([unit(np.array(e.a_cam)) for e in self.data.entries], axis=0)
        for t in self.data.trims:
            v = v + np.array(t.delta_cam)
        return unit(v)

    @property
    def rotation_cam_to_mount(self) -> np.ndarray | None:
        a = self.a_cam
        return None if a is None else rotation_between(a, np.array([0.0, 0.0, 1.0]))

    def spread_arcsec(self) -> float | None:
        """Largest angle between any entry and the mean: the repeatability of declaring 'aligned'."""
        if len(self.data.entries) < 2:
            return None
        mean = unit(np.mean([unit(np.array(e.a_cam)) for e in self.data.entries], axis=0))
        return max(math.degrees(math.acos(min(1.0, float(unit(np.array(e.a_cam)) @ mean)))) * 3600.0
                   for e in self.data.entries)

    # ------------------------------------------------------------------ changes
    def add_entry(self, a_cam: np.ndarray, **kw) -> CalibrationEntry:
        e = CalibrationEntry(time_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             a_cam=[float(x) for x in unit(a_cam)], **kw)
        self.data.entries.append(e)
        self.save()
        return e

    def trim(self, delta_cam: np.ndarray, source: str = "", max_deg: float = 0.3) -> None:
        """Nudge the stored axis by a small camera-frame vector (e.g. from a telescope's residual)."""
        d = np.asarray(delta_cam, dtype=float)
        n = float(np.linalg.norm(d))
        lim = math.radians(max_deg)
        if n > lim:
            d = d * (lim / n)
        self.data.trims.append(Trim(datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    [float(x) for x in d], source))
        self.save()

    def clear(self) -> None:
        """Forget everything (the previous file is kept as ``.bak``)."""
        self.data = CalibrationData()
        self.save()

    # ------------------------------------------------------------------ persistence
    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                os.replace(self.path, self.path.with_suffix(".bak"))
            except OSError:
                pass
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self.data), indent=1))
        tmp.replace(self.path)

    def load(self) -> None:
        assert self.path
        try:
            raw = json.loads(self.path.read_text())
            self.data = CalibrationData(
                version=raw.get("version", 1),
                entries=[CalibrationEntry(**e) for e in raw.get("entries", [])],
                trims=[Trim(**t) for t in raw.get("trims", [])])
        except (OSError, ValueError, TypeError) as exc:
            log.error("calibration file unreadable (%s); starting empty", exc)
            self.data = CalibrationData()

    def summary(self) -> dict:
        a = self.a_cam
        return {"calibrated": self.calibrated, "entries": len(self.data.entries), "trims": len(self.data.trims),
                "a_cam": None if a is None else [round(float(x), 6) for x in a],
                "spread_arcsec": self.spread_arcsec(),
                "last": self.data.entries[-1].time_utc if self.data.entries else None}

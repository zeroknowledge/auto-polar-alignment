"""Phase 4: use a telescope's own polar-alignment result to trim the camera-to-axis calibration.

Two parts:

* :class:`SeestarReader` obtains a :class:`PolarErrorReport` from the telescope (method and field names
  come from the config; they are unverified -- see :mod:`.client`).  Any other source (a person typing
  the numbers from the app, another vendor's API) can produce the same report.
* :func:`trim_calibration` is the part that matters and is testable without a telescope: it turns the
  residual the telescope reports *after our base declared itself aligned* into a correction of the
  stored axis vector, so the next alignment lands where the telescope says "aligned".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from ...astro import ARCSEC, PoleTarget, axis_in_camera, physical_axis, unit
from ...calibration import CalibrationStore
from ...config import SeestarConfig
from .client import SeestarClient, SeestarError

_UNIT_TO_RAD = {"arcsec": ARCSEC, "arcmin": 60 * ARCSEC, "deg": math.radians(1.0)}


@dataclass
class PolarErrorReport:
    """How far the telescope believes its axis is from its own idea of the pole."""

    alt_rad: float                     # + = axis too high
    east_rad: float                    # + = axis too far east (sky angle)
    source: str = "seestar"
    time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict = field(default_factory=dict)

    @property
    def total_arcmin(self) -> float:
        return math.degrees(math.hypot(self.alt_rad, self.east_rad)) * 60.0


class NotConfigured(RuntimeError):
    pass


def _dig(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        cur = cur[part]
    return cur


class SeestarReader:
    def __init__(self, cfg: SeestarConfig, client: SeestarClient | None = None) -> None:
        self.cfg = cfg
        self.client = client

    def read(self) -> PolarErrorReport:
        c = self.cfg
        if not (c.polar_align_method and c.result_alt_key and c.result_az_key):
            raise NotConfigured("seestar.polar_align_method / result_alt_key / result_az_key are empty: the Seestar's "
                                "polar-alignment API is not documented, probe it (see README) and set them")
        client = self.client or SeestarClient(c.host, c.port, c.timeout_s)
        if client._sock is None:
            client.connect()
        reply = client.call(c.polar_align_method)
        res = reply.get("result", reply)
        try:
            alt = float(_dig(res, c.result_alt_key))
            az = float(_dig(res, c.result_az_key))
        except (KeyError, TypeError, ValueError) as exc:
            raise SeestarError(f"could not find the configured fields in the reply: {exc}; reply was {reply}") from exc
        k = _UNIT_TO_RAD[c.units]
        return PolarErrorReport(alt_rad=c.sign_alt * alt * k, east_rad=c.sign_az * az * k, raw=reply)


def trim_calibration(store: CalibrationStore, report: PolarErrorReport, r_cam: np.ndarray, target: PoleTarget,
                     weight: float = 0.5) -> dict:
    """Feed a telescope-reported residual back into the stored axis vector.

    ``r_cam`` is the celestial->camera rotation of a solve taken at the moment the telescope measured.
    The telescope says the real axis is at ``target + (alt, east)``; the calibration believed it was at
    ``target``.  The corrected camera-frame axis is that sky direction pushed through the same solve, and
    ``weight`` of the difference is applied (averaging out the telescope's own measurement noise).
    """
    a_old = store.a_cam
    if a_old is None:
        raise ValueError("no calibration to trim")
    believed = physical_axis(r_cam, a_old, target)
    claimed = unit(believed + report.alt_rad * target.up + report.east_rad * target.east)
    a_new = axis_in_camera(r_cam, claimed, target)
    delta = weight * (a_new - a_old)
    store.trim(delta, source=report.source)
    return {"applied_arcsec": float(np.linalg.norm(delta) / ARCSEC), "reported_arcmin": report.total_arcmin}

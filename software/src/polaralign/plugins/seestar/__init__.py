"""Optional Seestar verification plugin (phase 4).  Import this package only when ``seestar.enabled``."""
from __future__ import annotations

from .verifier import NotConfigured, PolarErrorReport, SeestarReader, trim_calibration


def register_routes(app, rt) -> None:
    """Add /api/seestar/* to the FastAPI app.  Called by the CLI only when the plugin is enabled."""
    from fastapi import HTTPException

    from .client import SeestarError, discover

    reader = SeestarReader(rt.cfg.seestar)

    @app.get("/api/seestar/discover")
    def _discover() -> dict:
        return {"hosts": discover()}

    @app.post("/api/seestar/verify")
    def _verify(apply: bool = True) -> dict:
        """Read the telescope's own residual and (optionally) trim the calibration with it."""
        try:
            report = reader.read()
        except NotConfigured as exc:
            raise HTTPException(501, str(exc)) from exc
        except (SeestarError, OSError) as exc:
            raise HTTPException(502, f"Seestar: {exc}") from exc
        out = {"reported_arcmin": report.total_arcmin, "alt_arcmin": report.alt_rad * 3437.7468, "east_arcmin": report.east_rad * 3437.7468}
        if apply:
            s = rt.engine.sample(retries=2, quiet=True)
            m = s.measurement
            out["trim"] = trim_calibration(rt.calibration, report, m.rotation, s.target, rt.cfg.seestar.trim_weight)
        return out


__all__ = ["NotConfigured", "PolarErrorReport", "SeestarReader", "trim_calibration", "register_routes"]

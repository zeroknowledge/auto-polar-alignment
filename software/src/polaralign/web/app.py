"""FastAPI application: JSON API + server-sent events + static single-page UI (no build step)."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..runtime import Busy, Runtime

STATIC = Path(__file__).parent / "static"


class JogRequest(BaseModel):
    axis: str
    deg: float = Field(..., ge=-12, le=12)


class AlignRequest(BaseModel):
    allow_uncalibrated: bool = False


class LocationRequest(BaseModel):
    latitude: float
    longitude: float
    source: str = "manual"           # "browser" | "manual"
    unix_ms: float | None = None
    accuracy_m: float | None = None


class CameraRequest(BaseModel):
    exposure_s: float | None = Field(None, gt=0.005, le=10)
    gain: float | None = Field(None, ge=1, le=64)


class ConfirmRequest(BaseModel):
    confirm: bool = False


class SimCoarseRequest(BaseModel):
    error_deg: float = Field(0.0, ge=0, le=15)
    direction_deg: float = 130.0


def create_app(rt: Runtime) -> FastAPI:
    app = FastAPI(title="polaralign", version="0.1.0")
    token = rt.cfg.web.token

    def auth(x_token: str | None = Header(default=None)) -> None:
        if token and x_token != token:
            raise HTTPException(401, "missing or wrong X-Token")

    def job_or_409(fn):
        try:
            job = fn()
        except Busy as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"started": job.name}

    @app.get("/api/status")
    def status() -> dict:
        return rt.status()

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        async def gen():
            last_sent = 0.0
            while True:
                payload = rt.status()
                payload["log"] = [e for e in list(rt.events)[-60:]]
                yield f"data: {json.dumps(payload, default=str)}\n\n"
                last_sent = time.time()
                await asyncio.sleep(0.5 if rt.busy() else 1.0)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/log")
    def log(n: int = 100) -> list[dict]:
        return list(rt.events)[-n:]

    @app.get("/api/frame.png")
    def frame(overlay: int = 1) -> Response:
        png = rt.frame_png(overlay=bool(overlay))
        if png is None:
            raise HTTPException(404, "no frame captured yet")
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/align/start", dependencies=[Depends(auth)])
    def align_start(req: AlignRequest) -> dict:
        return job_or_409(lambda: rt.start_align(req.allow_uncalibrated))

    @app.post("/api/align/cancel", dependencies=[Depends(auth)])
    def align_cancel() -> dict:
        rt.cancel()
        return {"cancelled": True}

    @app.post("/api/measure", dependencies=[Depends(auth)])
    def measure() -> dict:
        return job_or_409(rt.start_measure)

    @app.post("/api/jog", dependencies=[Depends(auth)])
    def jog(req: JogRequest) -> dict:
        return job_or_409(lambda: rt.start_jog(req.axis, req.deg))

    @app.post("/api/home", dependencies=[Depends(auth)])
    def home(measure_span: bool = False) -> dict:
        """Home to MIN; with ?measure_span=true also drive to MAX and use the measured travel (slower)."""
        return job_or_409(lambda: rt.start_home(measure_span))

    @app.post("/api/release", dependencies=[Depends(auth)])
    def release() -> dict:
        rt.motion.release_all()
        return {"released": True}

    @app.post("/api/calibration/declare", dependencies=[Depends(auth)])
    def declare(req: ConfirmRequest) -> dict:
        if not req.confirm:
            raise HTTPException(400, "send {'confirm': true}: this records the *current* pointing as 'aligned'")
        return job_or_409(rt.start_declare_aligned)

    @app.post("/api/calibration/clear", dependencies=[Depends(auth)])
    def clear(req: ConfirmRequest) -> dict:
        if not req.confirm:
            raise HTTPException(400, "send {'confirm': true}: this forgets the stored camera-to-axis calibration")
        rt.calibration.clear()
        return rt.calibration.summary()

    @app.post("/api/location", dependencies=[Depends(auth)])
    def location(req: LocationRequest) -> dict:
        try:
            return rt.set_location(req.latitude, req.longitude, req.source, req.unix_ms, req.accuracy_m)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/camera", dependencies=[Depends(auth)])
    def camera(req: CameraRequest) -> dict:
        if req.exposure_s is not None:
            rt.measurer.exposure_s = req.exposure_s
        if req.gain is not None:
            rt.measurer.gain = req.gain
        return {"exposure_s": rt.measurer.exposure_s, "gain": rt.measurer.gain}

    @app.post("/api/sim/coarse", dependencies=[Depends(auth)])
    def sim_coarse(req: SimCoarseRequest) -> dict:
        """Simulator only: re-set the coarse tilt/heading by hand (the user turning the manual knobs)."""
        if rt.sim is None:
            raise HTTPException(404, "not a simulated base")
        if rt.busy():
            raise HTTPException(409, f"busy: {rt.job.name}")
        rt.sim.world.set_coarse(req.error_deg, req.direction_deg)
        return {"true_error_deg": rt.sim.world.true_axis_error_deg()}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app

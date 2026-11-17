"""Runtime: owns the hardware, the sensors, the location/time sources and the one-at-a-time job slot.

The web layer, the CLI and the tests all go through this object.  ``hardware = "sim"`` builds a
virtual base (see :mod:`polaralign.sim`); ``"pi"`` builds the real thing and reports -- rather than
hides -- anything it cannot find, so the UI stays usable on a bench with half the parts connected.
"""
from __future__ import annotations

import io
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .align.engine import AlignEngine, AlignError, AlignReport
from .align.pipeline import Measurer
from .astro import Site
from .calibration import CalibrationStore
from .clock import TimeSource
from .config import Config
from .extract import get_extractor
from .motion.controller import MotionController
from .sensors import GnssMonitor, Icm20948, ImuMonitor, KnockDetector, UbloxDdc
from .solve import get_solver

log = logging.getLogger(__name__)


class Busy(RuntimeError):
    pass


@dataclass
class Job:
    name: str
    started: float
    thread: threading.Thread | None = None
    result: dict | None = None
    error: str | None = None
    done: bool = False


class Runtime:
    def __init__(self, cfg: Config, sim=None) -> None:
        self.cfg = cfg
        self.events: deque[dict] = deque(maxlen=400)
        self._lock = threading.RLock()
        self.job: Job | None = None
        self.last_report: dict | None = None
        self.last_error_sample: dict | None = None
        self.last_solve: dict | None = None
        self.phase = {"phase": "idle", "message": "Ready."}
        self.startup_notes: list[str] = []
        self.phone_site: Site | None = None
        self.manual_site: Site | None = None
        self.imu: ImuMonitor | None = None
        self.gnss: GnssMonitor | None = None
        self.sim = sim
        state = cfg.state_path
        state.mkdir(parents=True, exist_ok=True)
        self.state_dir = state
        self.calibration = CalibrationStore(state / "calibration.json")

        if cfg.hardware == "sim":
            from .sim import build_sim_hardware
            self.sim = sim or build_sim_hardware(cfg, state_file=None)
            self.motion = self.sim.motion
            self.camera = self.sim.camera
            self.time_source = self.sim.time_source
            self.startup_notes.append("SIMULATED hardware: nothing here is real.")
        else:
            self.time_source = TimeSource()
            self.motion = self._build_real_motion(state)
            self.camera = self._build_real_camera()
            self._build_sensors()
        self.extractor = get_extractor(cfg.extractor)
        self.solver = get_solver(cfg.solver, cfg.camera, state)
        self.measurer = Measurer(self.camera, self.extractor, self.solver)
        self.engine = self._make_engine()

    # ------------------------------------------------------------------ construction
    def _build_real_motion(self, state: Path) -> MotionController:
        from .motion.gpio import FakeGPIO, LgpioBackend
        uart = None
        try:
            import serial  # pyserial
            uart = serial.Serial(self.cfg.motion.uart_port, self.cfg.motion.uart_baud, timeout=0.1)
        except Exception as exc:  # noqa: BLE001
            self.startup_notes.append(f"TMC2209 UART unavailable ({exc}); motor current/microsteps not programmed.")
        try:
            gpio = LgpioBackend(self.cfg.motion.gpiochip)
        except Exception as exc:  # noqa: BLE001
            self.startup_notes.append(f"GPIO unavailable ({exc}); motion disabled (using a dummy GPIO).")
            gpio = FakeGPIO()
        mc = MotionController(self.cfg.motion, gpio, uart, state_file=state / "motion.json")
        mc.configure_drivers()
        if mc.driver_error:
            self.startup_notes.append(f"Motor drivers: {mc.driver_error}")
        return mc

    def _build_real_camera(self):
        from .camera import FakeCamera, make_camera
        try:
            return make_camera(self.cfg.camera)
        except Exception as exc:  # noqa: BLE001
            self.startup_notes.append(f"Camera unavailable ({exc}); a blank fake camera is used.")
            return FakeCamera(self.cfg.camera)

    def _build_sensors(self) -> None:
        s = self.cfg.sensors
        bus = None
        if s.imu_enabled or s.gnss_enabled:
            try:
                from smbus2 import SMBus
                bus = SMBus(s.i2c_bus)
            except Exception as exc:  # noqa: BLE001
                self.startup_notes.append(f"I2C unavailable ({exc}); IMU and GNSS disabled.")
        if bus is not None and s.imu_enabled:
            try:
                imu = Icm20948(bus, s.imu_address)
                imu.init()
                self.imu = ImuMonitor(imu, s.imu_rate_hz, s.imu_axis_in_sensor, KnockDetector(s.knock_threshold_g))
                self.imu.start()
            except Exception as exc:  # noqa: BLE001
                self.startup_notes.append(f"IMU not found ({exc}).")
        if bus is not None and s.gnss_enabled:
            self.gnss = GnssMonitor(UbloxDdc(bus, s.gnss_address))
            self.gnss.start()

    def _make_engine(self) -> AlignEngine:
        knock = self.imu.knock.consume if self.imu else None
        return AlignEngine(self.cfg, self.measurer, self.motion, self.calibration, self.time_source, self.site,
                           knock_source=knock, on_event=self._on_event)

    # ------------------------------------------------------------------ location & time
    def site(self) -> Site | None:
        """Best available site: GNSS > phone > manual > config."""
        s = self.cfg.site
        if self.gnss:
            fix = self.gnss.current()
            if fix and fix.latitude_deg is not None and fix.longitude_deg is not None:
                if fix.time_utc and abs((fix.time_utc - self.time_source.now()).total_seconds()) > 2.0:
                    self.time_source.set_utc(fix.time_utc, "GNSS")
                return Site(fix.latitude_deg, fix.longitude_deg, s.pressure_hpa, s.temperature_c)
        if self.phone_site:
            return self.phone_site
        if self.manual_site:
            return self.manual_site
        if s.latitude_deg is not None and s.longitude_deg is not None:
            return Site(s.latitude_deg, s.longitude_deg, s.pressure_hpa, s.temperature_c)
        if self.cfg.hardware == "sim" and self.sim is not None:
            return self.sim.world.site
        return None

    def location_source(self) -> str:
        if self.gnss and self.gnss.current():
            return "GNSS"
        if self.phone_site:
            return "phone"
        if self.manual_site:
            return "manual"
        if self.cfg.site.latitude_deg is not None:
            return "config"
        if self.cfg.hardware == "sim":
            return "simulator"
        return "none"

    def set_location(self, lat: float, lon: float, source: str = "manual", unix_ms: float | None = None,
                     accuracy_m: float | None = None) -> dict:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("latitude/longitude out of range")
        s = self.cfg.site
        site = Site(lat, lon, s.pressure_hpa, s.temperature_c)
        if source == "browser":
            self.phone_site = site
        else:
            self.manual_site = site
        if unix_ms is not None:
            utc = datetime.fromtimestamp(unix_ms / 1000.0, tz=timezone.utc)
            if not (self.gnss and self.gnss.current()):
                self.time_source.set_utc(utc, f"{source} (phone clock)")
        self._on_event({"phase": "site", "message": f"location set from {source}: {lat:.4f}, {lon:.4f}"
                                                    + ("" if accuracy_m is None else f" (+/-{accuracy_m:.0f} m)")})
        return {"latitude": lat, "longitude": lon, "source": source, "time_source": self.time_source.source}

    # ------------------------------------------------------------------ jobs
    def _on_event(self, e: dict) -> None:
        e = {"t": time.time(), **e}
        self.events.append(e)
        if e.get("phase") not in ("site",):
            self.phase = {"phase": e.get("phase", ""), "message": e.get("message", ""), "iteration": e.get("iteration")}
        if "error" in e and isinstance(e["error"], dict):
            self.last_error_sample = e["error"]

    def busy(self) -> bool:
        return self.job is not None and not self.job.done

    def start_job(self, name: str, fn) -> Job:
        with self._lock:
            if self.busy():
                raise Busy(f"busy: {self.job.name}")
            job = Job(name, time.time())
            self.job = job

        def run() -> None:
            try:
                if self.imu:
                    self.imu.inhibit(1e6)
                job.result = fn()
            except Exception as exc:  # noqa: BLE001
                log.exception("job %s failed", name)
                job.error = str(exc)
                self._on_event({"phase": "error", "message": str(exc)})
            finally:
                if self.imu:
                    self.imu.inhibit(0.0)
                    self.imu._inhibit_until = time.monotonic() + 1.0
                job.done = True

        job.thread = threading.Thread(target=run, name=f"job-{name}", daemon=True)
        job.thread.start()
        return job

    def wait(self, timeout: float | None = None) -> None:
        if self.job and self.job.thread:
            self.job.thread.join(timeout)

    def cancel(self) -> None:
        self.engine.cancel()
        self.motion.abort()

    # ------------------------------------------------------------------ operations
    def start_align(self, allow_uncalibrated: bool = False) -> Job:
        self.engine.allow_uncalibrated = allow_uncalibrated

        def run() -> dict:
            rep = self.engine.run()
            self.last_report = rep.to_dict()
            return self.last_report

        return self.start_job("align", run)

    def run_align_blocking(self, allow_uncalibrated: bool = False) -> AlignReport:
        self.engine.allow_uncalibrated = allow_uncalibrated
        rep = self.engine.run()
        self.last_report = rep.to_dict()
        return rep

    def start_home(self, measure_span: bool = False) -> Job:
        def run() -> dict:
            self._on_event({"phase": "home", "message": "homing both axes to their MIN end stops"
                            + (" and measuring the travel to MAX" if measure_span else "")})
            self.motion.home(measure_span=measure_span)
            self._on_event({"phase": "idle", "message": "homed and centred"})
            return self.motion.status()
        return self.start_job("home", run)

    def start_jog(self, axis: str, deg: float) -> Job:
        if axis not in self.motion.axes:
            raise ValueError("axis must be 'az' or 'alt'")
        if abs(deg) > 12.0:
            raise ValueError("jog too large")

        def run() -> dict:
            res = self.motion.move_relative_deg(axis, deg, preload_finish=True)
            self._on_event({"phase": "jog", "message": f"{axis} moved {self.motion.axes[axis].usteps_to_deg(res.done):+.3f} deg"})
            return {"done_usteps": res.done}
        return self.start_job("jog", run)

    def start_measure(self) -> Job:
        """Phase-0 bench solve: capture, extract, solve, and (if calibrated) the pole error."""
        def run() -> dict:
            m = self.measurer.measure()
            info = self._solve_info(m)
            if m.ok and self.calibration.calibrated or (m.ok and self.engine.allow_uncalibrated):
                try:
                    s = self.engine.sample(retries=1, quiet=True)
                    info["error"] = s.to_dict()
                    self.last_error_sample = info["error"]
                except AlignError as exc:
                    info["error_note"] = str(exc)
            self.last_solve = info
            return info
        return self.start_job("measure", run)

    def start_declare_aligned(self) -> Job:
        def run() -> dict:
            self.engine.hemisphere = None
            entry = self.engine.declare_aligned()
            return {"entries": len(self.calibration.data.entries), "a_cam": entry.a_cam}
        return self.start_job("calibrate", run)

    def _solve_info(self, m) -> dict:
        info: dict = {"status": m.status, "n_stars": 0 if m.stars is None else len(m.stars),
                      "timings_ms": {k: round(v, 1) for k, v in m.timings_ms.items()}, "time": m.time.isoformat()}
        if m.stars is not None:
            info["background_adu"] = round(m.stars.background, 1)
            info["noise_adu"] = round(m.stars.noise, 2)
        if m.solution:
            s = m.solution
            info.update({"ra_deg": round(s.ra_deg, 5), "dec_deg": round(s.dec_deg, 5), "roll_deg": round(s.roll_deg, 3),
                         "fov_deg": round(s.fov_deg, 4), "matches": s.n_matches, "rmse_arcsec": round(s.rmse_arcsec, 2),
                         "solver_ms": round(m.outcome.t_ms, 1), "distortion": s.distortion})
        elif m.outcome:
            info["detail"] = m.outcome.detail
        return info

    # ------------------------------------------------------------------ views
    def frame_png(self, overlay: bool = True, max_width: int = 728) -> bytes | None:
        m = self.measurer.last
        if m is None or m.frame is None:
            return None
        from PIL import Image, ImageDraw
        pix = m.frame.pixels.astype(np.float32)
        lo, hi = np.percentile(pix, [1.0, 99.8])
        img = np.clip((pix - lo) / max(hi - lo, 1.0), 0, 1) ** 0.6
        im = Image.fromarray((img * 255).astype(np.uint8)).convert("RGB")
        if overlay and m.stars is not None:
            d = ImageDraw.Draw(im)
            for x, y, fl in zip(m.stars.x, m.stars.y, m.stars.flags):
                col = (80, 255, 120) if fl == 0 else (255, 190, 60)
                d.ellipse([x - 9, y - 9, x + 9, y + 9], outline=col, width=1)
        if im.width > max_width:
            im = im.resize((max_width, int(im.height * max_width / im.width)))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()

    def warnings(self) -> list[str]:
        w = list(self.startup_notes)
        for n, a in self.motion.axes.items():
            if not a.cfg.mechanics_confirmed:
                w.append(f"{n}: arm length and screw pitch are design values (hardware/README.md), not confirmed by measurement")
            if a.fault:
                w.append(f"{n}: {a.fault}")
        if not self.calibration.calibrated:
            w.append("No camera-to-axis calibration: align by hand with the telescope's own routine, then press 'Declare aligned'.")
        if self.site() is None:
            w.append("No location: refraction is not applied and errors are not shown as altitude/azimuth. "
                     "Use GNSS, 'Use phone location' or enter latitude/longitude.")
        elif self.time_source.source.startswith("system"):
            w.append("Clock source is the system clock (unverified); use GNSS or the phone to set the time.")
        return w

    def status(self) -> dict:
        site = self.site()
        job = self.job
        return {
            "hardware": self.cfg.hardware, "time_utc": self.time_source.now().isoformat(timespec="seconds"),
            "time_source": self.time_source.source,
            "job": None if job is None else {"name": job.name, "done": job.done, "error": job.error,
                                              "elapsed_s": round(time.time() - job.started, 1)},
            "phase": self.phase, "error": self.last_error_sample, "report": self.last_report,
            "solve": self.last_solve, "motion": self.motion.status(),
            "calibration": self.calibration.summary(),
            "site": None if site is None else {"latitude_deg": round(site.latitude_deg, 5),
                                               "longitude_deg": round(site.longitude_deg, 5),
                                               "source": self.location_source()},
            "imu": self.imu.status() if self.imu else {"available": False},
            "gnss": self.gnss.status() if self.gnss else {"available": False},
            "camera": {"backend": self.cfg.camera.backend, "exposure_s": self.measurer.exposure_s or self.cfg.camera.exposure_s,
                       "gain": self.measurer.gain or self.cfg.camera.gain, "fov_h_deg": round(self.cfg.camera.fov_h_deg, 2),
                       "sensor": ("colour, Bayer " + str((self.measurer.last.frame.meta.get("bayer") if self.measurer.last and self.measurer.last.frame
                                                          else self.cfg.camera.bayer_pattern)) if self.cfg.camera.colour else "monochrome"),
                       "arcsec_per_px": round(self.cfg.camera.arcsec_per_px, 1)},
            "extractor": self.extractor.name, "solver": self.solver.name,
            "config": {"target_arcmin": self.cfg.align.target_arcmin, "max_iterations": self.cfg.align.max_iterations,
                       "refraction": self.cfg.align.refraction},
            "warnings": self.warnings(),
        }

    def close(self) -> None:
        try:
            self.cancel()
            if self.imu:
                self.imu.stop()
            if self.gnss:
                self.gnss.stop()
            self.motion.close()
            self.camera.close()
        except Exception:  # noqa: BLE001  # pragma: no cover
            log.exception("error while closing")

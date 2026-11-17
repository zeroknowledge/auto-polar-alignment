"""Both axes plus their TMC2209 drivers, with saved position hints."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ..config import MotionConfig
from .gpio import GPIOBackend
from .stepper import MotionFault, MoveResult, StepperAxis
from .tmc2209 import Tmc2209, Tmc2209Error

log = logging.getLogger(__name__)


class MotionController:
    def __init__(self, cfg: MotionConfig, gpio: GPIOBackend, uart=None, state_file: Path | None = None) -> None:
        self.cfg = cfg
        self.gpio = gpio
        self.axes: dict[str, StepperAxis] = {
            "az": StepperAxis(cfg.az, cfg, gpio),
            "alt": StepperAxis(cfg.alt, cfg, gpio),
        }
        self.drivers: dict[str, Tmc2209] = {}
        self.driver_info: dict[str, dict] = {}
        self.driver_error: str | None = None
        self._uart = uart
        self._state_file = state_file
        self._thread_lock = threading.Lock()
        self._load_hint()

    # ------------------------------------------------------------------ drivers
    def configure_drivers(self) -> None:
        """Program current, microsteps and StealthChop over the shared UART.  Safe to call again."""
        if self._uart is None:
            self.driver_error = "no UART: drivers run on their power-on defaults / VREF current"
            log.warning(self.driver_error)
            return
        self.driver_error = None
        for name, axis in self.axes.items():
            drv = Tmc2209(self._uart, axis.cfg.uart_address, self.cfg.rsense_ohm)
            try:
                self.driver_info[name] = drv.configure(self.cfg.microsteps, self.cfg.run_current_a,
                                                       self.cfg.hold_current_a, self.cfg.stealthchop)
                self.drivers[name] = drv
            except Tmc2209Error as exc:
                self.driver_error = f"{name}: {exc}"
                log.error("driver %s: %s", name, exc)

    def driver_status(self) -> dict[str, dict]:
        out = {}
        for name, drv in self.drivers.items():
            try:
                out[name] = drv.status()
            except Tmc2209Error as exc:
                out[name] = {"error": str(exc)}
        return out

    # ------------------------------------------------------------------ motion API (degrees)
    def move_relative_deg(self, axis: str, deg: float, **kw) -> MoveResult:
        a = self.axes[axis]
        res = a.move_relative(a.deg_to_usteps(deg), **kw)
        self._save_hint()
        return res

    def move_relative_usteps(self, axis: str, usteps: int, **kw) -> MoveResult:
        res = self.axes[axis].move_relative(int(usteps), **kw)
        self._save_hint()
        return res

    def move_to_deg(self, axis: str, deg_from_centre: float, **kw) -> MoveResult:
        a = self.axes[axis]
        res = a.move_to(int(round(a.total_usteps / 2 + deg_from_centre * a.usteps_per_deg)), **kw)
        self._save_hint()
        return res

    def home(self, axes: tuple[str, ...] = ("az", "alt"), go_to_centre: bool = True, measure_span: bool = False) -> None:
        """Home axes in parallel threads (they are independent), then centre them."""
        errors: list[Exception] = []

        def run(name: str) -> None:
            try:
                self.axes[name].home(go_to_centre=go_to_centre, measure_span=measure_span)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(n,), daemon=True) for n in axes]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self._save_hint()
        if errors:
            raise errors[0]

    def release_all(self) -> None:
        for a in self.axes.values():
            a.release()

    def abort(self) -> None:
        for a in self.axes.values():
            a.abort()

    def close(self) -> None:
        self.abort()
        self.release_all()
        self.gpio.close()

    def status(self) -> dict:
        return {"axes": {n: a.status() for n, a in self.axes.items()}, "driver_error": self.driver_error,
                "drivers": self.driver_info}

    # ------------------------------------------------------------------ position hints
    def _save_hint(self) -> None:
        if not self._state_file:
            return
        data = {n: {"pos": a.pos, "homed": a.homed, "swapped": a.swapped} for n, a in self.axes.items()}
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(self._state_file)
        except OSError as exc:
            log.warning("could not save motion state: %s", exc)

    def _load_hint(self) -> None:
        """The screws are self-locking, so the plate is where we left it.  Use that as an *assumed*
        position (homed stays False); an end stop re-references the axis the moment it is touched."""
        if not self._state_file or not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text())
            for n, a in self.axes.items():
                if n in data and 0 <= int(data[n]["pos"]) <= a.total_usteps:
                    a.pos = int(data[n]["pos"])
                    a.swapped = bool(data[n].get("swapped", False))
        except (OSError, ValueError, KeyError):
            log.warning("ignoring unreadable motion state file")

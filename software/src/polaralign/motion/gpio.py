"""GPIO access.  ``lgpio`` on hardware (works on Pi Zero 2 W, Pi 4 and Pi 5; pigpio does not run on
the Pi 5), a recording fake for tests and the simulator.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)


class GPIOBackend(Protocol):
    def setup_output(self, pin: int, initial: int = 0) -> None: ...
    def setup_input(self, pin: int, pull_up: bool = True, debounce_us: int = 0) -> None: ...
    def write(self, pin: int, value: int) -> None: ...
    def read(self, pin: int) -> int: ...
    def close(self) -> None: ...


class LgpioBackend:
    """Thin wrapper over the ``lgpio`` module (apt: python3-lgpio).  UNTESTED on real hardware."""

    def __init__(self, chip: int = 0) -> None:
        import lgpio  # type: ignore[import-not-found]
        self._lg = lgpio
        self._h = lgpio.gpiochip_open(chip)
        self._claimed: set[int] = set()

    def setup_output(self, pin: int, initial: int = 0) -> None:
        self._lg.gpio_claim_output(self._h, pin, initial)
        self._claimed.add(pin)

    def setup_input(self, pin: int, pull_up: bool = True, debounce_us: int = 0) -> None:
        flags = self._lg.SET_PULL_UP if pull_up else 0
        self._lg.gpio_claim_input(self._h, pin, flags)
        if debounce_us:
            self._lg.gpio_set_debounce_micros(self._h, pin, int(debounce_us))
        self._claimed.add(pin)

    def write(self, pin: int, value: int) -> None:
        self._lg.gpio_write(self._h, pin, 1 if value else 0)

    def read(self, pin: int) -> int:
        return int(self._lg.gpio_read(self._h, pin))

    def close(self) -> None:
        for pin in list(self._claimed):
            try:
                self._lg.gpio_free(self._h, pin)
            except Exception:  # pragma: no cover
                pass
        self._claimed.clear()
        try:
            self._lg.gpiochip_close(self._h)
        except Exception:  # pragma: no cover
            pass


class FakeGPIO:
    """In-memory GPIO.  Write hooks let the simulator turn STEP edges into mount motion."""

    def __init__(self) -> None:
        self.levels: dict[int, int] = {}
        self.outputs: set[int] = set()
        self.inputs: dict[int, Callable[[], int]] = {}
        self._hooks: dict[int, list[Callable[[int, int], None]]] = {}
        self.writes = 0

    def setup_output(self, pin: int, initial: int = 0) -> None:
        self.outputs.add(pin)
        self.levels[pin] = initial

    def setup_input(self, pin: int, pull_up: bool = True, debounce_us: int = 0) -> None:
        self.inputs.setdefault(pin, lambda: 1 if pull_up else 0)

    def set_input_source(self, pin: int, source: Callable[[], int]) -> None:
        self.inputs[pin] = source

    def on_write(self, pin: int, hook: Callable[[int, int], None]) -> None:
        """hook(old, new) is called on every write that changes the level."""
        self._hooks.setdefault(pin, []).append(hook)

    def write(self, pin: int, value: int) -> None:
        value = 1 if value else 0
        old = self.levels.get(pin, 0)
        self.levels[pin] = value
        self.writes += 1
        if old != value:
            for h in self._hooks.get(pin, ()):
                h(old, value)

    def read(self, pin: int) -> int:
        if pin in self.inputs:
            return int(self.inputs[pin]())
        return self.levels.get(pin, 0)

    def close(self) -> None:
        pass

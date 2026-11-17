"""Clocks.  The alignment loop never calls ``time.sleep`` or ``datetime.now`` directly so the simulator
can run it on virtual time (the sky rotates, the settle delay "passes", nothing waits)."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class SimClock:
    """Virtual UTC time: ``sleep`` advances it instead of waiting."""

    def __init__(self, start: datetime) -> None:
        self._t = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._t

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._t = self._t + timedelta(seconds=seconds)


class TimeSource:
    """UTC time with a correctable offset and a note of where it came from.

    The Pi Zero 2 W has no RTC and, in hotspot mode, no NTP.  Sources, best first: GNSS, the phone's
    browser clock (POSTed to /api/location), the system clock (unverified).
    """

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()
        self.offset_s = 0.0
        self.source = "system clock (unverified)"
        self.set_at: datetime | None = None

    def now(self) -> datetime:
        return self.clock.now() + timedelta(seconds=self.offset_s)

    def set_utc(self, utc: datetime, source: str) -> None:
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=timezone.utc)
        self.offset_s = (utc - self.clock.now()).total_seconds()
        self.source = source
        self.set_at = self.clock.now()

    def sleep(self, seconds: float) -> None:
        self.clock.sleep(seconds)

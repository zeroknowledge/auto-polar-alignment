"""u-blox GNSS over I2C (DDC, address 0x42): time, latitude, longitude.

Protocol notes (u-blox receiver description): registers 0xFD/0xFE hold the number of bytes waiting
(big endian); reading register 0xFF streams them out, reading with nothing waiting returns 0xFF.  By
default the receiver emits NMEA (and UBX) on DDC, so we parse NMEA ($xxRMC, $xxGGA) and skip the rest.
UNTESTED on real hardware; the NMEA parser is unit-tested with checksummed sentences.

Note: the Pi's I2C controller has a clock-stretching bug.  If the GNSS module or the IMU misbehave,
drop the bus speed (``dtparam=i2c_arm_baudrate=100000``).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)


@dataclass
class GnssFix:
    valid: bool = False
    time_utc: datetime | None = None
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    altitude_m: float | None = None
    satellites: int = 0
    hdop: float | None = None
    fix_quality: int = 0
    received_at: float = 0.0           # time.monotonic() of the last RMC


def nmea_checksum_ok(line: str) -> bool:
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, cs = line[1:].partition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(cs[:2], 16)
    except ValueError:
        return False


def _deg(value: str, hemi: str) -> float | None:
    if not value:
        return None
    dot = value.index(".")
    d = int(value[: dot - 2])
    m = float(value[dot - 2:])
    deg = d + m / 60.0
    return -deg if hemi in ("S", "W") else deg


class NmeaParser:
    def __init__(self) -> None:
        self.fix = GnssFix()
        self._buf = ""
        self.sentences = 0
        self.bad_checksums = 0

    def feed(self, data: bytes) -> GnssFix:
        self._buf += data.decode("ascii", errors="ignore")
        while "\n" in self._buf:
            line, _, self._buf = self._buf.partition("\n")
            line = line.strip()
            if line.startswith("$"):
                self.parse_line(line)
        if len(self._buf) > 4096:
            self._buf = self._buf[-512:]
        return self.fix

    def parse_line(self, line: str) -> None:
        if not nmea_checksum_ok(line):
            self.bad_checksums += 1
            return
        f = line[1:line.index("*")].split(",")
        kind = f[0][-3:]
        self.sentences += 1
        if kind == "RMC" and len(f) >= 10:
            active = f[2] == "A"
            lat = _deg(f[3], f[4]) if f[3] else None
            lon = _deg(f[5], f[6]) if f[5] else None
            t = None
            if f[1] and f[9]:
                try:
                    hh, mm, ss = int(f[1][0:2]), int(f[1][2:4]), float(f[1][4:])
                    dd, mo, yy = int(f[9][0:2]), int(f[9][2:4]), 2000 + int(f[9][4:6])
                    t = datetime(yy, mo, dd, hh, mm, int(ss), int((ss % 1) * 1e6), tzinfo=timezone.utc)
                except ValueError:
                    t = None
            self.fix.valid = active and lat is not None and lon is not None and t is not None
            if self.fix.valid:
                self.fix.latitude_deg, self.fix.longitude_deg, self.fix.time_utc = lat, lon, t
                self.fix.received_at = time.monotonic()
        elif kind == "GGA" and len(f) >= 10:
            self.fix.fix_quality = int(f[6] or 0)
            self.fix.satellites = int(f[7] or 0)
            self.fix.hdop = float(f[8]) if f[8] else None
            self.fix.altitude_m = float(f[9]) if f[9] else None


class UbloxDdc:
    """Read the NMEA byte stream from a u-blox receiver on I2C."""

    def __init__(self, bus, address: int = 0x42) -> None:
        self.bus = bus
        self.addr = address

    def read_available(self, limit: int = 512) -> bytes:
        hi, lo = self.bus.read_i2c_block_data(self.addr, 0xFD, 2)
        n = min(((hi << 8) | lo), limit)
        out = bytearray()
        while n > 0:
            chunk = min(n, 32)
            out += bytes(self.bus.read_i2c_block_data(self.addr, 0xFF, chunk))
            n -= chunk
        return bytes(out).replace(b"\xff", b"")


class GnssMonitor:
    def __init__(self, source: UbloxDdc | None, poll_s: float = 0.5, read_fn=None) -> None:
        self.read_fn = read_fn or (source.read_available if source else None)
        self.parser = NmeaParser()
        self.poll_s = poll_s
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.read_fn is None or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="gnss", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data = self.read_fn()
                if data:
                    self.parser.feed(data)
                self.error = None
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
            time.sleep(self.poll_s)

    @property
    def fix(self) -> GnssFix:
        return self.parser.fix

    def current(self, max_age_s: float = 10.0) -> GnssFix | None:
        f = self.parser.fix
        if f.valid and time.monotonic() - f.received_at <= max_age_s:
            return f
        return None

    def status(self) -> dict:
        f = self.parser.fix
        return {"available": self.read_fn is not None, "error": self.error, "valid": self.current() is not None,
                "satellites": f.satellites, "latitude_deg": f.latitude_deg, "longitude_deg": f.longitude_deg,
                "time_utc": f.time_utc.isoformat() if f.time_utc else None, "sentences": self.parser.sentences}

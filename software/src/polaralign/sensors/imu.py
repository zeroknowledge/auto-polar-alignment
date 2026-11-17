"""ICM-20948 IMU over I2C (address 0x68, or 0x69 with AD0 high) with tilt readout and knock detection.

UNTESTED on real hardware.  Register map from the ICM-20948 datasheet (bank-switched via 0x7F); the
unit tests drive this code against a register-level fake of the chip.
The accelerometer is the useful part: the elevation of the polar axis (to set the coarse tilt to the
latitude).  The magnetometer (AK09916 behind the bypass) is exposed but is only a rough guide: stepper
motors, steel tripods and local anomalies make magnetic heading good to degrees at best.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

REG_BANK_SEL = 0x7F
# bank 0
WHO_AM_I, USER_CTRL, PWR_MGMT_1, PWR_MGMT_2, INT_PIN_CFG = 0x00, 0x03, 0x06, 0x07, 0x0F
ACCEL_XOUT_H, GYRO_XOUT_H, TEMP_OUT_H = 0x2D, 0x33, 0x39
# bank 2
GYRO_SMPLRT_DIV, GYRO_CONFIG_1, ACCEL_SMPLRT_DIV_2, ACCEL_CONFIG = 0x00, 0x01, 0x11, 0x14
WHO_AM_I_VALUE = 0xEA
AK_ADDR = 0x0C


class I2CLike(Protocol):
    def read_i2c_block_data(self, addr: int, reg: int, length: int) -> list[int]: ...
    def write_byte_data(self, addr: int, reg: int, value: int) -> None: ...


@dataclass
class ImuSample:
    t: float
    accel_g: np.ndarray          # (3,) in g, sensor frame; at rest = +1 g along "up"
    gyro_dps: np.ndarray         # (3,)
    temp_c: float


class Icm20948:
    ACCEL_LSB_PER_G = 8192.0     # +/-4 g
    GYRO_LSB_PER_DPS = 65.5      # +/-500 dps

    def __init__(self, bus: I2CLike, address: int = 0x68) -> None:
        self.bus = bus
        self.addr = address
        self._bank = -1

    def _bank_select(self, bank: int) -> None:
        if bank != self._bank:
            self.bus.write_byte_data(self.addr, REG_BANK_SEL, bank << 4)
            self._bank = bank

    def _w(self, bank: int, reg: int, val: int) -> None:
        self._bank_select(bank)
        self.bus.write_byte_data(self.addr, reg, val)

    def _r(self, bank: int, reg: int, n: int = 1) -> list[int]:
        self._bank_select(bank)
        return list(self.bus.read_i2c_block_data(self.addr, reg, n))

    def init(self) -> None:
        who = self._r(0, WHO_AM_I)[0]
        if who != WHO_AM_I_VALUE:
            raise OSError(f"ICM-20948 not found at 0x{self.addr:02x} (WHO_AM_I = 0x{who:02x}, expected 0xEA)")
        self._w(0, PWR_MGMT_1, 0x80)               # device reset
        time.sleep(0.1)
        self._bank = -1
        self._w(0, PWR_MGMT_1, 0x01)               # wake, auto clock
        self._w(0, PWR_MGMT_2, 0x00)               # accel + gyro on
        self._w(2, GYRO_SMPLRT_DIV, 10)
        self._w(2, GYRO_CONFIG_1, (3 << 3) | (1 << 1) | 1)            # +/-500 dps, DLPF on
        self._w(2, ACCEL_SMPLRT_DIV_2, 10)
        self._w(2, ACCEL_CONFIG, (3 << 3) | (1 << 1) | 1)             # +/-4 g, DLPF on
        self._bank_select(0)

    @staticmethod
    def _s16(hi: int, lo: int) -> int:
        v = (hi << 8) | lo
        return v - 65536 if v & 0x8000 else v

    def read(self) -> ImuSample:
        raw = self._r(0, ACCEL_XOUT_H, 6) + self._r(0, GYRO_XOUT_H, 6) + self._r(0, TEMP_OUT_H, 2)
        a = np.array([self._s16(raw[0], raw[1]), self._s16(raw[2], raw[3]), self._s16(raw[4], raw[5])]) / self.ACCEL_LSB_PER_G
        g = np.array([self._s16(raw[6], raw[7]), self._s16(raw[8], raw[9]), self._s16(raw[10], raw[11])]) / self.GYRO_LSB_PER_DPS
        temp = (self._s16(raw[12], raw[13]) - 21.0) / 333.87 + 21.0
        return ImuSample(time.monotonic(), a, g, temp)

    def read_mag_ut(self) -> np.ndarray | None:
        """AK09916 magnetometer through the I2C bypass (rough heading only)."""
        try:
            self._w(0, INT_PIN_CFG, 0x02)
            self.bus.write_byte_data(AK_ADDR, 0x31, 0x08)               # CNTL2: continuous mode 4 (100 Hz)
            d = list(self.bus.read_i2c_block_data(AK_ADDR, 0x10, 9))    # ST1 .. ST2
        except OSError:
            return None
        if not d[0] & 1:
            return None
        v = [d[1] | (d[2] << 8), d[3] | (d[4] << 8), d[5] | (d[6] << 8)]
        return np.array([x - 65536 if x & 0x8000 else x for x in v], dtype=float) * 0.15


def axis_elevation_deg(accel_g: np.ndarray, axis_in_sensor: np.ndarray) -> float:
    """Elevation of the polar axis above the horizon from a static accelerometer reading."""
    up = accel_g / np.linalg.norm(accel_g)
    ax = np.asarray(axis_in_sensor, dtype=float)
    ax = ax / np.linalg.norm(ax)
    return math.degrees(math.asin(max(-1.0, min(1.0, float(up @ ax)))))


class KnockDetector:
    """Flags bumps: deviation of the acceleration from a slow baseline, or a burst of rotation."""

    def __init__(self, threshold_g: float = 0.06, gyro_dps: float = 8.0, baseline_tau_s: float = 1.5,
                 refractory_s: float = 0.4) -> None:
        self.threshold_g = threshold_g
        self.gyro_dps = gyro_dps
        self.tau = baseline_tau_s
        self.refractory = refractory_s
        self._base: np.ndarray | None = None
        self._last_t: float | None = None
        self._last_knock = -1e9
        self._pending = False
        self.count = 0
        self.last_magnitude_g = 0.0
        self.last_knock_time: float | None = None

    def update(self, t: float, accel_g: np.ndarray, gyro_dps: np.ndarray) -> bool:
        if self._base is None:
            self._base = accel_g.copy()
            self._last_t = t
            return False
        dt = max(1e-3, t - (self._last_t or t))
        self._last_t = t
        dev = float(np.linalg.norm(accel_g - self._base))
        rot = float(np.linalg.norm(gyro_dps))
        hit = dev > self.threshold_g or rot > self.gyro_dps
        if hit and t - self._last_knock > self.refractory:
            self._last_knock = t
            self._pending = True
            self.count += 1
            self.last_magnitude_g = dev
            self.last_knock_time = t
        # the baseline follows slow changes (re-seating, thermal drift) but not impulses
        alpha = 1.0 - math.exp(-dt / self.tau)
        if not hit:
            self._base = self._base + alpha * (accel_g - self._base)
        return hit

    def consume(self) -> bool:
        """True once if a knock happened since the last call."""
        p, self._pending = self._pending, False
        return p


class ImuMonitor:
    """Background polling thread: latest sample, filtered tilt, knock events."""

    def __init__(self, imu: Icm20948 | None, rate_hz: float = 50.0, axis_in_sensor=(0.0, 0.0, 1.0),
                 knock: KnockDetector | None = None, sample_fn=None) -> None:
        self.imu = imu
        self.sample_fn = sample_fn or (imu.read if imu else None)
        self.period = 1.0 / rate_hz
        self.axis = np.asarray(axis_in_sensor, dtype=float)
        self.knock = knock or KnockDetector()
        self.latest: ImuSample | None = None
        self.error: str | None = None
        self._tilt_buf: deque[np.ndarray] = deque(maxlen=int(rate_hz * 1.0))
        self._inhibit_until = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def inhibit(self, seconds: float) -> None:
        """Ignore knocks while our own motors are moving (and briefly after)."""
        self._inhibit_until = max(self._inhibit_until, time.monotonic() + seconds)

    def start(self) -> None:
        if self.sample_fn is None or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="imu", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                s = self.sample_fn()
                self.latest = s
                self._tilt_buf.append(s.accel_g)
                if time.monotonic() < self._inhibit_until:
                    self.knock._base = s.accel_g.copy()      # re-seed so the motor's own vibration is not a knock
                else:
                    self.knock.update(s.t, s.accel_g, s.gyro_dps)
                self.error = None
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
            time.sleep(self.period)

    def tilt_deg(self) -> float | None:
        if not self._tilt_buf:
            return None
        return axis_elevation_deg(np.mean(self._tilt_buf, axis=0), self.axis)

    def status(self) -> dict:
        s = self.latest
        return {"available": self.sample_fn is not None, "error": self.error,
                "axis_elevation_deg": None if self.tilt_deg() is None else round(self.tilt_deg(), 2),
                "temp_c": None if s is None else round(s.temp_c, 1), "knocks": self.knock.count,
                "last_knock_g": round(self.knock.last_magnitude_g, 3)}


class FakeI2CIcm20948:
    """Register-level fake of the ICM-20948 for the tests (bank switching, big-endian data)."""

    def __init__(self) -> None:
        self.bank = 0
        self.regs: dict[tuple[int, int], int] = {(0, WHO_AM_I): WHO_AM_I_VALUE}
        self.accel_g = np.array([0.0, 0.0, 1.0])
        self.gyro_dps = np.zeros(3)
        self.writes: list[tuple[int, int, int]] = []

    def write_byte_data(self, addr: int, reg: int, value: int) -> None:
        if reg == REG_BANK_SEL:
            self.bank = value >> 4
            return
        self.writes.append((self.bank, reg, value))
        self.regs[(self.bank, reg)] = value

    def read_i2c_block_data(self, addr: int, reg: int, length: int) -> list[int]:
        out: list[int] = []
        for r in range(reg, reg + length):
            out.append(self._byte(r))
        return out

    def _byte(self, reg: int) -> int:
        if self.bank == 0 and ACCEL_XOUT_H <= reg < ACCEL_XOUT_H + 6:
            return self._split(self.accel_g * Icm20948.ACCEL_LSB_PER_G, reg - ACCEL_XOUT_H)
        if self.bank == 0 and GYRO_XOUT_H <= reg < GYRO_XOUT_H + 6:
            return self._split(self.gyro_dps * Icm20948.GYRO_LSB_PER_DPS, reg - GYRO_XOUT_H)
        if self.bank == 0 and reg in (TEMP_OUT_H, TEMP_OUT_H + 1):
            raw = int(round((24.0 - 21.0) * 333.87 + 21.0)) & 0xFFFF
            return (raw >> 8) if reg == TEMP_OUT_H else raw & 0xFF
        return self.regs.get((self.bank, reg), 0)

    @staticmethod
    def _split(vals: np.ndarray, idx: int) -> int:
        v = int(round(float(vals[idx // 2]))) & 0xFFFF
        return (v >> 8) if idx % 2 == 0 else v & 0xFF

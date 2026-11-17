import math
import time
from datetime import datetime, timezone

import numpy as np
import pytest

from polaralign.sensors import (FakeI2CIcm20948, Icm20948, ImuMonitor, KnockDetector, NmeaParser, UbloxDdc,
                                axis_elevation_deg, nmea_checksum_ok)
from polaralign.sensors.gnss import GnssMonitor


def nmea(body: str) -> bytes:
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return f"${body}*{cs:02X}\r\n".encode()


# ---------------------------------------------------------------- IMU
def test_icm20948_init_and_read_through_register_fake():
    bus = FakeI2CIcm20948()
    bus.accel_g = np.array([0.1, -0.2, 0.97])
    bus.gyro_dps = np.array([1.0, -2.0, 3.0])
    imu = Icm20948(bus, 0x68)
    imu.init()
    # bank 2 configuration writes happened, with bank selects in between
    banks = {w[0] for w in bus.writes}
    assert banks == {0, 2}
    s = imu.read()
    assert s.accel_g == pytest.approx([0.1, -0.2, 0.97], abs=1e-3)
    assert s.gyro_dps == pytest.approx([1.0, -2.0, 3.0], abs=0.02)
    assert s.temp_c == pytest.approx(24.0, abs=0.1)


def test_icm20948_wrong_device_is_reported():
    bus = FakeI2CIcm20948()
    bus.regs[(0, 0x00)] = 0x12
    with pytest.raises(OSError, match="not found"):
        Icm20948(bus).init()


@pytest.mark.parametrize("elev", [0.0, 25.0, 65.0, 90.0])
def test_axis_elevation_from_gravity(elev):
    # sensor z is the polar axis; tilt the unit so z is `elev` above horizontal
    a = np.array([math.cos(math.radians(elev)), 0.0, math.sin(math.radians(elev))])
    assert axis_elevation_deg(a, (0, 0, 1)) == pytest.approx(elev, abs=1e-6)
    assert axis_elevation_deg(a * 1.03, (0, 0, 1)) == pytest.approx(elev, abs=1e-6)   # magnitude irrelevant


def test_knock_detector_flags_impulse_not_slow_drift():
    k = KnockDetector(threshold_g=0.06)
    t = 0.0
    g = np.array([0.0, 0.0, 1.0])
    for _ in range(100):                       # at rest
        t += 0.02
        assert not k.update(t, g, np.zeros(3))
    for i in range(300):                       # slow thermal tilt of 0.03 g over 6 s: not a knock
        t += 0.02
        assert not k.update(t, g + np.array([0.03 * i / 300, 0, 0]), np.zeros(3))
    assert not k.consume() and k.count == 0
    t += 0.02
    assert k.update(t, g + np.array([0.03, 0.15, 0.0]), np.zeros(3))                    # a bump
    assert k.consume() and not k.consume() and k.count == 1
    t += 0.1
    k.update(t, g + np.array([0.03, 0.2, 0]), np.zeros(3))                              # inside refractory: same knock
    assert k.count == 1
    t += 1.0
    assert k.update(t, g, np.array([30.0, 0, 0])) and k.count == 2                      # rotation burst also counts


def test_imu_monitor_polls_and_reports_tilt_and_knocks():
    bus = FakeI2CIcm20948()
    imu = Icm20948(bus)
    imu.init()
    bus.accel_g = np.array([math.cos(math.radians(30)), 0.0, math.sin(math.radians(30))])
    mon = ImuMonitor(imu, rate_hz=200.0, knock=KnockDetector(0.05))
    mon.start()
    time.sleep(0.4)
    assert mon.tilt_deg() == pytest.approx(30.0, abs=0.1)
    bus.accel_g = bus.accel_g + np.array([0.0, 0.3, 0.0])
    time.sleep(0.2)
    bus.accel_g = bus.accel_g - np.array([0.0, 0.3, 0.0])
    time.sleep(0.2)
    mon.stop()
    assert mon.knock.consume()
    assert mon.status()["knocks"] >= 1


def test_imu_monitor_inhibit_masks_own_vibration():
    bus = FakeI2CIcm20948()
    imu = Icm20948(bus)
    imu.init()
    mon = ImuMonitor(imu, rate_hz=200.0, knock=KnockDetector(0.05))
    mon.inhibit(10.0)
    mon.start()
    time.sleep(0.1)
    bus.accel_g = np.array([0.0, 0.4, 1.0])
    time.sleep(0.2)
    mon.stop()
    assert mon.knock.count == 0


# ---------------------------------------------------------------- GNSS
def test_nmea_checksum():
    s = nmea("GNRMC,123519.00,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W,A").decode().strip()
    assert nmea_checksum_ok(s)
    assert not nmea_checksum_ok(s.replace("4807", "4808"))
    assert not nmea_checksum_ok("$GNRMC,no,checksum")


def test_parser_reads_time_and_position_both_hemispheres():
    p = NmeaParser()
    data = (nmea("GNGGA,092750.00,5321.6802,N,00630.3372,W,1,08,1.03,61.7,M,55.2,M,,")
            + nmea("GNRMC,092750.00,A,5321.6802,N,00630.3372,W,0.02,31.66,171126,,,A"))
    fix = p.feed(data)
    assert fix.valid and fix.satellites == 8 and fix.fix_quality == 1 and fix.altitude_m == pytest.approx(61.7)
    assert fix.latitude_deg == pytest.approx(53.361337, abs=1e-5) and fix.longitude_deg == pytest.approx(-6.505620, abs=1e-5)
    assert fix.time_utc == datetime(2026, 11, 17, 9, 27, 50, tzinfo=timezone.utc)
    south = NmeaParser().feed(nmea("GPRMC,010203.50,A,3351.0000,S,15112.0000,E,0,0,010126,,,A"))
    assert south.latitude_deg == pytest.approx(-33.85) and south.longitude_deg == pytest.approx(151.2)
    assert south.time_utc.microsecond == 500000


def test_parser_ignores_void_fix_bad_checksum_and_split_reads():
    p = NmeaParser()
    p.feed(nmea("GNRMC,092750.00,V,,,,,,,171126,,,N"))
    assert not p.fix.valid
    good = nmea("GNRMC,092750.00,A,5321.6802,N,00630.3372,W,0.02,31.66,171126,,,A")
    p.feed(good[:25])
    assert not p.fix.valid
    p.feed(good[25:])
    assert p.fix.valid
    bad = NmeaParser()
    bad.feed(good.replace(b"5321", b"5322"))
    assert not bad.fix.valid and bad.bad_checksums == 1


def test_ublox_ddc_reader_follows_the_documented_register_protocol():
    stream = nmea("GNRMC,092750.00,A,5321.6802,N,00630.3372,W,0.02,31.66,171126,,,A")

    class Bus:
        def __init__(self):
            self.buf = bytearray(stream)
            self.reads = []

        def read_i2c_block_data(self, addr, reg, n):
            self.reads.append((addr, reg, n))
            if reg == 0xFD:
                return [len(self.buf) >> 8, len(self.buf) & 0xFF]
            out = bytes(self.buf[:n])
            del self.buf[:n]
            return list(out) + [0xFF] * (n - len(out))

    bus = Bus()
    ddc = UbloxDdc(bus, 0x42)
    mon = GnssMonitor(ddc)
    data = ddc.read_available()
    assert data == stream and max(n for _, r, n in bus.reads if r == 0xFF) <= 32
    mon.parser.feed(data)
    assert mon.current() is not None and mon.status()["valid"]

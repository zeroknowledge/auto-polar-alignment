import pytest

from polaralign.motion import tmc2209 as t


def test_crc_known_vectors():
    assert t.crc8(bytes([0x05, 0x00, 0x00])) == 0x48          # classic "05 00 00 48" GCONF read of address 0
    assert t.read_request(0, t.IOIN) == bytes([0x05, 0x00, 0x06, 0x6F])


def test_write_datagram_layout():
    d = t.write_datagram(1, t.CHOPCONF, 0x10000053)
    assert len(d) == 8 and d[0] == 0x05 and d[1] == 1 and d[2] == (t.CHOPCONF | 0x80)
    assert d[3:7] == bytes.fromhex("10000053") and d[7] == t.crc8(d[:7])


def test_current_conversion_matches_datasheet_formula():
    cs, vsense = t.current_to_cs(0.5, 0.11)
    assert vsense == 1 and cs == 15
    assert t.cs_to_current(cs, vsense, 0.11) == pytest.approx(0.5, abs=0.03)
    for amps in (0.4, 0.45, 0.5, 0.55, 0.6):                   # the doc's 0.4-0.6 A range
        cs, vs = t.current_to_cs(amps)
        assert t.cs_to_current(cs, vs) == pytest.approx(amps, abs=0.03)
    assert t.current_to_cs(0.0) == (0, 1)


def test_configure_programs_both_drivers_over_the_shared_wire():
    bus = t.FakeTmcBus((0, 1))
    for addr in (0, 1):
        drv = t.Tmc2209(bus, addr)
        info = drv.configure(microsteps=16, run_current_a=0.5, stealthchop=True)
        assert info["irun_a"] == pytest.approx(0.5, abs=0.03)
    for addr in (0, 1):
        regs = bus.regs[addr]
        assert regs[t.GCONF] & (1 << 6) and regs[t.GCONF] & (1 << 7)          # pdn_disable, mstep_reg_select
        assert not regs[t.GCONF] & (1 << 2)                                    # StealthChop (spreadCycle off)
        assert (regs[t.CHOPCONF] >> 24) & 0xF == 4                             # MRES: 16 microsteps
        assert regs[t.CHOPCONF] & (1 << 28)                                    # interpolation to 256
        assert (regs[t.IHOLD_IRUN] >> 8) & 0x1F == 15 and regs[t.IHOLD_IRUN] & 0x1F == 0
    # the two drivers are separate: a write to address 1 must not touch address 0
    before = dict(bus.regs[0])
    t.Tmc2209(bus, 1).write_reg(t.TPOWERDOWN, 99)
    assert bus.regs[0] == before and bus.regs[1][t.TPOWERDOWN] == 99


def test_spreadcycle_option():
    bus = t.FakeTmcBus((0,))
    t.Tmc2209(bus, 0).configure(stealthchop=False)
    assert bus.regs[0][t.GCONF] & (1 << 2)


def test_missing_echo_is_diagnosed():
    bus = t.FakeTmcBus((0,), echo=False)           # RX not wired / wrong UART
    with pytest.raises(t.Tmc2209Error, match="echo"):
        t.Tmc2209(bus, 0).write_reg(t.GCONF, 0)


def test_bad_crc_is_rejected_by_chip_and_retried_on_read():
    bus = t.FakeTmcBus((0,))
    bad = bytearray(t.write_datagram(0, t.GCONF, 5))
    bad[7] ^= 0xFF
    bus.write(bytes(bad))
    assert bus.rejected == 1 and bus.regs[0][t.GCONF] != 5

    class Flaky(t.FakeTmcBus):
        def __init__(self):
            super().__init__((0,))
            self.first = True

        def read(self, size):
            out = bytearray(super().read(size))
            if self.first and len(out) >= 12:
                self.first = False
                out[-1] ^= 0x55            # corrupt the first reply's CRC
            return bytes(out)
    assert (t.Tmc2209(Flaky(), 0).read_reg(t.IOIN) >> 24) == t.CHIP_VERSION


def test_wrong_chip_version_detected():
    bus = t.FakeTmcBus((0,))
    bus.regs[0][t.IOIN] = 0x11 << 24              # e.g. a TMC2208
    with pytest.raises(t.Tmc2209Error, match="version"):
        t.Tmc2209(bus, 0).check_present()


def test_write_verified_detects_ignored_writes():
    class Deaf(t.FakeTmcBus):
        def write(self, data):
            if len(data) == 8:
                self._rx += data           # echo only: the chip "ignored" it
                return 8
            return super().write(data)
    with pytest.raises(t.Tmc2209Error, match="not acknowledged"):
        t.Tmc2209(Deaf((0,)), 0).write_verified(t.GCONF, 0x1C0)

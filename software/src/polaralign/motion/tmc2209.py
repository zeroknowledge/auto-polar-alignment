"""TMC2209 single-wire UART driver (datasheet rev 1.09, section 5).

Two drivers share one wire (PDN_UART) on the carrier PCB: GPIO14 (TX) drives the bus through 1 kOhm,
GPIO15 (RX) listens to it directly, so **every byte we send is echoed back** and has to be discarded
before the reply of a read request.  MS1/MS2 strapping gives the slave addresses: AZ = 0, ALT = 1.

Hardware prerequisites on the Pi (see README): ``dtoverlay=disable-bt`` so the PL011 UART lives on
GPIO14/15 as ``/dev/ttyAMA0``, and the serial login console switched off.

Not tested against real silicon: the CRC, datagram layout and the fake bus in the tests follow the
datasheet, which is not the same thing as a TMC2209 answering.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Protocol

log = logging.getLogger(__name__)

# registers
GCONF, GSTAT, IFCNT, SLAVECONF, IOIN = 0x00, 0x01, 0x02, 0x03, 0x06
IHOLD_IRUN, TPOWERDOWN, TSTEP, TPWMTHRS = 0x10, 0x11, 0x12, 0x13
VACTUAL = 0x22
MSCNT, MSCURACT, CHOPCONF, DRV_STATUS, PWMCONF = 0x6A, 0x6B, 0x6C, 0x6F, 0x70

CHIP_VERSION = 0x21
_SYNC = 0x05
_MRES = {256: 0, 128: 1, 64: 2, 32: 3, 16: 4, 8: 5, 4: 6, 2: 7, 1: 8}


class SerialLike(Protocol):
    def write(self, data: bytes) -> int | None: ...
    def read(self, size: int) -> bytes: ...
    def reset_input_buffer(self) -> None: ...


class Tmc2209Error(RuntimeError):
    pass


def crc8(data: bytes) -> int:
    """Trinamic CRC-8 (polynomial 0x07, LSB first) over all bytes of the datagram but the last."""
    crc = 0
    for byte in data:
        cur = byte
        for _ in range(8):
            if (crc >> 7) ^ (cur & 1):
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
            cur >>= 1
    return crc


def write_datagram(address: int, reg: int, value: int) -> bytes:
    body = bytes([_SYNC, address & 0xFF, (reg & 0x7F) | 0x80]) + (value & 0xFFFFFFFF).to_bytes(4, "big")
    return body + bytes([crc8(body)])


def read_request(address: int, reg: int) -> bytes:
    body = bytes([_SYNC, address & 0xFF, reg & 0x7F])
    return body + bytes([crc8(body)])


def current_to_cs(irms_a: float, rsense_ohm: float = 0.11) -> tuple[int, int]:
    """RMS motor current -> (CS 0..31, vsense).  I_rms = (CS+1)/32 * Vfs/(Rsense+0.02) / sqrt(2)."""
    if irms_a <= 0:
        return 0, 1
    def cs_for(vfs: float) -> float:
        return irms_a * math.sqrt(2.0) * 32.0 * (rsense_ohm + 0.02) / vfs - 1.0
    cs = cs_for(0.325)
    vsense = 0
    if cs < 16:                      # coarse at this range: use the 0.18 V full-scale (as TMCStepper does)
        cs = cs_for(0.18)
        vsense = 1
    return int(max(0, min(31, round(cs)))), vsense


def cs_to_current(cs: int, vsense: int, rsense_ohm: float = 0.11) -> float:
    vfs = 0.18 if vsense else 0.325
    return (cs + 1) / 32.0 * vfs / (rsense_ohm + 0.02) / math.sqrt(2.0)


class Tmc2209:
    def __init__(self, serial: SerialLike, address: int, rsense_ohm: float = 0.11,
                 retries: int = 3) -> None:
        self.ser = serial
        self.address = address
        self.rsense = rsense_ohm
        self.retries = retries

    # ----- raw register access -------------------------------------------------------------
    def write_reg(self, reg: int, value: int) -> None:
        dgram = write_datagram(self.address, reg, value)
        self.ser.reset_input_buffer()
        self.ser.write(dgram)
        echo = self.ser.read(len(dgram))           # discard our own bytes
        if len(echo) != len(dgram):
            raise Tmc2209Error(f"UART echo missing (got {len(echo)} of {len(dgram)} bytes): is /dev/ttyAMA0 wired and Bluetooth disabled?")

    def read_reg(self, reg: int) -> int:
        req = read_request(self.address, reg)
        last: Exception | None = None
        for _ in range(self.retries):
            self.ser.reset_input_buffer()
            self.ser.write(req)
            raw = self.ser.read(len(req) + 8)
            if len(raw) == 8 and raw[0] == _SYNC and raw[1] == 0xFF:
                raise Tmc2209Error("UART echo missing (the reply arrived without our own bytes in front of it): "
                                   "RX not wired to the shared bus, or wrong UART")
            if len(raw) < len(req) + 8:
                last = Tmc2209Error(f"no/short answer ({len(raw)} bytes): 12 V on? address strapping? PDN_UART pin wiring?")
                continue
            reply = raw[len(req):]
            if reply[0] != _SYNC or reply[2] != (reg & 0x7F) or crc8(reply[:7]) != reply[7]:
                last = Tmc2209Error(f"bad reply {reply.hex()}")
                continue
            return int.from_bytes(reply[3:7], "big")
        raise Tmc2209Error(f"read of register 0x{reg:02x} failed: {last}")

    def write_verified(self, reg: int, value: int) -> None:
        """Write and confirm via the IFCNT write counter (increments on every accepted write)."""
        for _ in range(self.retries):
            before = self.read_reg(IFCNT)
            self.write_reg(reg, value)
            if (self.read_reg(IFCNT) - before) & 0xFF == 1:
                return
        raise Tmc2209Error(f"write to register 0x{reg:02x} was not acknowledged (IFCNT)")

    # ----- high level ----------------------------------------------------------------------
    def check_present(self) -> int:
        ver = (self.read_reg(IOIN) >> 24) & 0xFF
        if ver != CHIP_VERSION:
            raise Tmc2209Error(f"driver {self.address}: IOIN version 0x{ver:02x}, expected 0x{CHIP_VERSION:02x}")
        return ver

    def configure(self, microsteps: int = 16, run_current_a: float = 0.5, hold_current_a: float = 0.0,
                  stealthchop: bool = True, power_down_ticks: int = 20) -> dict[str, float]:
        if microsteps not in _MRES:
            raise ValueError(f"microsteps must be one of {sorted(_MRES)}")
        self.check_present()
        self.write_verified(GSTAT, 0x07)                       # clear reset / error flags
        gconf = (1 << 6) | (1 << 7) | (1 << 8)                 # pdn_disable, mstep_reg_select, multistep_filt
        if not stealthchop:
            gconf |= 1 << 2                                    # en_spreadCycle
        self.write_verified(GCONF, gconf)                      # I_scale_analog = 0: current from IRUN, not VREF
        cs_run, vsense = current_to_cs(run_current_a, self.rsense)
        cs_hold = 0 if hold_current_a <= 0 else min(cs_run, current_to_cs(hold_current_a, self.rsense)[0])
        self.write_verified(IHOLD_IRUN, (6 << 16) | (cs_run << 8) | cs_hold)
        self.write_verified(TPOWERDOWN, power_down_ticks)
        chop = 3 | (5 << 4) | (0 << 7) | (2 << 15) | (vsense << 17) | (_MRES[microsteps] << 24) | (1 << 28)
        self.write_verified(CHOPCONF, chop)                    # TOFF=3 TBL=2 HSTRT=5 HEND=0, interpolation on
        got = {"irun_a": cs_to_current(cs_run, vsense, self.rsense), "vsense": float(vsense), "cs": float(cs_run)}
        log.info("TMC2209 addr %d configured: %d microsteps, IRUN %.3f A (CS=%d vsense=%d)",
                 self.address, microsteps, got["irun_a"], cs_run, vsense)
        return got

    def set_standstill_current(self, cs: int = 0) -> None:
        """Drop IHOLD (and thereby the holding current) to ``cs`` without touching IRUN."""
        cur = self.read_reg(IHOLD_IRUN)
        self.write_reg(IHOLD_IRUN, (cur & ~0x1F) | (cs & 0x1F))

    def status(self) -> dict[str, int]:
        drv = self.read_reg(DRV_STATUS)
        return {"drv_status": drv, "overtemp_warning": (drv >> 26) & 1, "overtemp_shutdown": (drv >> 25) & 1,
                "short_a": (drv >> 27) & 3, "open_load": (drv >> 6) & 3, "stst": (drv >> 31) & 1,
                "gstat": self.read_reg(GSTAT), "ifcnt": self.read_reg(IFCNT)}


class FakeTmcBus:
    """A serial object that behaves like one or more TMC2209s on a single wire with echo.

    It validates CRCs, counts accepted writes in IFCNT and answers reads, so the driver code is
    exercised end to end in tests.  Pass ``echo=False`` to simulate a missing RX connection.
    """

    def __init__(self, addresses: tuple[int, ...] = (0, 1), echo: bool = True) -> None:
        self.regs: dict[int, dict[int, int]] = {
            a: {GCONF: 0x141, GSTAT: 0x1, IFCNT: 0, IOIN: (CHIP_VERSION << 24) | 0x40 | (a << 2),
                IHOLD_IRUN: 0x00010808, TPOWERDOWN: 20, CHOPCONF: 0x10000053, DRV_STATUS: 0x80000000, PWMCONF: 0xC10D0024}
            for a in addresses}
        self._rx = bytearray()
        self.echo = echo
        self.rejected = 0
        self.log: list[tuple[int, int, int]] = []     # (address, reg, value) of accepted writes

    def reset_input_buffer(self) -> None:
        self._rx.clear()

    def write(self, data: bytes) -> int:
        if self.echo:
            self._rx += data
        if len(data) == 8:
            if data[0] != _SYNC or crc8(data[:7]) != data[7] or not data[2] & 0x80:
                self.rejected += 1
                return len(data)
            addr, reg, val = data[1], data[2] & 0x7F, int.from_bytes(data[3:7], "big")
            if addr in self.regs:
                if reg == GSTAT:
                    self.regs[addr][GSTAT] &= ~val
                else:
                    self.regs[addr][reg] = val
                self.regs[addr][IFCNT] = (self.regs[addr][IFCNT] + 1) & 0xFF
                self.log.append((addr, reg, val))
        elif len(data) == 4:
            if data[0] != _SYNC or crc8(data[:3]) != data[3]:
                self.rejected += 1
                return len(data)
            addr, reg = data[1], data[2] & 0x7F
            if addr in self.regs:
                body = bytes([_SYNC, 0xFF, reg]) + self.regs[addr].get(reg, 0).to_bytes(4, "big")
                self._rx += body + bytes([crc8(body)])
        return len(data)

    def read(self, size: int) -> bytes:
        out = bytes(self._rx[:size])
        del self._rx[:size]
        return out

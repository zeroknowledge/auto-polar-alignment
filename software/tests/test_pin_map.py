"""The software's pin defaults must equal the carrier PCB netlist (read-only cross-check).

The netlist maps Pi header *pin numbers* to nets; BCM GPIO numbers come from the netlist's own
``pi_gpio_map`` and are re-derived here from the standard Raspberry Pi 40-pin header table so that an
error in either is caught.
"""
import json
from pathlib import Path

import pytest

from polaralign.config import Config

NETLIST = Path(__file__).resolve().parents[2] / "hardware" / "pcb" / "netlist.json"

# physical header pin -> BCM GPIO (standard Raspberry Pi 40-pin header; GPIO-only pins)
PI_HEADER_BCM = {3: 2, 5: 3, 7: 4, 8: 14, 10: 15, 11: 17, 12: 18, 13: 27, 15: 22, 16: 23, 18: 24, 19: 10, 21: 9,
                 22: 25, 23: 11, 24: 8, 26: 7, 27: 0, 28: 1, 29: 5, 31: 6, 32: 12, 33: 13, 35: 19, 36: 16, 37: 26,
                 38: 20, 40: 21}

pytestmark = pytest.mark.skipif(not NETLIST.exists(), reason="hardware/pcb/netlist.json not present")


@pytest.fixture(scope="module")
def net():
    data = json.loads(NETLIST.read_text())
    parts = {p["ref"]: p for p in data["parts"]}
    j1 = parts["J1"]["pins"]                             # header pin -> net
    by_net = {n: int(pin) for pin, n in j1.items() if n}
    return data, parts, by_net


def test_netlist_gpio_numbers_match_standard_header(net):
    data, parts, _ = net
    for pin, label in data["pi_gpio_map"].items():
        bcm = int(label.split()[0].removeprefix("GPIO"))
        assert PI_HEADER_BCM[int(pin)] == bcm, f"header pin {pin}: netlist says {label}, standard table says GPIO{PI_HEADER_BCM[int(pin)]}"


def test_config_defaults_match_netlist(net):
    _, _, by_net = net
    bcm = {n: PI_HEADER_BCM[pin] for n, pin in by_net.items() if pin in PI_HEADER_BCM}
    m = Config().motion
    assert (m.az.step_pin, m.az.dir_pin, m.az.enable_pin) == (bcm["STEP_AZ"], bcm["DIR_AZ"], bcm["EN_AZ"])
    assert (m.alt.step_pin, m.alt.dir_pin, m.alt.enable_pin) == (bcm["STEP_ALT"], bcm["DIR_ALT"], bcm["EN_ALT"])
    assert (m.az.endstop_min_pin, m.az.endstop_max_pin) == (bcm["ES_AZ_MIN"], bcm["ES_AZ_MAX"])
    assert (m.alt.endstop_min_pin, m.alt.endstop_max_pin) == (bcm["ES_ALT_MIN"], bcm["ES_ALT_MAX"])
    assert bcm["SPARE"] == 26


def test_i2c_and_uart_pins(net):
    _, _, by_net = net
    assert PI_HEADER_BCM[by_net["SDA"]] == 2 and PI_HEADER_BCM[by_net["SCL"]] == 3          # I2C bus 1
    assert PI_HEADER_BCM[by_net["UART_TX_RAW"]] == 14 and PI_HEADER_BCM[by_net["UART_BUS"]] == 15   # /dev/ttyAMA0


def test_uart_addresses_follow_ms1_ms2_strapping(net):
    """TMC2209 slave address = MS1 + 2*MS2; U1 = azimuth, U2 = altitude."""
    _, parts, _ = net
    def address(ref):
        pins = parts[ref]["pins"]
        level = lambda n: 1 if n == "3V3" else 0
        return level(pins["A2"]) + 2 * level(pins["A3"])
    cfg = Config().motion
    assert address("U1") == cfg.az.uart_address == 0
    assert address("U2") == cfg.alt.uart_address == 1


def test_single_wire_uart_topology(net):
    """GPIO14 -> R1 -> bus; GPIO15 on the bus; both drivers' PDN_UART on the bus (echo must be discarded)."""
    data, _, _ = net
    bus = {tuple(p) for p in data["nets"]["UART_BUS"]}
    assert ("U1", "A4") in bus and ("U2", "A4") in bus and ("J1", "10") in bus
    assert ("R1", "2") in bus
    assert ("R1", "1") in {tuple(p) for p in data["nets"]["UART_TX_RAW"]}


def test_enable_pins_have_pullups_so_drivers_are_off_at_boot(net):
    data, parts, _ = net
    for en, res in (("EN_AZ", "R2"), ("EN_ALT", "R3")):
        assert res in {p[0] for p in data["nets"][en]}, f"{en} has no pull-up resistor"
        assert parts[res]["value"].startswith("10")
    assert Config().motion.az.enable_pin and True


def test_endstop_inputs_have_series_resistor_and_filter_cap(net):
    data, _, _ = net
    for es in ("ES_AZ_MIN", "ES_AZ_MAX", "ES_ALT_MIN", "ES_ALT_MAX"):
        refs = {p[0] for p in data["nets"][es]}
        assert any(r.startswith("R") for r in refs) and any(r.startswith("C") for r in refs), es

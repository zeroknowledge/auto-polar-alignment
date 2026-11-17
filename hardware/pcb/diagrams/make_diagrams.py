#!/usr/bin/env python3
"""Draw the carrier-PCB schematic sheets and the system wiring diagram from ../netlist.json.

Outputs (SVG, PDF, PNG each) in this folder:
  carrier_schematic_1_power        12 V input, protection, 5 V path, LED, test points
  carrier_schematic_2_pi_drivers   Pi header, TMC2209 sockets, motor connectors, UART/enable networks
  carrier_schematic_3_io           end-stop inputs, I2C sensor headers, spare GPIO
  system_wiring                    whole-system block wiring (power bank to telescope base)

Every label comes from netlist.json. Before drawing, the netlist is checked against the pin assignments in ../SPEC.md
(re-typed here independently), so a drawing cannot hide a netlist error. Requires: schemdraw, matplotlib.
Run:  python make_diagrams.py
"""
import json
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import schemdraw
import schemdraw.elements as elm
from schemdraw import Drawing

HERE = pathlib.Path(__file__).resolve().parent
NL = json.loads((HERE.parent / "netlist.json").read_text())
PARTS = {p["ref"]: p for p in NL["parts"]}
FORMATS = ("svg", "pdf", "png")

# ----------------------------------------------------------------------------- independent check against SPEC.md
SPEC_J1 = {1: "3V3", 17: "3V3", 2: "5V_PI", 4: "5V_PI", 3: "SDA", 5: "SCL", 8: "UART_TX_RAW", 10: "UART_BUS",
           11: "STEP_AZ", 13: "DIR_AZ", 15: "EN_AZ", 16: "STEP_ALT", 18: "DIR_ALT", 22: "EN_ALT",
           29: "ES_AZ_MIN", 31: "ES_AZ_MAX", 33: "ES_ALT_MIN", 35: "ES_ALT_MAX", 37: "SPARE"}
SPEC_J1.update({p: "GND" for p in (6, 9, 14, 20, 25, 30, 34, 39)})
SPEC_NC_J1 = {7, 12, 19, 21, 23, 24, 26, 27, 28, 32, 36, 38, 40}
SPEC_U = {  # module pin -> (U1 net, U2 net)
    "A1": ("EN_AZ", "EN_ALT"), "A2": ("GND", "3V3"), "A3": ("GND", "GND"), "A4": ("UART_BUS", "UART_BUS"),
    "A5": (None, None), "A6": ("GND", "GND"), "A7": ("STEP_AZ", "STEP_ALT"), "A8": ("DIR_AZ", "DIR_ALT"),
    "B1": ("+12V", "+12V"), "B2": ("GND", "GND"),
    "B3": ("AZ_COIL_A2", "ALT_COIL_A2"), "B4": ("AZ_COIL_A1", "ALT_COIL_A1"),
    "B5": ("AZ_COIL_B1", "ALT_COIL_B1"), "B6": ("AZ_COIL_B2", "ALT_COIL_B2"),
    "B7": ("3V3", "3V3"), "B8": ("GND", "GND")}


def check_against_spec():
    errs = []
    j1 = PARTS["J1"]["pins"]
    for pin, net in SPEC_J1.items():
        if j1.get(str(pin)) != net:
            errs.append(f"J1 pin {pin}: netlist {j1.get(str(pin))!r}, spec {net!r}")
    for pin in SPEC_NC_J1:
        if j1.get(str(pin)) is not None:
            errs.append(f"J1 pin {pin} should be NC, netlist has {j1.get(str(pin))!r}")
    for pin, (n1, n2) in SPEC_U.items():
        if PARTS["U1"]["pins"].get(pin) != n1:
            errs.append(f"U1 {pin}: netlist {PARTS['U1']['pins'].get(pin)!r}, spec {n1!r}")
        if PARTS["U2"]["pins"].get(pin) != n2:
            errs.append(f"U2 {pin}: netlist {PARTS['U2']['pins'].get(pin)!r}, spec {n2!r}")
    # motor connector pin order = module pins B3..B6
    for ref, u in (("J5", "AZ"), ("J6", "ALT")):
        want = [f"{u}_COIL_A2", f"{u}_COIL_A1", f"{u}_COIL_B1", f"{u}_COIL_B2"]
        got = [PARTS[ref]["pins"][str(i)] for i in range(1, 5)]
        if got != want:
            errs.append(f"{ref} pin order {got}, spec {want}")
    # end-stop chain and I2C header order
    for j, r, c, sig in (("J7", "R4", "C4", "ES_AZ_MIN"), ("J8", "R5", "C5", "ES_AZ_MAX"),
                         ("J9", "R6", "C6", "ES_ALT_MIN"), ("J10", "R7", "C7", "ES_ALT_MAX")):
        if PARTS[j]["pins"] != {"1": sig + "_IN", "2": "GND"}:
            errs.append(f"{j} pins {PARTS[j]['pins']}")
        if PARTS[r]["pins"] != {"1": sig + "_IN", "2": sig}:
            errs.append(f"{r} pins {PARTS[r]['pins']}")
        if PARTS[c]["pins"] != {"1": sig, "2": "GND"}:
            errs.append(f"{c} pins {PARTS[c]['pins']}")
    for j in ("J11", "J12"):
        if PARTS[j]["pins"] != {"1": "GND", "2": "3V3", "3": "5V_F", "4": "SDA", "5": "SCL"}:
            errs.append(f"{j} pins {PARTS[j]['pins']}")
    return errs


GPIO_NAMES = {int(k): v for k, v in NL["pi_gpio_map"].items()}
PI_NAMES = {1: "3V3", 2: "5V", 3: "GPIO2 SDA1", 4: "5V", 5: "GPIO3 SCL1", 6: "GND", 7: "GPIO4", 8: "GPIO14 TXD",
            9: "GND", 10: "GPIO15 RXD", 11: "GPIO17", 12: "GPIO18", 13: "GPIO27", 14: "GND", 15: "GPIO22",
            16: "GPIO23", 17: "3V3", 18: "GPIO24", 19: "GPIO10", 20: "GND", 21: "GPIO9", 22: "GPIO25",
            23: "GPIO11", 24: "GPIO8", 25: "GND", 26: "GPIO7", 27: "ID_SD", 28: "ID_SC", 29: "GPIO5", 30: "GND",
            31: "GPIO6", 32: "GPIO12", 33: "GPIO13", 34: "GND", 35: "GPIO19", 36: "GPIO16", 37: "GPIO26",
            38: "GPIO20", 39: "GND", 40: "GPIO21"}


SHORT = {"F1": "PTC 2 A hold", "F2": "PTC 2 A hold"}


def val(ref):
    return SHORT.get(ref, PARTS[ref]["value"])


def save(d, stem):
    for ext in FORMATS:
        d.save(str(HERE / f"{stem}.{ext}"))
    print("wrote", stem, FORMATS)


# ----- drawing helpers: every label is placed explicitly, nothing depends on the library's label placement -----
def T(d, x, y, s, ha="right", fs=8, color="black"):
    """Text next to point (x, y). ha='right' puts the text to the right of the point, 'left' to its left."""
    # theta(0): after a vertical element the drawing frame is rotated, which would put 'right' on the wrong side
    d += elm.Label().at((x, y)).theta(0).label(s, loc=ha, fontsize=fs, color=color)


def node(d, x, y, s=None, ha="right", open_=False, fs=8):
    d += elm.Dot(open=open_, radius=0.06).at((x, y))
    if s:
        T(d, x + (0.25 if ha == "right" else -0.25), y, s, ha=ha, fs=fs)


def gnd(d, x, y):
    d += elm.Ground().at((x, y))


def vert(d, cls, x, y_top, length, label=None, side="right", fs=8, up=False):
    """Vertical two-terminal part from y_top down by `length`; `up=True` flips polarity (start at the bottom)."""
    if up:
        d += cls().at((x, y_top - length)).up(length)
    else:
        d += cls().at((x, y_top)).down(length)
    if label:
        T(d, x + (0.45 if side == "right" else -0.45), y_top - length / 2, label, ha=side, fs=fs)


def horiz(d, cls, x, y, length, label=None, fs=8):
    d += cls().at((x, y)).right(length)
    if label:
        T(d, x + length / 2, y + 0.55, label, ha="top", fs=fs)


def wire(d, x0, y0, x1, y1):
    d += elm.Line().at((x0, y0)).to((x1, y1))


def ic(left, right, title, pitch=0.55, width=4.6, fs=7):
    """Ic with the first item on TOP. left/right: lists of (id, inside_label). Anchors are named L_<id> / R_<id>."""
    pins = [elm.IcPin(name=lab, pin=str(i), side="left", anchorname=f"L_{i}", lblsize=fs, pinlblsize=6)
            for i, lab in reversed(left)]
    pins += [elm.IcPin(name=lab, pin=str(i), side="right", anchorname=f"R_{i}", lblsize=fs, pinlblsize=6)
             for i, lab in reversed(right)]
    h = max(len(left), len(right)) * pitch + 0.5
    blk = elm.Ic(pins=pins, size=(width, h), pinspacing=pitch, edgepadH=0.3, label=title, lblloc="top", lblsize=8)
    blk._h = h   # remembered so place() can put the top-left corner where asked (Ic's origin is its bottom-left)
    return blk


def place(d, blk, x, y):
    """Place the block with its top-left corner at (x, y)."""
    blk.at((x, y - blk._h)).theta(0)   # theta(0): do not inherit the rotated frame left by a vertical element
    d += blk
    return blk


def stub(d, p, direction, net, length=0.9, nc=False):
    ln = elm.Line().at(p)
    ln = ln.left(length) if direction == "left" else ln.right(length)
    d += ln
    end = ln.end
    if nc:
        T(d, end[0] + (0.1 if direction == "right" else -0.1), end[1], "NC", ha=direction, fs=7, color="#888888")
        return
    d += elm.Dot(radius=0.045).at(end)
    T(d, end[0] + (0.15 if direction == "right" else -0.15), end[1], net, ha=direction, fs=8)


# ----------------------------------------------------------------------------- sheet 1: power
def sheet_power():
    d = Drawing()
    d.config(unit=2.4, fontsize=9)
    T(d, 0, 4.0, "APA-CARRIER rev A  -  sheet 1/3: power input, protection, 5 V path", fs=13)
    y = 0.0
    node(d, 0, y, "J2.1  12V_RAW\n(from PD trigger)", ha="left", open_=True)
    wire(d, 0, y, 1.0, y)
    horiz(d, elm.Fuse, 1.0, y, 2.4, f"F1  {val('F1')}")
    wire(d, 3.4, y, 4.2, y)
    node(d, 4.2, y)
    T(d, 4.2, y - 0.6, "12V_FUSED", ha="top", fs=8)
    horiz(d, elm.Schottky, 4.2, y, 2.0, f"D1  {val('D1')}")
    T(d, 6.9, y - 0.6, "reverse-polarity", ha="top", fs=7)
    wire(d, 6.2, y, 7.2, y)
    rail_x0, rail_x1 = 7.2, 21.6
    wire(d, rail_x0, y, rail_x1, y)
    node(d, rail_x0, y)
    T(d, 14.4, y + 0.55, "+12V rail", ha="top", fs=9)
    # branches: TVS, C1, C2, C3 (parts hang from the rail to ground)
    for ref, x in (("D2", 8.6), ("C1", 11.0), ("C2", 13.6), ("C3", 16.2)):
        node(d, x, y)
        wire(d, x, y, x, y - 0.5)
        if ref == "D2":
            vert(d, elm.Zener, x, y - 0.5, 2.2, f"D2  {val(ref)}\nTVS", up=True)
        else:
            vert(d, elm.Capacitor, x, y - 0.5, 2.2, f"{ref}  {val(ref)}\n(+ to rail)")
        wire(d, x, y - 2.7, x, y - 3.1)
        gnd(d, x, y - 3.1)
    node(d, 18.4, y)
    wire(d, 18.4, y, 18.4, y - 0.9)
    node(d, 18.4, y - 0.9, "TP1  +12V", open_=True)
    node(d, 20.2, y)
    wire(d, 20.2, y, 20.2, y - 0.9)
    node(d, 20.2, y - 0.9, "U1.B1 / U2.B1  VM\n(driver motor supply)", open_=True)
    wire(d, rail_x1, y, rail_x1 + 0.8, y)
    node(d, rail_x1 + 0.8, y, "J3.1  +12V\n(to buck module VIN)", open_=True)
    node(d, 0, -1.2, "J2.2  GND", ha="left", open_=True)
    wire(d, 0, -1.2, 0, -1.8)
    gnd(d, 0, -1.8)

    # 5 V path
    y5 = -8.0
    node(d, 0, y5, "J4.1  5V_BUCK\n(from buck module VOUT)", ha="left", open_=True)
    wire(d, 0, y5, 1.0, y5)
    horiz(d, elm.Fuse, 1.0, y5, 2.4, f"F2  {val('F2')}")
    wire(d, 3.4, y5, 4.2, y5)
    node(d, 4.2, y5)
    T(d, 4.45, y5 + 0.55, "5V_F", ha="right", fs=9)
    wire(d, 4.2, y5, 4.2, y5 - 0.6)
    vert(d, elm.Resistor, 4.2, y5 - 0.6, 2.0, f"R8  {val('R8')}")
    vert(d, elm.LED, 4.2, y5 - 2.6, 2.0, "LED1 red\n(5 V present)")
    wire(d, 4.2, y5 - 4.6, 4.2, y5 - 5.0)
    gnd(d, 4.2, y5 - 5.0)
    wire(d, 4.2, y5, 11.0, y5)
    node(d, 7.0, y5)
    wire(d, 7.0, y5, 7.0, y5 - 0.9)
    node(d, 7.0, y5 - 0.9, "TP2  5V_F", open_=True)
    node(d, 9.2, y5)
    wire(d, 9.2, y5, 9.2, y5 - 0.9)
    node(d, 9.2, y5 - 0.9, "J11.3 / J12.3\n5V_F (sensor 5 V)", open_=True)
    horiz(d, elm.Switch, 11.0, y5, 2.4, "JP1 jumper")
    wire(d, 13.4, y5, 14.4, y5)
    node(d, 14.4, y5, "5V_PI to Pi header pins 2 and 4\nREMOVE JP1 when powering the Pi over USB", open_=True)
    node(d, 0, y5 - 1.2, "J4.2  GND", ha="left", open_=True)
    wire(d, 0, y5 - 1.2, 0, y5 - 1.8)
    gnd(d, 0, y5 - 1.8)

    T(d, 7.0, -12.8,
      "Notes\n"
      "- F1 (PTC) sits before D1 so it protects the harness; the TVS sits after D1 so reverse polarity does not forward-bias it.\n"
      "- D2 1.5KE18A clamps near 25 V, below the TMC2209's 29 V absolute maximum. A PD trigger set to 20 V by mistake blows F1.\n"
      "- The buck module and the PD trigger are off-board: J3 feeds the buck input, J4 returns its 5 V output.\n"
      "- All grounds are one net (GND); both copper layers carry a GND pour.", fs=8)
    return d


# ----------------------------------------------------------------------------- sheet 2: Pi + drivers
def sheet_pi_drivers():
    d = Drawing()
    d.config(unit=2.4, fontsize=9)
    T(d, 0, 2.0, "APA-CARRIER rev A  -  sheet 2/3: Pi header, TMC2209 sockets, motor connectors", fs=13)
    J1 = PARTS["J1"]["pins"]
    left = [(n, PI_NAMES[n]) for n in range(1, 40, 2)]
    right = [(n, PI_NAMES[n]) for n in range(2, 41, 2)]
    j1 = place(d, ic(left, right, "J1  Pi 40-pin socket (bottom side)", pitch=0.52, width=4.2), 6.0, 0.0)
    for n, _ in left:
        net = J1.get(str(n))
        stub(d, getattr(j1, f"L_{n}"), "left", net, 1.8, nc=net is None)
    for n, _ in right:
        net = J1.get(str(n))
        stub(d, getattr(j1, f"R_{n}"), "right", net, 1.8, nc=net is None)

    lnames = ["EN", "MS1", "MS2", "PDN_UART", "PDN_UART_ALT", "CLK", "STEP", "DIR"]
    rnames = ["VM", "GND", "COIL_A2", "COIL_A1", "COIL_B1", "COIL_B2", "VIO", "GND"]
    for ref, y0, title in (("U1", 0.0, "TMC2209  AZIMUTH  (UART address 0)"), ("U2", -6.8, "TMC2209  ALTITUDE  (UART address 1)")):
        pins = PARTS[ref]["pins"]
        blk = place(d, ic([(f"A{i+1}", f"A{i+1}  {nm}") for i, nm in enumerate(lnames)],
                          [(f"B{i+1}", f"{nm}  B{i+1}") for i, nm in enumerate(rnames)],
                          f"{ref}  {title}", pitch=0.52, width=4.8), 24.0, y0)
        for i in range(8):
            a, b = f"A{i+1}", f"B{i+1}"
            stub(d, getattr(blk, f"L_{a}"), "left", pins.get(a), 1.8, nc=pins.get(a) is None)
            stub(d, getattr(blk, f"R_{b}"), "right", pins.get(b), 1.8)
    for ref, y0, ttl in (("J5", -0.3, "MOTOR AZ"), ("J6", -7.1, "MOTOR ALT")):
        pins = PARTS[ref]["pins"]
        blk = place(d, ic([(i, "") for i in range(1, 5)], [], f"{ref}  JST-XH 4P  {ttl}", pitch=0.52, width=1.0), 38.5, y0)
        for i in range(1, 5):
            stub(d, getattr(blk, f"L_{i}"), "left", pins[str(i)], 1.8)

    # discrete networks, below the header
    ox, oy = 0.0, -14.4
    T(d, ox, oy + 0.6, "UART, enable and decoupling networks", fs=10)
    node(d, ox, oy - 0.6, "UART_TX_RAW", ha="left", open_=True)
    wire(d, ox, oy - 0.6, ox + 1.0, oy - 0.6)
    horiz(d, elm.Resistor, ox + 1.0, oy - 0.6, 2.4, f"R1  {val('R1')}  (series on TX)")
    wire(d, ox + 3.4, oy - 0.6, ox + 4.4, oy - 0.6)
    node(d, ox + 4.4, oy - 0.6, "UART_BUS", open_=True)
    T(d, ox + 9.0, oy - 0.6,
      "UART_BUS = Pi RXD (pin 10) directly, plus both PDN_UART pins (single-wire UART:\nTX through 1 k, RX straight on the bus).", fs=8)
    for k, (ref, net) in enumerate((("R2", "EN_AZ"), ("R3", "EN_ALT"))):
        yy = oy - 2.4 - k * 1.8
        node(d, ox, yy, "3V3", ha="left", open_=True)
        wire(d, ox, yy, ox + 1.0, yy)
        horiz(d, elm.Resistor, ox + 1.0, yy, 2.4, f"{ref}  {val(ref)}")
        wire(d, ox + 3.4, yy, ox + 4.4, yy)
        node(d, ox + 4.4, yy, net, open_=True)
    T(d, ox + 9.0, oy - 3.3,
      "EN pull-ups keep both drivers disabled until the Pi drives EN low\n(Pi GPIOs default to pull-down at boot, which would enable them).", fs=8)
    for k, ref in enumerate(("C8", "C9")):
        xx = ox + 24.0 + k * 5.0
        node(d, xx, oy - 0.3, "3V3", open_=True, ha="right")
        wire(d, xx, oy - 0.3, xx, oy - 0.8)
        vert(d, elm.Capacitor, xx, oy - 0.8, 1.6, f"{ref}  {val(ref)}")
        wire(d, xx, oy - 2.4, xx, oy - 2.8)
        gnd(d, xx, oy - 2.8)
    T(d, ox + 24.0, oy - 4.8, "One 100 nF decoupling capacitor near each driver socket", fs=8)
    return d


# ----------------------------------------------------------------------------- sheet 3: I/O
def sheet_io():
    d = Drawing()
    d.config(unit=2.4, fontsize=9)
    T(d, 0, 1.6, "APA-CARRIER rev A  -  sheet 3/3: end stops, I2C sensor headers, spare GPIO", fs=13)
    chans = [("J7", "R4", "C4", "ES_AZ_MIN", "J1 pin 29 (GPIO5)"), ("J8", "R5", "C5", "ES_AZ_MAX", "J1 pin 31 (GPIO6)"),
             ("J9", "R6", "C6", "ES_ALT_MIN", "J1 pin 33 (GPIO13)"), ("J10", "R7", "C7", "ES_ALT_MAX", "J1 pin 35 (GPIO19)")]
    for k, (j, r, c, sig, gp) in enumerate(chans):
        y = -1.0 - k * 4.6
        node(d, 0, y, f"{j}.1  {sig}_IN", ha="left", open_=True)
        wire(d, 0, y, 1.0, y)
        horiz(d, elm.Resistor, 1.0, y, 2.4, f"{r}  {val(r)}")
        wire(d, 3.4, y, 6.0, y)
        node(d, 4.4, y)
        wire(d, 4.4, y, 4.4, y - 0.5)
        vert(d, elm.Capacitor, 4.4, y - 0.5, 1.6, f"{c}  {val(c)}")
        wire(d, 4.4, y - 2.1, 4.4, y - 2.4)
        gnd(d, 4.4, y - 2.4)
        node(d, 6.0, y, f"{sig}  ->  {gp}", open_=True)
        T(d, 0, y - 1.5, f"{j}.2 = GND", ha="right", fs=7, color="#555555")
    T(d, 0, -19.6,
      "RC filter per channel: 1 k series + 100 nF to GND (about 100 us), for ESD and contact bounce.\n"
      "The Pi's internal pull-ups are enabled in software; closing the switch pulls the line to GND.", fs=8)

    for k, ref in enumerate(("J11", "J12")):
        pins = PARTS[ref]["pins"]
        ttl = "IMU  ICM-20948" if ref == "J11" else "GNSS  u-blox (I2C DDC)"
        blk = place(d, ic([(i, "") for i in range(1, 6)], [], f"{ref}  1x5  {ttl}", pitch=0.52, width=1.0), 22.0 + k * 11.0, -1.4)
        for i in range(1, 6):
            stub(d, getattr(blk, f"L_{i}"), "left", pins[str(i)], 1.8)
    T(d, 18.0, -5.4,
      "SDA and SCL go to J1 pins 3 and 5. The Pi Zero already has 1.8 k pull-ups\non those pins, so the carrier adds none. Header pin order: GND, 3V3, 5V_F, SDA, SCL.", fs=8)
    node(d, 18.0, -8.4, "TP5  SPARE  =  J1 pin 37 (GPIO26)", open_=True)
    T(d, 18.0, -10.2, "Test points: TP1 +12V, TP2 5V_F, TP3 3V3, TP4 GND, TP5 SPARE.\nMounting: four M3 holes H1-H4.", fs=8)
    return d


# ----------------------------------------------------------------------------- system wiring diagram
def system_wiring():
    fig, ax = plt.subplots(figsize=(15, 9.8))
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 98)
    ax.axis("off")
    ax.set_title("Auto polar aligner: system wiring", fontsize=15, loc="left")

    def box(x, y, w, h, text, fc="#eef2f7", ec="#33475b", fs=9, bold=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2", fc=fc, ec=ec, lw=1.4))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal")

    def line(pts, color, label=None, lw=2.0, ls="-", lpos=None, fs=7.5):
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color=color, lw=lw, ls=ls, solid_capstyle="round", zorder=1)
        if label:
            lx, ly = lpos if lpos else ((xs[0] + xs[-1]) / 2, (ys[0] + ys[-1]) / 2 + 1.0)
            ax.text(lx, ly, label, fontsize=fs, color=color, ha="center", va="bottom", zorder=3,
                    bbox=dict(fc="white", ec="none", pad=0.6, alpha=0.9))

    RED, ORG, BLU, GRN, PUR, BLK = "#c0392b", "#e67e22", "#2471a3", "#1e8449", "#7d3c98", "#222222"
    ax.text(1, 96.2, "red / orange: power (12 V / 5 V)    black: motor wires, 40-pin header    blue: Wi-Fi    green: sensors and end stops    purple: camera",
            fontsize=8, color="#444444")
    # off-board power chain
    box(2, 80, 24, 12, "USB-C power bank\n(must offer 12 V PD)", fc="#fdf2e9")
    box(36, 80, 24, 12, "USB-C PD trigger\nboard, set to 12 V", fc="#fdf2e9")
    box(70, 80, 24, 12, "Buck converter\n12 V -> 5 V, 3 A", fc="#fdf2e9")
    line([(26, 86), (36, 86)], RED, "USB-C", lpos=(31, 87))
    # carrier PCB
    box(30, 22, 84, 50, "", fc="#f4faf4", ec="#1e8449")
    ax.text(58, 68.6, "APA-CARRIER PCB  (85 x 60 mm)", fontsize=10, fontweight="bold", color="#1e8449")
    box(33, 56, 20, 8, "J2  12V IN\nF1 PTC, D1 Schottky, TVS\nbulk capacitors", fs=7.5)
    box(33, 46, 20, 7, "J3  12V OUT  (to buck VIN)", fs=7.5)
    box(33, 36, 20, 7, "J4  5V IN  (from buck)\nF2 PTC, JP1, LED", fs=7.5)
    box(33, 26, 20, 7, "J11 / J12  I2C headers\n(IMU, GNSS)", fs=7.5)
    box(58, 56, 20, 10, "J1  40-pin socket\nSTEP/DIR/EN, UART,\nend stops, I2C, 3V3, 5V", fc="#fff9e6", fs=7.5)
    box(84, 56, 26, 11, "U1  TMC2209  AZIMUTH\nUART address 0", fc="#e8f1fb", fs=8)
    box(84, 40, 26, 11, "U2  TMC2209  ALTITUDE\nUART address 1", fc="#e8f1fb", fs=8)
    box(84, 25, 26, 9, "J7-J10  end-stop inputs\n(1 k + 100 nF filter each)", fs=7.5)
    # Raspberry Pi below
    box(40, 3, 62, 13, "Raspberry Pi Zero 2 W\nplugged under the carrier\nWi-Fi hotspot, web UI, plate solver, motion control", fc="#fdebd0", fs=8.5, bold=True)
    line([(68, 16), (68, 56)], BLK, "40-pin header", lw=3.0, lpos=(68, 24))
    # power wires (kept outside the boxes; crossings are plain crossings, not junctions)
    line([(48, 80), (48, 64)], RED, "12 V", lpos=(49.8, 70))
    line([(33, 49.5), (29.5, 49.5), (29.5, 75), (76, 75), (76, 80)], ORG, "12 V to buck VIN (J3)", ls="--", lpos=(60, 75.6))
    line([(88, 80), (88, 77.8), (27.5, 77.8), (27.5, 39.5), (33, 39.5)], ORG, "5 V from buck VOUT (J4)", ls="--", lpos=(72, 78.4))
    # motors
    box(122, 56, 26, 11, "NEMA 17  AZIMUTH\n+ M6 lead screw", fc="#fbeee6", fs=8)
    box(122, 40, 26, 11, "NEMA 17  ALTITUDE\n+ M6 lead screw", fc="#fbeee6", fs=8)
    line([(110, 61.5), (122, 61.5)], BLK, "J5  4 wires", lpos=(116, 62.2))
    line([(110, 45.5), (122, 45.5)], BLK, "J6  4 wires", lpos=(116, 46.2))
    # end stops
    box(122, 22, 26, 12, "4x micro limit switch\nAZ min/max, ALT min/max\n(JST-XH 2-pin)", fc="#fbeee6", fs=7.5)
    line([(110, 29.5), (122, 29.5)], GRN, "4 signals + GND", lpos=(116, 30.6))
    # IMU, GNSS
    box(2, 26, 22, 9, "IMU  ICM-20948\n(I2C)", fc="#eafaf1", fs=8)
    box(2, 13, 22, 9, "GNSS  u-blox\n(I2C DDC)", fc="#eafaf1", fs=8)
    line([(24, 30.5), (33, 30.5)], GRN, "I2C: SDA, SCL, 3V3, 5V, GND", lpos=(20, 36.0))
    line([(24, 17.5), (31, 17.5), (31, 27.5), (33, 27.5)], GRN, None)
    # phone, camera, telescope
    box(2, 1.5, 26, 9, "Phone (browser)\nAlign button, jog,\nlive error readout", fc="#fdfefe", fs=8)
    line([(28, 6), (40, 6)], BLU, "Wi-Fi", ls="--", lpos=(34, 7))
    box(112, 4, 36, 12, "Camera IMX296 mono\n16 mm lens, 0-40 deg tilt mount\nCSI ribbon (22-pin to 15-pin)", fc="#f5eef8", fs=7.5)
    line([(102, 9.5), (112, 9.5)], PUR, "CSI", lpos=(107, 10.3))
    box(106, 76, 42, 16, "Telescope (Seestar S50)\nmounts on the 3/8-16 stud of the top plate\n(mechanical only; no wire to the base)", fc="#ebf5fb", fs=8)
    for ext in FORMATS:
        fig.savefig(HERE / f"system_wiring.{ext}", bbox_inches="tight", dpi=150)
    plt.close(fig)
    print("wrote system_wiring", FORMATS)


def main():
    errs = check_against_spec()
    if errs:
        print("NETLIST DOES NOT MATCH SPEC:")
        for e in errs:
            print("  -", e)
        sys.exit(1)
    print(f"netlist matches SPEC.md: {len(SPEC_J1)} J1 pins, {len(SPEC_NC_J1)} NC pins, 32 module pins, "
          "motor/end-stop/I2C wiring all checked")
    schemdraw.use("matplotlib")
    save(sheet_power(), "carrier_schematic_1_power")
    save(sheet_pi_drivers(), "carrier_schematic_2_pi_drivers")
    save(sheet_io(), "carrier_schematic_3_io")
    system_wiring()


if __name__ == "__main__":
    main()

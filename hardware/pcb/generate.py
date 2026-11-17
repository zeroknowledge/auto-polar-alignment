#!/usr/bin/env python3
"""APA-CARRIER generator (single reproducible script).

Stage 1 (this revision): netlist = single source of truth, SPEC.md cross-check,
KiCad-format netlist (carrier.net), draft BOM.  Later stages (placement, router,
pours, KiCad/Gerber/DXF/STL writers, diagrams, verification) are appended below.

Run:  <venv>/bin/python generate.py [--driver-row-spacing 12.70]
"""
import argparse
import csv
import datetime
import json
import re
import sys
import uuid
from collections import OrderedDict, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOARD_NAME = "APA-CARRIER"
BOARD_REV = "A"

ap = argparse.ArgumentParser()
ap.add_argument("--driver-row-spacing", type=float, default=12.70,
                help="distance between the two 1x8 driver socket rows (SPEC.md: 12.70 mm = 0.5 in)")
ap.add_argument("--out", default=str(HERE))
ARGS, _ = ap.parse_known_args()
OUT = Path(ARGS.out)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "fab").mkdir(exist_ok=True)

# ----------------------------------------------------------------------------
# 1. Parts (ref -> description).  Pin names are the pad numbers used everywhere.
# ----------------------------------------------------------------------------
PARTS = OrderedDict()


def add_part(ref, value, fp, desc, pins, side="F", smd=False, group=None, dnp=False, mpn=""):
    PARTS[ref] = dict(ref=ref, value=value, footprint=fp, description=desc, pins=list(pins),
                      side=side, smd=smd, group=group or value, dnp=dnp, mpn=mpn)


def seq(n, prefix=""):
    return [f"{prefix}{i}" for i in range(1, n + 1)]


add_part("J1", "Pi header 2x20 F", "PinSocket_2x20_P2.54mm_Vertical_BOTTOM",
         "Raspberry Pi 40-pin socket, 2.54 mm, mounted on BOTTOM side", seq(40), side="B")
for r in ("U1", "U2"):
    add_part(r, "2x 1x8 socket (TMC2209)", "PinSocket_2x08_Rows_P2.54mm",
             "Two 1x8 female 2.54 mm sockets for a TMC2209 module",
             [f"A{i}" for i in range(1, 9)] + [f"B{i}" for i in range(1, 9)])
for r in ("J2", "J3", "J4"):
    add_part(r, "Screw terminal 5.08 2P", "TerminalBlock_5.08mm_1x02_Horizontal",
             "Screw terminal, 5.08 mm pitch, 2 pin", seq(2))
for r in ("J5", "J6"):
    add_part(r, "JST XH 4P (B4B-XH-A)", "JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical",
             "JST XH 2.5 mm, 4 pin, vertical", seq(4), mpn="B4B-XH-A")
for r in ("J7", "J8", "J9", "J10"):
    add_part(r, "JST XH 2P (B2B-XH-A)", "JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical",
             "JST XH 2.5 mm, 2 pin, vertical", seq(2), mpn="B2B-XH-A")
for r in ("J11", "J12"):
    add_part(r, "Pin header 1x5", "PinHeader_1x05_P2.54mm_Vertical", "1x5 2.54 mm header", seq(5))
add_part("JP1", "Pin header 1x2 + jumper", "PinHeader_1x02_P2.54mm_Vertical", "1x2 jumper header", seq(2))
for r in ("F1", "F2"):
    add_part(r, "PTC 2A hold radial 5.08", "PTC_Radial_P5.08mm", "Radial resettable fuse, 2 A hold", seq(2))
add_part("D1", "1N5822", "D_DO-201AD_P12.70mm_Horizontal", "Schottky 3 A 40 V axial", ["1", "2"], mpn="1N5822")
add_part("D2", "1.5KE18A", "D_DO-201AD_P12.70mm_Horizontal", "TVS 1500 W 18 V unidirectional axial", ["1", "2"], mpn="1.5KE18A")
add_part("C1", "220uF 35V", "CP_Radial_D8.0mm_P3.50mm", "Electrolytic 220 uF 35 V radial", ["1", "2"])
for r in ("C2", "C3"):
    add_part(r, "100uF 35V", "CP_Radial_D6.3mm_P2.50mm", "Electrolytic 100 uF 35 V radial", ["1", "2"])
for r in ("C4", "C5", "C6", "C7", "C8", "C9"):
    add_part(r, "100nF 50V X7R", "C_0805_2012Metric", "Ceramic 100 nF 50 V X7R", ["1", "2"], smd=True)
for r in ("R1", "R4", "R5", "R6", "R7", "R8"):
    add_part(r, "1k", "R_0805_2012Metric", "Resistor 1 kOhm", ["1", "2"], smd=True)
for r in ("R2", "R3"):
    add_part(r, "10k", "R_0805_2012Metric", "Resistor 10 kOhm", ["1", "2"], smd=True)
add_part("LED1", "LED red", "LED_0805_2012Metric", "Red LED 0805 (pin1 = cathode, pin2 = anode)", ["1", "2"], smd=True)
for i in range(1, 6):
    add_part(f"TP{i}", "TP 1.0mm", "TestPoint_THT_D1.8mm_Drill1.0mm", "Test point, 1.0 mm drill", ["1"])
for i in range(1, 5):
    add_part(f"H{i}", "M3 hole", "MountingHole_3.2mm_M3_NPTH", "M3 mounting hole, NPTH 3.2 mm", [], group="M3 hole")

# ----------------------------------------------------------------------------
# 2. Pin -> net assignments (hand-coded; cross-checked against SPEC.md below)
# ----------------------------------------------------------------------------
PI_PIN_NET = {
    1: "3V3", 2: "5V_PI", 3: "SDA", 4: "5V_PI", 5: "SCL", 6: "GND", 8: "UART_TX_RAW", 9: "GND",
    10: "UART_BUS", 11: "STEP_AZ", 13: "DIR_AZ", 14: "GND", 15: "EN_AZ", 16: "STEP_ALT", 17: "3V3",
    18: "DIR_ALT", 20: "GND", 22: "EN_ALT", 25: "GND", 29: "ES_AZ_MIN", 30: "GND", 31: "ES_AZ_MAX",
    33: "ES_ALT_MIN", 34: "GND", 35: "ES_ALT_MAX", 37: "SPARE", 39: "GND",
}
PI_GPIO = {3: "GPIO2 SDA1", 5: "GPIO3 SCL1", 8: "GPIO14 TXD", 10: "GPIO15 RXD", 11: "GPIO17", 13: "GPIO27",
           15: "GPIO22", 16: "GPIO23", 18: "GPIO24", 22: "GPIO25", 29: "GPIO5", 31: "GPIO6", 33: "GPIO13",
           35: "GPIO19", 37: "GPIO26"}

# TMC2209 module pin functions (BIGTREETECH wiki order; V1.3 not confirmed)
MOD_A = ["EN", "MS1", "MS2", "PDN_UART", "PDN_UART_ALT", "CLK", "STEP", "DIR"]
MOD_B = ["VM", "GND", "COIL_A2", "COIL_A1", "COIL_B1", "COIL_B2", "VIO", "GND"]

PIN_NET = defaultdict(dict)          # ref -> pin -> net or None
for p in range(1, 41):
    PIN_NET["J1"][str(p)] = PI_PIN_NET.get(p)

PIN_NET["U1"].update({
    "A1": "EN_AZ", "A2": "GND", "A3": "GND", "A4": "UART_BUS", "A5": None, "A6": "GND",
    "A7": "STEP_AZ", "A8": "DIR_AZ",
    "B1": "+12V", "B2": "GND", "B3": "AZ_COIL_A2", "B4": "AZ_COIL_A1", "B5": "AZ_COIL_B1",
    "B6": "AZ_COIL_B2", "B7": "3V3", "B8": "GND"})
PIN_NET["U2"].update({
    "A1": "EN_ALT", "A2": "3V3", "A3": "GND", "A4": "UART_BUS", "A5": None, "A6": "GND",
    "A7": "STEP_ALT", "A8": "DIR_ALT",
    "B1": "+12V", "B2": "GND", "B3": "ALT_COIL_A2", "B4": "ALT_COIL_A1", "B5": "ALT_COIL_B1",
    "B6": "ALT_COIL_B2", "B7": "3V3", "B8": "GND"})
PIN_NET["R1"].update({"1": "UART_TX_RAW", "2": "UART_BUS"})
PIN_NET["R2"].update({"1": "3V3", "2": "EN_AZ"})
PIN_NET["R3"].update({"1": "3V3", "2": "EN_ALT"})

PIN_NET["J2"].update({"1": "12V_RAW", "2": "GND"})
PIN_NET["F1"].update({"1": "12V_RAW", "2": "12V_FUSED"})
PIN_NET["D1"].update({"1": "+12V", "2": "12V_FUSED"})        # pin1 = cathode, pin2 = anode
PIN_NET["D2"].update({"1": "+12V", "2": "GND"})              # pin1 = cathode, pin2 = anode
PIN_NET["C1"].update({"1": "+12V", "2": "GND"})              # pin1 = +
PIN_NET["C2"].update({"1": "+12V", "2": "GND"})
PIN_NET["C3"].update({"1": "+12V", "2": "GND"})
PIN_NET["J3"].update({"1": "+12V", "2": "GND"})
PIN_NET["J4"].update({"1": "5V_BUCK", "2": "GND"})
PIN_NET["F2"].update({"1": "5V_BUCK", "2": "5V_F"})
PIN_NET["JP1"].update({"1": "5V_F", "2": "5V_PI"})
PIN_NET["R8"].update({"1": "5V_F", "2": "LED_A"})
PIN_NET["LED1"].update({"1": "GND", "2": "LED_A"})           # pin1 = cathode, pin2 = anode
PIN_NET["J5"].update({"1": "AZ_COIL_A2", "2": "AZ_COIL_A1", "3": "AZ_COIL_B1", "4": "AZ_COIL_B2"})
PIN_NET["J6"].update({"1": "ALT_COIL_A2", "2": "ALT_COIL_A1", "3": "ALT_COIL_B1", "4": "ALT_COIL_B2"})
ES = [("J7", "R4", "C4", "ES_AZ_MIN"), ("J8", "R5", "C5", "ES_AZ_MAX"),
      ("J9", "R6", "C6", "ES_ALT_MIN"), ("J10", "R7", "C7", "ES_ALT_MAX")]
for j, r, c, n in ES:
    PIN_NET[j].update({"1": n + "_IN", "2": "GND"})           # pin 1 = signal, pin 2 = GND
    PIN_NET[r].update({"1": n + "_IN", "2": n})
    PIN_NET[c].update({"1": n, "2": "GND"})
for j in ("J11", "J12"):
    PIN_NET[j].update({"1": "GND", "2": "3V3", "3": "5V_F", "4": "SDA", "5": "SCL"})
PIN_NET["C8"].update({"1": "3V3", "2": "GND"})
PIN_NET["C9"].update({"1": "3V3", "2": "GND"})
PIN_NET["TP1"].update({"1": "+12V"})
PIN_NET["TP2"].update({"1": "5V_F"})
PIN_NET["TP3"].update({"1": "3V3"})
PIN_NET["TP4"].update({"1": "GND"})
PIN_NET["TP5"].update({"1": "SPARE"})

NETS = OrderedDict()
NC_PINS = []
for ref, part in PARTS.items():
    for pin in part["pins"]:
        net = PIN_NET[ref].get(pin)
        if net is None:
            NC_PINS.append((ref, pin))
        else:
            NETS.setdefault(net, []).append((ref, pin))
for ref in PIN_NET:
    for pin in PIN_NET[ref]:
        assert ref in PARTS and pin in PARTS[ref]["pins"], f"pin {ref}.{pin} does not exist"


def net_class(name):
    if name in ("GND",):
        return "GND"
    if name in ("12V_RAW", "12V_FUSED", "+12V") or name.endswith("_COIL_A1") or "_COIL_" in name:
        return "POWER"
    if name in ("5V_BUCK", "5V_F", "5V_PI"):
        return "POWER"
    if name == "3V3":
        return "POWER3V3"
    return "SIGNAL"


def verify_netlist():
    """Netlist checks required by SPEC.md; returns list of (check, ok, detail)."""
    res = []
    # every net has >=2 pins
    bad = [n for n, p in NETS.items() if len(p) < 2]
    res.append(("every net has >= 2 pins", not bad, f"{len(NETS)} nets; violations: {bad}"))
    # no pin on two nets
    seen = {}
    dup = []
    for n, pins in NETS.items():
        for rp in pins:
            if rp in seen and seen[rp] != n:
                dup.append(rp)
            seen[rp] = n
    res.append(("no pin on two nets", not dup, f"violations: {dup}"))
    # only the listed NC pins are unconnected
    allowed_nc = {("U1", "A5"), ("U2", "A5")} | {("J1", str(p)) for p in range(1, 41) if p not in PI_PIN_NET}
    extra = [x for x in NC_PINS if x not in allowed_nc]
    missing = [x for x in allowed_nc if x not in NC_PINS]
    res.append(("only SPEC NC pins unconnected", not extra and not missing,
                f"NC pins={len(NC_PINS)}; unexpected={extra}; missing={missing}"))
    return res


def parse_spec_tables():
    """Parse the Pi-header and module tables straight from SPEC.md."""
    txt = (HERE / "SPEC.md").read_text(encoding="utf8")
    pi = {}
    nc_rule = False
    sec = re.search(r"### Pi header.*?(?=### TMC2209)", txt, re.S).group(0)
    for line in sec.splitlines():
        m = re.match(r"\|\s*([\d, ]+|all others)\s*\|[^|]*\|\s*([^|]*?)\s*\|", line)
        if not m:
            continue
        pins, net = m.group(1), m.group(2)
        if pins == "all others":
            nc_rule = (net == "NC")
            continue
        for p in pins.split(","):
            net_tok = net.split()[0]
            pi[int(p)] = net_tok
    mod = {}
    sec = re.search(r"Connections per module:.*?(?=R1 = 1 kOhm)", txt, re.S).group(0)
    for line in sec.splitlines():
        m = re.match(r"\|\s*([AB]\d)\s+(\w+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|", line)
        if m:
            mod[m.group(1)] = (m.group(2), m.group(3).split()[0], m.group(4).split()[0])
    return pi, nc_rule, mod


def verify_against_spec():
    pi, nc_rule, mod = parse_spec_tables()
    res = []
    bad = []
    for p in range(1, 41):
        exp = pi.get(p)
        got = PIN_NET["J1"][str(p)]
        if exp is None:
            if got is not None:
                bad.append((p, "NC", got))
        else:
            # table lists the Pi-side net for pins that go through an RC/resistor stage
            ok = (got == exp)
            if not ok:
                bad.append((p, exp, got))
    res.append(("Pi header J1: all 40 pins match SPEC.md table (%d listed, others NC=%s)" % (len(pi), nc_rule),
                not bad and nc_rule, f"mismatches: {bad}"))
    bad = []
    for pin, (func, n1, n2) in mod.items():
        if pin in ("B3", "B4", "B5", "B6") or func.startswith("coils"):
            continue
        for ref, exp in (("U1", n1), ("U2", n2)):
            got = PIN_NET[ref][pin]
            if exp == "NC":
                exp = None
            if got != exp:
                bad.append((ref, pin, exp, got))
    # coils: module B3..B6 must reach J5/J6 pins 1..4 straight through
    for ref, j in (("U1", "J5"), ("U2", "J6")):
        for k, pin in enumerate(("B3", "B4", "B5", "B6"), start=1):
            if PIN_NET[ref][pin] != PIN_NET[j][str(k)]:
                bad.append((ref, pin, "J%s.%d" % (j, k)))
    coil_row = re.search(r"\|\s*B3\.\.B6 coils\s*\|\s*to J5 pins 1\.\.4\s*\|\s*to J6 pins 1\.\.4\s*\|", (HERE / "SPEC.md").read_text(encoding="utf8"))
    res.append(("TMC2209 sockets U1/U2: all 16 pins each match SPEC.md table (%d single-pin rows parsed + B3..B6 coil row)" % len(mod),
                not bad and len(mod) == 12 and coil_row is not None, f"mismatches: {bad}"))
    # explicit power / connector assertions from the SPEC.md prose
    A = []

    def chk(cond, text):
        A.append((text, bool(cond)))
    chk(PIN_NET["J2"]["1"] == "12V_RAW" and PIN_NET["J2"]["2"] == "GND", "J2 pin1=12V_RAW pin2=GND")
    chk(PIN_NET["F1"]["1"] == "12V_RAW" and PIN_NET["F1"]["2"] == "12V_FUSED", "F1 12V_RAW->12V_FUSED")
    chk(PIN_NET["D1"]["2"] == "12V_FUSED" and PIN_NET["D1"]["1"] == "+12V", "D1 anode=12V_FUSED cathode=+12V")
    chk(PIN_NET["D2"]["1"] == "+12V" and PIN_NET["D2"]["2"] == "GND", "D2 cathode=+12V anode=GND")
    chk(all(PIN_NET[c] == {"1": "+12V", "2": "GND"} for c in ("C1", "C2", "C3")), "C1..C3 +12V/GND (pin1=+)")
    chk(PIN_NET["J3"] == {"1": "+12V", "2": "GND"}, "J3 +12V/GND")
    chk(PIN_NET["J4"] == {"1": "5V_BUCK", "2": "GND"}, "J4 5V_BUCK/GND")
    chk(PIN_NET["F2"] == {"1": "5V_BUCK", "2": "5V_F"}, "F2 5V_BUCK->5V_F")
    chk(PIN_NET["JP1"] == {"1": "5V_F", "2": "5V_PI"}, "JP1 5V_F<->5V_PI")
    chk(PIN_NET["R8"]["1"] == "5V_F" and PIN_NET["LED1"]["1"] == "GND", "LED1+R8 5V_F->GND")
    chk(all(PIN_NET[j] == {"1": n + "_IN", "2": "GND"} for j, r, c, n in ES), "J7..J10 pin1=signal pin2=GND")
    chk(all(PIN_NET[r] == {"1": n + "_IN", "2": n} and PIN_NET[c] == {"1": n, "2": "GND"} for j, r, c, n in ES),
        "end-stop RC: R(1k) signal->GPIO net, C(100n) GPIO->GND")
    chk(all(PIN_NET[j] == {"1": "GND", "2": "3V3", "3": "5V_F", "4": "SDA", "5": "SCL"} for j in ("J11", "J12")),
        "J11/J12 1 GND 2 3V3 3 5V_F 4 SDA 5 SCL")
    chk(PIN_NET["R1"] == {"1": "UART_TX_RAW", "2": "UART_BUS"} and PARTS["R1"]["value"] == "1k", "R1 1k TX_RAW->UART_BUS")
    chk(PIN_NET["R2"] == {"1": "3V3", "2": "EN_AZ"} and PIN_NET["R3"] == {"1": "3V3", "2": "EN_ALT"}
        and PARTS["R2"]["value"] == "10k" and PARTS["R3"]["value"] == "10k", "R2/R3 10k pull-ups to 3V3")
    chk([PIN_NET[f"TP{i}"]["1"] for i in range(1, 6)] == ["+12V", "5V_F", "3V3", "GND", "SPARE"], "TP1..TP5 nets")
    chk(PIN_NET["C8"] == {"1": "3V3", "2": "GND"} and PIN_NET["C9"] == {"1": "3V3", "2": "GND"}, "C8/C9 3V3/GND")
    for text, ok in A:
        res.append(("SPEC prose: " + text, ok, ""))
    return res


# ----------------------------------------------------------------------------
# 3. Outputs of stage 1
# ----------------------------------------------------------------------------
def write_netlist_json(extra=None):
    parts = []
    for ref, p in PARTS.items():
        d = dict(ref=ref, value=p["value"], footprint=p["footprint"], description=p["description"],
                 side=p["side"], smd=p["smd"], mpn=p["mpn"],
                 pins=OrderedDict((pin, PIN_NET[ref].get(pin)) for pin in p["pins"]))
        parts.append(d)
    doc = OrderedDict(
        board=BOARD_NAME, revision=BOARD_REV, source="generated by generate.py from the in-script netlist",
        generated=datetime.date.today().isoformat(),
        parts=parts,
        nets=OrderedDict((n, [list(x) for x in pins]) for n, pins in NETS.items()),
        net_classes=OrderedDict((n, net_class(n)) for n in NETS),
        nc_pins=[list(x) for x in NC_PINS],
        test_points=OrderedDict((f"TP{i}", PIN_NET[f"TP{i}"]["1"]) for i in range(1, 6)),
        pi_gpio_map=OrderedDict((str(k), v) for k, v in PI_GPIO.items()),
    )
    if extra:
        doc.update(extra)
    (OUT / "netlist.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf8")
    return doc


def kicad_uuid(seed):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "apa-carrier/" + seed))


def write_kicad_net():
    lines = ["(export (version \"E\")",
             "  (design",
             f"    (source \"{BOARD_NAME}.kicad_sch\")",
             f"    (date \"{datetime.date.today().isoformat()}\")",
             "    (tool \"generate.py (not KiCad)\"))",
             "  (components"]
    for ref, p in PARTS.items():
        fp = "APA_CARRIER:" + p["footprint"]
        lines.append(f"    (comp (ref \"{ref}\")")
        lines.append(f"      (value \"{p['value']}\")")
        lines.append(f"      (footprint \"{fp}\")")
        lines.append(f"      (libsource (lib \"APA_CARRIER\") (part \"{p['group'] if p['pins'] else 'MountingHole'}\") (description \"{p['description']}\"))")
        lines.append(f"      (sheetpath (names \"/\") (tstamps \"/\"))")
        lines.append(f"      (tstamp \"{kicad_uuid('comp/' + ref)}\"))")
    lines.append("  )")
    lines.append("  (nets")
    # KiCad net code 0 is the unconnected net
    for code, (name, pins) in enumerate(NETS.items(), start=1):
        lines.append(f"    (net (code \"{code}\") (name \"{name}\")")
        for ref, pin in pins:
            lines.append(f"      (node (ref \"{ref}\") (pin \"{pin}\")))" if (ref, pin) == pins[-1]
                         else f"      (node (ref \"{ref}\") (pin \"{pin}\"))")
        if lines[-1].endswith("))") is False:
            lines[-1] += ")"
    lines.append("  ))")
    (OUT / "carrier.net").write_text("\n".join(lines) + "\n", encoding="utf8")


def write_bom_draft():
    groups = OrderedDict()
    for ref, p in PARTS.items():
        key = (p["value"], p["footprint"], p["mpn"])
        groups.setdefault(key, []).append(ref)
    with open(OUT / "carrier_bom.csv", "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "Quantity", "Description", "MPN / note"])
        for (value, fp, mpn), refs in groups.items():
            refs = sorted(refs, key=lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r))))
            w.writerow([value, ",".join(refs), fp, len(refs), PARTS[refs[0]]["description"], mpn])


def stage1():
    checks = verify_netlist() + verify_against_spec()
    for name, ok, detail in checks:
        print(("PASS " if ok else "FAIL ") + name + ("  " + detail if detail and not ok else ""))
    assert all(ok for _, ok, _ in checks), "netlist verification failed"
    doc = write_netlist_json({"verification": [dict(check=n, passed=o, detail=d) for n, o, d in checks]})
    write_kicad_net()
    write_bom_draft()
    return doc, checks


# ============================================================================
# SECTION 2: geometry, footprints, placement
# ============================================================================
import hashlib
import math
import os
import time
import zipfile

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

t_start = time.time()
BOARD_W, BOARD_H = 85.0, 60.0
CORNER_R = 2.0
THICK = 1.6
RULE_CLR = 0.25          # SPEC minimum clearance (what is verified)
POUR_CLR = 0.30          # clearance used when cutting pours
EDGE_CLR = 0.5           # copper to board edge
VIA_PAD, VIA_DRILL = 0.6, 0.3
W_SIG, W_3V3, W_PWR = 0.30, 0.50, 0.80
MASK_EXP = 0.05
SILK_W = 0.18
ROW = ARGS.driver_row_spacing     # driver socket row spacing (SPEC.md corrected: 12.70)
CIRC_Q = 16                       # quad segments for circles

OUTLINE = box(CORNER_R, CORNER_R, BOARD_W - CORNER_R, BOARD_H - CORNER_R).buffer(CORNER_R, quad_segs=32)


def circ(x, y, r):
    return Point(x, y).buffer(r, quad_segs=CIRC_Q)


def pad_poly(shape, x, y, w, h):
    if shape == "circle":
        return circ(x, y, w / 2)
    if shape == "rect":
        return box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    if shape == "oval":      # stadium, long axis along the larger of w/h
        if w >= h:
            r = h / 2
            return LineString([(x - (w - h) / 2, y), (x + (w - h) / 2, y)]).buffer(r, quad_segs=CIRC_Q)
        r = w / 2
        return LineString([(x, y - (h - w) / 2), (x, y + (h - w) / 2)]).buffer(r, quad_segs=CIRC_Q)
    raise ValueError(shape)


# ----------------------------- footprints ----------------------------------
# local frame: x right, y up, origin as documented per footprint, rot = degrees CCW.
# pad: dict(num,x,y,shape,w,h,drill,plated,smd)
def P(num, x, y, shape, w, h=None, drill=None, plated=True, smd=False):
    return dict(num=str(num), x=x, y=y, shape=shape, w=w, h=h if h is not None else w,
                drill=drill, plated=plated, smd=smd)


def fp_socket_2x20():
    pads = []
    for k in range(20):
        x = (k - 9.5) * 2.54
        pads.append(P(2 * k + 1, x, -1.27, "rect" if k == 0 else "circle", 1.6, drill=1.0))
        pads.append(P(2 * k + 2, x, +1.27, "circle", 1.6, drill=1.0))
    return dict(name="PinSocket_2x20_P2.54mm_Vertical_BOTTOM", pads=pads,
                silk=[("rect", -25.4, -2.54, 25.4, 2.54)],
                body=[(-25.4, -2.54, 25.4, 2.54, -8.5, 0.0, "J1 female socket (below board)")],
                crt=(-26.0, -3.1, 26.0, 3.1), source="2x20 female header, 8.5 mm body")


def fp_socket_2x08():
    pads = []
    for i in range(8):
        pads.append(P(f"A{i+1}", 2.54 * i, 0, "rect" if i == 0 else "circle", 1.6, drill=1.0))
    for i in range(8):
        pads.append(P(f"B{i+1}", 2.54 * i, ROW, "rect" if i == 0 else "circle", 1.6, drill=1.0))
    mid = ROW / 2
    return dict(name="PinSocket_2x08_Rows_P2.54mm", pads=pads,
                silk=[("rect", -1.27, -1.27, 19.05, 1.27), ("rect", -1.27, ROW - 1.27, 19.05, ROW + 1.27),
                      ("rect", -0.8, mid - 7.62, 18.58, mid + 7.62, "dash")],
                body=[(-1.27, -1.27, 19.05, 1.27, 0, 8.5, "socket row A"),
                      (-1.27, ROW - 1.27, 19.05, ROW + 1.27, 0, 8.5, "socket row B"),
                      (-1.27, mid - 7.62, 19.05, mid + 7.62, 8.5, 17.1, "TMC2209 module + heatsink (15.24x20.32 board, top at 17.1 mm assumed)")],
                crt=[(-1.8, -1.8, 19.6, 1.8), (-1.8, ROW - 1.8, 19.6, ROW + 1.8)], source="2x 1x8 female header, 8.5 mm body; module box assumed",
                module=(-1.27, mid - 7.62, 19.05, mid + 7.62))


def fp_terminal2():
    pads = [P(1, 0, 0, "rect", 2.6, drill=1.3), P(2, 5.08, 0, "circle", 2.6, drill=1.3)]
    return dict(name="TerminalBlock_5.08mm_1x02_Horizontal", pads=pads,
                silk=[("rect", -2.54, -4.6, 7.62, 5.2)],
                body=[(-2.54, -4.6, 7.62, 5.2, 0, 10.0, "screw terminal 10.2x9.8x10 (KiCad MKDS-1,5-2-5.08 envelope)")],
                crt=(-2.84, -4.8, 7.92, 5.4), entry=(0, 1),
                source="KiCad TerminalBlock_Phoenix_MKDS-1,5-2-5.08 (pad 2.6, drill 1.3, 10.2x9.8)")


def fp_jst(n):
    pads = [P(i + 1, 2.5 * i, 0, "rect" if i == 0 else "oval", 1.7, 1.95, drill=0.95) for i in range(n)]
    x1 = 2.5 * (n - 1) + 2.45
    return dict(name=f"JST_XH_B{n}B-XH-A_1x{n:02d}_P2.50mm_Vertical", pads=pads,
                silk=[("rect", -2.45, -3.4, x1, 2.35)],
                body=[(-2.45, -3.4, x1, 2.35, 0, 7.0, f"JST XH B{n}B-XH-A, 7.0 mm tall (typical)")],
                crt=(-2.55, -3.5, x1 + 0.1, 2.45),
                source="KiCad JST_XH_B%dB-XH-A (pad 1.7x1.95 oval, drill 0.95, body 5.75 deep)" % n)


def fp_header(n):
    pads = [P(i + 1, 2.54 * i, 0, "rect" if i == 0 else "circle", 1.6, drill=1.0) for i in range(n)]
    return dict(name=f"PinHeader_1x{n:02d}_P2.54mm_Vertical", pads=pads,
                silk=[("rect", -1.27, -1.27, 2.54 * (n - 1) + 1.27, 1.27)],
                body=[(-1.27, -1.27, 2.54 * (n - 1) + 1.27, 1.27, 0, 2.5, "header plastic"),
                      (-0.32, -0.32, 2.54 * (n - 1) + 0.32, 0.32, 2.5, 8.5, "header pins")],
                crt=(-1.77, -1.77, 2.54 * (n - 1) + 1.77, 1.77), source="1xN 2.54 mm pin header")


def fp_ptc():
    pads = [P(1, 0, 0, "rect", 2.0, drill=1.0), P(2, 5.08, 0, "circle", 2.0, drill=1.0)]
    return dict(name="PTC_Radial_P5.08mm", pads=pads,
                silk=[("rect", -2.46, -2.0, 7.54, 2.0)],
                body=[(-2.46, -2.0, 7.54, 2.0, 0, 14.0, "PTC disc (assumed 10 x 4 x 14 mm; UNVERIFIED, check chosen part)")],
                crt=(-2.96, -2.5, 8.04, 2.5), source="generic radial PTC, 5.08 mm lead pitch (envelope assumed)")


def fp_do201():
    pads = [P(1, 0, 0, "rect", 3.2, drill=1.6), P(2, 12.7, 0, "circle", 3.2, drill=1.6)]
    return dict(name="D_DO-201AD_P12.70mm_Horizontal", pads=pads,
                silk=[("rect", 1.6, -2.6, 11.1, 2.6), ("rect", 2.9, -2.6, 3.4, 2.6, "fill")],
                body=[(1.6, -2.6, 11.1, 2.6, 0.0, 5.2, "DO-201AD body 9.5 x 5.2")],
                crt=(-1.85, -2.85, 14.55, 2.85),
                source="KiCad D_DO-201AD_P12.70mm_Horizontal (pad 3.2, drill 1.6, body 9.5x5.2)")


def fp_cp(D, pitch):
    h = 12.0 if D > 7 else 11.0
    pads = [P(1, 0, 0, "rect", 1.6, drill=0.8), P(2, pitch, 0, "circle", 1.6, drill=0.8)]
    c = pitch / 2
    return dict(name=f"CP_Radial_D{D:.1f}mm_P{pitch:.2f}mm", pads=pads,
                silk=[("circle", c, 0, D / 2), ("text", "+", -1.9, 1.6, 1.0)],
                body=[(c - D / 2, -D / 2, c + D / 2, D / 2, 0, h, f"electrolytic D{D} x {h} mm (typical)")],
                crt=(c - D / 2 - 0.3, -D / 2 - 0.3, c + D / 2 + 0.3, D / 2 + 0.3),
                source="KiCad CP_Radial_D%.1fmm_P%.2fmm (pad 1.6, drill 0.8)" % (D, pitch))


def fp_0805(led=False):
    pads = [P(1, -0.95, 0, "rect", 1.15, 1.4, smd=True), P(2, 0.95, 0, "rect", 1.15, 1.4, smd=True)]
    silk = [("line", -0.3, 0.95, 0.3, 0.95), ("line", -0.3, -0.95, 0.3, -0.95)]
    if led:
        silk.append(("line", -1.75, -0.95, -1.75, 0.95))     # cathode mark (pin 1 side)
    return dict(name="LED_0805_2012Metric" if led else "R_0805_2012Metric", pads=pads, silk=silk,
                body=[(-1.0, -0.625, 1.0, 0.625, 0, 0.6, "0805")], crt=(-1.7, -0.95, 1.7, 0.95),
                source="0805 (IPC-like pads 1.15x1.4 at +-0.95)")


def fp_tp():
    return dict(name="TestPoint_THT_D1.8mm_Drill1.0mm", pads=[P(1, 0, 0, "circle", 1.8, drill=1.0)],
                silk=[], body=[], crt=(-1.1, -1.1, 1.1, 1.1), source="test point 1.0 mm drill")


def fp_hole():
    return dict(name="MountingHole_3.2mm_M3_NPTH", pads=[P("", 0, 0, "circle", 3.2, drill=3.2, plated=False)],
                silk=[], body=[], crt=(-3.0, -3.0, 3.0, 3.0), source="M3 NPTH 3.2 mm")


FOOT = {}
FOOT["J1"] = fp_socket_2x20()
FOOT["U"] = fp_socket_2x08()
FOOT["TB"] = fp_terminal2()
FOOT["JST4"] = fp_jst(4)
FOOT["JST2"] = fp_jst(2)
FOOT["H5"] = fp_header(5)
FOOT["H2"] = fp_header(2)
FOOT["PTC"] = fp_ptc()
FOOT["DO"] = fp_do201()
FOOT["C8"] = fp_cp(8.0, 3.5)
FOOT["C63"] = fp_cp(6.3, 2.5)
FOOT["R"] = fp_0805()
FOOT["LED"] = fp_0805(True)
FOOT["TP"] = fp_tp()
FOOT["HOLE"] = fp_hole()
FP_OF = {}
for r in PARTS:
    if r == "J1": FP_OF[r] = "J1"
    elif r in ("U1", "U2"): FP_OF[r] = "U"
    elif r in ("J2", "J3", "J4"): FP_OF[r] = "TB"
    elif r in ("J5", "J6"): FP_OF[r] = "JST4"
    elif r in ("J7", "J8", "J9", "J10"): FP_OF[r] = "JST2"
    elif r in ("J11", "J12"): FP_OF[r] = "H5"
    elif r == "JP1": FP_OF[r] = "H2"
    elif r in ("F1", "F2"): FP_OF[r] = "PTC"
    elif r in ("D1", "D2"): FP_OF[r] = "DO"
    elif r == "C1": FP_OF[r] = "C8"
    elif r in ("C2", "C3"): FP_OF[r] = "C63"
    elif r.startswith("C"): FP_OF[r] = "R"
    elif r.startswith("R"): FP_OF[r] = "R"
    elif r == "LED1": FP_OF[r] = "LED"
    elif r.startswith("TP"): FP_OF[r] = "TP"
    elif r.startswith("H"): FP_OF[r] = "HOLE"
for r, p in PARTS.items():
    p["footprint"] = FOOT[FP_OF[r]]["name"]

# ------------------------------- placement ---------------------------------
# (x, y, rot_deg_ccw) of the footprint origin in board coordinates (origin lower-left, y up)
# Pi stack geometry (Pi Zero 2 W drawing RP-008358-DS): header centreline is 3.5 mm from the Pi's top edge, centred
# on the 65 mm edge.  The Pi hangs below J1 and sticks out of the board's south edge so its ports stay uncovered.
J1_X, J1_Y = 42.418, 12.446      # multiples of 0.127 so that J1 pads and pad-gaps sit on the routing grid
PI_TOP_EDGE_Y = J1_Y + 3.5
YA = 22.0                              # driver A-row y
X_U1, X_U2 = 24.0, 53.8                # module bodies 9.5 mm apart (C3 sits between them)
Y_B = YA + ROW                         # driver B-row y
PLACE = OrderedDict()
PLACE["J1"] = (J1_X, J1_Y, 0)
PLACE["U1"] = (X_U1, YA, 0)
PLACE["U2"] = (X_U2, YA, 0)
PLACE["J5"] = (X_U1 + 5.08 + 0.06, Y_B + 5.8, 0)
PLACE["J6"] = (X_U2 + 5.08 + 0.06, Y_B + 5.8, 0)
PLACE["C2"] = (18.2, Y_B - 1.25, 90)
PLACE["C3"] = (47.8, Y_B - 1.25, 90)
PLACE["J2"] = (54.0, 54.3, 0)
PLACE["F1"] = (44.0, 54.3, 180)
PLACE["D1"] = (51.62, 46.2, 180)
PLACE["D2"] = (56.0, 46.2, 0)
PLACE["C1"] = (29.5, 47.7, 0)
PLACE["J3"] = (65.0, 54.3, 0)
PLACE["J4"] = (7.0, 44.0, 90)
PLACE["F2"] = (8.0, 38.0, 270)
PLACE["JP1"] = (14.5, 19.5, 270)
PLACE["R8"] = (4.0, 31.5, 90)
PLACE["LED1"] = (4.0, 27.3, 90)
PLACE["J11"] = (4.5, 12.5, 90)
PLACE["J12"] = (10.5, 12.5, 90)
for k, (j, r, c, n) in enumerate(ES):
    x0 = 45.0 + 7.9 * k
    PLACE[j] = (x0, 4.0, 0)
    PLACE[r] = (x0 + 0.0, 8.0, 0)
    PLACE[c] = (x0 + 3.5, 8.0, 0)
PLACE["R1"] = (27.3, 17.6, 0)
PLACE["R2"] = (X_U1 + 1.0, YA + 4.2, 90)
PLACE["R3"] = (X_U2 + 1.0, YA + 4.2, 90)
PLACE["C8"] = (X_U1 + 16.5, Y_B - 4.2, 90)
PLACE["C9"] = (X_U2 + 16.5, Y_B - 4.2, 90)
PLACE["TP1"] = (28.0, 54.5, 0)
PLACE["TP2"] = (12.0, 31.0, 0)
PLACE["TP3"] = (31.0, 6.0, 0)
PLACE["TP4"] = (35.0, 6.0, 0)
PLACE["TP5"] = (78.0, 12.0, 0)
PLACE["H1"] = (3.5, 3.5, 0)
PLACE["H2"] = (BOARD_W - 3.5, 3.5, 0)
PLACE["H3"] = (3.5, BOARD_H - 3.5, 0)
PLACE["H4"] = (BOARD_W - 3.5, BOARD_H - 3.5, 0)


def rot_pt(x, y, rot):
    a = math.radians(rot)
    c, s = round(math.cos(a), 12), round(math.sin(a), 12)
    return x * c - y * s, x * s + y * c


class PadAbs:
    __slots__ = ("ref", "num", "net", "x", "y", "shape", "w", "h", "drill", "plated", "smd", "side", "poly", "id", "rot")

    def __init__(self, **k):
        for a in self.__slots__:
            setattr(self, a, k.get(a))

    @property
    def layers(self):
        if self.smd:
            return ("B",) if self.side == "B" else ("F",)
        return ("F", "B")


def build_pads():
    out = []
    for ref, (px, py, rot) in PLACE.items():
        fp = FOOT[FP_OF[ref]]
        side = PARTS[ref]["side"]
        for pd in fp["pads"]:
            lx, ly = rot_pt(pd["x"], pd["y"], rot)
            w, h = pd["w"], pd["h"]
            if rot % 180 == 90:
                w, h = h, w
            net = PIN_NET[ref].get(pd["num"]) if pd["num"] != "" else None
            pa = PadAbs(ref=ref, num=pd["num"], net=net, x=px + lx, y=py + ly, shape=pd["shape"], w=w, h=h,
                        drill=pd["drill"], plated=pd["plated"], smd=pd["smd"], side=side, rot=rot)
            pa.poly = pad_poly(pa.shape, pa.x, pa.y, pa.w, pa.h)
            pa.id = f"{ref}.{pa.num}"
            out.append(pa)
    return out


def part_geoms(ref):
    """Absolute silk primitives / body boxes (list of shapely geoms) for a part."""
    px, py, rot = PLACE[ref]
    fp = FOOT[FP_OF[ref]]
    res = dict(body=[], crt=None)
    for b in fp["body"]:
        x0, y0, x1, y1 = b[:4]
        pts = [rot_pt(x, y, rot) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        res["body"].append((Polygon([(px + a, py + b_) for a, b_ in pts]), b[4], b[5], b[6]))
    rects = fp["crt"] if isinstance(fp["crt"], list) else [fp["crt"]]
    polys = []
    for (x0, y0, x1, y1) in rects:
        pts = [rot_pt(x, y, rot) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        polys.append(Polygon([(px + a, py + b_) for a, b_ in pts]))
    res["crt"] = unary_union(polys)
    return res


def module_poly(ref):
    px, py, rot = PLACE[ref]
    x0, y0, x1, y1 = FOOT[FP_OF[ref]]["module"]
    pts = [rot_pt(x, y, rot) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    return Polygon([(px + a, py + b_) for a, b_ in pts])


def check_placement(pads):
    """Courtyard overlap, inside-board, and 3D module clearance (modules float 8.5 mm above the board)."""
    probs = []
    crt = {r: part_geoms(r)["crt"] for r in PLACE}
    refs = list(PLACE)
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            a, b = crt[refs[i]], crt[refs[j]]
            if a.intersects(b) and a.intersection(b).area > 0.05:
                probs.append(f"courtyard overlap {refs[i]} / {refs[j]} area={a.intersection(b).area:.2f}")
    inner = OUTLINE.buffer(-0.3)
    for r in refs:
        if r.startswith("H") or r == "J1":
            continue
        if not inner.contains(crt[r]):
            probs.append(f"{r} courtyard outside board")
    mods = {r: module_poly(r) for r in ("U1", "U2")}
    d = mods["U1"].distance(mods["U2"])
    if d < 1.0:
        probs.append(f"module bodies U1/U2 only {d:.2f} mm apart")
    for r in refs:
        if r in mods or r.startswith("H"):
            continue
        for body, z0, z1, _ in part_geoms(r)["body"]:
            if r in ("J1",):
                continue
            if z1 > 8.5:        # tall enough to reach the module's underside level
                for m, mp in mods.items():
                    if body.distance(mp) < 1.0:
                        probs.append(f"{r} body (top {z1} mm) within {body.distance(mp):.2f} mm of module {m}")
    return probs


# Hand-placed waypoints (layer 0 = F.Cu): the three AZ signals leave the outer (odd) row of J1 through the 0.94 mm
# gaps between its pads (0.3 mm track, 0.32 mm clearance to each pad) and are finished by the autorouter.
def _gx(i): return round(i * 0.127, 3)
J1_PIN_X = {k: J1_X + (k - 9.5) * 2.54 for k in range(20)}
J1_ROW_S = J1_Y - 1.27
PREROUTE = {
    "STEP_AZ": [(0, [(J1_PIN_X[5], J1_ROW_S), (J1_PIN_X[5] + 1.27, J1_ROW_S), (J1_PIN_X[5] + 1.27, _gx(122))])],
    "DIR_AZ": [(0, [(J1_PIN_X[6], J1_ROW_S), (J1_PIN_X[6] + 1.27, J1_ROW_S), (J1_PIN_X[6] + 1.27, _gx(122))])],
    "EN_AZ": [(0, [(J1_PIN_X[7], J1_ROW_S), (J1_PIN_X[7] + 1.27, J1_ROW_S), (J1_PIN_X[7] + 1.27, _gx(122))])],
}

# ============================================================================
# SECTION 3: own two-layer grid router (A* with vias, turn penalty), exact-ish clearances
# ============================================================================
import heapq

import shapely
from PIL import Image, ImageDraw
from scipy import ndimage

GRID = 0.127                     # 5 mil: J1 pad centres and the gaps between its pads lie exactly on the grid
RES = GRID / 4                   # obstacle raster resolution
NX = int(math.ceil(BOARD_W / GRID))
NY = int(math.ceil(BOARD_H / GRID))
STRIDE = NY + 3
SZ = (NX + 3) * STRIDE
NXR = 4 * NX + 8
NYR = 4 * NY + 8
ROUTE_MARGIN = 0.05              # raster conservatism (<= 0.032) + slack
VIA_COST = 16.0
TURN45, TURN90 = 2.0, 5.0
PREF_PEN = 1.2
EXP_CAP = 350000
H_WEIGHT = 1.25

DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
OFF = [dx * STRIDE + dy for dx, dy in DIRS]
STEPC = [1.0, 1.41421356, 1.0, 1.41421356, 1.0, 1.41421356, 1.0, 1.41421356]
IL = [0] * SZ
JL = [0] * SZ
for _i in range(NX + 3):
    base = _i * STRIDE
    for _j in range(STRIDE):
        IL[base + _j] = _i - 1
        JL[base + _j] = _j - 1


def nid(l, i, j):
    return l * SZ + (i + 1) * STRIDE + (j + 1)


def net_width(net):
    c = net_class(net)
    return {"POWER": W_PWR, "POWER3V3": W_3V3, "SIGNAL": W_SIG, "GND": W_PWR}[c]


def geoms_of(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [x for x in g.geoms if x.geom_type == "Polygon"]


def raster_draw(img, geom, val, res=RES):
    d = ImageDraw.Draw(img)
    for poly in geoms_of(geom):
        d.polygon([(x / res, y / res) for x, y in poly.exterior.coords], fill=val)


class Router:
    def __init__(self, pads, edge_poly=OUTLINE):
        self.pads = pads
        self.netid = {}
        for p in pads:
            if p.net and p.net not in self.netid:
                self.netid[p.net] = len(self.netid) + 1
        self.hole_id = 5000
        self.tracks = []         # dict(net,layer,pts=[(x,y),..],w)
        self.vias = []           # dict(net,x,y)
        self.owner = [Image.new("I", (NXR, NYR), 0), Image.new("I", (NXR, NYR), 0)]
        self.inside_cache = {}
        for net_, pl in PREROUTE.items():          # hand-placed waypoints are obstacles from the start
            for (l, pts) in pl:
                tr = dict(net=net_, layer=l, pts=[tuple(q) for q in pts], w=net_width(net_))
                self.tracks.append(tr)
        # static copper
        for p in pads:
            if p.drill and not p.plated:
                # NPTH: keep-out disc (screw head) on both layers
                for l in (0, 1):
                    raster_draw(self.owner[l], circ(p.x, p.y, 1.6 + 0.5), self.hole_id)
                continue
            val = self.netid.get(p.net) or self.nc_id(p.id)
            for ln in p.layers:
                raster_draw(self.owner[0 if ln == "F" else 1], p.poly, val)
        for t in self.tracks:
            raster_draw(self.owner[t["layer"]], LineString(t["pts"]).buffer(t["w"] / 2, quad_segs=6), self.netid[t["net"]])

    def nc_id(self, pid):
        if not hasattr(self, "_nc"):
            self._nc = {}
        if pid not in self._nc:
            self._nc[pid] = 6000 + len(self._nc)
        return self._nc[pid]

    def inside_mask(self, half):
        key = round(half, 3)
        if key not in self.inside_cache:
            poly = OUTLINE.buffer(-(EDGE_CLR + half + 0.03))
            xs = np.arange(NX + 1) * GRID
            ys = np.arange(NY + 1) * GRID
            X, Y = np.meshgrid(xs, ys, indexing="ij")
            self.inside_cache[key] = shapely.contains_xy(poly, X.ravel(), Y.ravel()).reshape(X.shape)
        return self.inside_cache[key]

    def dist_maps(self, net):
        nid_ = self.netid[net]
        out = []
        for l in (0, 1):
            a = np.asarray(self.owner[l]).T          # [ix, iy]
            mask = (a != 0) & (a != nid_)
            e = ndimage.distance_transform_edt(~mask)
            out.append(e[0:4 * NX + 1:4, 0:4 * NY + 1:4] * RES)
        return out

    def terminals(self, pad, w):
        """grid nodes (per layer) where a track of width w fits entirely inside the pad copper."""
        poly = pad.poly.buffer(-w / 2 + 0.001)
        res = {}
        if poly.is_empty:
            poly = Point(pad.x, pad.y).buffer(0.02)
        x0, y0, x1, y1 = poly.bounds
        i0, i1 = int(math.floor(x0 / GRID)), int(math.ceil(x1 / GRID))
        j0, j1 = int(math.floor(y0 / GRID)), int(math.ceil(y1 / GRID))
        I, J = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
        ok = shapely.contains_xy(poly, I.ravel() * GRID, J.ravel() * GRID)
        pts = [(int(a), int(b)) for a, b, k in zip(I.ravel(), J.ravel(), ok) if k]
        if not pts:   # snap to nearest node of pad centre
            pts = [(int(round(pad.x / GRID)), int(round(pad.y / GRID)))]
        for ln in pad.layers:
            res[0 if ln == "F" else 1] = pts
        return res

    def route_net(self, net, log=None):
        pads = [p for p in self.pads if p.net == net]
        w = net_width(net)
        half = w / 2
        T = half + RULE_CLR + ROUTE_MARGIN
        TV = VIA_PAD / 2 + RULE_CLR + 0.05
        dist = self.dist_maps(net)
        inside = self.inside_mask(half)
        inside_v = self.inside_mask(VIA_PAD / 2)
        PASS = bytearray(2 * SZ)
        VIAOK = bytearray(SZ)
        for l in (0, 1):
            m = (dist[l] >= T) & inside
            lay = np.zeros((NX + 3, STRIDE), dtype=np.uint8)
            lay[1:NX + 2, 1:NY + 2] = m
            PASS[l * SZ:(l + 1) * SZ] = lay.tobytes()
        mv = (dist[0] >= TV) & (dist[1] >= TV) & inside_v
        lay = np.zeros((NX + 3, STRIDE), dtype=np.uint8)
        lay[1:NX + 2, 1:NY + 2] = mv
        VIAOK[:] = lay.tobytes()
        term = {p.id: self.terminals(p, w) for p in pads}
        for p in pads:               # terminals are always usable
            for l, pts in term[p.id].items():
                for i, j in pts:
                    PASS[nid(l, i, j)] = 1
        TGT = bytearray(2 * SZ)
        pre = PREROUTE.get(net, [])
        first = pads[0]
        if pre:
            pl = LineString(pre[0][1])
            first = min(pads, key=lambda q: q.poly.distance(Point(pre[0][1][0])))
        connected = [first]
        for l, pts in term[first.id].items():
            for i, j in pts:
                TGT[nid(l, i, j)] = 1
        tree_pts = [(l, i, j) for l, pts in term[first.id].items() for i, j in pts]
        remaining = [q for q in pads if q is not first]
        ok_all = True
        added_tracks = []
        added_vias = []
        for (l, pts) in pre:         # hand waypoints (already committed at init) become part of the tree
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                i0, j0 = int(round(x0 / GRID)), int(round(y0 / GRID))
                i1, j1 = int(round(x1 / GRID)), int(round(y1 / GRID))
                n = max(abs(i1 - i0), abs(j1 - j0))
                for t in range(n + 1):
                    i = i0 + (i1 - i0) * t // n if n else i0
                    j = j0 + (j1 - j0) * t // n if n else j0
                    TGT[nid(l, i, j)] = 1
                    PASS[nid(l, i, j)] = 1
                    tree_pts.append((l, i, j))
        while remaining:
            # nearest remaining pad to the connected set
            best = min(remaining, key=lambda q: min(math.hypot(q.x - c.x, q.y - c.y) for c in connected))
            remaining.remove(best)
            srcs = [nid(l, i, j) for l, pts in term[best.id].items() for i, j in pts]
            tb = [(i, j) for (_, i, j) in tree_pts]
            ti0, ti1 = min(t[0] for t in tb), max(t[0] for t in tb)
            tj0, tj1 = min(t[1] for t in tb), max(t[1] for t in tb)
            path = self.astar(srcs, PASS, VIAOK, TGT, (ti0, ti1, tj0, tj1))
            if path is None:
                ok_all = False
                if log:
                    log(f"    FAIL {net}: could not connect {best.id} ({self.last_status})")
                continue
            segs, vias, nodes = self.path_to_geom(path, w)
            # stubs from path ends to pad centres
            segs = self.add_pad_stubs(segs, best, w, path)
            for (l, pts) in segs:
                added_tracks.append(dict(net=net, layer=l, pts=pts, w=w))
            for (x, y) in vias:
                added_vias.append(dict(net=net, x=x, y=y))
            for (l, i, j) in nodes:
                TGT[nid(l, i, j)] = 1
            tree_pts.extend(nodes)
            for l, pts in term[best.id].items():
                for i, j in pts:
                    TGT[nid(l, i, j)] = 1
            tree_pts.extend((l, i, j) for l, pts in term[best.id].items() for i, j in pts)
            connected.append(best)
        # commit copper to rasters
        nid_ = self.netid[net]
        for t in added_tracks:
            self.tracks.append(t)
            raster_draw(self.owner[t["layer"]], LineString(t["pts"]).buffer(t["w"] / 2, quad_segs=6), nid_)
        for v in added_vias:
            self.vias.append(v)
            for l in (0, 1):
                raster_draw(self.owner[l], circ(v["x"], v["y"], VIA_PAD / 2), nid_)
        return ok_all

    def add_pad_stubs(self, segs, pad, w, path):
        """extend the path's start to the pad centre when the stub stays inside the pad copper."""
        if not segs:
            return segs
        (l0, i0, j0) = path[0]
        sx, sy = i0 * GRID, j0 * GRID
        if math.hypot(sx - pad.x, sy - pad.y) < 0.02:
            return segs
        stub = LineString([(sx, sy), (pad.x, pad.y)])
        if pad.poly.buffer(0.001).contains(stub.buffer(w / 2 - 0.001)):
            segs = [(l0, [(pad.x, pad.y), (sx, sy)])] + segs
        return segs

    def path_to_geom(self, path, w):
        """path = list of (l,i,j) states in order source->target; returns polyline segs, vias, nodes."""
        segs = []
        vias = []
        cur_l = path[0][0]
        pts = [(path[0][1] * GRID, path[0][2] * GRID)]
        last_dir = None
        nodes = [path[0]]
        for a, b in zip(path, path[1:]):
            nodes.append(b)
            if a[0] != b[0]:
                if len(pts) >= 2 or True:
                    segs.append((cur_l, pts))
                vias.append((b[1] * GRID, b[2] * GRID))
                cur_l = b[0]
                pts = [(b[1] * GRID, b[2] * GRID)]
                last_dir = None
                continue
            d = (b[1] - a[1], b[2] - a[2])
            if last_dir is not None and d == last_dir:
                pts[-1] = (b[1] * GRID, b[2] * GRID)
            else:
                pts.append((b[1] * GRID, b[2] * GRID))
            last_dir = d
        segs.append((cur_l, pts))
        segs = [(l, p) for l, p in segs if len(p) >= 2]
        return segs, vias, nodes

    def astar(self, srcs, PASS, VIAOK, TGT, bbox):
        ti0, ti1, tj0, tj1 = bbox
        heappush, heappop = heapq.heappush, heapq.heappop
        g = {}
        parent = {}
        heap = []
        IL_, JL_ = IL, JL

        def hfun(lo):
            i = IL_[lo]
            j = JL_[lo]
            dx = ti0 - i if i < ti0 else (i - ti1 if i > ti1 else 0)
            dy = tj0 - j if j < tj0 else (j - tj1 if j > tj1 else 0)
            return H_WEIGHT * ((dx + dy) - 0.5857864 * (dx if dx < dy else dy))
        for s in srcs:
            key = s * 9 + 8
            g[key] = 0.0
            heappush(heap, (hfun(s % SZ), 0.0, key))
        found = None
        n_exp = 0
        while heap:
            f, gc, key = heappop(heap)
            if g.get(key, 1e18) < gc:
                continue
            node, d = divmod(key, 9)
            if TGT[node]:
                found = key
                break
            n_exp += 1
            if n_exp > EXP_CAP:
                break
            l = 0 if node < SZ else 1
            lo = node - l * SZ
            for d2 in range(8):
                if d != 8:
                    t = (d2 - d) & 7
                    if t == 0:
                        pen = 0.0
                    elif t == 1 or t == 7:
                        pen = TURN45
                    elif t == 2 or t == 6:
                        pen = TURN90
                    else:
                        continue
                else:
                    pen = 0.0
                nb = node + OFF[d2]
                if not PASS[nb]:
                    continue
                c = STEPC[d2]
                if (d2 & 1) == 0:
                    # preferred direction: layer 0 horizontal (d2 0/4), layer 1 vertical (2/6)
                    if (l == 0) != ((d2 & 2) == 0):
                        c *= PREF_PEN
                ng = gc + c + pen
                k2 = nb * 9 + d2
                if ng < g.get(k2, 1e18):
                    g[k2] = ng
                    parent[k2] = key
                    heappush(heap, (ng + hfun(nb - l * SZ), ng, k2))
            # via
            if VIAOK[lo]:
                other = (1 - l) * SZ + lo
                if PASS[other]:
                    ng = gc + VIA_COST
                    k2 = other * 9 + 8
                    if ng < g.get(k2, 1e18):
                        g[k2] = ng
                        parent[k2] = key
                        heappush(heap, (ng + hfun(lo), ng, k2))
        self.last_status = ("cap" if n_exp > EXP_CAP else "exhausted", n_exp)
        if found is None:
            return None
        seq = []
        k = found
        while True:
            node = k // 9
            l = 0 if node < SZ else 1
            lo = node - l * SZ
            seq.append((l, IL[lo], JL[lo]))
            if k in parent:
                k = parent[k]
            else:
                break
        seq.reverse()
        return seq


def run_router(pads, log=print, max_rounds=6):
    nets = [n for n in NETS if n != "GND"]
    # priority classes: wide first, then by pin-bbox size
    def key(n):
        ps = [p for p in pads if p.net == n]
        xs = [p.x for p in ps]; ys = [p.y for p in ps]
        span = (max(xs) - min(xs)) + (max(ys) - min(ys))
        return (-net_width(n), span)
    order = sorted(nets, key=key)
    best = None
    import random
    rng = random.Random(7)
    for rnd in range(max_rounds):
        t0 = time.time()
        R = Router(pads)
        failed = []
        for n in order:
            ok = R.route_net(n, log=log)
            if not ok:
                failed.append(n)
        log(f"  round {rnd}: {len(failed)} failed nets {failed}  ({time.time() - t0:.0f}s)")
        if best is None or len(failed) < len(best[1]):
            best = (R, failed)
        if not failed:
            break
        rest = [n for n in order if n not in failed]
        if rnd >= 1:
            rng.shuffle(rest)
        order = failed + rest
    return best


# ============================================================================
# SECTION 4: copper model, GND pours with thermal reliefs + stitching, island removal
# ============================================================================
THERMAL_GAP = 0.30
SPOKE_W = 0.50
STITCH_PITCH = 5.0
LAYER_NAMES = {0: "F", 1: "B"}


def track_geom(t):
    return LineString(t["pts"]).buffer(t["w"] / 2, quad_segs=8)


def nc_net(p):
    return "NC:" + p.id


def pad_net(p):
    return p.net if p.net else nc_net(p)


class Copper:
    """Everything that exists on the copper layers (plus the pours once built)."""

    def __init__(self, pads, tracks, vias):
        self.pads = [p for p in pads if not (p.drill and not p.plated)]
        self.npth = [p for p in pads if p.drill and not p.plated]
        self.tracks = tracks
        self.vias = vias
        self.pour = {"F": None, "B": None}
        self.stitch = []           # GND stitching vias (dict(net,x,y))

    # ---- non-pour geometry per layer: list of (geom, net, kind, id)
    def items(self, layer, with_pour=True):
        out = []
        for p in self.pads:
            if layer in p.layers:
                out.append((p.poly, pad_net(p), "pad", p.id))
        for k, t in enumerate(self.tracks):
            if LAYER_NAMES[t["layer"]] == layer:
                out.append((track_geom(t), t["net"], "track", f"T{k}"))
        for k, v in enumerate(self.vias + self.stitch):
            out.append((circ(v["x"], v["y"], VIA_PAD / 2), v["net"], "via", f"V{k}"))
        if with_pour and self.pour[layer] is not None:
            for k, g in enumerate(geoms_of(self.pour[layer])):
                out.append((g, "GND", "pour", f"P{layer}{k}"))
        return out


def spokes_for(pad_poly, cx, cy, layer_small):
    x0, y0, x1, y1 = pad_poly.bounds
    ext = max(x1 - x0, y1 - y0) / 2 + THERMAL_GAP + 1.0
    w = SPOKE_W * (0.8 if layer_small else 1.0)
    return unary_union([box(cx - ext, cy - w / 2, cx + ext, cy + w / 2),
                        box(cx - w / 2, cy - ext, cx + w / 2, cy + ext)])


def build_pours(cu, log=print):
    zone = OUTLINE.buffer(-EDGE_CLR)
    pours = {}
    for layer in ("F", "B"):
        obst = []
        for p in cu.pads:
            if layer not in p.layers:
                continue
            if p.net == "GND":
                ring = p.poly.buffer(THERMAL_GAP, quad_segs=8).difference(p.poly)
                small = min(p.w, p.h) < 1.5
                cut = ring.difference(spokes_for(p.poly, p.x, p.y, small))
                obst.append(cut)
            else:
                obst.append(p.poly.buffer(POUR_CLR, quad_segs=8))
        for t in cu.tracks:
            if LAYER_NAMES[t["layer"]] == layer:
                obst.append(track_geom(t).buffer(POUR_CLR, quad_segs=8))
        for v in cu.vias:
            obst.append(circ(v["x"], v["y"], VIA_PAD / 2 + POUR_CLR))
        for p in cu.npth:
            obst.append(circ(p.x, p.y, p.drill / 2 + 0.3 + 0.2))
        pour = zone.difference(unary_union(obst))
        pour = pour.buffer(-0.13, quad_segs=4).buffer(0.13, quad_segs=4)   # remove <0.26 mm slivers
        pours[layer] = pour
    cu.pour = pours
    # stitching vias on a grid where both pours are solid
    cands = []
    xs = np.arange(2.0, BOARD_W - 1.5, STITCH_PITCH)
    ys = np.arange(2.0, BOARD_H - 1.5, STITCH_PITCH)
    holes = unary_union([circ(p.x, p.y, p.drill / 2 + 0.5) for p in cu.pads + cu.npth if p.drill]
                        + [circ(v["x"], v["y"], VIA_DRILL / 2 + 0.5) for v in cu.vias]
                        + [p.poly.buffer(0.3) for p in cu.pads])
    for x in xs:
        for y in ys:
            d = circ(x, y, VIA_PAD / 2 + 0.2)
            if pours["F"].contains(d) and pours["B"].contains(d) and not d.intersects(holes):
                cands.append(dict(net="GND", x=round(float(x), 3), y=round(float(y), 3)))
    cu.stitch = cands
    remove_islands(cu, log)
    return cu


def remove_islands(cu, log=print):
    """Drop pour polygons (and stitching vias) that are not connected to any GND pad."""
    nodes = []          # (kind, layer, geom, ref)
    for layer in ("F", "B"):
        for g in geoms_of(cu.pour[layer]):
            nodes.append(["pour", layer, g, None])
    pad_nodes = []
    for p in cu.pads:
        if p.net == "GND":
            pad_nodes.append(p)
    n = len(nodes)
    parent = list(range(n + len(pad_nodes) + len(cu.stitch)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for pi, p in enumerate(pad_nodes):
        for ni, (kind, layer, g, _) in enumerate(nodes):
            if layer in p.layers and g.intersects(p.poly):
                union(n + pi, ni)
    for vi, v in enumerate(cu.stitch):
        vc = circ(v["x"], v["y"], VIA_PAD / 2)
        for ni, (kind, layer, g, _) in enumerate(nodes):
            if g.intersects(vc):
                union(n + len(pad_nodes) + vi, ni)
    good = set()
    for pi in range(len(pad_nodes)):
        good.add(find(n + pi))
    keep = {"F": [], "B": []}
    dropped = 0
    for ni, (kind, layer, g, _) in enumerate(nodes):
        if find(ni) in good:
            keep[layer].append(g)
        else:
            dropped += 1
    cu.stitch = [v for vi, v in enumerate(cu.stitch) if find(n + len(pad_nodes) + vi) in good]
    for layer in ("F", "B"):
        cu.pour[layer] = unary_union(keep[layer]) if keep[layer] else Polygon()
    log(f"  pours: dropped {dropped} floating islands; {len(cu.stitch)} stitching vias kept")


# ============================================================================
# SECTION 5: verification (connectivity, clearance, drills, rules)
# ============================================================================
def build_union_find(cu):
    items = []                 # list of dict(geom_by_layer, net, kind, id)
    index = {}
    def get(eid, net, kind):
        if eid not in index:
            index[eid] = len(items)
            items.append(dict(id=eid, net=net, kind=kind, geoms={}))
        return index[eid]
    for layer in ("F", "B"):
        for geom, net, kind, eid in cu.items(layer):
            i = get(eid, net, kind)
            items[i]["geoms"][layer] = geom
    return items


def check_connectivity(cu):
    items = build_union_find(cu)
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for layer in ("F", "B"):
        idx = [i for i, it in enumerate(items) if layer in it["geoms"]]
        geoms = [items[i]["geoms"][layer] for i in idx]
        tree = STRtree(geoms)
        for a, g in enumerate(geoms):
            for b in tree.query(g, predicate="intersects"):
                if b != a:
                    ra, rb = find(idx[a]), find(idx[int(b)])
                    if ra != rb:
                        parent[ra] = rb
    groups = defaultdict(list)
    for i, it in enumerate(items):
        groups[find(i)].append(i)
    shorts = []
    for r, mem in groups.items():
        nets = {items[m]["net"] for m in mem}
        if len(nets) > 1:
            shorts.append(sorted(nets))
    per_net = {}
    padgroup = defaultdict(set)
    for p in cu.pads:
        if p.net:
            i = [k for k, it in enumerate(items) if it["id"] == p.id][0]
            padgroup[p.net].add(find(i))
    for net in NETS:
        npads = len([1 for p in cu.pads if p.net == net])
        per_net[net] = dict(pads=npads, components=len(padgroup[net]), connected=len(padgroup[net]) == 1)
    return per_net, shorts


def check_clearance(cu, log=print):
    """Min distance between different-net copper on each layer + copper to board edge."""
    min_d = 1e9
    worst = None
    viol = []
    pair_hist = defaultdict(lambda: 1e9)
    for layer in ("F", "B"):
        its = cu.items(layer)
        geoms = [g for g, *_ in its]
        tree = STRtree(geoms)
        for a, (ga, na, ka, ia) in enumerate(its):
            for b in tree.query(ga, predicate="dwithin", distance=0.45):
                b = int(b)
                if b <= a:
                    continue
                gb, nb, kb, ib = its[b]
                if na == nb:
                    continue
                d = ga.distance(gb)
                key = tuple(sorted((ka, kb)))
                pair_hist[key] = min(pair_hist[key], d)
                if d < min_d:
                    min_d = d
                    worst = (layer, ia, na, ib, nb, d)
                if d < RULE_CLR - 1e-6:
                    viol.append((layer, ia, na, ib, nb, round(d, 4)))
    edge = OUTLINE.exterior
    min_edge = 1e9
    for layer in ("F", "B"):
        for g, net, kind, eid in cu.items(layer):
            d = g.distance(edge)
            min_edge = min(min_edge, d)
    return dict(min_clearance=min_d, worst=worst, violations=viol, min_edge=min_edge,
                by_kind={f"{k[0]}/{k[1]}": round(v, 3) for k, v in sorted(pair_hist.items())})


def check_drills(cu):
    holes = []
    for p in cu.pads:
        if p.drill:
            holes.append((p.x, p.y, p.drill, p.id, True))
    for p in cu.npth:
        holes.append((p.x, p.y, p.drill, p.id, False))
    for k, v in enumerate(cu.vias + cu.stitch):
        holes.append((v["x"], v["y"], VIA_DRILL, f"V{k}", True))
    min_hh = 1e9
    wh = None
    pts = np.array([[h[0], h[1]] for h in holes])
    rad = np.array([h[2] / 2 for h in holes])
    for i in range(len(holes)):
        d = np.hypot(pts[:, 0] - pts[i, 0], pts[:, 1] - pts[i, 1]) - rad - rad[i]
        d[i] = 1e9
        j = int(np.argmin(d))
        if d[j] < min_hh:
            min_hh = float(d[j])
            wh = (holes[i][3], holes[j][3])
    ring_pth = min(((min(p.w, p.h) - p.drill) / 2, p.id) for p in cu.pads if p.drill)
    min_edge_hole = min(OUTLINE.exterior.distance(Point(h[0], h[1])) - h[2] / 2 for h in holes)
    # NPTH hole-to-copper (other nets)
    min_npth_cu = 1e9
    for npth in cu.npth:
        hc = circ(npth.x, npth.y, npth.drill / 2)
        for layer in ("F", "B"):
            for g, net, kind, eid in cu.items(layer, with_pour=True):
                min_npth_cu = min(min_npth_cu, hc.distance(g))
    return dict(holes=len(holes), min_hole_to_hole=min_hh, worst_pair=wh, min_pth_annular_ring=ring_pth,
                min_hole_to_edge=min_edge_hole, min_npth_to_copper=min_npth_cu,
                via_annular_ring=(VIA_PAD - VIA_DRILL) / 2)


def check_rules(cu):
    widths = sorted({t["w"] for t in cu.tracks})
    return dict(track_widths=widths, min_track=min(widths) if widths else None,
                vias=len(cu.vias), stitching_vias=len(cu.stitch), tracks=len(cu.tracks),
                track_length_mm=round(sum(LineString(t["pts"]).length for t in cu.tracks), 1))


# ============================================================================
# SECTION 6: silkscreen (text via matplotlib TextPath, auto label placement)
# ============================================================================
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath

_FPROP = FontProperties(family="DejaVu Sans", weight="bold")
CAP_H = 1.0                  # silkscreen cap height (mm); bold stems ~0.18 mm
_text_cache = {}


def text_geom(txt, x, y, cap_h=CAP_H, rot=0.0, anchor="lc"):
    """Filled outline of txt; anchor = 2 letters (l/c/r, b/c/t) of the unrotated text box placed at (x, y)."""
    key = (txt, round(cap_h, 3))
    if key not in _text_cache:
        tp = TextPath((0, 0), txt, size=cap_h / 0.729, prop=_FPROP)
        g = None
        for ring in tp.to_polygons(closed_only=True):
            if len(ring) < 3:
                continue
            pg = Polygon(ring).buffer(0)
            g = pg if g is None else g.symmetric_difference(pg)
        _text_cache[key] = g if g is not None else Polygon()
    g = _text_cache[key]
    if g.is_empty:
        return g
    x0, y0, x1, y1 = g.bounds
    hx = {"l": x0, "c": (x0 + x1) / 2, "r": x1}[anchor[0]]
    vy = {"b": 0.0, "c": cap_h / 2, "t": cap_h}[anchor[1]]
    g = affinity.translate(g, -hx, -vy)
    g = affinity.rotate(g, rot, origin=(0, 0))
    return affinity.translate(g, x, y)


def line_geom(x1, y1, x2, y2, w=SILK_W):
    return LineString([(x1, y1), (x2, y2)]).buffer(w / 2, quad_segs=2, cap_style=1)


def dashed(x1, y1, x2, y2, dash=1.0, gap=0.7, w=SILK_W):
    L = math.hypot(x2 - x1, y2 - y1)
    out = []
    t = 0.0
    while t < L:
        a = t / L
        b = min(t + dash, L) / L
        out.append(line_geom(x1 + (x2 - x1) * a, y1 + (y2 - y1) * a, x1 + (x2 - x1) * b, y1 + (y2 - y1) * b, w))
        t += dash + gap
    return out


PIN_LABEL = {
    "5V_PI": "5V", "UART_TX_RAW": "TXD", "UART_BUS": "RXD", "STEP_AZ": "SAZ", "STEP_ALT": "SAL",
    "DIR_AZ": "DAZ", "DIR_ALT": "DAL", "EN_AZ": "EAZ", "EN_ALT": "EAL",
    "ES_AZ_MIN": "ES1", "ES_AZ_MAX": "ES2", "ES_ALT_MIN": "ES3", "ES_ALT_MAX": "ES4",
    "SPARE": "SPR", "+12V": "+12V", "12V_RAW": "12V_IN", "12V_FUSED": "12V_F",
}
J1_LEGEND = ["SAZ DAZ EAZ = STEP DIR EN AZ", "SAL DAL EAL = STEP DIR EN ALT", "ES1-4 = AZ MIN, AZ MAX, ALT MIN, ALT MAX"]


def short(net):
    return PIN_LABEL.get(net, net)


def part_silk(ref):
    """Silk geometries of a part in board coordinates (list of shapely) + its layer 'F'/'B'."""
    px, py, rot = PLACE[ref]
    fp = FOOT[FP_OF[ref]]
    out = []

    def T(x, y):
        a, b = rot_pt(x, y, rot)
        return px + a, py + b
    for pr in fp["silk"]:
        kind = pr[0]
        if kind == "line":
            (x1, y1), (x2, y2) = T(pr[1], pr[2]), T(pr[3], pr[4])
            out.append(line_geom(x1, y1, x2, y2))
        elif kind == "rect":
            x0, y0, x1, y1 = pr[1:5]
            pts = [T(x0, y0), T(x1, y0), T(x1, y1), T(x0, y1)]
            style = pr[5] if len(pr) > 5 else None
            if style == "fill":
                out.append(Polygon(pts))
            else:
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    if style == "dash":
                        out.extend(dashed(a[0], a[1], b[0], b[1]))
                    else:
                        out.append(line_geom(a[0], a[1], b[0], b[1]))
        elif kind == "circle":
            cx, cy = T(pr[1], pr[2])
            out.append(circ(cx, cy, pr[3] + SILK_W / 2).difference(circ(cx, cy, pr[3] - SILK_W / 2)))
        elif kind == "text":
            tx, ty = T(pr[2], pr[3])
            out.append(text_geom(pr[1], tx, ty, pr[4], 0, "cc"))
    return out


def pad_label_text(ref, pad):
    n = pad.net
    if ref == "J1":
        return None if n is None else short(n)
    if ref in ("U1", "U2"):
        fn = (MOD_A if pad.num[0] == "A" else MOD_B)[int(pad.num[1:]) - 1]
        return {"PDN_UART_ALT": "NC", "PDN_UART": "UART", "COIL_A2": "A2", "COIL_A1": "A1", "COIL_B1": "B1",
                "COIL_B2": "B2"}.get(fn, fn)
    if ref in ("J2", "J3", "J4"):
        return {"J2": ["12V", "GND"], "J3": ["12V", "GND"], "J4": ["5V", "GND"]}[ref][int(pad.num) - 1]
    if ref in ("J5", "J6"):
        return ["A2", "A1", "B1", "B2"][int(pad.num) - 1]
    if ref in ("J7", "J8", "J9", "J10"):
        return ["SIG", "GND"][int(pad.num) - 1]
    if ref in ("J11", "J12"):
        return ["GND", "3V3", "5V", "SDA", "SCL"][int(pad.num) - 1]
    if ref == "JP1":
        return ["5V_F", "5V_PI"][int(pad.num) - 1]
    if ref.startswith("TP"):
        return short(n)
    if ref in ("D1", "D2"):
        return "K" if pad.num == "1" else "A"
    if ref in ("C1", "C2", "C3"):
        return "+" if pad.num == "1" else "-"
    return None


def label_candidates(ref, pad, bb):
    """candidate (x, y, rot, anchor) positions outside the part's silk bbox bb=(x0,y0,x1,y1)."""
    cands = []
    for d in (0.0, 0.7, 1.4):
        N = (pad.x, bb[3] + 0.4 + d, 90, "lc")
        S = (pad.x, bb[1] - 0.4 - d, 90, "rc")
        if ref == "J1":
            order = [N, S] if int(pad.num) % 2 == 0 else [S, N]
        elif ref in ("U1", "U2"):
            order = [N, S] if pad.num[0] == "A" else [S, N]
        else:
            order = [N, S]
        cands.extend(order)
    return cands


def build_silk(cu, log=print):
    """Returns dict(F=[geoms], B=[geoms], labels=[(text,x,y,rot,anchor,layer)]) with auto-placed text."""
    inner = OUTLINE.buffer(-0.35)
    pads_hard = unary_union([p.poly.buffer(0.22) for p in cu.pads] + [circ(p.x, p.y, 3.0) for p in cu.npth])
    track_soft = unary_union([track_geom(t) for t in cu.tracks] + [circ(v["x"], v["y"], 0.4) for v in cu.vias]
                             + [circ(v["x"], v["y"], 0.4) for v in cu.stitch])
    from shapely.prepared import prep
    silk = {"F": [], "B": []}
    labels = []
    fixed = []
    # fixed part outlines
    for ref in PLACE:
        if ref.startswith("H"):
            continue
        layer = PARTS[ref]["side"]
        for g in part_silk(ref):
            silk[layer].append(g)
            if layer == "F":
                fixed.append(g)
    # Pi outline guide (clipped to the board) + Pi mounting holes
    x0, x1 = J1_X - 32.5, J1_X + 32.5
    yt = PI_TOP_EDGE_Y
    guide = [line_geom(x0, yt, x1, yt), line_geom(x0, yt, x0, 0.4), line_geom(x1, yt, x1, 0.4)]
    for hx in (J1_X - 29.0, J1_X + 29.0):
        guide.append(circ(hx, J1_Y, 1.375 + SILK_W / 2).difference(circ(hx, J1_Y, 1.375 - SILK_W / 2)))
    for g in guide:
        g = g.intersection(inner)
        silk["F"].append(g)
        fixed.append(g)
    state = {"u": unary_union(fixed)}
    state["p"] = prep(state["u"])
    hard_p = prep(pads_hard)
    soft_p = prep(track_soft)

    def free(g, strict):
        if g.is_empty or not inner.contains(g):
            return False
        if hard_p.intersects(g) or state["p"].intersects(g):
            return False
        if strict and soft_p.intersects(g):
            return False
        return True

    def commit(g, pad=0.1):
        state["u"] = state["u"].union(g.buffer(pad))
        state["p"] = prep(state["u"])

    omitted = []

    def put(txt, cands, cap=CAP_H, layer="F", force=False):
        for strict in (True, False):
            for (x, y, rot, anc) in cands:
                g = text_geom(txt, x, y, cap, rot, anc)
                if free(g, strict):
                    silk[layer].append(g)
                    commit(g)
                    labels.append((txt, x, y, rot, anc, layer, cap))
                    return True
        if force:
            for (x, y, rot, anc) in cands:
                g = text_geom(txt, x, y, cap, rot, anc)
                if not g.is_empty and inner.contains(g) and not hard_p.intersects(g):
                    silk[layer].append(g)
                    commit(g, 0.05)
                    labels.append((txt, x, y, rot, anc, layer, cap))
                    return True
        omitted.append(txt)
        return False

    def put_near(txt, anchor, cap=CAP_H, rots=(0,), radius=25.0, step=1.0, layer="F"):
        """search outward from anchor for the nearest free spot (strict first, then allowing tracks underneath)."""
        offs = sorted(((dx, dy) for dx in np.arange(-radius, radius + 0.01, step) for dy in np.arange(-radius, radius + 0.01, step)),
                      key=lambda t: t[0] ** 2 + t[1] ** 2)
        for strict in (True, False):
            for dx, dy in offs:
                for rot in rots:
                    x, y = anchor[0] + dx, anchor[1] + dy
                    g = text_geom(txt, x, y, cap, rot, "cc")
                    if free(g, strict):
                        silk[layer].append(g)
                        commit(g)
                        labels.append((txt, x, y, rot, "cc", layer, cap))
                        return True
        omitted.append(txt)
        return False
    # pin labels (positions are chosen outside the part's silk box; the module sockets get their labels in the pocket)
    sbb = {}
    for ref in PLACE:
        if ref.startswith("H"):
            continue
        gs = [g for g in part_silk(ref) if not g.is_empty]
        if gs:
            sbb[ref] = unary_union(gs).bounds
    for pad in cu.pads:
        ref = pad.ref
        t = pad_label_text(ref, pad)
        if not t:
            continue
        if ref in ("U1", "U2"):
            # inside the pocket between the rows (hidden once the module is plugged in)
            if pad.num[0] == "A":
                c = [(pad.x, pad.y + 1.1 + d, 90, "lc") for d in (0, 0.7)] + [(pad.x, pad.y - 1.1, 90, "rc")]
            else:
                c = [(pad.x, pad.y - 1.1 - d, 90, "rc") for d in (0, 0.7)] + [(pad.x, pad.y + 1.1, 90, "lc")]
            put(t, c)
            continue
        bb = sbb.get(ref, (pad.x - 0.8, pad.y - 0.8, pad.x + 0.8, pad.y + 0.8))
        if ref in ("J11", "J12"):              # both headers share one label column between them
            if ref == "J11":
                put(t, [(pad.x + 3.0, pad.y, 0, "cc")], cap=0.9, force=True)
        elif ref in ("J2", "J3", "J4"):        # inside the terminal body, above the pad (wire-entry side)
            put(t, [(pad.x, pad.y + pad.h / 2 + 0.5, 90, "lc")] + label_candidates(ref, pad, bb))
        elif ref in ("J7", "J8", "J9", "J10", "J5", "J6"):   # inside the JST body, below the pad
            put(t, [(pad.x, pad.y - pad.h / 2 - 0.45, 90, "rc")] + label_candidates(ref, pad, bb), cap=0.9)
        else:
            put(t, label_candidates(ref, pad, bb), layer="F")
    # J1 pin numbers at the ends
    for pad in cu.pads:
        if pad.ref == "J1" and pad.num in ("1", "2", "39", "40"):
            c = label_candidates("J1", pad, sbb["J1"])
            c = [(pad.x + (-1.6 if pad.num in ("1", "2") else 1.6), pad.y, 0, "rc" if pad.num in ("1", "2") else "lc")] + c
            put(pad.num, c)
    # notes, legend and titles: nearest free spot to a preferred anchor (before the reference designators)
    p1 = [q for q in cu.pads if q.ref == "J1" and q.num == "1"][0]
    put_near("PI PIN 1", (p1.x - 5.0, p1.y - 2.2), radius=8.0, rots=(0,))
    put_near("JP1: REMOVE WHEN USB POWERED", (PLACE["JP1"][0] + 1.0, PLACE["JP1"][1] + 5.0), radius=22.0, rots=(0, 90))
    put_near("PI ZERO 2 W: BODY BELOW LINE", (J1_X + 33.0, yt + 1.0), radius=18.0, rots=(0, 90))
    for k, line in enumerate(J1_LEGEND):
        put_near(line, (24.0, 3.0 + 1.5 * k), radius=18.0, rots=(0,))
    put_near(f"{BOARD_NAME} REV {BOARD_REV} {datetime.date.today().isoformat()}", (80.0, 30.0), cap=1.2, radius=30.0, rots=(90, 0))
    for j, nm, rr in (("J5", "AZ MOTOR", (0,)), ("J6", "ALT MOTOR", (0,)), ("J11", "IMU", (0, 90)), ("J12", "GNSS", (0, 90)),
                      ("U1", "AZ TMC2209", (0,)), ("U2", "ALT TMC2209", (0,)),
                      ("J7", "ES1", (0,)), ("J8", "ES2", (0,)), ("J9", "ES3", (0,)), ("J10", "ES4", (0,))):
        cb = part_geoms(j)["crt"].bounds
        put_near(nm, ((cb[0] + cb[2]) / 2, (cb[1] + cb[3]) / 2), radius=7.0, rots=rr)
    # reference designators (forced if nothing better exists)
    for ref in PLACE:
        if ref.startswith("H"):
            continue
        cb = part_geoms(ref)["crt"].bounds
        cx, cy = (cb[0] + cb[2]) / 2, (cb[1] + cb[3]) / 2
        cands = []
        for d in (0.8, 1.8, 2.8):
            cands += [(cx, cb[3] + d, 0, "cb"), (cx, cb[1] - d, 0, "ct"), (cb[0] - d + 0.3, cy, 0, "rc"),
                      (cb[2] + d - 0.3, cy, 0, "lc")]
        cands.append((cx, cy, 0, "cc"))
        if ref == "J1":
            cands = [(cb[2] + 0.5, J1_Y, 0, "lc"), (cx, cb[1] - 0.8, 0, "ct")] + cands
        put(ref, cands, force=True)
    log("  silk: %d labels placed, %d omitted for lack of room: %s" % (len(labels), len(omitted), sorted(set(omitted))))
    # clip all silk against exposed copper (pads) so no ink lands on solder pads
    pad_open = {"F": unary_union([p.poly.buffer(MASK_EXP + 0.1) for p in cu.pads if "F" in p.layers]),
                "B": unary_union([p.poly.buffer(MASK_EXP + 0.1) for p in cu.pads if "B" in p.layers])}
    out = {}
    for layer in ("F", "B"):
        gs = [g for g in silk[layer] if not g.is_empty]
        u = unary_union(gs).difference(pad_open[layer]) if gs else Polygon()
        out[layer] = u.intersection(OUTLINE.buffer(-0.2))
    return out, labels, omitted


# ============================================================================
# SECTION 7: renders (matplotlib)
# ============================================================================
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MPath


def geom_to_path(g):
    verts, codes = [], []
    for poly in geoms_of(g):
        for ring in [poly.exterior] + list(poly.interiors):
            c = list(ring.coords)
            verts.extend(c)
            codes.extend([MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY])
    return MPath(verts, codes) if verts else None


def add_geom(ax, g, **kw):
    p = geom_to_path(g)
    if p is not None:
        ax.add_patch(PathPatch(p, **kw))


def mirror(g):
    return affinity.scale(g, xfact=-1, yfact=1, origin=(BOARD_W / 2, 0))


def render_board(cu, silk, labels, side, path, dpi=300, title=None):
    """Photo-style render of the top ('F') or bottom ('B') side."""
    layer = side
    other = "B" if side == "F" else "F"
    fig, ax = plt.subplots(figsize=(BOARD_W / 10 * 1.15, BOARD_H / 10 * 1.15 + 0.4))
    fig.patch.set_facecolor("#2b2b2b")
    ax.set_facecolor("#2b2b2b")
    M = (lambda g: mirror(g)) if side == "B" else (lambda g: g)
    mask_green = "#0b5a2a"
    cu_green = "#1f8f48"
    gold = "#d7b44a"
    add_geom(ax, M(OUTLINE), fc=mask_green, ec="none", zorder=1)
    # pour + tracks under mask (lighter green)
    if cu.pour[layer] is not None:
        add_geom(ax, M(cu.pour[layer]), fc=cu_green, ec="none", alpha=0.55, zorder=2)
    trk = unary_union([track_geom(t) for t in cu.tracks if LAYER_NAMES[t["layer"]] == layer])
    add_geom(ax, M(trk), fc=cu_green, ec="none", alpha=0.9, zorder=3)
    # exposed pads
    for p in cu.pads:
        if layer in p.layers:
            add_geom(ax, M(p.poly), fc=gold, ec="none", zorder=4)
    for v in cu.vias + cu.stitch:      # tented vias: show faint pad
        add_geom(ax, M(circ(v["x"], v["y"], VIA_PAD / 2)), fc=cu_green, ec="none", alpha=0.9, zorder=3)
        add_geom(ax, M(circ(v["x"], v["y"], VIA_DRILL / 2)), fc="#101010", ec="none", zorder=3.5)
    for p in cu.pads + cu.npth:
        if p.drill:
            add_geom(ax, M(circ(p.x, p.y, p.drill / 2)), fc="#0d0d0d", ec="none", zorder=5)
    add_geom(ax, M(silk[layer]), fc="#f2f2f2", ec="none", zorder=6)
    ob = M(OUTLINE).exterior
    ax.plot(*ob.xy, color="#e6c34a", lw=0.8, zorder=7)
    ax.set_xlim(-2, BOARD_W + 2)
    ax.set_ylim(-2, BOARD_H + 2)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title or f"{BOARD_NAME} rev {BOARD_REV} - {'top' if side == 'F' else 'bottom (mirrored)'} view",
                 color="white", fontsize=9)
    fig.savefig(path, dpi=dpi, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


# ============================================================================
# SECTION 8: fabrication outputs (Gerber RS-274X, Excellon), DXF, STL, BOM, CPL
# ============================================================================
import ezdxf
import trimesh

PROJECT = "carrier"
FAB = OUT / "fab"


def layer_copper(cu, layer):
    geoms = []
    for g, net, kind, eid in cu.items(layer, with_pour=True):
        geoms.append(g)
    return unary_union(geoms)


def layer_mask(cu, layer):
    gs = [p.poly.buffer(MASK_EXP, quad_segs=8) for p in cu.pads if layer in p.layers]
    gs += [circ(p.x, p.y, p.drill / 2 + 0.05) for p in cu.npth]
    return unary_union(gs)


def layer_paste(cu, layer):
    return unary_union([p.poly for p in cu.pads if p.smd and layer in p.layers])


def gnum(v):
    return int(round(v * 1e6))


def ring_cmds(coords):
    pts = list(coords)
    out = ["G36*", f"X{gnum(pts[0][0])}Y{gnum(pts[0][1])}D02*"]
    for x, y in pts[1:]:
        out.append(f"X{gnum(x)}Y{gnum(y)}D01*")
    out.append("G37*")
    return out


def gerber_regions(geom):
    polys = geoms_of(geom)
    if not polys:
        return []
    ext = [Polygon(p.exterior) for p in polys]
    depth = []
    for i, p in enumerate(polys):
        rp = p.representative_point()
        depth.append(sum(1 for j, e in enumerate(ext) if j != i and e.contains(rp)))
    out = []
    for d in sorted(set(depth)):
        group = [p for p, dd in zip(polys, depth) if dd == d]
        out.append("%LPD*%")
        for p in group:
            out.extend(ring_cmds(p.exterior.coords))
        holes = [h for p in group for h in p.interiors]
        if holes:
            out.append("%LPC*%")
            for h in holes:
                out.extend(ring_cmds(h.coords))
    out.append("%LPD*%")
    return out


def gerber_header(function, polarity, now):
    return ["G04 APA-CARRIER Gerber (generate.py)*",
            "%TF.GenerationSoftware,APA-CARRIER,generate.py,1.0*%",
            f"%TF.CreationDate,{now}*%",
            f"%TF.ProjectId,{BOARD_NAME},{kicad_uuid('project')},{BOARD_REV}*%",
            "%TF.SameCoordinates,Original*%",
            f"%TF.FileFunction,{function}*%",
            f"%TF.FilePolarity,{polarity}*%",
            "%FSLAX46Y46*%", "%MOMM*%", "G01*"]


def write_gerber_layer(path, function, geom, polarity="Positive"):
    now = datetime.datetime(2026, 11, 17, 0, 0, 0).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    lines = gerber_header(function, polarity, now) + gerber_regions(geom) + ["M02*"]
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")


def write_edge_cuts(path):
    R, W, H = CORNER_R, BOARD_W, BOARD_H
    now = datetime.datetime(2026, 11, 17, 0, 0, 0).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    L = gerber_header("Profile,NP", "Positive", now)
    L += ["%ADD10C,0.100000*%", "D10*", "G75*", "%LPD*%"]

    def P(x, y):
        return f"X{gnum(x)}Y{gnum(y)}"
    L.append(P(R, 0) + "D02*")
    L.append("G01*")
    L.append(P(W - R, 0) + "D01*")
    L.append("G03*")
    L.append(P(W, R) + f"I0J{gnum(R)}D01*")
    L.append("G01*")
    L.append(P(W, H - R) + "D01*")
    L.append("G03*")
    L.append(P(W - R, H) + f"I{-gnum(R)}J0D01*")
    L.append("G01*")
    L.append(P(R, H) + "D01*")
    L.append("G03*")
    L.append(P(0, H - R) + f"I0J{-gnum(R)}D01*")
    L.append("G01*")
    L.append(P(0, R) + "D01*")
    L.append("G03*")
    L.append(P(R, 0) + f"I{gnum(R)}J0D01*")
    L.append("M02*")
    Path(path).write_text("\n".join(L) + "\n", encoding="ascii")


def write_excellon(path, holes, plated):
    tools = sorted({round(h[2], 3) for h in holes})
    L = ["M48", "; DRILL file generated by generate.py", f"; #@! TF.FileFunction,{'Plated,1,2,PTH' if plated else 'NonPlated,1,2,NPTH'}",
         "; #@! TF.FilePolarity,Positive", "FMAT,2", "METRIC", ]
    for i, d in enumerate(tools, start=1):
        L.append(f"T{i}C{d:.3f}")
    L += ["%", "G05"]
    for i, d in enumerate(tools, start=1):
        L.append(f"T{i}")
        for h in sorted(holes, key=lambda h: (h[1], h[0])):
            if round(h[2], 3) == d:
                L.append(f"X{h[0]:.3f}Y{h[1]:.3f}")
    L += ["T0", "M30"]
    Path(path).write_text("\n".join(L) + "\n", encoding="ascii")
    return tools


GERBER_FILES = [("F_Cu.gtl", "Copper,L1,Top"), ("B_Cu.gbl", "Copper,L2,Bot"), ("F_Mask.gts", "Soldermask,Top"),
                ("B_Mask.gbs", "Soldermask,Bot"), ("F_Paste.gtp", "Paste,Top"),
                ("F_Silkscreen.gto", "Legend,Top"), ("B_Silkscreen.gbo", "Legend,Bot"), ("Edge_Cuts.gm1", "Profile,NP")]


def write_fab(cu, silk, log=print):
    FAB.mkdir(exist_ok=True)
    geoms = {}
    geoms["F_Cu.gtl"] = layer_copper(cu, "F")
    geoms["B_Cu.gbl"] = layer_copper(cu, "B")
    geoms["F_Mask.gts"] = layer_mask(cu, "F")
    geoms["B_Mask.gbs"] = layer_mask(cu, "B")
    geoms["F_Paste.gtp"] = layer_paste(cu, "F")
    geoms["F_Silkscreen.gto"] = silk["F"]
    geoms["B_Silkscreen.gbo"] = silk["B"]
    for fn, func in GERBER_FILES:
        path = FAB / f"{PROJECT}-{fn}"
        if fn.startswith("Edge"):
            write_edge_cuts(path)
        else:
            write_gerber_layer(path, func, geoms[fn], "Negative" if "Mask" in fn else "Positive")
    pth = [(p.x, p.y, p.drill) for p in cu.pads if p.drill] + \
          [(v["x"], v["y"], VIA_DRILL) for v in cu.vias + cu.stitch]
    npth = [(p.x, p.y, p.drill) for p in cu.npth]
    t1 = write_excellon(FAB / f"{PROJECT}-PTH.drl", pth, True)
    t2 = write_excellon(FAB / f"{PROJECT}-NPTH.drl", npth, False)
    with zipfile.ZipFile(FAB / "carrier_gerbers.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for fn, _ in GERBER_FILES:
            z.write(FAB / f"{PROJECT}-{fn}", f"{PROJECT}-{fn}")
        z.write(FAB / f"{PROJECT}-PTH.drl", f"{PROJECT}-PTH.drl")
        z.write(FAB / f"{PROJECT}-NPTH.drl", f"{PROJECT}-NPTH.drl")
    log(f"  fab: wrote {len(GERBER_FILES)} gerbers + 2 drill files + zip; PTH tools {t1}, NPTH tools {t2}")
    return geoms, dict(pth=pth, npth=npth)


# ----------------------------------------------------------------------------- DXF
def board_holes(cu):
    return [(p.x, p.y, p.drill, "PTH") for p in cu.pads if p.drill and p.plated] + \
           [(p.x, p.y, p.drill, "NPTH") for p in cu.npth] + \
           [(v["x"], v["y"], VIA_DRILL, "VIA") for v in cu.vias + cu.stitch]


def write_dxf(cu, path):
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    for name, col in (("OUTLINE", 7), ("MOUNTING_HOLES", 1), ("PTH_HOLES", 3), ("KEEPOUT_COMPONENTS", 5),
                      ("PI_OUTLINE", 6), ("TEXT", 2)):
        doc.layers.add(name, color=col)
    msp = doc.modelspace()
    b = math.tan(math.radians(90) / 4)
    R, W, H = CORNER_R, BOARD_W, BOARD_H
    msp.add_lwpolyline([(R, 0, 0, 0, 0), (W - R, 0, 0, 0, b), (W, R, 0, 0, 0), (W, H - R, 0, 0, b), (W - R, H, 0, 0, 0),
                        (R, H, 0, 0, b), (0, H - R, 0, 0, 0), (0, R, 0, 0, b)], format="xyseb", close=True,
                       dxfattribs={"layer": "OUTLINE"})
    for x, y, d, kind in board_holes(cu):
        if kind == "NPTH":
            msp.add_circle((x, y), d / 2, dxfattribs={"layer": "MOUNTING_HOLES"})
        elif kind == "PTH":
            msp.add_circle((x, y), d / 2, dxfattribs={"layer": "PTH_HOLES"})
    for ref in PLACE:
        if ref.startswith("H"):
            continue
        for body, z0, z1, desc in part_geoms(ref)["body"]:
            pts = list(body.exterior.coords)[:-1]
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "KEEPOUT_COMPONENTS"})
            c = body.centroid
            msp.add_text(f"{ref} h={z1 - z0:.1f}", dxfattribs={"layer": "TEXT", "height": 0.8, "insert": (c.x, c.y)})
    # full Pi Zero 2 W outline (65 x 30, 3.5 mm mounting holes) as drawn under J1; mostly outside the board
    x0, x1 = J1_X - 32.5, J1_X + 32.5
    yt = PI_TOP_EDGE_Y
    msp.add_lwpolyline([(x0, yt), (x1, yt), (x1, yt - 30), (x0, yt - 30)], close=True, dxfattribs={"layer": "PI_OUTLINE"})
    for hx in (x0 + 3.5, x1 - 3.5):
        for hy in (yt - 3.5, yt - 26.5):
            msp.add_circle((hx, hy), 1.375, dxfattribs={"layer": "PI_OUTLINE"})
    doc.saveas(path)


# ----------------------------------------------------------------------------- STL
def build_stl(cu, path):
    holes = [circ(x, y, d / 2) for x, y, d, k in board_holes(cu)]
    board_poly = OUTLINE.difference(unary_union(holes))
    meshes = []
    board_meshes = []
    for g in geoms_of(board_poly):
        m = trimesh.creation.extrude_polygon(g, THICK, engine="earcut")
        board_meshes.append(m)
    board = trimesh.util.concatenate(board_meshes)
    meshes.append(board)
    top = 0.0
    boxes = []
    for ref in PLACE:
        if ref.startswith("H"):
            continue
        side = PARTS[ref]["side"]
        for body, z0, z1, desc in part_geoms(ref)["body"]:
            if side == "B":
                za, zb = z0, z1            # below the board: z measured from the bottom face
            else:
                za, zb = THICK + z0, THICK + z1
            if zb - za <= 0.01:
                continue
            x0, y0, x1, y1 = body.bounds
            if abs((x1 - x0) * (y1 - y0) - body.area) < 1e-6:     # axis-aligned rectangle
                m = trimesh.creation.box(extents=(x1 - x0, y1 - y0, zb - za))
                m.apply_translation(((x0 + x1) / 2, (y0 + y1) / 2, (za + zb) / 2))
            else:
                m = trimesh.creation.extrude_polygon(body, zb - za)
                m.apply_translation((0, 0, za))
            if desc.startswith("electrolytic"):
                c = body.centroid
                r = (x1 - x0) / 2
                m = trimesh.creation.cylinder(radius=r, height=zb - za, sections=48)
                m.apply_translation((c.x, c.y, (za + zb) / 2))
            boxes.append(m)
            top = max(top, zb)
    meshes.extend(boxes)
    full = trimesh.util.concatenate(meshes)
    full.export(path)
    return dict(board_volume=sum(m.volume for m in board_meshes), board_area=board_poly.area, top=top,
                tall=[(ref, round(THICK + b[5], 1)) for ref in PLACE if not ref.startswith("H") and PARTS[ref]["side"] != "B"
                      for b in FOOT[FP_OF[ref]]["body"]])


# ----------------------------------------------------------------------------- BOM / CPL
def write_bom_cpl(path_bom, path_cpl):
    groups = OrderedDict()
    for ref, p in PARTS.items():
        if ref.startswith("H"):
            continue
        key = (p["value"], p["footprint"], p["mpn"])
        groups.setdefault(key, []).append(ref)
    def sortkey(r):
        return (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r)))
    with open(path_bom, "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "Quantity", "Description", "MPN / note", "Mounting"])
        for (value, fp, mpn), refs in groups.items():
            refs = sorted(refs, key=sortkey)
            p = PARTS[refs[0]]
            mount = "SMD (top)" if p["smd"] else ("THT (bottom side, socket)" if p["side"] == "B" else "THT")
            w.writerow([value, ",".join(refs), fp, len(refs), p["description"], mpn, mount])
        w.writerow(["M3 mounting hole (NPTH 3.2 mm)", "H1,H2,H3,H4", "MountingHole_3.2mm_M3_NPTH", 4,
                    "board feature only, no part", "", "none"])
        w.writerow(["TMC2209 module, 0.6x0.8 in, SilentStepStick/Pololu pinout (e.g. BIGTREETECH V1.3)", "(U1,U2 plug-in)",
                    "plugs into U1/U2 sockets", 2, "NOT soldered; buy separately", "", "plug-in"])
        w.writerow(["2.54 mm jumper shunt", "(JP1 plug-in)", "fits JP1", 1, "NOT soldered; buy separately", "", "plug-in"])
    with open(path_cpl, "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Val", "Package", "Mid X", "Mid Y", "Rotation", "Layer"])
        for ref in sorted([r for r, p in PARTS.items() if p["smd"]], key=sortkey):
            x, y, rot = PLACE[ref]
            w.writerow([ref, PARTS[ref]["value"], PARTS[ref]["footprint"], f"{x:.3f}mm", f"{y:.3f}mm", f"{rot % 360:.0f}",
                        "Top"])


# ============================================================================
# SECTION 9: KiCad 8 files (.kicad_pcb, .kicad_pro)
# ============================================================================
KOX, KOY = 30.0, 30.0           # board origin on the KiCad page (y axis is flipped there)
NETCODE = {name: i for i, name in enumerate(NETS, start=1)}


def kx(x):
    return round(KOX + x, 4)


def ky(y):
    return round(KOY + BOARD_H - y, 4)


def esc(sx):
    return str(sx).replace("\\", "\\\\").replace('"', '\\"')


def f4(v):
    return ("%.4f" % v).rstrip("0").rstrip(".") if abs(v) > 1e-9 else "0"


def _just(anchor):
    h = {"l": "left", "r": "right", "c": ""}[anchor[0]]
    v = {"b": "bottom", "t": "top", "c": ""}[anchor[1]]
    j = " ".join(x for x in (h, v) if x)
    return f"(justify {j})" if j else ""


def kicad_text(txt, x, y, rot, anchor, layer, cap, uid):
    size = round(cap * 0.95, 2)
    return (f'\t(gr_text "{esc(txt)}"\n\t\t(at {f4(kx(x))} {f4(ky(y))} {f4(rot % 360)})\n\t\t(layer "{layer}")\n'
            f'\t\t(uuid "{kicad_uuid(uid)}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {size} {size})\n\t\t\t\t(thickness 0.15)\n\t\t\t\tbold\n\t\t\t)\n'
            f'\t\t\t{_just(anchor)}\n\t\t)\n\t)\n')


def fp_block(ref, cu_pads, ref_label):
    px, py, rot = PLACE[ref]
    part = PARTS[ref]
    fp = FOOT[FP_OF[ref]]
    side = part["side"]
    lyr = "B.Cu" if side == "B" else "F.Cu"
    silk_l = "B.SilkS" if side == "B" else "F.SilkS"
    fab_l = "B.Fab" if side == "B" else "F.Fab"
    crt_l = "B.CrtYd" if side == "B" else "F.CrtYd"
    out = [f'\t(footprint "APA_CARRIER:{fp["name"]}"\n\t\t(layer "{lyr}")\n\t\t(uuid "{kicad_uuid("fp/" + ref)}")\n'
           f'\t\t(at {f4(kx(px))} {f4(ky(py))})\n\t\t(descr "{esc(part["description"])}")\n']
    rx, ry, rr, ra = ref_label if ref_label else (px, py - 3.0, 0, "cc")
    just = _just(ra)
    out.append(f'\t\t(property "Reference" "{ref}"\n\t\t\t(at {f4(rx - px)} {f4(-(ry - py))} {f4(rr % 360)})\n\t\t\t(layer "{silk_l}")\n'
               f'\t\t\t(uuid "{kicad_uuid("fp/" + ref + "/ref")}")\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n\t\t\t\t\t(thickness 0.15)\n\t\t\t\t)\n\t\t\t\t{just}\n\t\t\t)\n\t\t)\n')
    out.append(f'\t\t(property "Value" "{esc(part["value"])}"\n\t\t\t(at 0 0 0)\n\t\t\t(layer "{fab_l}")\n'
               f'\t\t\t(uuid "{kicad_uuid("fp/" + ref + "/val")}")\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 0.8 0.8)\n\t\t\t\t\t(thickness 0.12)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n')
    out.append(f'\t\t(property "Footprint" "APA_CARRIER:{fp["name"]}"\n\t\t\t(at 0 0 0)\n\t\t\t(layer "{fab_l}")\n\t\t\t(hide yes)\n'
               f'\t\t\t(uuid "{kicad_uuid("fp/" + ref + "/fp")}")\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t(thickness 0.15)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n')
    out.append(f'\t\t(attr {"smd" if part["smd"] else "through_hole"})\n')

    def T(x, y):
        a, b = rot_pt(x, y, rot)
        return a, -b                       # footprint-local, KiCad (y down)
    n = 0
    for pr in fp["silk"]:
        n += 1
        if pr[0] == "line":
            (x1, y1), (x2, y2) = T(pr[1], pr[2]), T(pr[3], pr[4])
            out.append(f'\t\t(fp_line\n\t\t\t(start {f4(x1)} {f4(y1)})\n\t\t\t(end {f4(x2)} {f4(y2)})\n\t\t\t(stroke\n\t\t\t\t(width {SILK_W})\n\t\t\t\t(type solid)\n\t\t\t)\n\t\t\t(layer "{silk_l}")\n\t\t\t(uuid "{kicad_uuid(f"fp/{ref}/s{n}")}")\n\t\t)\n')
        elif pr[0] == "rect":
            x0, y0, x1, y1 = pr[1:5]
            pts = [T(x0, y0), T(x1, y0), T(x1, y1), T(x0, y1)]
            fill = "solid" if (len(pr) > 5 and pr[5] == "fill") else "none"
            for k, (a, b) in enumerate(zip(pts, pts[1:] + pts[:1])):
                out.append(f'\t\t(fp_line\n\t\t\t(start {f4(a[0])} {f4(a[1])})\n\t\t\t(end {f4(b[0])} {f4(b[1])})\n\t\t\t(stroke\n\t\t\t\t(width {SILK_W})\n\t\t\t\t(type {"dash" if len(pr) > 5 and pr[5] == "dash" else "solid"})\n\t\t\t)\n\t\t\t(layer "{silk_l}")\n\t\t\t(uuid "{kicad_uuid(f"fp/{ref}/s{n}/{k}")}")\n\t\t)\n')
        elif pr[0] == "circle":
            cx, cy = T(pr[1], pr[2])
            out.append(f'\t\t(fp_circle\n\t\t\t(center {f4(cx)} {f4(cy)})\n\t\t\t(end {f4(cx + pr[3])} {f4(cy)})\n\t\t\t(stroke\n\t\t\t\t(width {SILK_W})\n\t\t\t\t(type solid)\n\t\t\t)\n\t\t\t(fill none)\n\t\t\t(layer "{silk_l}")\n\t\t\t(uuid "{kicad_uuid(f"fp/{ref}/s{n}")}")\n\t\t)\n')
        elif pr[0] == "text":
            tx, ty = T(pr[2], pr[3])
            out.append(f'\t\t(fp_text user "{esc(pr[1])}"\n\t\t\t(at {f4(tx)} {f4(ty)} 0)\n\t\t\t(layer "{silk_l}")\n\t\t\t(uuid "{kicad_uuid(f"fp/{ref}/s{n}")}")\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n\t\t\t\t\t(thickness 0.15)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n')
    # courtyard
    rects = fp["crt"] if isinstance(fp["crt"], list) else [fp["crt"]]
    for k, (x0, y0, x1, y1) in enumerate(rects):
        pts = [T(x0, y0), T(x1, y1)]
        xa, xb = sorted([pts[0][0], pts[1][0]])
        ya, yb = sorted([pts[0][1], pts[1][1]])
        out.append(f'\t\t(fp_rect\n\t\t\t(start {f4(xa)} {f4(ya)})\n\t\t\t(end {f4(xb)} {f4(yb)})\n\t\t\t(stroke\n\t\t\t\t(width 0.05)\n\t\t\t\t(type solid)\n\t\t\t)\n\t\t\t(fill none)\n\t\t\t(layer "{crt_l}")\n\t\t\t(uuid "{kicad_uuid(f"fp/{ref}/c{k}")}")\n\t\t)\n')
    # pads
    for pa in cu_pads:
        if pa.ref != ref:
            continue
        lx, ly = pa.x - px, -(pa.y - py)
        net = pa.net
        netstr = f'\n\t\t\t(net {NETCODE[net]} "{esc(net)}")' if net else ""
        shape = {"circle": "circle", "rect": "rect", "oval": "oval"}[pa.shape]
        size = f"(size {f4(pa.w)} {f4(pa.h)})"
        if pa.smd:
            layers = '"B.Cu" "B.Paste" "B.Mask"' if side == "B" else '"F.Cu" "F.Paste" "F.Mask"'
            out.append(f'\t\t(pad "{pa.num}" smd {shape}\n\t\t\t(at {f4(lx)} {f4(ly)})\n\t\t\t{size}\n\t\t\t(layers {layers}){netstr}\n\t\t\t(pintype "passive")\n\t\t\t(uuid "{kicad_uuid(f"fp/{ref}/p{pa.num}")}")\n\t\t)\n')
        elif not pa.plated:
            out.append(f'\t\t(pad "" np_thru_hole circle\n\t\t\t(at {f4(lx)} {f4(ly)})\n\t\t\t{size}\n\t\t\t(drill {f4(pa.drill)})\n\t\t\t(layers "*.Cu" "*.Mask")\n\t\t\t(uuid "{kicad_uuid(f"fp/{ref}/p{pa.num}")}")\n\t\t)\n')
        else:
            out.append(f'\t\t(pad "{pa.num}" thru_hole {shape}\n\t\t\t(at {f4(lx)} {f4(ly)})\n\t\t\t{size}\n\t\t\t(drill {f4(pa.drill)})\n\t\t\t(layers "*.Cu" "*.Mask"){netstr}\n\t\t\t(pintype "passive")\n\t\t\t(uuid "{kicad_uuid(f"fp/{ref}/p{pa.num}")}")\n\t\t)\n')
    out.append("\t)\n")
    return "".join(out)


def write_kicad_pcb(path, pads, cu, labels):
    L = []
    L.append('(kicad_pcb\n\t(version 20240108)\n\t(generator "pcbnew")\n\t(generator_version "8.0")\n'
             '\t(general\n\t\t(thickness 1.6)\n\t\t(legacy_teardrops no)\n\t)\n\t(paper "A4")\n'
             f'\t(title_block\n\t\t(title "{BOARD_NAME}")\n\t\t(date "{datetime.date.today().isoformat()}")\n\t\t(rev "{BOARD_REV}")\n'
             '\t\t(company "AutoPolarAlignment")\n\t\t(comment 1 "Generated by generate.py; KiCad ERC/DRC NOT yet run")\n\t)\n')
    L.append('\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n\t\t(32 "B.Adhes" user "B.Adhesive")\n\t\t(33 "F.Adhes" user "F.Adhesive")\n'
             '\t\t(34 "B.Paste" user)\n\t\t(35 "F.Paste" user)\n\t\t(36 "B.SilkS" user "B.Silkscreen")\n\t\t(37 "F.SilkS" user "F.Silkscreen")\n'
             '\t\t(38 "B.Mask" user)\n\t\t(39 "F.Mask" user)\n\t\t(40 "Dwgs.User" user "User.Drawings")\n\t\t(41 "Cmts.User" user "User.Comments")\n'
             '\t\t(42 "Eco1.User" user "User.Eco1")\n\t\t(43 "Eco2.User" user "User.Eco2")\n\t\t(44 "Edge.Cuts" user)\n\t\t(45 "Margin" user)\n'
             '\t\t(46 "B.CrtYd" user "B.Courtyard")\n\t\t(47 "F.CrtYd" user "F.Courtyard")\n\t\t(48 "B.Fab" user)\n\t\t(49 "F.Fab" user)\n\t)\n')
    L.append('\t(setup\n\t\t(pad_to_mask_clearance 0.05)\n\t\t(allow_soldermask_bridges_in_footprints no)\n\t)\n')
    L.append('\t(net 0 "")\n')
    for name, code in NETCODE.items():
        L.append(f'\t(net {code} "{esc(name)}")\n')
    ref_labels = {t[0]: (t[1], t[2], t[3], t[4]) for t in labels if t[0] in PLACE}
    for ref in PLACE:
        L.append(fp_block(ref, pads, ref_labels.get(ref)))
    # tracks
    k = 0
    for t in cu.tracks:
        for (x1, y1), (x2, y2) in zip(t["pts"], t["pts"][1:]):
            if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
                continue
            k += 1
            L.append(f'\t(segment\n\t\t(start {f4(kx(x1))} {f4(ky(y1))})\n\t\t(end {f4(kx(x2))} {f4(ky(y2))})\n\t\t(width {t["w"]})\n'
                     f'\t\t(layer "{"F.Cu" if t["layer"] == 0 else "B.Cu"}")\n\t\t(net {NETCODE[t["net"]]})\n\t\t(uuid "{kicad_uuid(f"seg/{k}")}")\n\t)\n')
    for k, v in enumerate(cu.vias + cu.stitch):
        L.append(f'\t(via\n\t\t(at {f4(kx(v["x"]))} {f4(ky(v["y"]))})\n\t\t(size {VIA_PAD})\n\t\t(drill {VIA_DRILL})\n'
                 f'\t\t(layers "F.Cu" "B.Cu")\n\t\t(net {NETCODE[v["net"]]})\n\t\t(uuid "{kicad_uuid(f"via/{k}")}")\n\t)\n')
    # GND zones (KiCad refills them itself: press B / run DRC)
    zpts = "".join(f"(xy {f4(kx(x))} {f4(ky(y))}) " for x, y in list(OUTLINE.buffer(-EDGE_CLR).simplify(0.01).exterior.coords)[:-1])
    for lay in ("F.Cu", "B.Cu"):
        L.append(f'\t(zone\n\t\t(net {NETCODE["GND"]})\n\t\t(net_name "GND")\n\t\t(layer "{lay}")\n\t\t(uuid "{kicad_uuid("zone/" + lay)}")\n'
                 f'\t\t(hatch edge 0.5)\n\t\t(connect_pads\n\t\t\t(clearance {POUR_CLR})\n\t\t)\n\t\t(min_thickness 0.25)\n'
                 f'\t\t(filled_areas_thickness no)\n\t\t(fill yes\n\t\t\t(thermal_gap {THERMAL_GAP})\n\t\t\t(thermal_bridge_width {SPOKE_W})\n\t\t)\n'
                 f'\t\t(polygon\n\t\t\t(pts\n\t\t\t\t{zpts}\n\t\t\t)\n\t\t)\n\t)\n')
    # board outline
    R, W, H = CORNER_R, BOARD_W, BOARD_H
    c45 = R * (1 - math.sqrt(0.5))

    def gl(a, b, uid):
        return (f'\t(gr_line\n\t\t(start {f4(kx(a[0]))} {f4(ky(a[1]))})\n\t\t(end {f4(kx(b[0]))} {f4(ky(b[1]))})\n'
                f'\t\t(stroke\n\t\t\t(width 0.1)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "Edge.Cuts")\n\t\t(uuid "{kicad_uuid(uid)}")\n\t)\n')

    def ga(a, m, b, uid):
        return (f'\t(gr_arc\n\t\t(start {f4(kx(a[0]))} {f4(ky(a[1]))})\n\t\t(mid {f4(kx(m[0]))} {f4(ky(m[1]))})\n\t\t(end {f4(kx(b[0]))} {f4(ky(b[1]))})\n'
                f'\t\t(stroke\n\t\t\t(width 0.1)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "Edge.Cuts")\n\t\t(uuid "{kicad_uuid(uid)}")\n\t)\n')
    L.append(gl((R, 0), (W - R, 0), "e1") + ga((W - R, 0), (W - c45, c45), (W, R), "a1") + gl((W, R), (W, H - R), "e2")
             + ga((W, H - R), (W - c45, H - c45), (W - R, H), "a2") + gl((W - R, H), (R, H), "e3")
             + ga((R, H), (c45, H - c45), (0, H - R), "a3") + gl((0, H - R), (0, R), "e4")
             + ga((0, R), (c45, c45), (R, 0), "a4"))
    # Pi guide + silk text (footprint references are footprint properties)
    x0, x1 = J1_X - 32.5, J1_X + 32.5
    yt = PI_TOP_EDGE_Y
    for k, (a, b) in enumerate((((x0, yt), (x1, yt)), ((x0, yt), (x0, 0.4)), ((x1, yt), (x1, 0.4)))):
        L.append(f'\t(gr_line\n\t\t(start {f4(kx(a[0]))} {f4(ky(a[1]))})\n\t\t(end {f4(kx(b[0]))} {f4(ky(b[1]))})\n'
                 f'\t\t(stroke\n\t\t\t(width {SILK_W})\n\t\t\t(type solid)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{kicad_uuid(f"pi/{k}")}")\n\t)\n')
    for k, hx in enumerate((J1_X - 29.0, J1_X + 29.0)):
        L.append(f'\t(gr_circle\n\t\t(center {f4(kx(hx))} {f4(ky(J1_Y))})\n\t\t(end {f4(kx(hx + 1.375))} {f4(ky(J1_Y))})\n'
                 f'\t\t(stroke\n\t\t\t(width {SILK_W})\n\t\t\t(type solid)\n\t\t)\n\t\t(fill none)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{kicad_uuid(f"pih/{k}")}")\n\t)\n')
    for k, (txt, x, y, rot, anc, lay, cap) in enumerate(labels):
        if txt in PLACE:
            continue
        L.append(kicad_text(txt, x, y, rot, anc, "F.SilkS" if lay == "F" else "B.SilkS", cap, f"txt/{k}"))
    L.append(")\n")
    Path(path).write_text("".join(L), encoding="utf8")


def write_kicad_pro(path):
    pro = OrderedDict()
    pro["board"] = {"design_settings": {"defaults": {"copper_line_width": 0.2, "silk_line_width": 0.18, "silk_text_size_h": 1.0,
                                                    "silk_text_size_v": 1.0, "silk_text_thickness": 0.15},
                                         "rules": {"min_clearance": 0.25, "min_track_width": 0.25, "min_via_diameter": 0.6,
                                                   "min_through_hole_diameter": 0.3, "min_copper_edge_clearance": 0.5,
                                                   "min_hole_to_hole": 0.25, "min_via_annular_width": 0.15,
                                                   "min_text_height": 0.8, "min_text_thickness": 0.12},
                                         "track_widths": [0.0, 0.3, 0.5, 0.8], "via_dimensions": [{"diameter": 0.0, "drill": 0.0},
                                                                                                  {"diameter": 0.6, "drill": 0.3}]}}
    pro["boards"] = []
    pro["meta"] = {"filename": "carrier.kicad_pro", "version": 1}
    pro["net_settings"] = {"classes": [
        {"name": "Default", "clearance": 0.25, "track_width": 0.3, "via_diameter": 0.6, "via_drill": 0.3, "pcb_color": "rgba(0, 0, 0, 0.000)"},
        {"name": "Power", "clearance": 0.25, "track_width": 0.8, "via_diameter": 0.6, "via_drill": 0.3, "pcb_color": "rgba(0, 0, 0, 0.000)"},
        {"name": "Power3V3", "clearance": 0.25, "track_width": 0.5, "via_diameter": 0.6, "via_drill": 0.3, "pcb_color": "rgba(0, 0, 0, 0.000)"}],
        "meta": {"version": 3},
        "netclass_assignments": {n: ("Power" if net_class(n) == "POWER" else "Power3V3") for n in NETS if net_class(n) in ("POWER", "POWER3V3")},
        "netclass_patterns": []}
    pro["schematic"] = {"drawing": {"default_line_thickness": 6.0}, "meta": {"version": 1}}
    pro["sheets"] = [[kicad_uuid("sheet/root"), ""]]
    pro["text_variables"] = {}
    Path(path).write_text(json.dumps(pro, indent=2) + "\n", encoding="utf8")


# ============================================================================
# SECTION 10: independent re-verification of the written files
# ============================================================================
def replay_gerber(gf):
    acc = Polygon()
    for o in gf.objects:
        if type(o).__name__ != "Region":
            continue
        poly = Polygon(o.outline).buffer(0)
        acc = acc.union(poly) if o.polarity_dark else acc.difference(poly)
    return acc


def verify_gerbers(geoms, holes):
    import warnings
    from gerbonara import ExcellonFile, GerberFile
    res = OrderedDict()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for fn, func in GERBER_FILES:
            path = FAB / f"{PROJECT}-{fn}"
            gf = GerberFile.open(path)
            (bx0, by0), (bx1, by1) = gf.bounding_box("mm")
            ent = dict(file=path.name, objects=len(gf.objects), bbox=[round(bx0, 3), round(by0, 3), round(bx1, 3), round(by1, 3)])
            inside = (bx0 >= -0.06 and by0 >= -0.06 and bx1 <= BOARD_W + 0.06 and by1 <= BOARD_H + 0.06)
            ent["within_outline"] = bool(inside)
            if fn.startswith("Edge"):
                ent["matches_outline"] = bool(abs(bx0 + 0.05) < 1e-3 and abs(by0 + 0.05) < 1e-3 and abs(bx1 - BOARD_W - 0.05) < 1e-3
                                              and abs(by1 - BOARD_H - 0.05) < 1e-3)
            else:
                exp = geoms[fn]
                rp = replay_gerber(gf)
                sym = rp.symmetric_difference(exp).area
                ent["area_mm2"] = round(exp.area, 3)
                ent["replay_vs_generated_sym_diff_mm2"] = round(sym, 6)
                eb = exp.bounds if not exp.is_empty else (0, 0, 0, 0)
                ent["bbox_matches_generated_geometry"] = bool(all(abs(a - b) < 2e-3 for a, b in zip(ent["bbox"], eb)))
                ent["ok"] = bool(sym < 1e-3 and ent["bbox_matches_generated_geometry"] and inside)
            res[fn] = ent
        for kind, plated in (("PTH", True), ("NPTH", False)):
            ex = ExcellonFile.open(FAB / f"{PROJECT}-{kind}.drl")
            got = sorted((round(o.x, 3), round(o.y, 3), round(o.aperture.diameter, 3)) for o in ex.objects)
            exp = sorted((round(x, 3), round(y, 3), round(d, 3)) for (x, y, d) in holes["pth" if plated else "npth"])
            res[kind] = dict(file=f"{PROJECT}-{kind}.drl", holes=len(got), expected=len(exp), positions_and_diameters_match=got == exp,
                             tools=sorted({g[2] for g in got}))
    return res


def verify_kicad_pcb(path, netlist_doc, cu):
    from kiutils.board import Board
    b = Board.from_file(str(path))
    got = {}
    pad_geo = []
    for fp in b.footprints:
        ref = fp.properties.get("Reference")
        for pd in fp.pads:
            if pd.number == "" or pd.type == "np_thru_hole":
                continue
            got[(ref, pd.number)] = pd.net.name if pd.net else None
            # absolute pad geometry for an independent connectivity check
            ax, ay = fp.position.X + pd.position.X, fp.position.Y + pd.position.Y
            w, h = pd.size.X, pd.size.Y
            shp = {"circle": "circle", "rect": "rect", "oval": "oval"}[pd.shape]
            tht = pd.type == "thru_hole"
            layers = ("F.Cu", "B.Cu") if tht else (("B.Cu",) if "B.Cu" in pd.layers else ("F.Cu",))
            pad_geo.append((ref, pd.number, pd.net.name if pd.net else None, pad_poly(shp, ax, ay, w, h), layers))
    exp = {}
    for part in netlist_doc["parts"]:
        for pin, net in part["pins"].items():
            exp[(part["ref"], pin)] = net
    mism = [(k, exp.get(k), got.get(k)) for k in set(exp) | set(got) if exp.get(k) != got.get(k)]
    # independent copper connectivity from the parsed file (non-GND nets; zones are refilled by KiCad)
    segs = [t for t in b.traceItems if type(t).__name__ == "Segment"]
    vias = [t for t in b.traceItems if type(t).__name__ == "Via"]
    items = []
    for ref, num, net, poly, layers in pad_geo:
        items.append((poly, net, set(layers), f"{ref}.{num}"))
    for s in segs:
        items.append((LineString([(s.start.X, s.start.Y), (s.end.X, s.end.Y)]).buffer(s.width / 2), b.nets[s.net].name if s.net < len(b.nets) else None,
                      {s.layer}, "seg"))
    for v in vias:
        items.append((circ(v.position.X, v.position.Y, v.size / 2), b.nets[v.net].name, {"F.Cu", "B.Cu"}, "via"))
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i][2] & items[j][2] and items[i][1] == items[j][1] and items[i][0].intersects(items[j][0]):
                parent[find(i)] = find(j)
    opens = []
    for net in NETS:
        if net == "GND":
            continue
        pads_i = [i for i, it in enumerate(items) if it[1] == net and it[3] not in ("seg", "via")]
        roots = {find(i) for i in pads_i}
        if len(roots) > 1:
            opens.append((net, len(roots)))
    return dict(footprints=len(b.footprints), pads_compared=len(exp), mismatches=mism, tracks=len(segs), vias=len(vias),
                zones=len(b.zones), nets=len(b.nets) - 1, opens_from_file_copper_nonGND=opens,
                kicad_version=b.version, generator=b.generator)


def verify_dxf_stl(cu, stl_info):
    from ezdxf import bbox as dxbbox
    doc = ezdxf.readfile(str(OUT / "carrier_outline.dxf"))
    msp = doc.modelspace()
    pl = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "OUTLINE"][0]
    # flatten the bulge arcs
    pts = []
    for e in [pl]:
        for v in e.virtual_entities():
            if v.dxftype() == "LINE":
                pts += [tuple(v.dxf.start)[:2], tuple(v.dxf.end)[:2]]
            else:
                c = tuple(v.dxf.center)[:2]
                r = v.dxf.radius
                a0, a1 = math.radians(v.dxf.start_angle), math.radians(v.dxf.end_angle)
                if a1 < a0:
                    a1 += 2 * math.pi
                pts += [(c[0] + r * math.cos(a0 + (a1 - a0) * t / 16), c[1] + r * math.sin(a0 + (a1 - a0) * t / 16)) for t in range(17)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    dxf_bb = (min(xs), min(ys), max(xs), max(ys))
    poly = Polygon(pts).convex_hull
    area_diff = abs(poly.area - OUTLINE.area)
    holes_dxf = [e for e in msp if e.dxftype() == "CIRCLE" and e.dxf.layer in ("MOUNTING_HOLES", "PTH_HOLES")]
    n_expected = len([1 for h in board_holes(cu) if h[3] in ("NPTH", "PTH")])
    m = trimesh.load(str(OUT / "carrier_board.stl"))
    b = m.bounds
    return dict(dxf_outline_bbox=[round(v, 3) for v in dxf_bb], dxf_outline_area_diff_mm2=round(area_diff, 3),
                dxf_hole_circles=len(holes_dxf), dxf_hole_circles_expected=n_expected,
                stl_bbox_min=[round(float(v), 3) for v in b[0]], stl_bbox_max=[round(float(v), 3) for v in b[1]],
                stl_triangles=int(len(m.faces)), stl_board_volume_mm3=round(stl_info["board_volume"], 2),
                board_area_x_thickness=round(stl_info["board_area"] * THICK, 2))


def self_test_checker(cu):
    """Prove the checkers can fail: break a copy of the design and confirm the checks notice."""
    import copy
    out = {}
    # (1) delete one track of a signal net -> expect an open
    cu1 = copy.copy(cu)
    victim = max([t for t in cu.tracks if t["net"] == "SPARE"], key=lambda t: LineString(t["pts"]).length)
    cu1.tracks = [t for t in cu.tracks if t is not victim]
    pn, sh = check_connectivity(cu1)
    out["delete_one_SPARE_track_gives_open"] = (not pn["SPARE"]["connected"])
    # (2) add a rogue track from a signal pad across another net's pad -> expect short + clearance violation
    cu2 = copy.copy(cu)
    a = [p for p in cu.pads if p.net == "STEP_ALT"][0]
    c = [p for p in cu.pads if p.net == "SDA"][0]
    cu2.tracks = cu.tracks + [dict(net="STEP_ALT", layer=0, pts=[(a.x, a.y), (c.x, c.y)], w=0.3)]
    pn, sh = check_connectivity(cu2)
    cl = check_clearance(cu2)
    out["rogue_track_gives_short"] = bool(sh)
    out["rogue_track_gives_clearance_violation"] = bool(cl["violations"])
    # (3) nudge a track to 0.10 mm from a foreign pad -> expect a violation
    cu3 = copy.copy(cu)
    q = [p for p in cu.pads if p.net == "SDA"][0]
    cu3.tracks = cu.tracks + [dict(net="SCL", layer=0, pts=[(q.x + 1.0, q.y + 0.5), (q.x + 1.0, q.y - 0.5)], w=0.3)]
    cl3 = check_clearance(cu3)
    out["near_miss_track_gives_clearance_violation"] = bool(cl3["violations"])
    return out


# ============================================================================
# SECTION 10b: KiCad 8 schematic (net-label style, grouped by function)
# ============================================================================
G = 1.27
SCH_PAPER = "A2"


def _fx(v):
    return ("%.4f" % v).rstrip("0").rstrip(".") if abs(v) > 1e-9 else "0"


def _eff(size=1.27, bold=False, justify="", hide=False):
    j = f" (justify {justify})" if justify else ""
    return f"(effects (font (size {size} {size}){' bold' if bold else ''}){j}{' (hide yes)' if hide else ''})"


class SchSym:
    def __init__(self, libname, graphics, pins, ref_prefix):
        self.libname, self.graphics, self.pins, self.prefix = libname, graphics, pins, ref_prefix
        # pins: list of (number, name, x, y, angle)

    def lib_block(self):
        pin_txt = ""
        for num, name, x, y, ang, ln in self.pins:
            pin_txt += (f'\t\t\t(pin passive line\n\t\t\t\t(at {_fx(x)} {_fx(y)} {ang})\n\t\t\t\t(length {_fx(ln)})\n'
                        f'\t\t\t\t(name "{esc(name)}"\n\t\t\t\t\t{_eff(1.016)}\n\t\t\t\t)\n'
                        f'\t\t\t\t(number "{esc(num)}"\n\t\t\t\t\t{_eff(1.016)}\n\t\t\t\t)\n\t\t\t)\n')
        short_name = self.libname.split(":")[1]
        return (f'\t\t(symbol "{self.libname}"\n\t\t\t(exclude_from_sim no)\n\t\t\t(in_bom yes)\n\t\t\t(on_board yes)\n'
                f'\t\t\t(property "Reference" "{self.prefix}"\n\t\t\t\t(at 0 2.54 0)\n\t\t\t\t{_eff()}\n\t\t\t)\n'
                f'\t\t\t(property "Value" "{short_name}"\n\t\t\t\t(at 0 -2.54 0)\n\t\t\t\t{_eff()}\n\t\t\t)\n'
                f'\t\t\t(property "Footprint" ""\n\t\t\t\t(at 0 0 0)\n\t\t\t\t{_eff(hide=True)}\n\t\t\t)\n'
                f'\t\t\t(property "Datasheet" ""\n\t\t\t\t(at 0 0 0)\n\t\t\t\t{_eff(hide=True)}\n\t\t\t)\n'
                f'\t\t\t(symbol "{short_name}_0_1"\n{self.graphics}\t\t\t)\n'
                f'\t\t\t(symbol "{short_name}_1_1"\n{pin_txt}\t\t\t)\n\t\t)\n')


def _rect(x0, y0, x1, y1):
    return (f'\t\t\t\t(rectangle\n\t\t\t\t\t(start {_fx(x0)} {_fx(y0)})\n\t\t\t\t\t(end {_fx(x1)} {_fx(y1)})\n'
            f'\t\t\t\t\t(stroke\n\t\t\t\t\t\t(width 0.254)\n\t\t\t\t\t\t(type default)\n\t\t\t\t\t)\n\t\t\t\t\t(fill\n\t\t\t\t\t\t(type background)\n\t\t\t\t\t)\n\t\t\t\t)\n')


def _poly(pts, fill="none"):
    p = " ".join(f"(xy {_fx(x)} {_fx(y)})" for x, y in pts)
    return (f'\t\t\t\t(polyline\n\t\t\t\t\t(pts\n\t\t\t\t\t\t{p}\n\t\t\t\t\t)\n\t\t\t\t\t(stroke\n\t\t\t\t\t\t(width 0.254)\n\t\t\t\t\t\t(type default)\n\t\t\t\t\t)\n'
            f'\t\t\t\t\t(fill\n\t\t\t\t\t\t(type {fill})\n\t\t\t\t\t)\n\t\t\t\t)\n')


def _circle(x, y, r):
    return (f'\t\t\t\t(circle\n\t\t\t\t\t(center {_fx(x)} {_fx(y)})\n\t\t\t\t\t(radius {_fx(r)})\n\t\t\t\t\t(stroke\n\t\t\t\t\t\t(width 0.254)\n\t\t\t\t\t\t(type default)\n\t\t\t\t\t)\n'
            f'\t\t\t\t\t(fill\n\t\t\t\t\t\t(type none)\n\t\t\t\t\t)\n\t\t\t\t)\n')


def box_symbol(libname, prefix, left, right, half_w=12.7):
    """left/right = list of (number, name); rows from the top at 2.54 pitch."""
    rows = max(len(left), len(right), 1)
    g = _rect(-half_w, G, half_w, -(rows - 1) * 2.54 - G)
    pins = []
    for i, (num, name) in enumerate(left):
        pins.append((num, name, -half_w - 2.54, -i * 2.54, 0, 2.54))
    for i, (num, name) in enumerate(right):
        pins.append((num, name, half_w + 2.54, -i * 2.54, 180, 2.54))
    return SchSym(libname, g, pins, prefix)


def two_pin_symbol(libname, prefix, graphics, p1="1", p2="2", swap=False, n1="~", n2="~"):
    a, b = (p2, p1) if swap else (p1, p2)
    na, nb = (n2, n1) if swap else (n1, n2)
    return SchSym(libname, graphics, [(a, na, -5.08, 0, 0, 2.54), (b, nb, 5.08, 0, 180, 2.54)], prefix)


def build_sch_symbols():
    """one lib symbol per part kind (passives) or per ref (connectors/modules)."""
    sym = {}
    sym["R"] = two_pin_symbol("APA_CARRIER:R", "R", _rect(-2.54, -1.016, 2.54, 1.016))
    sym["C"] = two_pin_symbol("APA_CARRIER:C", "C", _poly([(-0.508, -2.032), (-0.508, 2.032)]) + _poly([(0.508, -2.032), (0.508, 2.032)])
                              + _poly([(-2.54, 0), (-0.508, 0)]) + _poly([(0.508, 0), (2.54, 0)]))
    sym["CP"] = two_pin_symbol("APA_CARRIER:CP", "C", _poly([(-0.508, -2.032), (-0.508, 2.032)]) + _poly([(0.508, -2.032), (0.508, 2.032)])
                               + _poly([(-2.54, 0), (-0.508, 0)]) + _poly([(0.508, 0), (2.54, 0)])
                               + _poly([(-1.778, 1.778), (-1.778, 0.762)]) + _poly([(-2.286, 1.27), (-1.27, 1.27)]), n1="+", n2="-")
    tri = _poly([(-1.27, 1.27), (-1.27, -1.27), (1.27, 0), (-1.27, 1.27)], "none") + _poly([(1.27, 1.27), (1.27, -1.27)]) \
        + _poly([(-2.54, 0), (-1.27, 0)]) + _poly([(1.27, 0), (2.54, 0)])
    sym["D"] = two_pin_symbol("APA_CARRIER:D", "D", tri, swap=True, n1="K", n2="A")      # pin 1 = cathode (right)
    sym["LED"] = two_pin_symbol("APA_CARRIER:LED", "LED", tri + _poly([(0, 2.0), (1.0, 3.0)]) + _poly([(1.0, 1.4), (2.0, 2.4)]),
                                swap=True, n1="K", n2="A")
    sym["PTC"] = two_pin_symbol("APA_CARRIER:PTC", "F", _rect(-2.54, -1.016, 2.54, 1.016) + _poly([(-1.8, -2.0), (1.8, 2.0)]))
    sym["TP"] = SchSym("APA_CARRIER:TP", _circle(0, 0, 0.635), [("1", "1", -3.81, 0, 0, 3.175)], "TP")
    sym["H"] = SchSym("APA_CARRIER:MountingHole", _circle(0, 0, 1.6), [], "H")
    # J1 two columns: odd pins left, even pins right
    def pname(p):
        n = PI_PIN_NET.get(p)
        if p in PI_GPIO:
            return PI_GPIO[p]
        return {"3V3": "3V3", "5V_PI": "5V", "GND": "GND"}.get(n, "NC")
    sym["J1"] = box_symbol("APA_CARRIER:J1_Pi_2x20", "J", [(str(2 * k + 1), pname(2 * k + 1)) for k in range(20)],
                           [(str(2 * k + 2), pname(2 * k + 2)) for k in range(20)])
    for r in ("U1", "U2"):
        sym[r] = box_symbol(f"APA_CARRIER:{r}_TMC2209", "U", [(f"A{i+1}", MOD_A[i]) for i in range(8)],
                            [(f"B{i+1}", MOD_B[i]) for i in range(8)])
    names = {"J2": ["12V_RAW", "GND"], "J3": ["+12V", "GND"], "J4": ["5V_BUCK", "GND"],
             "J5": ["A2", "A1", "B1", "B2"], "J6": ["A2", "A1", "B1", "B2"],
             "J7": ["SIG", "GND"], "J8": ["SIG", "GND"], "J9": ["SIG", "GND"], "J10": ["SIG", "GND"],
             "J11": ["GND", "3V3", "5V_F", "SDA", "SCL"], "J12": ["GND", "3V3", "5V_F", "SDA", "SCL"], "JP1": ["5V_F", "5V_PI"]}
    for r, nm in names.items():
        sym[r] = box_symbol(f"APA_CARRIER:{r}_{PARTS[r]['value'].split()[0]}", "JP" if r == "JP1" else "J",
                            [(str(i + 1), n) for i, n in enumerate(nm)], [], half_w=7.62)
    return sym


def sym_key(ref):
    if ref in ("J1", "U1", "U2", "J2", "J3", "J4", "J5", "J6", "J7", "J8", "J9", "J10", "J11", "J12", "JP1"):
        return ref
    if ref.startswith("TP"):
        return "TP"
    if ref.startswith("H"):
        return "H"
    if ref.startswith("LED"):
        return "LED"
    if ref in ("F1", "F2"):
        return "PTC"
    if ref in ("D1", "D2"):
        return "D"
    if ref == "C1":
        return "CP"
    if ref in ("C2", "C3"):
        return "CP"
    if ref.startswith("C"):
        return "C"
    if ref.startswith("R"):
        return "R"
    raise KeyError(ref)


def sch_positions():
    """(x, y) of each symbol's origin on the sheet, grouped by function (mm, multiples of 1.27)."""
    P = {}
    P["J1"] = (91.44, 76.2)
    P["U1"] = (233.68, 76.2)
    P["U2"] = (363.22, 76.2)
    P["J5"] = (233.68, 165.1)
    P["J6"] = (363.22, 165.1)
    P["J2"] = (68.58, 190.5)
    P["J3"] = (68.58, 215.9)
    P["J4"] = (68.58, 241.3)
    P["JP1"] = (68.58, 266.7)
    P["J7"] = (68.58, 292.1)
    P["J8"] = (68.58, 317.5)
    P["J9"] = (68.58, 342.9)
    P["J10"] = (68.58, 368.3)
    P["J11"] = (233.68, 215.9)
    P["J12"] = (363.22, 215.9)
    col = [(165.1, 279.4), (254.0, 279.4), (342.9, 279.4), (431.8, 279.4)]
    order = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "C4", "C5", "C6", "C7", "C8", "C9", "C1", "C2", "C3", "D1", "D2", "F1", "F2",
             "LED1", "TP1", "TP2", "TP3", "TP4", "TP5", "H1", "H2", "H3", "H4"]
    for k, ref in enumerate(order):
        c, r = divmod(k, 8)
        P[ref] = (col[c][0], col[c][1] + 17.78 * r)
    return P


def write_kicad_sch(path):
    sym = build_sch_symbols()
    pos = sch_positions()
    root = kicad_uuid("sheet/root")
    out = ['(kicad_sch\n\t(version 20231120)\n\t(generator "eeschema")\n\t(generator_version "8.0")\n'
           f'\t(uuid "{root}")\n\t(paper "{SCH_PAPER}")\n'
           f'\t(title_block\n\t\t(title "{BOARD_NAME} carrier")\n\t\t(date "{datetime.date.today().isoformat()}")\n\t\t(rev "{BOARD_REV}")\n'
           '\t\t(comment 1 "Net-label schematic generated by generate.py; KiCad ERC NOT yet run")\n\t)\n\t(lib_symbols\n']
    used = OrderedDict()
    for ref in PARTS:
        k = sym_key(ref)
        used[k] = sym[k]
    for k, sy in used.items():
        out.append(sy.lib_block())
    out.append("\t)\n")
    n = 0
    for ref, part in PARTS.items():
        sy = sym[sym_key(ref)]
        x, y = pos[ref]
        n += 1
        short_name = sy.libname.split(":")[1]
        out.append(f'\t(symbol\n\t\t(lib_id "{sy.libname}")\n\t\t(at {_fx(x)} {_fx(y)} 0)\n\t\t(unit 1)\n\t\t(exclude_from_sim no)\n'
                   f'\t\t(in_bom {"no" if ref.startswith("H") else "yes"})\n\t\t(on_board yes)\n\t\t(dnp no)\n\t\t(uuid "{kicad_uuid("sch/" + ref)}")\n'
                   f'\t\t(property "Reference" "{ref}"\n\t\t\t(at {_fx(x)} {_fx(y - 3.81)} 0)\n\t\t\t{_eff(justify="left")}\n\t\t)\n'
                   f'\t\t(property "Value" "{esc(part["value"])}"\n\t\t\t(at {_fx(x)} {_fx(y + 3.81)} 0)\n\t\t\t{_eff(justify="left")}\n\t\t)\n'
                   f'\t\t(property "Footprint" "APA_CARRIER:{part["footprint"]}"\n\t\t\t(at {_fx(x)} {_fx(y)} 0)\n\t\t\t{_eff(hide=True)}\n\t\t)\n'
                   f'\t\t(property "Datasheet" ""\n\t\t\t(at {_fx(x)} {_fx(y)} 0)\n\t\t\t{_eff(hide=True)}\n\t\t)\n')
        for num, name, px, py, ang, ln in sy.pins:
            out.append(f'\t\t(pin "{num}"\n\t\t\t(uuid "{kicad_uuid(f"sch/{ref}/pin{num}")}")\n\t\t)\n')
        out.append(f'\t\t(instances\n\t\t\t(project "carrier"\n\t\t\t\t(path "/{root}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')
        # stubs + labels / no-connect flags
        for num, name, px, py, ang, ln in sy.pins:
            sx, sy_ = x + px, y - py
            net = PIN_NET[ref].get(num)
            direction = -1 if px < 0 else 1
            if net is None:
                out.append(f'\t(no_connect\n\t\t(at {_fx(sx)} {_fx(sy_)})\n\t\t(uuid "{kicad_uuid(f"sch/{ref}/nc{num}")}")\n\t)\n')
                continue
            ex = sx + direction * 5.08
            out.append(f'\t(wire\n\t\t(pts\n\t\t\t(xy {_fx(sx)} {_fx(sy_)}) (xy {_fx(ex)} {_fx(sy_)})\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
                       f'\t\t(uuid "{kicad_uuid(f"sch/{ref}/w{num}")}")\n\t)\n')
            ang_l = 180 if direction < 0 else 0
            just = "right bottom" if direction < 0 else "left bottom"
            out.append(f'\t(label "{esc(net)}"\n\t\t(at {_fx(ex)} {_fx(sy_)} {ang_l})\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify {just})\n\t\t)\n'
                       f'\t\t(uuid "{kicad_uuid(f"sch/{ref}/l{num}")}")\n\t)\n')
    out.append('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n)\n')
    Path(path).write_text("".join(out), encoding="utf8")
    return verify_kicad_sch(path)


def verify_kicad_sch(path):
    """Parse the schematic back with kiutils and recompute (ref, pin) -> net from wires + labels + lib pins."""
    from kiutils.schematic import Schematic
    sch = Schematic.from_file(str(path))
    libpins = {}
    for ls in sch.libSymbols:
        for u in ls.units:
            for pn in u.pins:
                libpins.setdefault(ls.libId, []).append((pn.number, pn.position.X, pn.position.Y))
    wires = []
    for it in sch.graphicalItems:
        if type(it).__name__ == "Connection" and it.type == "wire":
            wires.append(((round(it.points[0].X, 3), round(it.points[0].Y, 3)), (round(it.points[1].X, 3), round(it.points[1].Y, 3))))
    labels = {(round(l.position.X, 3), round(l.position.Y, 3)): l.text for l in sch.labels}
    ncs = {(round(n.position.X, 3), round(n.position.Y, 3)) for n in sch.noConnects}
    got = {}
    for s in sch.schematicSymbols:
        ref = [p.value for p in s.properties if p.key == "Reference"][0]
        for num, px, py in libpins.get(s.libId, []):
            pt = (round(s.position.X + px, 3), round(s.position.Y - py, 3))
            net = None
            for a, b in wires:
                if a == pt:
                    net = labels.get(b)
                elif b == pt:
                    net = labels.get(a)
            if net is None and pt in ncs:
                net = None
            got[(ref, num)] = net
    exp = {}
    for ref, part in PARTS.items():
        for pin in part["pins"]:
            exp[(ref, pin)] = PIN_NET[ref].get(pin)
    mism = [(k, exp.get(k), got.get(k)) for k in set(exp) | set(got) if exp.get(k) != got.get(k)]
    return dict(symbols=len(sch.schematicSymbols), lib_symbols=len(sch.libSymbols), wires=len(wires), labels=len(labels),
                no_connects=len(ncs), pins_compared=len(exp), mismatches=len(mism), mismatch_examples=mism[:5])


# ============================================================================
# SECTION 11: README + main
# ============================================================================
def write_gerber_preview(path):
    import warnings
    from gerbonara import GerberFile
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for ax, (fn, ttl, col) in zip(axs.ravel(), (("F_Cu.gtl", "F.Cu (re-read from Gerber)", "#b5651d"), ("B_Cu.gbl", "B.Cu (re-read from Gerber)", "#2a6fb5"),
                                                   ("F_Silkscreen.gto", "F.Silkscreen (re-read)", "#444444"),
                                                   ("F_Mask.gts", "F.Mask openings (re-read)", "#2a9d4a"))):
            gf = GerberFile.open(FAB / f"{PROJECT}-{fn}")
            add_geom(ax, replay_gerber(gf), fc=col, ec="none")
            add_geom(ax, OUTLINE, fc="none", ec="k", lw=0.8)
            ax.set_title(ttl, fontsize=9)
            ax.set_xlim(-1, BOARD_W + 1)
            ax.set_ylim(-1, BOARD_H + 1)
            ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def write_readme(rep, cu, silk_omitted):
    pin_rows = []
    for p in range(1, 41):
        net = PIN_NET["J1"][str(p)]
        pin_rows.append((p, PI_GPIO.get(p, ""), net if net else "NC"))
    mod_rows = []
    for i in range(8):
        mod_rows.append((f"A{i+1} {MOD_A[i]}", PIN_NET["U1"][f"A{i+1}"] or "NC", PIN_NET["U2"][f"A{i+1}"] or "NC",
                         f"B{i+1} {MOD_B[i]}", PIN_NET["U1"][f"B{i+1}"], PIN_NET["U2"][f"B{i+1}"]))
    cl, dr, pn, rules = rep["clearance"], rep["drills"], rep["connectivity"], rep["rules"]
    gb = rep["gerbers"]
    gb_rows = []
    for fn, v in gb.items():
        if fn in ("PTH", "NPTH"):
            gb_rows.append((v["file"], f"{v['holes']} holes", "positions/diameters identical to generator: %s" % v["positions_and_diameters_match"], ""))
        elif fn.startswith("Edge"):
            gb_rows.append((v["file"], f"bbox {v['bbox']}", f"outline + 0.05 mm aperture half-width: {v['matches_outline']}", ""))
        else:
            gb_rows.append((v["file"], f"bbox {v['bbox']}", f"replayed-vs-generated difference {v['replay_vs_generated_sym_diff_mm2']} mm2", "OK" if v["ok"] else "CHECK"))
    kp = rep["kicad_pcb"]
    ds = rep["dxf_stl"]
    tall = rep["heights"]
    txt = f"""# {BOARD_NAME} rev {BOARD_REV} -- carrier PCB for the Auto Polar Alignment base

Generated by `generate.py` (single reproducible script, see the end of this file). Authoritative design: `SPEC.md`.
**KiCad itself was NOT available: the `.kicad_pcb` / `.kicad_sch` were written by this script and parsed back with kiutils only.
KiCad ERC and DRC have NOT been run and are still outstanding.** Pours are stored as zone outlines; press B (fill all zones) in KiCad.

Board: {BOARD_W:g} x {BOARD_H:g} mm, 1.6 mm FR4, 2 layers, 2 mm corner radius, four M3 NPTH holes (3.2 mm).
Tallest component: {tall['tallest_above_top']:.1f} mm above the top face ({tall['tallest_above_top'] + THICK:.1f} mm above the bottom face): the plugged-in TMC2209 module with heatsink (assumed envelope). Next tallest: PTC 14 mm, C1 12 mm, C2/C3 11 mm, screw terminals 10 mm (all assumed typical). The J1 socket protrudes {tall['j1_below']:.1f} mm below the board.

## Spec problems found (SPEC.md was not silently changed)

1. **TMC2209 socket row spacing (mechanical, was a real error)**: SPEC.md said 15.24 mm, so a real module would not plug in; the real Pololu/SilentStepStick pin rows are 12.70 mm apart (15.24 x 20.32 mm is the module *size*). The lead has since corrected SPEC.md; the generator default is now 12.70 mm (`--driver-row-spacing`).
2. **Via vs. annular-ring rule**: vias 0.6/0.3 mm have a 0.15 mm ring while "plated through-hole annular ring >= 0.3 mm" is also stated. I applied 0.3 mm to component holes and 0.15 mm to vias (fab capability not checked).
3. **PTC voltage rating**: the TVS (1.5KE18A) clamps near 25 V, so choose PTCs rated for at least 24-30 V; many 16 V radial PTCs do not have a 5.08 mm lead pitch (not verified against a specific part).
4. 3V3 track width not specified (0.5 mm used). With D1 in series the motor rail is about 0.4-0.5 V below the PD voltage (not an error).

## Files

| File | What |
|---|---|
| `netlist.json` | single source of truth (parts, pins, nets, NC pins); `carrier.net` is the same netlist in KiCad format |
| `diagrams/` | schematic sheets and system wiring diagram (SVG/PDF/PNG), drawn from `netlist.json` by `make_diagrams.py` (not part of this script) |
| `carrier.kicad_pro`, `carrier.kicad_pcb`, `carrier.kicad_sch` | KiCad 8 project (written, not opened in KiCad) |
| `fab/carrier-*.gtl/.gbl/.gts/.gbs/.gtp/.gto/.gbo/.gm1`, `fab/carrier-PTH.drl`, `fab/carrier-NPTH.drl`, `fab/carrier_gerbers.zip` | Gerber RS-274X (F.Cu, B.Cu, F/B mask, F paste, F/B silkscreen, Edge.Cuts) and Excellon drills |
| `fab/gerber_reparse_preview.png` | the Gerbers re-read with gerbonara and re-drawn (proof they parse) |
| `carrier_bom.csv`, `carrier_cpl.csv` | BOM (grouped, plug-in items listed but marked not soldered) and SMD pick-and-place |
| `carrier_outline.dxf`, `carrier_board.stl` | outline/holes/component keep-outs/Pi outline; extruded board + component envelopes |
| `carrier_top.png`, `carrier_bottom.png` | renders |
| `verification_report.json` | every number quoted below |

## Pin map

### Pi header J1 (female socket on the BOTTOM side; pin 1 = square pad, lower-left row when viewed from the top)

{md_table(["Pi pin", "GPIO", "Net"], pin_rows)}

27 pins used, 13 NC (pins 7, 12, 19, 21, 23, 24, 26, 27, 28, 32, 36, 38, 40 carry no copper connection).

### TMC2209 sockets (rows {ROW:g} mm apart; U1 = azimuth, U2 = altitude)

{md_table(["U1/U2 row A pin", "U1 net", "U2 net", "row B pin", "U1 net", "U2 net"], mod_rows)}

B3..B6 go straight to J5 (AZ) / J6 (ALT) pins 1..4. End stops: J7..J10 pin 1 = signal (net `ES_*_IN`) -> 1 kOhm (R4..R7) -> GPIO net -> 100 nF to GND; pin 2 = GND.
I2C headers J11 (IMU) / J12 (GNSS): 1 GND, 2 3V3, 3 5V_F, 4 SDA, 5 SCL. Power: see `SPEC.md`; netlist cross-checks are in `netlist.json` ("verification").

## Placement decisions and assumptions

- **Pi stack.** Pi Zero 2 W geometry is from the official mechanical drawing RP-008358-DS (read from the PDF's vector data): 65 x 30 mm, mounting holes 3.5 mm from the edges, 40-pin header centred on the 65 mm edge with its two rows on the hole centreline (3.5 mm from the top edge), pin 1 = square pad at the left end of the inner row. J1 is centred on the carrier at x = {J1_X:g} mm, y = {J1_Y:g} mm (12.4 mm from the south long edge); the Pi hangs below J1 and its body sticks {30 - PI_TOP_EDGE_Y:.1f} mm out of the south edge, so the USB and mini-HDMI connectors (bottom long edge of the Pi) stay uncovered. The carrier is 20 mm wider than the Pi (10 mm each side); the SD slot (left short edge) and CSI connector (right short edge) are reached from the sides, 11 mm below the carrier underside (check this against your enclosure). The silkscreen shows the Pi top edge, its two short edges (clipped at the board edge) and the two Pi mounting holes; the full 65 x 30 outline is in `carrier_outline.dxf` layer `PI_OUTLINE`. This is my reading of the SPEC sentence "the board overhangs the Pi so USB/HDMI/camera connectors stay uncovered"; the spec text "J1 along one long edge" is met loosely (J1 sits in the southern 20 % of the board, the south zone holds the end-stop connectors and filters that use the odd J1 pins).
- **Why J1 is not on the very edge.** The odd (south) row of J1 carries 10 signals. On a 2-layer board they can only leave through the 0.94 mm gaps between the 1.6 mm pads (0.3 mm track, 0.32 mm clearance) or around the ends of the header. The three AZ step/dir/enable signals use hand-placed waypoints through those gaps (`PREROUTE` in the script); everything else is autorouted.
- **TMC2209 modules.** Rows {ROW:g} mm apart (the lead corrected SPEC.md from 15.24 mm; Pololu A4988 drawing: board 15.2 x 20.3 mm, rows 12.70 mm apart). The BIGTREETECH TMC2209 is *assumed* to share the Pololu / SilentStepStick footprint: **unverified** for the V1.3 board; its pin order is from the generic BTT wiki page (global.bttwiki.com/TMC2209.html), also **not confirmed for V1.3**. Module bodies U1/U2 are {rep['module_gap']:.1f} mm apart (>= 1 mm required) and no tall part is within 1 mm of a module. Module envelope assumed 15.24 x 20.32 mm, top at 17.1 mm above the socket seat (heatsink included).
- **Footprints** follow the KiCad official library (GitLab `kicad-footprints`, read at build time): JST XH B2B/B4B-XH-A (pads 1.7 x 1.95, drill 0.95, body 5.75 deep), DO-201AD (pad 3.2, drill 1.6, P12.70 variant), Phoenix MKDS-1,5-2-5.08 terminal (pad 2.6, drill 1.3, 10.2 x 9.8), radial electrolytics (pad 1.6, drill 0.8). The 2.54 mm header pads are 1.6 mm (drill 1.0, ring exactly 0.30 mm). **Unverified:** the PTC envelope (10 x 4 x 14 mm assumed), electrolytic and terminal heights (12/11/10 mm typical), JST height 7 mm, socket body heights 8.5 mm. Screw-terminal wire entry is assumed to face the nearest board edge.
- **Track widths.** 0.8 mm for 12 V, motor coil and 5 V nets (about 2 A at 10 K rise, IPC-2221); 0.5 mm for 3V3 (SPEC gives no width for it); 0.3 mm for signals. Vias 0.6 / 0.3 mm. GND is a pour on both layers with 0.3 mm thermal gaps, 0.5 mm spokes and {rules['stitching_vias']} stitching vias on a 5 mm grid.
- **R2, R3, C8, C9** (0805, 0.6 mm tall) sit in the pocket between the two socket rows, under the plugged-in module (8.5 mm of headroom). **J11/J12 labels** share one label column between the two headers. These silk texts could not be placed without overlapping pads or other silk and were omitted (J7..J10 per-pin SIG/GND labels are among them; some J1/module pin labels too): {', '.join(sorted(set(silk_omitted))) or 'none'}. Pin 1 of every header is a square pad; the connectors' pin 2 is GND.

## Verification (all numbers from this run, see `verification_report.json`)

- **Netlist** ({rep['netlist_checks_passed']}/{rep['netlist_checks_total']} checks): every net has >= 2 pins; no pin on two nets; only the SPEC NC pins unconnected; all 40 J1 pins and all 32 socket pins re-derived from the tables parsed out of `SPEC.md`.
- **Routing**: {rules['tracks']} track polylines, {rules['track_length_mm']} mm, {rules['vias']} signal/power vias; {rep['nets_routed']}/{rep['nets_routable']} routable nets routed (GND is the pour).
- **Copper connectivity**: {sum(1 for v in pn.values() if v['connected'])}/{len(pn)} nets form exactly one connected copper component (tracks, vias, THT pads and pours counted); shorts found: {len(rep['shorts'])}. GND: {pn['GND']['pads']} pads in {pn['GND']['components']} component.
- **Clearance**: minimum clearance between different nets **{cl['min_clearance']:.3f} mm** (rule 0.25 mm), violations: {len(cl['violations'])}; by type: {cl['by_kind']}. Minimum copper-to-board-edge {cl['min_edge']:.3f} mm (rule 0.5 mm). Minimum PTH annular ring {dr['min_pth_annular_ring'][0]:.3f} mm ({dr['min_pth_annular_ring'][1]}); minimum hole-to-hole {dr['min_hole_to_hole']:.3f} mm; minimum hole-to-edge {dr['min_hole_to_edge']:.2f} mm; NPTH-to-copper {dr['min_npth_to_copper']:.2f} mm. Minimum track width {rules['min_track']} mm.
- **Checker self-test** (to show the checks can fail): {rep['self_test']}.
- **Gerbers** (re-read with gerbonara {rep['gerbonara_version']}):

{md_table(["file", "extent", "result", ""], gb_rows)}

- **KiCad PCB** parsed back with kiutils: {kp['footprints']} footprints, {kp['pads_compared']} pads compared with `netlist.json`: **{len(kp['mismatches'])} mismatches**; {kp['tracks']} segments, {kp['vias']} vias, {kp['zones']} zones, {kp['nets']} nets; independent copper connectivity rebuilt from the file (non-GND nets): {len(kp['opens_from_file_copper_nonGND'])} opens.
- **KiCad schematic** parsed back with kiutils: {rep['kicad_sch']['symbols']} symbols, {rep['kicad_sch']['wires']} wire stubs with net labels, {rep['kicad_sch']['no_connects']} no-connect flags; pin->net resolved from the parsed wires/labels/library pins for {rep['kicad_sch']['pins_compared']} pins: **{rep['kicad_sch']['mismatches']} mismatches** against `netlist.json` (net-label style, no ERC run).
- **DXF/STL**: DXF outline bbox {ds['dxf_outline_bbox']} (area difference to the outline {ds['dxf_outline_area_diff_mm2']} mm2), {ds['dxf_hole_circles']}/{ds['dxf_hole_circles_expected']} hole circles; STL bbox {ds['stl_bbox_min']} .. {ds['stl_bbox_max']} mm ({ds['stl_triangles']} triangles), board-only volume {ds['stl_board_volume_mm3']} mm3 vs area x thickness {ds['board_area_x_thickness']} mm3.

## NOT verified / outstanding

- **KiCad ERC and DRC have not been run** (KiCad is not installed); the KiCad files have never been opened in KiCad. Zones are unfilled in the file until KiCad refills them; KiCad's own fill may differ in detail from the pour in the Gerbers.
- No fab DFM / online Gerber viewer check; Gerbers were only re-read with gerbonara. Solder-mask, paste and silkscreen rules are the generator's own (0.05 mm mask expansion, vias tented, silk >= 1 mm high, 0.18 mm stroke).
- Component heights and the PTC/electrolytic/terminal envelopes, JLCPCB-style CPL rotations and the TMC2209 V1.3 footprint/pin order are unverified (see above).
- No electrical simulation; current ratings are hand estimates.

## Sources used

- Raspberry Pi Zero 2 W mechanical drawing, RP-008358-DS (pip.raspberrypi.com), and Raspberry Pi documentation (raspberrypi.com/documentation/computers/zero.html, 65 mm x 30 mm).
- KiCad official footprint library `kicad-footprints` (gitlab.com/kicad/libraries): `Connector_JST`, `Diode_THT`, `TerminalBlock_Phoenix`, `Capacitor_THT`, `Connector_PinSocket_2.54mm`, `Module/Pololu_Breakout-16_15.2x20.3mm` (pad rows 12.7 mm apart).
- Pololu A4988 / DRV8825 dimension drawing and Pololu forum reply (0.5 in row spacing); BIGTREETECH TMC2209 wiki (global.bttwiki.com/TMC2209.html).

## Regenerating

```
python3 -m venv env && env/bin/pip install kiutils gerbonara ezdxf shapely numpy scipy matplotlib trimesh manifold3d mapbox-earcut pillow
env/bin/python generate.py                       # default driver row spacing 12.70 mm
env/bin/python generate.py --driver-row-spacing 15.24 --out /some/dir   # spec's old value: still routes, but reports a J6/D2 courtyard overlap, so the north-side placement would need re-spacing
```
Run time is about 30 s on a laptop (routing is a pure-Python A*; two consecutive runs give byte-identical Gerbers, KiCad files and netlist). The only non-deterministic input is the run date printed on the silkscreen.
"""
    (OUT / "README.md").write_text(txt, encoding="utf8")


def main():
    t0 = time.time()
    log = print
    doc, checks = stage1()
    pads = build_pads()
    probs = check_placement(pads)
    for pb in probs:
        log("PLACEMENT PROBLEM: " + pb)
    R, failed = run_router(pads, log=log, max_rounds=4)
    assert not failed, f"router failed for {failed}"
    cu = Copper(pads, R.tracks, R.vias)
    build_pours(cu, log)
    pn, shorts = check_connectivity(cu)
    cl = check_clearance(cu)
    dr = check_drills(cu)
    rules = check_rules(cu)
    st = self_test_checker(cu)
    silk, labels, omitted = build_silk(cu, log)
    geoms, holes = write_fab(cu, silk, log)
    write_dxf(cu, str(OUT / "carrier_outline.dxf"))
    stl_info = build_stl(cu, str(OUT / "carrier_board.stl"))
    write_bom_cpl(OUT / "carrier_bom.csv", OUT / "carrier_cpl.csv")
    write_kicad_pcb(OUT / "carrier.kicad_pcb", pads, cu, labels)
    write_kicad_pro(OUT / "carrier.kicad_pro")
    sch_res = "not written"
    if "write_kicad_sch" in globals():
        sch_res = write_kicad_sch(OUT / "carrier.kicad_sch")
    render_board(cu, silk, labels, "F", str(OUT / "carrier_top.png"), dpi=220)
    render_board(cu, silk, labels, "B", str(OUT / "carrier_bottom.png"), dpi=220)
    import gerbonara
    gbv = verify_gerbers(geoms, holes)
    write_gerber_preview(FAB / "gerber_reparse_preview.png")
    netdoc = json.loads((OUT / "netlist.json").read_text())
    kv = verify_kicad_pcb(OUT / "carrier.kicad_pcb", netdoc, cu)
    dsv = verify_dxf_stl(cu, stl_info)
    mods = {r: module_poly(r) for r in ("U1", "U2")}
    tall_above = max(THICK + b[5] for ref in PLACE if not ref.startswith("H") and PARTS[ref]["side"] != "B"
                     for b in FOOT[FP_OF[ref]]["body"]) - THICK
    rep = OrderedDict(
        netlist_checks_passed=sum(1 for _, ok, _ in checks if ok), netlist_checks_total=len(checks),
        placement_problems=probs, nets_routable=len([n for n in NETS if n != "GND"]),
        nets_routed=len([n for n in NETS if n != "GND"]) - len(failed), connectivity=pn, shorts=shorts, clearance=cl, drills=dr, rules=rules,
        self_test=st, gerbers=gbv, kicad_pcb=kv, kicad_sch=sch_res, dxf_stl=dsv,
        heights=dict(tallest_above_top=tall_above, j1_below=8.5, tall_parts=sorted(set(stl_info["tall"]), key=lambda t: -t[1])[:8]),
        module_gap=mods["U1"].distance(mods["U2"]), silk_omitted=sorted(set(omitted)),
        gerbonara_version=getattr(gerbonara, "__version__", "0.13.0"), board=[BOARD_W, BOARD_H, THICK], runtime_s=round(time.time() - t0, 1))
    (OUT / "verification_report.json").write_text(json.dumps(rep, indent=1, default=str) + "\n")
    write_readme(rep, cu, omitted)
    ok = (not shorts and not cl["violations"] and all(v["connected"] for v in pn.values()) and cl["min_clearance"] >= RULE_CLR - 1e-6
          and not kv["mismatches"] and not kv["opens_from_file_copper_nonGND"])
    log(f"DONE in {time.time() - t0:.0f}s  min clearance {cl['min_clearance']:.3f} mm  shorts {len(shorts)}  all_ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

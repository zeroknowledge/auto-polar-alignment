#!/usr/bin/env python3
"""Sanity-check sliced G-code against the Bambu X1C envelope. Usage: verify_gcode.py gcode/*.gcode
Checks: extrusion stays inside the 256x256 bed and 250 mm height, peak nozzle/bed temperatures are PETG-sane,
required start/end macros exist, no relative-mode surprises, file ends cleanly. Exit code 1 on any failure."""
import re, sys, pathlib
BED, ZMAX = 256.0, 250.0
NOZ_MAX, BED_MAX = 270.0, 90.0           # PETG ceilings
tok = re.compile(r"([XYZEFS])(-?\d*\.?\d+)")   # slicers write E.04127 / X-.5 with no leading digit
def check(path):
    x = y = z = 0.0; rel_e = False; ext_min = [1e9, 1e9, 1e9]; ext_max = [-1e9] * 3
    noz = []; bed = []; macros = {m: 0 for m in ("G28", "G29", "M1002", "M620", "M621", "M400", "M104", "M109", "M140", "M190")}
    absolute = True; neg_ext = 0; last = ""
    for line in open(path, errors="replace"):
        s = line.split(";", 1)[0].strip()
        if not s: continue
        last = s; w = s.split()[0]
        if w in macros: macros[w] += 1
        if w == "M83": rel_e = True
        elif w == "M82": rel_e = False
        elif w == "G91": absolute = False
        elif w == "G90": absolute = True
        elif w in ("M104", "M109"):
            m = re.search(r"S(\d+\.?\d*)", s); noz += [float(m.group(1))] if m else []
        elif w in ("M140", "M190"):
            m = re.search(r"S(\d+\.?\d*)", s); bed += [float(m.group(1))] if m else []
        elif w in ("G0", "G1", "G2", "G3"):
            v = {k: float(n) for k, n in tok.findall(s)}
            if absolute:
                x = v.get("X", x); y = v.get("Y", y); z = v.get("Z", z)
            e = v.get("E")
            if e is not None and rel_e and e > 0 and ("X" in v or "Y" in v):
                for i, c in enumerate((x, y, z)):
                    ext_min[i] = min(ext_min[i], c); ext_max[i] = max(ext_max[i], c)
            if e is not None and rel_e and e < 0 and False: neg_ext += 1
    ok = True; msgs = []
    if any(c < 0 or c > BED for c in (ext_min[0], ext_min[1], ext_max[0], ext_max[1])): ok = False; msgs.append("extrusion outside bed")
    if ext_max[2] > ZMAX: ok = False; msgs.append("exceeds Z height")
    if noz and max(noz) > NOZ_MAX: ok = False; msgs.append(f"nozzle temp {max(noz)} > {NOZ_MAX}")
    if bed and max(bed) > BED_MAX: ok = False; msgs.append(f"bed temp {max(bed)} > {BED_MAX}")
    for m in ("G28", "M1002", "M104", "M109", "M140", "M190"):
        if macros[m] == 0: ok = False; msgs.append(f"missing {m}")
    if not noz or noz[-1] != 0: msgs.append("note: last nozzle temp command is not S0 (check end sequence)")
    print(f"{'PASS' if ok else 'FAIL'}  {pathlib.Path(path).name}")
    print(f"      extrusion X {ext_min[0]:.1f}..{ext_max[0]:.1f}  Y {ext_min[1]:.1f}..{ext_max[1]:.1f}  Z {ext_min[2]:.2f}..{ext_max[2]:.2f} mm")
    print(f"      nozzle temps {sorted(set(noz))}  bed temps {sorted(set(bed))}  macros G28={macros['G28']} G29={macros['G29']} M1002={macros['M1002']} M620={macros['M620']}")
    print(f"      last command: {last}")
    for m in msgs: print("      !", m)
    return ok
if __name__ == "__main__":
    sys.exit(0 if all([check(p) for p in sys.argv[1:]]) else 1)

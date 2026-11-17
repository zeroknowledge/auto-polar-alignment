#!/usr/bin/env python3
"""Independent checks of the carrier PCB (lead's script, shares no code with generate.py).

Reads ONLY: carrier.kicad_pcb, netlist.json, fab/*.gtl|gbl|drl|zip, carrier_board.stl.
Needs: kiutils, shapely, gerbonara, numpy, trimesh.   Run:  python check_independent.py

Checks
  1  pin map: every pad's net equals netlist.json, NC pads carry no net
  2  footprint geometry: pitches / row spacings against the standard parts
  3  copper clearance between different nets on each layer (and to non-plated holes)
  4  copper-to-board-edge distance and containment
  5  annular rings and hole-to-hole spacing
  6  connectivity of every net except GND (GND is a pour; the zones are saved unfilled, so it cannot be tested here)
  7  KiCad file vs Excellon drill files: every hole matched by position and diameter
  8  Gerber extents, zip contents, board STL size
Limits (stated, not hidden): KiCad's own ERC/DRC was not run (KiCad is not installed); the GND pour is not verified;
solder-mask and silkscreen rules are not checked.
"""
import json
import math
import pathlib
import sys
import zipfile
from collections import defaultdict

import numpy as np
from kiutils.board import Board
from kiutils.items.brditems import Segment, Via
from shapely.geometry import LineString, Point, box
from shapely.affinity import rotate
from shapely.strtree import STRtree

HERE = pathlib.Path(__file__).resolve().parent
MIN_CLEAR, MIN_EDGE, MIN_RING, MIN_HOLE_GAP = 0.20, 0.30, 0.15, 0.25   # typical low-cost fab limits (mm)
results = []


def report(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))


board = Board.from_file(str(HERE / "carrier.kicad_pcb"))
NL = json.loads((HERE / "netlist.json").read_text())
NLP = {p["ref"]: p for p in NL["parts"]}
netname = {n.number: n.name for n in board.nets}

# ---------------------------------------------------------------- build copper items
def fp_ref(fp):
    return fp.properties.get("Reference") if fp.properties else None


def to_world(fp, lx, ly):
    a = math.radians(fp.position.angle or 0.0)
    return (fp.position.X + lx * math.cos(a) + ly * math.sin(a), fp.position.Y - lx * math.sin(a) + ly * math.cos(a))


def pad_geom(cx, cy, w, h, shape, ang):
    if shape == "circle":
        g = Point(cx, cy).buffer(w / 2, 24)
    elif shape == "oval":
        if abs(w - h) < 1e-6:
            g = Point(cx, cy).buffer(w / 2, 24)
        elif w > h:
            g = LineString([(cx - (w - h) / 2, cy), (cx + (w - h) / 2, cy)]).buffer(h / 2, 24)
        else:
            g = LineString([(cx, cy - (h - w) / 2), (cx, cy + (h - w) / 2)]).buffer(w / 2, 24)
    else:
        g = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return rotate(g, -ang, origin=(cx, cy)) if ang else g


items = []          # dict(id, kind, net, geoms{layer: geom}, ref, pin)
holes = []          # dict(x, y, d, plated, owner, net)
padpos = defaultdict(dict)
for fp in board.footprints:
    ref = fp_ref(fp)
    for pad in fp.pads:
        cx, cy = to_world(fp, pad.position.X, pad.position.Y)
        padpos[ref][pad.number] = (cx, cy)
        net = pad.net.name if (pad.net and pad.net.name) else None
        if pad.drill and pad.drill.diameter:
            holes.append(dict(x=cx, y=cy, d=pad.drill.diameter, plated=pad.type == "thru_hole", owner=f"{ref}.{pad.number}", net=net))
        if pad.type == "np_thru_hole":
            continue
        layers = [l for l in ("F.Cu", "B.Cu") if ("*.Cu" in pad.layers or l in pad.layers)]
        ang = pad.position.angle or 0.0
        g = pad_geom(cx, cy, pad.size.X, pad.size.Y, pad.shape, ang)
        items.append(dict(id=f"{ref}.{pad.number}", kind="pad", net=net, geoms={l: g for l in layers}, ref=ref, pin=pad.number,
                          size=min(pad.size.X, pad.size.Y), drill=pad.drill.diameter if pad.drill else 0))
for t in board.traceItems:
    net = netname.get(t.net)
    if isinstance(t, Segment):
        items.append(dict(id=f"trk{len(items)}", kind="track", net=net, width=t.width,
                          geoms={t.layer: LineString([(t.start.X, t.start.Y), (t.end.X, t.end.Y)]).buffer(t.width / 2, 12)}))
    elif isinstance(t, Via):
        g = Point(t.position.X, t.position.Y).buffer(t.size / 2, 24)
        items.append(dict(id=f"via{len(items)}", kind="via", net=net, geoms={"F.Cu": g, "B.Cu": g}, size=t.size, drill=t.drill))
        holes.append(dict(x=t.position.X, y=t.position.Y, d=t.drill, plated=True, owner="via", net=net))

# ---------------------------------------------------------------- board outline (Edge.Cuts)
pts = []
for g in board.graphicItems:
    if getattr(g, "layer", None) == "Edge.Cuts":
        for a in ("start", "mid", "end"):
            p = getattr(g, a, None)
            if p is not None:
                pts.append((p.X, p.Y))
xs, ys = zip(*pts)
x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
BW, BH = x1 - x0, y1 - y0
RADIUS = 2.0
interior = box(x0 + RADIUS, y0 + RADIUS, x1 - RADIUS, y1 - RADIUS).buffer(RADIUS, 32)
print(f"board outline {BW:.2f} x {BH:.2f} mm; {len(board.footprints)} footprints, {sum(1 for i in items if i['kind']=='track')} track segments, "
      f"{sum(1 for i in items if i['kind']=='via')} vias, {len(holes)} holes")

# ---------------------------------------------------------------- 1 pin map
bad = []
for fp in board.footprints:
    ref = fp_ref(fp)
    want = NLP.get(ref, {}).get("pins", {})
    for pad in fp.pads:
        got = pad.net.name if (pad.net and pad.net.name) else None
        if ref in NLP and pad.type != "np_thru_hole" and want.get(pad.number) != got:
            bad.append(f"{ref}.{pad.number}: board {got!r} vs netlist {want.get(pad.number)!r}")
missing = [r for r in NLP if r not in {fp_ref(f) for f in board.footprints}]
report("1 pin map matches netlist.json", not bad and not missing,
       f"{sum(len(f.pads) for f in board.footprints)} pads checked; mismatches: {bad[:4]} missing parts: {missing}")

# ---------------------------------------------------------------- 2 footprint geometry
def pitches(ref, pins):
    p = [padpos[ref][k] for k in pins]
    return p

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

geo = []
def expect(label, got, want, tol=0.02):
    ok = abs(got - want) <= tol
    geo.append(ok)
    if not ok:
        print(f"      geometry mismatch: {label}: {got:.3f} mm, expected {want:.3f}")
    return ok

for u in ("U1", "U2"):
    expect(f"{u} row spacing A-to-B", dist(padpos[u]["A1"], padpos[u]["B1"]), 12.70)
    expect(f"{u} pitch", dist(padpos[u]["A1"], padpos[u]["A2"]), 2.54)
    expect(f"{u} length A1-A8", dist(padpos[u]["A1"], padpos[u]["A8"]), 7 * 2.54)
expect("J1 pitch", dist(padpos["J1"]["1"], padpos["J1"]["3"]), 2.54)
expect("J1 row spacing", dist(padpos["J1"]["1"], padpos["J1"]["2"]), 2.54)
expect("J1 length pins 1-39", dist(padpos["J1"]["1"], padpos["J1"]["39"]), 19 * 2.54)
for j in ("J2", "J3", "J4"):
    expect(f"{j} pitch", dist(padpos[j]["1"], padpos[j]["2"]), 5.08)
for j in ("J5", "J6"):
    expect(f"{j} pitch (JST-XH)", dist(padpos[j]["1"], padpos[j]["2"]), 2.5)
for j in ("J7", "J8", "J9", "J10"):
    expect(f"{j} pitch (JST-XH)", dist(padpos[j]["1"], padpos[j]["2"]), 2.5)
for j in ("J11", "J12"):
    expect(f"{j} pitch", dist(padpos[j]["1"], padpos[j]["2"]), 2.54)
for f_ in ("F1", "F2"):
    expect(f"{f_} lead pitch", dist(padpos[f_]["1"], padpos[f_]["2"]), 5.08)
expect("C1 lead pitch", dist(padpos["C1"]["1"], padpos["C1"]["2"]), 3.5)
for c in ("C2", "C3"):
    expect(f"{c} lead pitch", dist(padpos[c]["1"], padpos[c]["2"]), 2.5)
d1 = dist(padpos["D1"]["1"], padpos["D1"]["2"]); d2 = dist(padpos["D2"]["1"], padpos["D2"]["2"])
report("2 standard footprint dimensions", all(geo),
       f"{len(geo)} dimensions checked (Pololu 12.70 mm rows, 2.54 headers, 5.08 terminals, 2.5 JST-XH); diode lead spans D1 {d1:.2f} mm, D2 {d2:.2f} mm (DO-201AD is normally 12.7 mm or more)")

# ---------------------------------------------------------------- 3 clearance
worst = {}
viol = []
for layer in ("F.Cu", "B.Cu"):
    its = [i for i in items if layer in i["geoms"]]
    geoms = [i["geoms"][layer] for i in its]
    tree = STRtree(geoms)
    mind = 9.9
    for a, ga in enumerate(geoms):
        for b in tree.query(ga.buffer(0.5)):
            if b <= a:
                continue
            ia, ib = its[a], its[b]
            if ia["net"] == ib["net"] and ia["net"] is not None:
                continue
            if ia.get("ref") and ia.get("ref") == ib.get("ref") and ia["net"] is None and ib["net"] is None:
                continue
            d = ga.distance(geoms[b])
            mind = min(mind, d)
            if d < MIN_CLEAR:
                viol.append((layer, ia["id"], ia["net"], ib["id"], ib["net"], round(d, 3)))
    worst[layer] = mind
npth = [h for h in holes if not h["plated"]]
hole_min = 9.9
for h in npth:
    hg = Point(h["x"], h["y"]).buffer(h["d"] / 2, 24)
    for i in items:
        for g in i["geoms"].values():
            hole_min = min(hole_min, hg.distance(g))
report("3 clearance between different nets", not viol,
       f"min F.Cu {worst['F.Cu']:.3f} mm, B.Cu {worst['B.Cu']:.3f} mm (limit {MIN_CLEAR}); non-plated hole to copper {hole_min:.2f} mm; violations: {viol[:5]}")

# ---------------------------------------------------------------- 4 edge
edge_min = 9.9
outside = []
for i in items:
    for g in i["geoms"].values():
        if not interior.contains(g):
            outside.append(i["id"])
        edge_min = min(edge_min, interior.exterior.distance(g))
report("4 copper inside outline, distance to edge", not outside and edge_min >= MIN_EDGE,
       f"min copper-to-edge {edge_min:.3f} mm (limit {MIN_EDGE}); outside: {outside[:5]}")

# ---------------------------------------------------------------- 5 rings, hole gaps
rings = [((i["size"] - i["drill"]) / 2, i["id"]) for i in items if i.get("drill")]
ring_min = min(rings)
gaps = []
for a in range(len(holes)):
    for b in range(a + 1, len(holes)):
        ha, hb = holes[a], holes[b]
        c = math.hypot(ha["x"] - hb["x"], ha["y"] - hb["y"])
        if c < 3.0:
            gaps.append((c - (ha["d"] + hb["d"]) / 2, ha["owner"], hb["owner"]))
gap_min = min(gaps) if gaps else (9.9, "", "")
report("5 annular ring and hole-to-hole spacing", ring_min[0] >= MIN_RING and gap_min[0] >= MIN_HOLE_GAP,
       f"min ring {ring_min[0]:.3f} mm at {ring_min[1]} (limit {MIN_RING}); min hole-to-hole wall {gap_min[0]:.3f} mm between {gap_min[1]} and {gap_min[2]} (limit {MIN_HOLE_GAP})")

# ---------------------------------------------------------------- 6 connectivity (except GND)
parent = list(range(len(items)))
def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]
        a = parent[a]
    return a
shorts = []
for layer in ("F.Cu", "B.Cu"):
    idx = [k for k, i in enumerate(items) if layer in i["geoms"]]
    geoms = [items[k]["geoms"][layer] for k in idx]
    tree = STRtree(geoms)
    for a, ga in enumerate(geoms):
        for b in tree.query(ga):
            if b <= a or not ga.intersects(geoms[b]):
                continue
            ka, kb = idx[a], idx[b]
            if items[ka]["net"] != items[kb]["net"]:
                shorts.append((items[ka]["id"], items[ka]["net"], items[kb]["id"], items[kb]["net"]))
            else:
                parent[find(ka)] = find(kb)
comp = defaultdict(set)
for k, i in enumerate(items):
    if i["net"]:
        comp[i["net"]].add(find(k))
open_nets = {n: len(c) for n, c in comp.items() if len(c) > 1 and n != "GND"}
nets_checked = [n for n in comp if n != "GND"]
report("6 every non-GND net is one connected piece of copper, no shorts", not open_nets and not shorts,
       f"{len(nets_checked)} nets checked; open nets {open_nets}; shorts {shorts[:3]}")
gnd_pads = sum(1 for i in items if i["net"] == "GND" and i["kind"] == "pad")
print(f"      note: GND has {gnd_pads} pads and relies on the pour; {len([z for z in board.zones if not z.filledPolygons])} zones are saved unfilled, so GND connectivity is NOT verified here")

# ---------------------------------------------------------------- 7 drills vs Excellon
from gerbonara import ExcellonFile, GerberFile
import gerbonara
def excellon(path):
    return [(round(o.x, 3), round(o.y, 3), round(o.tool.diameter, 3)) for o in ExcellonFile.open(str(path)).objects]
pth = excellon(HERE / "fab" / "carrier-PTH.drl")
npth_x = excellon(HERE / "fab" / "carrier-NPTH.drl")
ex = [e for e in (b[2] for b in [])]  # placeholder to keep lints quiet
# KiCad (y down, offset) -> Gerber (y up, origin at lower-left of outline)
def to_g(x, y):
    return (round(x - x0, 3), round(y1 - y, 3))
kh_pth = [(*to_g(h["x"], h["y"]), round(h["d"], 3)) for h in holes if h["plated"]]
kh_np = [(*to_g(h["x"], h["y"]), round(h["d"], 3)) for h in holes if not h["plated"]]
def match(a, b):
    left, worst_ = 0, 0.0
    pool = list(b)
    for (x, y, d) in a:
        best = None
        for k, (xx, yy, dd) in enumerate(pool):
            if abs(dd - d) < 0.011:
                e = math.hypot(x - xx, y - yy)
                if best is None or e < best[0]:
                    best = (e, k)
        if best is None or best[0] > 0.02:
            left += 1
        else:
            worst_ = max(worst_, best[0])
            pool.pop(best[1])
    return left, worst_, len(pool)
l1, w1, r1 = match(kh_pth, pth)
l2, w2, r2 = match(kh_np, npth_x)
report("7 KiCad holes == Excellon holes (position + diameter)", l1 == 0 and r1 == 0 and l2 == 0 and r2 == 0,
       f"PTH: {len(kh_pth)} in KiCad / {len(pth)} in drill file, unmatched {l1}/{r1}, worst offset {w1:.4f} mm; NPTH: {len(kh_np)}/{len(npth_x)} unmatched {l2}/{r2}")
dias = sorted({d for _, _, d in pth})
print(f"      drill sizes used (mm): {dias}")

# ---------------------------------------------------------------- 8 gerbers, zip, stl
ok8 = True
msgs = []
for fn in ("carrier-F_Cu.gtl", "carrier-B_Cu.gbl", "carrier-F_Mask.gts", "carrier-B_Mask.gbs", "carrier-F_Silkscreen.gto",
           "carrier-B_Silkscreen.gbo", "carrier-Edge_Cuts.gm1"):
    try:
        g = GerberFile.open(str(HERE / "fab" / fn))
        (bx0, by0), (bx1, by1) = g.bounding_box(unit=gerbonara.utils.MM)
        inside = bx0 >= -0.1 and by0 >= -0.1 and bx1 <= BW + 0.1 and by1 <= BH + 0.1
        ok8 &= inside
        msgs.append(f"{fn}: {len(list(g.objects))} objects, extents {bx0:.2f},{by0:.2f} to {bx1:.2f},{by1:.2f}{'' if inside else '  OUTSIDE OUTLINE'}")
    except Exception as e:                                     # noqa: BLE001
        ok8 = False
        msgs.append(f"{fn}: cannot parse ({e})")
z = zipfile.ZipFile(HERE / "fab" / "carrier_gerbers.zip")
names = set(z.namelist())
need = {"carrier-F_Cu.gtl", "carrier-B_Cu.gbl", "carrier-Edge_Cuts.gm1", "carrier-PTH.drl", "carrier-NPTH.drl",
        "carrier-F_Mask.gts", "carrier-B_Mask.gbs", "carrier-F_Silkscreen.gto", "carrier-B_Silkscreen.gbo"}
missing_z = sorted(need - {n.split("/")[-1] for n in names})
ok8 &= not missing_z
import trimesh
m = trimesh.load(str(HERE / "carrier_board.stl"))
ext = m.bounds[1] - m.bounds[0]
stl_ok = abs(ext[0] - BW) < 1.0 and abs(ext[1] - BH) < 1.0
ok8 &= stl_ok
report("8 Gerbers parse and fit the outline; zip complete; STL matches board", ok8,
       f"zip has {len(names)} files, missing {missing_z}; STL {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm")
for s in msgs:
    print("      " + s)

print()
print(f"{sum(results)}/{len(results)} checks passed")
print("NOT verified: KiCad ERC/DRC (KiCad not installed); GND pour continuity; mask/silkscreen rules; footprint pinouts of your actual modules.")
sys.exit(0 if all(results) else 1)

#!/usr/bin/env python3
"""Write connectors.json: per-connector pad bounding box in BOARD coordinates (mm, origin at the south-west corner, y up).
Read by ../cad/aligner_case.py so the case's cable slots follow the real connector positions. Needs kiutils."""
import json, math, pathlib
from kiutils.board import Board
HERE = pathlib.Path(__file__).resolve().parent
b = Board.from_file(str(HERE / "carrier.kicad_pcb"))
xs, ys = [], []
for g in b.graphicItems:
    if getattr(g, "layer", None) == "Edge.Cuts":
        for a in ("start", "mid", "end"):
            p = getattr(g, a, None)
            if p is not None:
                xs.append(p.X); ys.append(p.Y)
x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
def world(fp, lx, ly):
    a = math.radians(fp.position.angle or 0.0)
    return (fp.position.X + lx * math.cos(a) + ly * math.sin(a), fp.position.Y - lx * math.sin(a) + ly * math.cos(a))
out = {"board": {"w": round(x1 - x0, 3), "h": round(y1 - y0, 3)}, "parts": {}}
for fp in b.footprints:
    ref = fp.properties.get("Reference")
    pts = []
    for pad in fp.pads:
        wx, wy = world(fp, pad.position.X, pad.position.Y)
        pts.append((wx - x0, y1 - wy))
    if pts:
        px, py = zip(*pts)
        out["parts"][ref] = {"x0": round(min(px), 2), "x1": round(max(px), 2), "y0": round(min(py), 2), "y1": round(max(py), 2)}
(HERE / "connectors.json").write_text(json.dumps(out, indent=1))
print("board", out["board"])
for r in ("J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8", "J9", "J10", "J11", "J12", "JP1", "U1", "U2"):
    print(r, out["parts"][r])
# hole positions (mounting) for the case posts
holes = []
for fp in b.footprints:
    for pad in fp.pads:
        if pad.type == "np_thru_hole":
            wx, wy = world(fp, pad.position.X, pad.position.Y)
            holes.append((round(wx - x0, 2), round(y1 - wy, 2), pad.drill.diameter))
print("mounting holes:", holes)

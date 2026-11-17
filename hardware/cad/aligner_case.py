"""Electronics case and lid for the carrier PCB (+ Pi Zero 2 W underneath, + PD trigger and buck modules in a side bay).

The case hangs UNDER the tilt plate (floor against its underside) and tilts with it, so the IMU on the carrier reads plate tilt.
Case frame: x along the length (west to east), y along the width (south = Pi side to north), z from the floor's outer face.
PCB sits on four posts, components facing the lid; the Pi hangs under the PCB on its 40-pin socket.
Cable slots come from hardware/pcb/connectors.json (real connector positions). Guessed items are marked GUESS.

Run:  python aligner_case.py <out_dir>
"""
import json
import pathlib
import sys

import aligner_cad as c
import aligner_cad2 as c2
from aligner_cad import U, D, box, cylz, to_trimesh

HERE = pathlib.Path(__file__).resolve().parent
CONN = json.loads((HERE.parent / "pcb" / "connectors.json").read_text())

WALL, FLOOR, LID_T = 2.4, 5.0, 3.0
POST_H = 14.0                    # PCB underside height above the floor: 8.5 socket + 1.6 Pi + 1.5 parts under it + 2.4 clearance
PCB_W, PCB_H, PCB_T = CONN["board"]["w"], CONN["board"]["h"], 1.6
PCB_TOP_H = 17.1                 # tallest part above the PCB (TMC2209 + heatsink, assumed envelope, from pcb/README.md)
LID_GAP = 2.0
CAV_H = POST_H + PCB_T + PCB_TOP_H + LID_GAP
WEST_MARGIN = 8.6                # west of the PCB: room for a lid screw post beside the PCB corner
BAY_W = 38.0                     # east bay for the PD-trigger and buck modules (GUESS: each up to about 38 x 34 x 15 mm)
PI_SOUTH = 16.0                  # Pi hangs about 14.5 mm south of the PCB edge, plus clearance
PX0, PY0 = WALL + WEST_MARGIN, WALL + PI_SOUTH      # PCB south-west corner in case coordinates
OX = WEST_MARGIN + PCB_W + 1.0 + 2.0 + BAY_W + 2 * WALL
OY = PI_SOUTH + PCB_H + 1.0 + 2 * WALL
H_TOTAL = FLOOR + CAV_H + LID_T
PCB_HOLES = [(3.5, 3.5), (81.5, 3.5), (3.5, 56.5), (81.5, 56.5)]
SLOT_Z0 = FLOOR + POST_H + PCB_T - 2.0               # cable slots start just below the PCB top face
SLOT_H = 12.0
assert abs(OY - c2.CASE_OY) < 0.05, f"update CASE_OY in aligner_cad2.py to {OY:.2f}"


def wall_slot(wall, centre, width, z0, z1):
    """Rectangular cut through one outer wall. wall in 'W','N','S','E'; centre along the wall."""
    h = width / 2
    if wall == "W":
        return box(-1, centre - h, z0, WALL + 1, centre + h, z1)
    if wall == "E":
        return box(OX - WALL - 1, centre - h, z0, OX + 1, centre + h, z1)
    if wall == "S":
        return box(centre - h, -1, z0, centre + h, WALL + 1, z1)
    return box(centre - h, OY - WALL - 1, z0, centre + h, OY + 1, z1)


def connector_slots():
    """One merged slot per wall group, from the real connector positions (nearest of the W / S / N walls)."""
    groups = {}
    for ref in ("J2", "J3", "J4", "J5", "J6", "J7", "J8", "J9", "J10", "J11", "J12"):
        p = CONN["parts"][ref]
        xc, yc = (p["x0"] + p["x1"]) / 2, (p["y0"] + p["y1"]) / 2
        dist = {"W": xc, "S": yc, "N": PCB_H - yc}
        wall = min(dist, key=dist.get)
        lo, hi = (p["y0"], p["y1"]) if wall == "W" else (p["x0"], p["x1"])
        lo, hi = lo - 6.0, hi + 6.0                       # body of the connector plus room for the wire bend
        g = groups.setdefault((wall, ref in ("J5", "J6") and "motor" or "other"), [])
        g.append((lo, hi))
    cuts = []
    for (wall, _), spans in groups.items():
        spans.sort()
        merged = [list(spans[0])]
        for lo, hi in spans[1:]:
            if lo <= merged[-1][1] + 1.0:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        for lo, hi in merged:
            off = PY0 if wall == "W" else PX0
            cuts.append(wall_slot(wall, off + (lo + hi) / 2, hi - lo, SLOT_Z0, SLOT_Z0 + SLOT_H))
    return cuts


def case():
    body = box(0, 0, 0, OX, OY, FLOOR + CAV_H)
    cav = box(WALL, WALL, FLOOR, OX - WALL, OY - WALL, FLOOR + CAV_H + 1)
    parts = [D(body, cav)]
    # PCB posts, M3 heat-set inserts
    for hx, hy in PCB_HOLES:
        parts.append(cylz(PX0 + hx, PY0 + hy, FLOOR - 0.01, FLOOR + POST_H, 7.0))
    # lid screw posts in the four inner corners
    corner = []
    for cx in (WALL + 3.8, OX - WALL - 3.8):
        for cy in (WALL + 3.8, OY - WALL - 3.8):
            corner.append((cx, cy))
            parts.append(box(cx - 3.8, cy - 3.8, FLOOR - 0.01, cx + 3.8, cy + 3.8, FLOOR + CAV_H))
    # bosses for the four M4 inserts that take the screws coming down through the tilt plate
    mount = [(OX / 2 + sx * c2.CASE_HOLE_Y, y) for sx in (-1, 1) for y in (c2.CASE_HOLE_INSET, OY - c2.CASE_HOLE_INSET)]
    for mx, my in mount:
        parts.append(cylz(mx, my, FLOOR - 0.01, FLOOR + 3.0, 10.0))
    body = U(*parts)
    cuts = []
    for hx, hy in PCB_HOLES:
        cuts.append(cylz(PX0 + hx, PY0 + hy, FLOOR + POST_H - 5.0, FLOOR + POST_H + 1, c.M3_INSERT[0]))
    for cx, cy in corner:
        cuts.append(cylz(cx, cy, FLOOR + CAV_H - 6.0, FLOOR + CAV_H + 1, c.M3_INSERT[0]))
    for mx, my in mount:
        cuts.append(cylz(mx, my, -1, 6.0, 5.6))                       # M4 heat-set insert, entered from the outer face
    cuts += connector_slots()
    # GUESS: ribbon slot for the camera cable on the south wall, at Pi level, near the Pi's east end
    cuts.append(wall_slot("S", PX0 + 70.0, 20.0, FLOOR + POST_H - 10.0, FLOOR + POST_H - 2.0))
    # GUESS: USB-C opening for the PD trigger board in the east wall of the bay, board assumed on the floor
    cuts.append(wall_slot("E", OY * 0.62, 13.0, FLOOR + 1.0, FLOOR + 10.0))
    # tie-wrap slots through the floor for the two modules in the bay
    bx = PX0 + PCB_W + 3.0 + BAY_W / 2
    for by in (OY * 0.28, OY * 0.62):
        for dx in (-9.0, 9.0):
            cuts.append(box(bx + dx - 1.0, by - 6.0, -1, bx + dx + 1.0, by + 6.0, FLOOR + 1))
    return D(body, *cuts)


def lid():
    body = box(0, 0, 0, OX, OY, LID_T)
    cuts = []
    for cx in (WALL + 3.8, OX - WALL - 3.8):
        for cy in (WALL + 3.8, OY - WALL - 3.8):
            cuts += [cylz(cx, cy, -1, LID_T + 1, 3.4), cylz(cx, cy, -1, 2.0, 6.4)]
    return D(body, *cuts)


PARTS3 = {"10_electronics_case": case, "11_case_lid": lid}


def fit_report():
    """Do the PCB, the Pi and the tall parts fit the cavity? Prints measured margins."""
    cs = case()
    z_pcb0 = FLOOR + POST_H
    pcb = box(PX0, PY0, z_pcb0, PX0 + PCB_W, PY0 + PCB_H, z_pcb0 + PCB_T + PCB_TOP_H)
    pi = box(PX0 + 12.2, PY0 - 14.5, z_pcb0 - 8.5 - 1.6 - 1.5, PX0 + 12.2 + 65.0, PY0 + 15.5, z_pcb0 - 8.5)
    ov_pcb = (cs ^ pcb).volume()
    ov_pi = (cs ^ pi).volume()
    print(f"case outer {OX:.1f} x {OY:.1f} x {H_TOTAL:.1f} mm (cavity height {CAV_H:.1f}); PCB envelope overlap with case "
          f"{ov_pcb:.2f} mm3, Pi envelope overlap {ov_pi:.2f} mm3 (both should be 0)")
    print(f"clearances: PCB top parts to lid {LID_GAP:.1f} mm; Pi underside to floor {z_pcb0 - 8.5 - 1.6 - 1.5 - FLOOR:.1f} mm; "
          f"Pi south edge to south wall {PY0 - 14.5 - WALL:.1f} mm")
    return ov_pcb < 0.01 and ov_pi < 0.01


def main(out):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ok = fit_report()
    for name, fn in PARTS3.items():
        m = fn()
        if m.is_empty():
            raise SystemExit(f"{name}: empty")
        tm = to_trimesh(m)
        tm.export(out / f"{name}.stl")
        bb = tm.bounds
        print(f"{name:20s} watertight={tm.is_watertight!s:5s} vol={tm.volume/1000:6.1f} cm3 "
              f"size={bb[1][0]-bb[0][0]:.1f}x{bb[1][1]-bb[0][1]:.1f}x{bb[1][2]-bb[0][2]:.1f} mm zmin={bb[0][2]:.2f}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "../stl"))

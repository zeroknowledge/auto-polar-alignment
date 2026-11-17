"""Parametric CAD for the auto polar aligner, Batch 1 printed parts.

Built with manifold3d (boolean solid modelling) and exported as STL via trimesh.
All dimensions in mm. Every part is modelled in PRINT ORIENTATION (flat face on z=0).

Batch 1 = parts whose geometry is fixed by standard hardware (M6 nut, 608 bearing, NEMA 17 face,
3/8-16 nut) and by the stack numbers below. Anything that depends on a dimension we have not measured
(lazy-Susan hole pattern, camera board, lens barrel) is parametric here and flagged in README.md.

Run:  python aligner_cad.py <out_dir>
"""
import math
import sys
from functools import reduce
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import CrossSection, Manifold

SEG = 72  # circle resolution

# ---------------------------------------------------------------- hardware constants
M6_NUT_AF = 10.0 + 0.25        # brass M6 hex nut is 10 mm across flats
M6_NUT_T = 5.0 + 0.3           # M6 nut thickness (~5 mm) plus clearance
ROD_HOLE = 6.8                 # clearance for M6x1 rod (nut grips the thread, the block must not)
DOWEL = 3.0                    # 3 mm steel dowel pin (pressed into the block, free in the yoke)
DOWEL_PRESS = 3.0              # press-fit pocket in the block
DOWEL_FREE = 3.25              # free-turning hole in the yoke
HEX38_AF = 14.29 + 0.3         # 3/8-16 hex nut (9/16 in across flats)
HEX38_T = 8.3                  # standard 3/8-16 nut is about 8.3 mm thick
NEMA17 = dict(sq=42.3, holes=31.0, boss=22.6, m3=3.4)
M4_CLR = 4.6
M3_CLR = 3.4
M3_INSERT = (4.2, 5.0)         # heat-set insert pocket (diameter, depth); tune with fit_test

# ---------------------------------------------------------------- stack numbers (assembled frame)
SPIDER_T = 12.0                # base spider thickness (hub and arms): holds one 3/8-16 nut inside it
LS_H = 12.0                    # lazy-Susan height (MEASURE YOURS)
AZP_T = 6.0                    # azimuth plate thickness
ARM_AZ = 80.0                  # tangent-arm radius for the azimuth drive
BLOCK = dict(x=20.0, y=16.0, z=18.0)  # nut trunnion block, local frame (rod along local z)
GAP = 0.5                      # running clearance around the trunnion block
# Azimuth drive: rod runs horizontally along world Y at x = ARM_AZ; the block's pivot axis is vertical,
# so the block's local x (20 mm) is the world-Z extent and local z (18 mm, the rod direction) is world-Y.
Z_ROD = SPIDER_T + LS_H + AZP_T + GAP + BLOCK["x"] / 2   # rod axis height above the bottom of the spider
LS_SLOT = (34.0, 62.0)         # radial slot range for lazy-Susan bolts (MEASURE YOUR PATTERN)
FACE_Y = 58.0                  # y of the azimuth motor face plate (see base_spider)
AZ_DISC_R = 75.0               # azimuth plate radius

# ---- coarse tilt stage (Batch 2), assembled frame: x toward the pole, z up, origin on the bearing axis ----
AZ_TOP = SPIDER_T + LS_H + AZP_T          # top face of the azimuth plate (30 mm)
HX = -20.0                     # coarse hinge axis x. Kept inside the azimuth disc: at |y| = 61 the disc reaches x = -43.6
HZ = 86.0                      # coarse hinge axis height: the tilt-plate arm tip clipped the azimuth plate at HZ = 82 (tilt 65 deg)
CHK_Y = (49.0, 61.0)           # coarse cheek |y| range (fixed to the azimuth plate)
CHK_U = (-12.0, 46.0)          # cheek extent in x relative to the hinge
CHK_BASE_U = (-4.0, 17.0, 38.0)  # cheek base bolt positions (x relative to the hinge)
CHK_BOLT_Y = 55.0              # |y| of the cheek base bolts (centre of the cheek)
R_LOCK = 40.0                  # radius of the lock bolt circle about the coarse hinge
TILT_MIN, TILT_MAX = 15.0, 100.0   # plate tilt from horizontal covered by the arc slots (deg)

# ---- end-stop micro switches (KW12-3 class, roller lever). Body and lever figures are NOT confirmed: see README ----
SW_BODY = (20.0, 10.5, 6.5)    # L along the lever, W in the pressing direction, T along the mounting-hole axis
SW_HOLE_SPACING = 9.5          # unconfirmed; typical for this switch family
SW_PILOT_D = 1.9               # pilot for an M2 self-tapping screw
SW_LEVER = 14.0                # roller centre beyond the end of the body, along L (assumed)
SW_ROLLER_R = 2.75             # roller radius (assumed)
SW_ROLLER_OFF = 3.0            # roller centre beyond the body's lever-side face (assumed)
AZ_TRIG = 8.0                  # azimuth trigger angle (deg): beyond the +/-6 deg working range, short of the hard limits
AZ_TAB = dict(x0=-90.0, x1=-72.0, half=5.0)    # rim tab on the azimuth plate at -x
AZ_RX = -80.0                  # x where the switch rollers meet the tab
AZ_BLOCK_TOP = SPIDER_T + LS_H - 1.5           # switch blocks stop 1.5 mm below the azimuth plate

# ---- azimuth preload spring: post on the azimuth plate rim (rotates) and three alternative pegs on the spider (fixed) ----
PRE_R = 88.0                   # radius of the rotating post
PRE_ANG = 13.2                 # angle of the rotating post past +y (deg): the spring then pulls it toward +x, i.e. clockwise
PRE_POST = (-PRE_R * math.sin(math.radians(PRE_ANG)), PRE_R * math.cos(math.radians(PRE_ANG)))
PRE_PEGS_X = (14.0, 22.0, 30.0)               # x of the fixed pegs; y equals the rotating post's y
PRE_SPRING_Z = SPIDER_T + LS_H + AZP_T + 2.0  # height of the spring hooks, 2 mm above the azimuth plate top


def az_stop():
    """Geometry of the azimuth end-stop switches (the one on the -y side; mirror y for the other).
    Returns roller centre, body box and block extents, all for the -y switch."""
    t = math.radians(AZ_TRIG)
    h = AZ_TAB["half"]
    xp = AZ_RX * math.cos(t) + h * math.sin(t)         # the tab's -y face point (AZ_RX, -h) after rotating by +t
    yp = AZ_RX * math.sin(t) - h * math.cos(t)
    y_line = yp + (AZ_RX - xp) * math.tan(t)
    yc = y_line - SW_ROLLER_R / math.cos(t)            # roller centre touching the face at the trigger angle
    xb = AZ_RX - SW_LEVER                               # body centre (lever points toward +x)
    y_face = yc - SW_ROLLER_OFF
    return dict(roller=(AZ_RX, yc, AZ_BLOCK_TOP + SW_BODY[2] / 2), xb=xb, y_face=y_face,
                body=(xb - SW_BODY[0] / 2, xb + SW_BODY[0] / 2, y_face - SW_BODY[1], y_face, AZ_BLOCK_TOP, AZ_BLOCK_TOP + SW_BODY[2]))


# ---------------------------------------------------------------- tiny CSG helpers
def U(*ms):
    return reduce(lambda a, b: a + b, ms)


def D(base, *cuts):
    for c in cuts:
        base = base - c
    return base


def box(x0, y0, z0, x1, y1, z1):
    return Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def cylz(cx, cy, z0, z1, d, seg=SEG):
    return Manifold.cylinder(z1 - z0, d / 2, d / 2, seg).translate((cx, cy, z0))


def cyly(cx, cz, y0, y1, d):
    return Manifold.cylinder(y1 - y0, d / 2, d / 2, SEG).rotate((-90, 0, 0)).translate((cx, y0, cz))


def cylx(cy, cz, x0, x1, d):
    return Manifold.cylinder(x1 - x0, d / 2, d / 2, SEG).rotate((0, 90, 0)).translate((x0, cy, cz))


def teardrop_y(cx, cz, y0, y1, d):
    """Horizontal hole along +y whose top is a 45-degree point, so it prints without supports."""
    r = d / 2
    k = r * math.cos(math.radians(45))
    # Base corners sit 0.4 mm inside the circle so the triangle overlaps it instead of touching it tangentially;
    # an exactly tangent join leaves sliver triangles that float32 STL rounding turns into open edges.
    kb = k - 0.4
    pts = [(cx - k, -(cz + kb)), (cx + k, -(cz + kb)), (cx, -(cz + r * math.sqrt(2)))]  # py = -z after the rotate
    arr = np.array(pts, dtype=float)
    area2 = np.sum(arr[:, 0] * np.roll(arr[:, 1], -1) - np.roll(arr[:, 0], -1) * arr[:, 1])
    if area2 < 0:
        arr = arr[::-1]
    tri = Manifold.extrude(CrossSection([arr]), y1 - y0).rotate((-90, 0, 0)).translate((0, y0, 0))
    return cyly(cx, cz, y0, y1, d) + tri


def hexz(cx, cy, z0, z1, af):
    r = af / math.sqrt(3)
    return Manifold.cylinder(z1 - z0, r, r, 6).translate((cx, cy, z0))


def slotz(x0, y0, x1, y1, z0, z1, d):
    return (cylz(x0, y0, z0, z1, d) + cylz(x1, y1, z0, z1, d)).hull()


def prism_yz(pts, x0, x1):
    """Extrude a polygon given as (y, z) points along +x from x0 to x1."""
    arr = np.array(pts, dtype=float)
    area2 = np.sum(arr[:, 0] * np.roll(arr[:, 1], -1) - np.roll(arr[:, 0], -1) * arr[:, 1])
    if area2 < 0:  # manifold wants counter-clockwise outer contours; a clockwise one is treated as empty
        arr = arr[::-1]
    cs = CrossSection([arr])
    return Manifold.extrude(cs, x1 - x0).rotate((90, 0, 90)).translate((x0, 0, 0))


# ---------------------------------------------------------------- parts
def fit_test():
    """Tolerance coupon. Print this FIRST: it tells you which hole sizes to use on your printer.

    Each row has three sizes, smallest on the left. Pick the smallest that the real part enters
    with a gentle push, then edit the matching constant at the top of this file.
    """
    W, H, T = 124.0, 74.0, 9.0
    base = box(0, 0, 0, W, H, T)
    cuts = []
    xs = [22.0, 62.0, 102.0]
    # row 1: M6 nut pockets (AF)  and  8 mm hinge pin holes
    for x, af in zip([14, 36, 58], [10.0, 10.2, 10.4]):
        cuts.append(hexz(x, 60, 3.0, T + 1, af))
    for x, d in zip([84, 98, 112], [8.0, 8.15, 8.3]):
        cuts.append(cylz(x, 60, -1, T + 1, d))
    # row 2: 608 bearing pockets (OD) with a through hole
    for x, d in zip([20, 62, 104], [22.0, 22.15, 22.3]):
        cuts.append(cylz(x, 36, T - 7.0, T + 1, d))
        cuts.append(cylz(x, 36, -1, T, 13.0))
    # row 3: 3/8-16 nut pockets, 3 mm dowel holes, M3 heat-set insert holes
    for x, af in zip([14, 36], [14.3, 14.6]):
        cuts.append(hexz(x, 10, 1.0, T + 1, af))
    for x, d in zip([58, 66, 74], [3.0, 3.1, 3.25]):
        cuts.append(cylz(x, 10, 3.0, T + 1, d))
    for x, d in zip([90, 100, 110], [4.0, 4.2, 4.4]):
        cuts.append(cylz(x, 10, 3.0, T + 1, d))
    return D(base, *cuts)


def nut_trunnion():
    """Holds an M6 brass nut and pivots about a pin axis that is perpendicular to the rod.

    Print standing as modelled (rod bore vertical). Two 3 mm dowel pins press into the side holes
    and turn freely in the yoke that carries the block. Print 3 (two used, one spare).
    """
    bx, by, bz = BLOCK["x"], BLOCK["y"], BLOCK["z"]
    body = box(-bx / 2, -by / 2, 0, bx / 2, by / 2, bz)
    # chamfer-ish: round the vertical edges
    body = (cylz(-bx / 2 + 3, -by / 2 + 3, 0, bz, 6) + cylz(bx / 2 - 3, -by / 2 + 3, 0, bz, 6) +
            cylz(-bx / 2 + 3, by / 2 - 3, 0, bz, 6) + cylz(bx / 2 - 3, by / 2 - 3, 0, bz, 6)).hull()
    cuts = [cylz(0, 0, -1, bz + 1, ROD_HOLE),
            hexz(0, 0, bz - M6_NUT_T, bz + 1, M6_NUT_AF),
            cylx(0, bz / 2, -bx / 2 - 1, -bx / 2 + 4.0, DOWEL_PRESS),
            cylx(0, bz / 2, bx / 2 - 4.0, bx / 2 + 1, DOWEL_PRESS)]
    return D(body, *cuts)


def base_spider():
    """Bottom stage: 3/8-16 hub for the tripod, four arms that carry the lazy-Susan bottom ring, and
    the azimuth motor mount (face plate, riser and gussets) on the +x arm."""
    hub_h = SPIDER_T  # the lazy-Susan sits on this face; a taller hub would hit the azimuth plate
    parts = [cylz(0, 0, 0, hub_h, 50.0)]
    for k in range(4):
        a = math.radians(90 * k)
        arm = box(0, -12, 0, 70, 12, SPIDER_T).rotate((0, 0, math.degrees(a)))
        parts.append(arm)
    # outrigger plate that carries the motor, joined to the +x arm
    xo0, xo1, yo0, yo1 = 52.0, 108.0, -12.0, 110.0
    parts.append(box(xo0, yo0, 0, xo1, yo1, SPIDER_T))
    # motor face plate. FACE_Y keeps the face clear of the R75 azimuth disc: at y=FACE_Y the disc edge is at
    # x = sqrt(75^2 - FACE_Y^2) = 47.6 mm, against the plate's near edge at x = ARM_AZ - 25 = 55 mm.
    yf0, yf1 = FACE_Y, FACE_Y + 6.0
    top = Z_ROD + 25.0
    parts.append(box(ARM_AZ - 28, yf0, 0, ARM_AZ + 28, yf1, top))
    # riser under the motor body
    parts.append(box(ARM_AZ - 22, yf1, 0, ARM_AZ + 22, yf1 + 40, Z_ROD - NEMA17["sq"] / 2))
    # gussets (triangles in y,z) BEHIND the face plate (motor side), just outside the motor body's width.
    # Gussets on the arm side would run through the footprint of the azimuth disc.
    for gx in (ARM_AZ - 28, ARM_AZ + 23):
        parts.append(prism_yz([(yf1, SPIDER_T), (yf1 + 36, SPIDER_T), (yf1, top - 6)], gx, gx + 5))
    # azimuth end stops: the -x arm is extended, with a cross bar carrying one switch block each side of the rim tab
    st = az_stop()
    bx0, bx1 = st["body"][0] - 2.0, st["body"][1] + 2.0
    ybar = abs(st["body"][2]) + 1.0
    parts.append(box(-108.0, -12.0, 0, -68.0, 12.0, SPIDER_T))
    parts.append(box(bx0, -ybar, 0, bx1, ybar, SPIDER_T))
    for sg in (-1, 1):
        ya, yb = sorted((sg * (abs(st["body"][2]) + 1.0), sg * (abs(st["y_face"]) - 1.0)))
        parts.append(box(bx0, ya, SPIDER_T - 0.01, bx1, yb, AZ_BLOCK_TOP))
    # azimuth preload: extend the +y arm and raise a block carrying three alternative spring pegs
    py = PRE_POST[1]
    parts.append(box(-12.0, 64.0, 0, PRE_PEGS_X[-1] + 8.0, py + 8.0, SPIDER_T))
    parts.append(box(PRE_PEGS_X[0] - 6.0, py - 6.0, SPIDER_T - 0.01, PRE_PEGS_X[-1] + 6.0, py + 6.0, AZ_TOP))
    body = U(*parts)

    cuts = [
        # tripod socket: one 3/8-16 nut from underneath (about 5 threads of engagement), stud clearance above
        hexz(0, 0, -1, HEX38_T + 0.5, HEX38_AF),
        cylz(0, 0, 0, hub_h + 1, 10.0),
    ]
    # lazy-Susan bolt slots, counterbored from underneath so heads sit flush with the tripod head
    for k in range(4):
        a = math.radians(90 * k)
        x0, y0 = LS_SLOT[0] * math.cos(a), LS_SLOT[0] * math.sin(a)
        x1, y1 = LS_SLOT[1] * math.cos(a), LS_SLOT[1] * math.sin(a)
        cuts.append(slotz(x0, y0, x1, y1, -1, SPIDER_T + 1, M4_CLR))
        cuts.append(slotz(x0, y0, x1, y1, -1, 3.4, 8.4))
    # NEMA 17 pattern in the face plate
    zc = Z_ROD
    cuts.append(teardrop_y(ARM_AZ, zc, yf0 - 1, yf1 + 1, NEMA17["boss"]))  # teardrop: prints with no supports
    for dx in (-1, 1):
        for dz in (-1, 1):
            cuts.append(cyly(ARM_AZ + dx * NEMA17["holes"] / 2, zc + dz * NEMA17["holes"] / 2,
                             yf0 - 1, yf1 + 1, NEMA17["m3"]))
    for px_ in PRE_PEGS_X:                                                   # M3 heat-set insert for a spring peg (M3 x 10 screw + washer)
        cuts.append(cylz(px_, PRE_POST[1], AZ_TOP - M3_INSERT[1], AZ_TOP + 1, M3_INSERT[0]))
    # M2 self-tapping pilots for the two azimuth end-stop switches (hole axis vertical, 9.5 mm apart along the switch)
    for sg in (-1, 1):
        ym = sg * (abs(st["body"][2]) + abs(st["body"][3])) / 2
        for dx in (-SW_HOLE_SPACING / 2, SW_HOLE_SPACING / 2):
            cuts.append(cylz(st["xb"] + dx, ym, AZ_BLOCK_TOP - 8.0, AZ_BLOCK_TOP + 1, SW_PILOT_D))
    return D(body, *cuts)


def az_plate():
    """Azimuth plate: rides on the lazy-Susan top ring and carries the nut-trunnion yoke.
    Print flat, underside on the bed."""
    R = 75.0
    body = U(cylz(0, 0, 0, AZP_T, 2 * R), box(60, -12, 0, 96, 12, AZP_T),
             box(AZ_TAB["x0"], -AZ_TAB["half"], 0, AZ_TAB["x1"], AZ_TAB["half"], AZP_T),   # rim tab for the end stops
             box(70.0, -6.0, 0, PRE_R + 7.0, 6.0, AZP_T).rotate((0, 0, 90.0 + PRE_ANG)))    # rim tab for the preload spring
    zt = AZP_T
    zc = zt + GAP + BLOCK["x"] / 2
    cap_under = zt + GAP + BLOCK["x"] + GAP
    for dx in (-16.0, 16.0):
        body = body + box(ARM_AZ + dx - 5, -5, zt - 0.01, ARM_AZ + dx + 5, 5, cap_under)
    cuts = []
    # lazy-Susan bolt slots with counterbore from the top
    for k in range(4):
        a = math.radians(90 * k)
        x0, y0 = LS_SLOT[0] * math.cos(a), LS_SLOT[0] * math.sin(a)
        x1, y1 = LS_SLOT[1] * math.cos(a), LS_SLOT[1] * math.sin(a)
        cuts.append(slotz(x0, y0, x1, y1, -1, zt + 1, M4_CLR))
        cuts.append(slotz(x0, y0, x1, y1, zt - 3.5, zt + 1, 8.4))
    # cap screw inserts in the posts
    for dx in (-16.0, 16.0):
        cuts.append(cylz(ARM_AZ + dx, 0, cap_under - M3_INSERT[1], cap_under + 1, M3_INSERT[0]))
    # yoke pivot hole for the lower dowel
    cuts.append(cylz(ARM_AZ, 0, zt - 4.0, zt + 1, DOWEL_FREE))
    # coarse-cheek base bolts (Batch 2): M4 from underneath into heat-set inserts in the cheeks, heads counterbored
    for u in CHK_BASE_U:
        for sy in (-1, 1):
            cuts.append(cylz(HX + u, sy * CHK_BOLT_Y, -1, zt + 1, M4_CLR))
            cuts.append(cylz(HX + u, sy * CHK_BOLT_Y, -1, 3.5, 8.4))
    cuts.append(cylz(PRE_POST[0], PRE_POST[1], zt - M3_INSERT[1], zt + 1, M3_INSERT[0]))   # insert for the spring screw
    return D(body, *cuts)


def az_cap():
    """Cap that closes the yoke over the nut trunnion. Print upside down as modelled (flat on bed)."""
    t = 5.0
    body = box(ARM_AZ - 26, -7, 0, ARM_AZ + 26, 7, t)
    cuts = [cylz(ARM_AZ - 16, 0, -1, t + 1, M3_CLR), cylz(ARM_AZ + 16, 0, -1, t + 1, M3_CLR),
            cylz(ARM_AZ, 0, -1, 4.0, DOWEL_FREE)]
    # counterbore the screw heads
    cuts += [cylz(ARM_AZ - 16, 0, t - 2.5, t + 1, 6.2), cylz(ARM_AZ + 16, 0, t - 2.5, t + 1, 6.2)]
    return D(body, *cuts)


PARTS = {
    "00_fit_test": fit_test,
    "01_nut_trunnion": nut_trunnion,
    "02_base_spider": base_spider,
    "03_az_plate": az_plate,
    "04_az_cap": az_cap,
}


def to_trimesh(m: Manifold) -> trimesh.Trimesh:
    mesh = m.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3],
                           faces=np.asarray(mesh.tri_verts), process=True)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Z_ROD (rod axis above spider bottom) = {Z_ROD:.2f} mm")
    for name, fn in PARTS.items():
        m = fn()
        if m.is_empty():
            raise SystemExit(f"{name}: boolean result is empty, check polygon winding / cuts")
        tm = to_trimesh(m)
        path = out / f"{name}.stl"
        tm.export(path)
        bb = tm.bounds
        print(f"{name:18s} watertight={tm.is_watertight!s:5s} vol={tm.volume/1000:7.1f} cm3 "
              f"size={bb[1][0]-bb[0][0]:.0f}x{bb[1][1]-bb[0][1]:.0f}x{bb[1][2]-bb[0][2]:.0f} mm "
              f"zmin={bb[0][2]:.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../stl")

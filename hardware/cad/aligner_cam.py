"""Camera cradle (0-40 deg tilt), camera plate and dew shield for the Waveshare IMX296 Global Camera (A) + 16 mm C-mount lens.

Camera dimensions (Waveshare outline drawing, IMX296-Global-Camera-A-details-size.jpg): board 38 +/-0.2 x 38 +/-0.2 mm, 1.6 mm
thick; four 2.5 mm holes on a 30 x 30 mm square; Ø28.5 mount boss 12.5 mm above the board front (CS mount, before the included
5 mm C-CS adapter); 15-pin FPC connector on the back, 2.5 mm deep. Lens (Waveshare 16 mm): Ø39 x 50 mm, 134 g, manual iris/focus.

Frames
  cradle (p', y, h): p' along the top plate (away from the hinge), h up from the plate's top face. Base lies on the plate at
                     p = CRADLE_P0 .. CRADLE_P0 + BASE_L.
  plate  (u, y, a) : camera plate; a runs along the lens axis (a = 0 is the plate's rear face where the board sits).
  The plate pivots about (PIV_P, PIV_H) and tilts toward +p' (away from the rod and the telescope, toward the sky above the pole
  axis for northern sites), by delta = 0..40 deg:
     p' = PIV_P + u cos(d) + (a - T/2) sin(d);   h = PIV_H - u sin(d) + (a - T/2) cos(d)

Run:  python aligner_cam.py <out_dir>
"""
import math
import sys
from pathlib import Path

import numpy as np

import aligner_cad as c
import aligner_cad2 as c2
from aligner_cad import U, D, box, cylz, cyly, teardrop_y, to_trimesh

# camera
BOARD, BOARD_T, HOLE_SQ = 38.0, 1.6, 30.0
BOSS_D, BOSS_H = 28.5, 12.5
ADAPTER_H = 5.0                          # included C-CS adapter ring
LENS_D, LENS_L = 39.0, 50.0
# cradle
BASE_L, BASE_W, BASE_T = 42.0, 59.0, 5.0
CHEEK_Y = (22.5, 28.5)                   # cheek |y| (plate half-width 22 + 0.5 running gap)
PIV_P, PIV_H = 21.0, 40.0
CHEEK_TOP = 60.0
PLATE_W, PLATE_T = 44.0, 6.0
LOCK_R = 18.0                            # arc-slot bolt radius on the plate
DELTA_SLOT = (-5.0, 50.0)                # tilt range the arc slot covers (deg); 0..40 is the intended working range
HOLE_PIN = 4.5                           # M4 clearance for pivot and lock bolts
M25_INSERT = (3.6, 4.5)                  # M2.5 heat-set insert pocket (dia, depth): confirm with the fit-test coupon
# dew shield
SHIELD_ID, SHIELD_WALL = LENS_D + 2.0, 1.8
SHIELD_GRIP, SHIELD_EXT = 28.0, 25.0     # length over the lens barrel / beyond the front of the lens (see README: vignetting)


def cradle_base():
    """Base plate with two cheeks, one piece. Print as modelled (base on the bed, cheeks upright)."""
    body = U(box(0, -BASE_W / 2, 0, BASE_L, BASE_W / 2, BASE_T))
    for sg in (-1, 1):
        y0, y1 = sorted((sg * CHEEK_Y[0], sg * CHEEK_Y[1]))
        body = body + box(0, y0, 0, BASE_L, y1, CHEEK_TOP)
    cuts = []
    for sg in (-1, 1):
        y0, y1 = sorted((sg * (CHEEK_Y[0] - 1), sg * (CHEEK_Y[1] + 1)))
        cuts.append(teardrop_y(PIV_P, PIV_H, y0, y1, HOLE_PIN))            # pivot bolt
        angs = [math.radians(180.0 - d) for d in np.arange(DELTA_SLOT[0], DELTA_SLOT[1] + 0.01, 5.0)]
        pts = [(PIV_P + LOCK_R * math.cos(a), PIV_H + LOCK_R * math.sin(a)) for a in angs]
        for (xa, za), (xb, zb) in zip(pts, pts[1:]):
            cuts.append((cyly(xa, za, y0, y1, HOLE_PIN) + cyly(xb, zb, y0, y1, HOLE_PIN)).hull())
    for bp in c2.CRADLE_BOLT_P:
        for sg in (-1, 1):
            x, y = bp, sg * c2.CRADLE_BOLT_Y
            cuts += [cylz(x, y, -1, BASE_T + 1, c.M3_CLR), cylz(x, y, BASE_T - 2.5, BASE_T + 1, 6.2)]
    return D(body, *cuts)


def camera_plate():
    """Camera plate. Rear face (a = 0, where the board sits) on the bed. u runs along p'; y across."""
    body = box(-PLATE_W / 2, -PLATE_W / 2, 0, PLATE_W / 2, PLATE_W / 2, PLATE_T)
    cuts = [cylz(0, 0, -1, PLATE_T + 1, BOSS_D + 3.5)]                       # boss (Ø28.5) passes through
    for sx in (-1, 1):
        for sy in (-1, 1):
            cuts.append(cylz(sx * HOLE_SQ / 2, sy * HOLE_SQ / 2, -1, M25_INSERT[1], M25_INSERT[0]))   # M2.5 inserts, board screws
    a = PLATE_T / 2
    for sg in (-1, 1):                                                       # M4 inserts in the side faces: pivot and lock bolt
        for u in (0.0, -LOCK_R):
            y_edge = sg * PLATE_W / 2
            y0, y1 = (y_edge - 6.5, y_edge + 1) if sg > 0 else (y_edge - 1, y_edge + 6.5)
            cuts.append(cyly(u, a, y0, y1, 5.6))
    return D(body, *cuts)


def dew_shield():
    """Slit tube that clamps on the lens barrel with one M3 bolt through two ears. Print standing."""
    ro = SHIELD_ID / 2 + SHIELD_WALL
    L = SHIELD_GRIP + SHIELD_EXT
    tube = cylz(0, 0, 0, L, 2 * ro) - cylz(0, 0, -1, L + 1, SHIELD_ID)
    ears = box(ro - 1.0, -6.0, 0, ro + 8.0, 6.0, SHIELD_GRIP)
    body = tube + ears
    cuts = [box(ro - 3.0, -0.8, -1, ro + 9.0, 0.8, L + 1)]                   # the slit, through ears and tube wall
    cuts.append(cyly(ro + 4.0, SHIELD_GRIP / 2, -7.0, 7.0, c.M3_CLR))        # M3 clamp bolt across the slit
    return D(body, *cuts)


PARTS4 = {"12_cam_cradle": cradle_base, "13_cam_plate": camera_plate, "14_dew_shield": dew_shield}


# ---------------------------------------------------------------- placement helpers (used by check_assembly.py)
def plate_local_to_cradle(m, delta_deg):
    d = math.radians(delta_deg)
    cd, sd = math.cos(d), math.sin(d)
    # plate print frame (u, y, a) -> (p', y, h); plate centre is (0, 0, PLATE_T/2)
    R = np.array([[cd, 0, sd], [0, 1, 0], [-sd, 0, cd]])
    t = np.array([PIV_P, 0, PIV_H]) - R @ np.array([0, 0, PLATE_T / 2])
    return c2.affine(m, R, t)


def cradle_to_Pprint(m):
    """Cradle (p', y, h) -> top-plate print frame (p, y, z'): z' = -h (top face is z' = 0, the cradle stands on it)."""
    return c2.affine(m, np.diag([1.0, 1.0, -1.0]), [c2.CRADLE_P0, 0, 0])


def camera_envelopes():
    """Plate-frame boxes/cylinders for the board, boss, adapter, lens and dew shield (a from the plate's rear face)."""
    env = {}
    env["board"] = box(-BOARD / 2, -BOARD / 2, -BOARD_T, BOARD / 2, BOARD / 2, 0)
    env["conn"] = box(-BOARD / 2, -9.0, -BOARD_T - 2.5, -BOARD / 2 + 12.0, 9.0, -BOARD_T)       # rear FPC connector, on the -u edge
    a_front = BOSS_H - BOARD_T + 0.0                                         # boss face, measured from the plate rear face
    env["boss"] = cylz(0, 0, 0, a_front + ADAPTER_H, BOSS_D)
    env["lens"] = cylz(0, 0, a_front + ADAPTER_H, a_front + ADAPTER_H + LENS_L, LENS_D)
    ro = SHIELD_ID / 2 + SHIELD_WALL
    lens_front = a_front + ADAPTER_H + LENS_L
    env["shield"] = cylz(0, 0, lens_front - SHIELD_GRIP, lens_front + SHIELD_EXT, 2 * ro)
    return env, lens_front


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in PARTS4.items():
        m = fn()
        if m.is_empty():
            raise SystemExit(f"{name}: empty")
        tm = to_trimesh(m)
        tm.export(out / f"{name}.stl")
        bb = tm.bounds
        print(f"{name:16s} watertight={tm.is_watertight!s:5s} vol={tm.volume/1000:6.1f} cm3 "
              f"size={bb[1][0]-bb[0][0]:.1f}x{bb[1][1]-bb[0][1]:.1f}x{bb[1][2]-bb[0][2]:.1f} mm zmin={bb[0][2]:.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../stl")

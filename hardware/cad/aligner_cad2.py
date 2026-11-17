"""Batch 2 printed parts: the tall-hinge tilt stage. Needs aligner_cad.py (shared constants and helpers).

Frames used (all lengths mm):
  assembled world : x toward the pole, y east, z up, origin on the bearing axis at the bottom of the base spider.
  T-local (s,y,n) : origin on the COARSE hinge axis; s runs along the tilt plate away from the hinge, n is the plate normal.
                    world = (HX,0,HZ) + R_T * local, R_T = [[-cos a, 0, sin a], [0, -1, 0], [sin a, 0, cos a]], a = plate tilt
                    from horizontal (a = 90 - latitude). R_T has determinant +1 (y is mirrored, parts are symmetric in y).
  P-local (p,y,n'): origin on the ALTITUDE hinge axis, at T-local (S_A, 0, N_A); P-local = T-local rotated by beta (+/-6 deg).
Every printed part is modelled in its PRINT frame (flat on z = 0); the *_to_* helpers map print frames to the above.

Run:  python aligner_cad2.py <out_dir>      (also writes the updated 03_az_plate via aligner_cad)
"""
import math
import sys
from pathlib import Path

import numpy as np
from manifold3d import CrossSection, Manifold

import aligner_cad as c
from aligner_cad import U, D, box, cylz, cyly, hexz, slotz, teardrop_y, to_trimesh, prism_yz

# ---------------------------------------------------------------- constants
CHEEK_PIN_D = 8.1              # 8 mm hinge pin, clamped by an M4 set screw (tune with the fit-test coupon)
ARM_Y = (38.5, 48.5)           # tilt-plate arm |y| (sits between the coarse cheeks at 49..61)
LUG_R, BOSS_R = 20.0, 9.0      # hinge lug and lock-bolt boss radii
BEARING_D, BEARING_W = 22.15, 7.0
T_N = (-20.0, -14.0)           # T-local n range of the main tilt plate (plate hangs BELOW the hinge so the part prints flat)
T_S0, T_S1 = 32.0, 178.0
T_HALF_W = 72.0
T2_N = (-26.0, -20.0)          # motor beam, lapped under the end of the main plate
T2_S = (160.0, 255.0)
T2_HALF_W = 50.0
S_A, N_A = 50.0, 40.0          # altitude hinge axis in T-local
L_ALT = 150.0                  # altitude tangent-arm length (screw to hinge)
ALT_CHK_Y = (58.0, 70.0)       # altitude cheeks |y|, bolted to the top of the tilt plate
P_LUG_Y = (47.0, 57.0)
P_AX_Z = 20.0                  # print-frame z of the altitude axis (n' = 0): z' = 20 - n'
P_P0, P_P1 = 22.0, 200.0       # extended from 190 so the camera cradle sits wholly on the plate
CRADLE_P0 = 158.0              # p of the cradle base's west edge (beyond the rod, which stands at p = 150)
CRADLE_BOLT_P = (5.0, 27.0)    # cradle bolt positions along p, measured from CRADLE_P0
CRADLE_BOLT_Y = 16.0
# telescope seat disc: flat, pinned to the top plate, with an engraved yaw index (see README for why this and not a key)
SEAT_D, SEAT_T = 90.0, 4.0
SEAT_PIN_DX = 30.0             # dowel pins at p = P_STUD +/- this
# altitude end stops: an ear on the top plate swings between two micro switches on a tower beside the plate
ALT_TRIG = 7.3                 # trigger angle (deg): beyond the +/-6 deg working range, short of the hard limits (about 8.5)
EAR_P = (172.0, 188.0)         # ear extent along p
EAR_Y = (71.9, 87.0)           # ear extent in T-local +y (print frame -y)
WALL_GAP = 1.5                 # ear tip to tower wall
TOWER_BASE = (198.0, 236.0, 80.0, 108.0)      # s0, s1, y0, y1 of the tower's base plate
TOWER_BOLTS = ((206.0, 84.0), (230.0, 84.0), (206.0, 102.0), (230.0, 102.0))
TOWER_WALL_T = 8.0


def alt_stop():
    """Switch positions for the altitude end stops, T-local coordinates (s, y, n)."""
    b = math.radians(ALT_TRIG)
    pc = (EAR_P[0] + EAR_P[1]) / 2
    sc = S_A + pc
    n_at = lambda beta, npr: N_A + pc * math.sin(beta) + npr * math.cos(beta)
    L, W, T = c.SW_BODY
    y_w = EAR_Y[1] + WALL_GAP
    xb = sc - c.SW_LEVER
    n_roller_lo = n_at(-b, 14.0) - c.SW_ROLLER_R          # ear bottom (n' = 14) presses the lower switch's roller from above
    top_lo = n_roller_lo - c.SW_ROLLER_OFF
    n_roller_hi = n_at(+b, 20.0) + c.SW_ROLLER_R          # ear top (n' = 20) presses the upper switch's roller from below
    bot_hi = n_roller_hi + c.SW_ROLLER_OFF
    return dict(sc=sc, xb=xb, y_wall=y_w, y_roller=y_w - T / 2,
                lo=dict(roller=n_roller_lo, body=(top_lo - W, top_lo)),
                hi=dict(roller=n_roller_hi, body=(bot_hi, bot_hi + W)))
P_HALF_W = 72.0
P_STUD = 70.0                  # telescope stud position along the top plate
TAB_Y = (10.3, 16.3)           # trunnion yoke tabs |y|
LAP_S = (166.0, 172.0)
LAP_Y = 30.0
BLOCK_NP = 2.0                 # trunnion block centre n' below the plate (print frame z' = 18)
# electronics case hangs under the main tilt plate (see aligner_case.py); its four M4 screws come down through the plate
CASE_S0 = 70.0                 # tilt-plate s of the case's south face
CASE_OY = 81.8                 # case width along s (asserted equal in aligner_case.py)
CASE_HOLE_Y = 56.0             # |y| of the case mounting screws
CASE_HOLE_INSET = 6.0          # screw distance in from the case's south / north faces


def arc_slot(z0, z1, d=6.6, step=5.0):
    """Arc slot centred on the hinge (origin), radius R_LOCK, covering TILT_MIN..TILT_MAX, in a (x,y) cross-section."""
    angs = [math.radians(a) for a in np.arange(c.TILT_MIN, c.TILT_MAX + 0.01, step)]
    pts = [(c.R_LOCK * math.cos(a), -c.R_LOCK * math.sin(a)) for a in angs]
    segs = [(cylz(x0, y0, z0, z1, d) + cylz(x1, y1, z0, z1, d)).hull() for (x0, y0), (x1, y1) in zip(pts, pts[1:])]
    return U(*segs)


# ---------------------------------------------------------------- parts (print frames)
def coarse_cheek():
    """Fixed cheek on the azimuth plate. Print flat; print two (the part is symmetric through its thickness).
    Print frame: X = x - HX, Y = z - HZ, Z = thickness."""
    t = c.CHK_Y[1] - c.CHK_Y[0]
    u0, u1 = c.CHK_U
    w0, w1 = c.AZ_TOP - c.HZ, 16.0
    body = box(u0, w0, 0, u1, w1, t)
    cuts = [cylz(0, 0, -1, t + 1, CHEEK_PIN_D),
            arc_slot(-1, t + 1),
            cyly(0, t / 2, 3.0, w1 + 1, 4.5),                 # M4 set screw onto the hinge pin, from the top edge
            cyly(0, t / 2, w1 - 7.0, w1 + 1, 5.6)]            # heat-set insert pocket for it
    for u in c.CHK_BASE_U:
        cuts.append(cyly(u, t / 2, w0 - 1, w0 + 6.5, 5.6))    # base inserts (M4 bolts come up through the azimuth plate)
    return D(body, *cuts)


def tilt_plate_1():
    """Main tilt plate with the two hinge/lock arms. T-local frame, printed plate-down (z' = n + 20)."""
    n0, n1 = T_N
    parts = [box(T_S0, -T_HALF_W, n0, T_S1, T_HALF_W, n1)]
    for sg in (-1, 1):
        y0, y1 = sorted((sg * ARM_Y[0], sg * ARM_Y[1]))
        lug = c.cyly(0, 0, y0, y1, 2 * LUG_R)
        boss = c.cyly(-c.R_LOCK, 0, y0, y1, 2 * BOSS_R)
        bar = box(-c.R_LOCK - BOSS_R, y0, n0, 40.0, y1, n0 + 10.0)
        parts.append(U(lug, boss, bar).hull())
    body = U(*parts)
    cuts = []
    for sg in (-1, 1):
        y_in, y_out = sg * ARM_Y[0], sg * ARM_Y[1]
        lo, hi = sorted((y_in, y_out))
        pk0, pk1 = (y_out - BEARING_W, y_out + 1) if sg > 0 else (y_out - 1, y_out + BEARING_W)
        cuts.append(teardrop_y(0, 0, pk0, pk1, BEARING_D))                 # 608 bearing pocket from the outer face
        cuts.append(teardrop_y(0, 0, lo - 1, hi + 1, 16.0))                # bearing seat lip: opening through the arm
        cuts.append(teardrop_y(-c.R_LOCK, 0, lo - 1, hi + 1, 6.6))         # M6 lock bolt through the arm
    for s in (S_A - 12, S_A + 12):                                          # bolts that hold the altitude cheeks
        for sy in (-1, 1):
            cuts += [cylz(s, sy * 64.0, n0 - 1, n1 + 1, c.M4_CLR), cylz(s, sy * 64.0, n0 - 1, n0 + 3.0, 8.4)]
    for s in LAP_S:                                                         # lap joint to the motor beam
        for sy in (-1, 1):
            cuts += [cylz(s, sy * LAP_Y, n0 - 1, n1 + 1, c.M4_CLR), cylz(s, sy * LAP_Y, n1 - 3.5, n1 + 1, 8.4)]
    for s in (CASE_S0 + CASE_HOLE_INSET, CASE_S0 + CASE_OY - CASE_HOLE_INSET):   # electronics case screws, from the top
        for sy in (-1, 1):
            cuts += [cylz(s, sy * CASE_HOLE_Y, n0 - 1, n1 + 1, c.M4_CLR), cylz(s, sy * CASE_HOLE_Y, n1 - 3.5, n1 + 1, 8.4)]
    return D(body, *cuts).translate((0, 0, -n0))


def tilt_plate_2():
    """Motor beam: lapped under the main plate, carries the altitude motor and the spring anchors. Print flat."""
    n0, n1 = T2_N
    body = U(box(T2_S[0], -T2_HALF_W, n0, T2_S[1], T2_HALF_W, n1),
             box(TOWER_BASE[0] - 2.0, T2_HALF_W - 0.01, n0, T2_S[1], TOWER_BASE[3] + 3.0, n1))   # wing under the end-stop tower
    mx = S_A + L_ALT
    cuts = [cylz(mx, 0, n0 - 1, n1 + 1, c.NEMA17["boss"])]
    for dx in (-1, 1):
        for dy in (-1, 1):
            cuts.append(cylz(mx + dx * c.NEMA17["holes"] / 2, dy * c.NEMA17["holes"] / 2, n0 - 1, n1 + 1, c.NEMA17["m3"]))
    for s in LAP_S:
        for sy in (-1, 1):
            cuts.append(cylz(s, sy * LAP_Y, n1 - 5.0, n1 + 1, 5.6))        # M4 inserts for the lap bolts
    for sy in (-1, 1):
        cuts.append(cylz(225.0, sy * 45.0, n1 - 5.0, n1 + 1, c.M3_INSERT[0]))   # spring anchor screws
    for bs, by in TOWER_BOLTS:                                              # M4 bolts for the end-stop tower, nuts below
        cuts += [cylz(bs, by, n0 - 1, n1 + 1, c.M4_CLR), hexz(bs, by, n0 - 1, n0 + 3.2, 7.3)]
    return D(body, *cuts).translate((0, 0, -n0))


def alt_cheek():
    """Altitude hinge cheek, bolted to the top of the tilt plate. Print flat, print two.
    Print frame: X = s - S_A, Y = n - N_A, Z = thickness."""
    t = ALT_CHK_Y[1] - ALT_CHK_Y[0]
    y0, y1 = T_N[1] - N_A, 14.0
    body = box(-16.0, y0, 0, 16.0, y1, t)
    cuts = [cylz(0, 0, -1, t + 1, CHEEK_PIN_D),
            cyly(0, t / 2, 3.0, y1 + 1, 4.5), cyly(0, t / 2, y1 - 7.0, y1 + 1, 5.6)]
    for x in (-12.0, 12.0):
        cuts.append(cyly(x, t / 2, y0 - 1, y0 + 6.5, 5.6))
    return D(body, *cuts)


def top_plate():
    """Top plate. Print frame is flipped: z' = 20 - n', so the top face (the telescope seat) lies on the bed and the
    lugs, tabs and stud boss stand up with no supports."""
    parts = [box(P_P0, -P_HALF_W, 0, P_P1, P_HALF_W, 6.0)]
    for sg in (-1, 1):
        y0, y1 = sorted((sg * P_LUG_Y[0], sg * P_LUG_Y[1]))
        lug = c.cyly(0, P_AX_Z, y0, y1, 2 * LUG_R)
        web = box(0, y0, 0, 30.0, y1, 6.0)
        parts.append(U(lug, web).hull())
        ty0, ty1 = sorted((sg * TAB_Y[0], sg * TAB_Y[1]))
        parts.append(box(L_ALT - 8, ty0, 6.0, L_ALT + 8, ty1, 30.0))        # trunnion yoke tabs
        parts.append(cylz(175.0, sg * 45.0, 6.0, 12.0, 10.0))               # spring anchor bosses
    parts.append(box(EAR_P[0], -EAR_Y[1], 0, EAR_P[1], -EAR_Y[0] + 0.1, 6.0))             # end-stop ear (T-local +y side)
    parts.append(cylz(P_STUD, 0, 6.0, 14.0, 28.0))                          # boss under the plate for the stud head
    for bp in CRADLE_BOLT_P:                                                # inserts for the camera cradle bolts
        for sg in (-1, 1):
            parts.append(cylz(CRADLE_P0 + bp, sg * CRADLE_BOLT_Y, 6.0, 12.0, 9.0))
    body = U(*parts)
    cuts = [hexz(P_STUD, 0, 7.0, 15.0, c.HEX38_AF),                         # 3/8-16 bolt head, from below
            cylz(P_STUD, 0, -1, 15.0, 9.8),                                 # bolt shaft up through the plate
            slotz(L_ALT - 4.5, 0, L_ALT + 4.5, 0, -1, 7.0, 11.0)]           # clearance for the altitude rod
    for sx in (-1, 1):                                                      # dowel holes for the telescope seat disc (blind, from the top face)
        cuts.append(cylz(P_STUD + sx * SEAT_PIN_DX, 0, -1, 4.0, 3.2))
    for bp in CRADLE_BOLT_P:                                                # M3 from the top face into inserts below
        for sg in (-1, 1):
            cuts += [cylz(CRADLE_P0 + bp, sg * CRADLE_BOLT_Y, -1, 7.0, c.M3_CLR),
                     cylz(CRADLE_P0 + bp, sg * CRADLE_BOLT_Y, 6.5, 13.0, c.M3_INSERT[0])]
    for sg in (-1, 1):
        y_out = sg * P_LUG_Y[1]
        lo, hi = sorted((sg * P_LUG_Y[0], y_out))
        pk0, pk1 = (y_out - BEARING_W, y_out + 1) if sg > 0 else (y_out - 1, y_out + BEARING_W)
        cuts.append(teardrop_y(0, P_AX_Z, pk0, pk1, BEARING_D))
        cuts.append(teardrop_y(0, P_AX_Z, lo - 1, hi + 1, 16.0))
        ty_in = sg * TAB_Y[0]
        d0, d1 = (ty_in - 0.5, ty_in + 5.0) if sg > 0 else (ty_in - 5.0, ty_in + 0.5)
        cuts.append(cyly(L_ALT, 18.0, d0, d1, c.DOWEL_FREE))                # dowel holes for the nut trunnion
        cuts.append(cylz(175.0, sg * 45.0, 6.0, 13.0, c.M3_INSERT[0]))      # spring screw inserts
    return D(body, *cuts)


def telescope_seat():
    """Seat disc under the telescope. Print with the TOP face (the one the S50 sits on, carrying the index marks) on the bed.
    Installed, print x maps to -p, so the arrow is cut at print angle 180 deg to point toward +p (the camera end)."""
    body = cylz(0, 0, 0, SEAT_T, SEAT_D)
    cuts = [cylz(0, 0, -1, SEAT_T + 1, 9.8)]
    for sx in (-1, 1):
        cuts.append(cylz(sx * SEAT_PIN_DX, 0, SEAT_T - 3.0, SEAT_T + 1, 3.2))            # dowel holes on the underside
    depth = 0.5
    for k in range(24):                                                                    # ticks every 15 deg, long ones every 90
        r0, r1 = (31.0, 42.0) if k % 6 == 0 else (37.0, 42.0)
        cuts.append(box(r0, -0.4, -0.1, r1, 0.4, depth).rotate((0, 0, 15.0 * k)))
    tri = np.array([[26.0, -4.0], [36.0, 0.0], [26.0, 4.0]])                               # arrow, cut at print angle 180 deg
    arrow = Manifold.extrude(CrossSection([tri]), depth + 0.1).translate((0, 0, -0.1)).rotate((0, 0, 180.0))
    cuts.append(arrow)
    return D(body, *cuts)


def alt_tower():
    """Switch tower for the altitude end stops, bolted to the motor beam. Print standing as modelled."""
    st = alt_stop()
    L, W, T = c.SW_BODY
    s0, s1 = st["xb"] - L / 2 - 3.0, st["xb"] + L / 2 + 1.0
    yw = st["y_wall"]
    n_floor = T2_N[1]                                   # top face of the motor beam
    n_top = st["hi"]["body"][1] + 4.0
    parts = [box(TOWER_BASE[0], TOWER_BASE[2], n_floor, TOWER_BASE[1], TOWER_BASE[3], n_floor + 5.0),
             box(s0, yw, n_floor, s1, yw + TOWER_WALL_T, n_top)]
    for xs in (s0, s1 - 4.0):                           # gussets on the outer side of the wall
        parts.append(prism_yz([(yw + TOWER_WALL_T, n_floor), (TOWER_BASE[3], n_floor), (yw + TOWER_WALL_T, n_floor + 60.0)], xs, xs + 4.0))
    body = U(*parts)
    cuts = []
    for sw in ("lo", "hi"):                             # M2 self-tapping pilots, hole axis along y, from the inner face
        nc = sum(st[sw]["body"]) / 2
        for dx in (-c.SW_HOLE_SPACING / 2, c.SW_HOLE_SPACING / 2):
            cuts.append(cyly(st["xb"] + dx, nc, yw - 1.0, yw + 6.0, c.SW_PILOT_D))
    for bs, by in TOWER_BOLTS:
        cuts += [cylz(bs, by, n_floor - 1, n_floor + 6, c.M4_CLR), cylz(bs, by, n_floor + 1.5, n_floor + 6, 8.4)]
    return D(body, *cuts).translate((0, 0, -n_floor))


PARTS2 = {
    "05_coarse_cheek": coarse_cheek,
    "06_tilt_plate_1": tilt_plate_1,
    "07_tilt_plate_2": tilt_plate_2,
    "08_alt_cheek": alt_cheek,
    "09_top_plate": top_plate,
    "15_alt_endstop_tower": alt_tower,
    "16_telescope_seat": telescope_seat,
}


# ---------------------------------------------------------------- placement helpers (used by check_assembly.py)
def affine(m, R, t):
    return m.transform(np.hstack([np.asarray(R, float), np.asarray(t, float).reshape(3, 1)]))


def T_to_world(m, alpha_deg):
    a = math.radians(alpha_deg)
    ca, sa = math.cos(a), math.sin(a)
    return affine(m, [[-ca, 0, sa], [0, -1, 0], [sa, 0, ca]], [c.HX, 0, c.HZ])


def Tprint_to_T(m, base_n):
    """Main/ beam plate print frame (z' = n - base_n) back to T-local."""
    return m.translate((0, 0, base_n))


def Pprint_to_T(m, beta_deg):
    b = math.radians(beta_deg)
    cb, sb = math.cos(b), math.sin(b)
    Rp = np.array([[cb, 0, -sb], [0, 1, 0], [sb, 0, cb]])
    A = np.diag([1.0, -1.0, -1.0])
    return affine(m, Rp @ A, Rp @ np.array([0, 0, P_AX_Z]) + np.array([S_A, 0, N_A]))


def coarse_cheek_to_world(m, side):
    sg = 1 if side > 0 else -1
    R = [[1, 0, 0], [0, 0, sg], [0, 1, 0]]
    return affine(m, R, [c.HX, sg * c.CHK_Y[0], c.HZ])


def alt_cheek_to_T(m, side):
    sg = 1 if side > 0 else -1
    R = [[1, 0, 0], [0, 0, sg], [0, 1, 0]]
    return affine(m, R, [S_A, sg * ALT_CHK_Y[0], N_A])


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    c.main(out)                                   # re-export Batch 1 (the azimuth plate gained cheek holes)
    for name, fn in PARTS2.items():
        m = fn()
        if m.is_empty():
            raise SystemExit(f"{name}: empty result")
        tm = to_trimesh(m)
        tm.export(out / f"{name}.stl")
        bb = tm.bounds
        print(f"{name:18s} watertight={tm.is_watertight!s:5s} vol={tm.volume/1000:7.1f} cm3 "
              f"size={bb[1][0]-bb[0][0]:.0f}x{bb[1][1]-bb[0][1]:.0f}x{bb[1][2]-bb[0][2]:.0f} mm zmin={bb[0][2]:.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../stl")

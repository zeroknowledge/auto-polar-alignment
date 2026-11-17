"""Whole-assembly sweep for the tall-hinge stack: collisions and minimum gaps from latitude -10 to 75 deg.

Places the Batch 1 and Batch 2 parts, plus envelopes for the two motors, the altitude rod and coupler, the nut block and a
telescope-sized box (Seestar S50: 142 x 130 x 257 mm, bottom on the top plate, centred on the stud), for
  plate tilt  a = 90 - latitude  every 10 deg from 100 to 20, plus 15   (latitude -10 ... 75)
  altitude    beta in {-6, 0, +6} deg,   azimuth theta in {-6, 0, +6} deg (at the two extreme tilts)
and prints the minimum gap for every pair that is not a deliberate contact. Negative numbers are overlap volume (mm^3).
Also prints the centre-of-gravity offset from the bearing axis (printed parts at 40% effective infill, telescope 2.5 kg).
Limits: envelopes are simplified boxes, the telescope is a box (conservative), screws/pins/bearings are not modelled.
"""
import itertools
import math
import sys

import numpy as np

import aligner_cad as c
import aligner_cad2 as c2
import check_clearance as cc
from aligner_cad import box, cylz

SEARCH = 40.0
TELE = dict(w=142.0, d=130.0, h=257.0)          # y, p, n'
ALPHAS = [100, 90, 80, 70, 60, 50, 40, 30, 20, 15]
BETAS = [-6, 0, 6]
THETAS_EXTRA = [-6, 6]


def tl_cyl(x, y, n0, n1, d):
    return cylz(x, y, n0, n1, d)


def build_local():
    """Everything in T-local or P-local frames, before posing."""
    L = {}
    L["T1"] = c2.Tprint_to_T(c2.tilt_plate_1(), c2.T_N[0])
    L["T2"] = c2.Tprint_to_T(c2.tilt_plate_2(), c2.T2_N[0])
    cheek = c2.alt_cheek()
    L["altL"] = c2.alt_cheek_to_T(cheek, -1)
    L["altR"] = c2.alt_cheek_to_T(cheek, +1)
    mx = c2.S_A + c2.L_ALT
    half = c.NEMA17["sq"] / 2
    L["altmotor"] = box(mx - half, -half, c2.T2_N[0] - 34.0, mx + half, half, c2.T2_N[0])
    L["rod"] = U_(tl_cyl(mx, 0, -10.0, 10.0, 14.0), tl_cyl(mx, 0, 2.0, 72.0, 6.0))   # coupler + rod (top clears the nut by 4 mm at full raise)
    import aligner_case as cs
    L["tower"] = c2.Tprint_to_T(c2.alt_tower(), c2.T2_N[1])
    st_ = c2.alt_stop(); sl_, sw_, sh_ = c.SW_BODY
    L["swlo"] = box(st_["xb"] - sl_ / 2, st_["y_wall"] - sh_, st_["lo"]["body"][0], st_["xb"] + sl_ / 2, st_["y_wall"], st_["lo"]["body"][1])
    L["swhi"] = box(st_["xb"] - sl_ / 2, st_["y_wall"] - sh_, st_["hi"]["body"][0], st_["xb"] + sl_ / 2, st_["y_wall"], st_["hi"]["body"][1])
    L["case"] = box(c2.CASE_S0, -cs.OX / 2, c2.T_N[0] - cs.H_TOTAL, c2.CASE_S0 + cs.OY, cs.OX / 2, c2.T_N[0])   # case + lid, under T1
    return L, cheek


def U_(*ms):
    out = ms[0]
    for m in ms[1:]:
        out = out + m
    return out


def pose(L, cheek, top, nut_block, alpha, beta, theta, delta=None):
    """World-frame manifolds for one configuration."""
    W = {}
    plate = cc.az_stack()
    W["azplate"] = plate
    W["cheekL"] = c2.coarse_cheek_to_world(cheek_c, -1)
    W["cheekR"] = c2.coarse_cheek_to_world(cheek_c, +1)
    for k in ("T1", "T2", "altL", "altR", "altmotor", "rod", "case", "tower", "swlo", "swhi"):
        W[k] = c2.T_to_world(L[k], alpha)
    W["P"] = c2.T_to_world(c2.Pprint_to_T(top, beta), alpha)
    # nut block: stays aligned with the rod (vertical in T-local) at the height of the P tab pivot
    b = math.radians(beta)
    n_piv = c2.N_A + c2.L_ALT * math.sin(b) + c2.BLOCK_NP * math.cos(b)
    mx = c2.S_A + c2.L_ALT
    bx, by, bz = c.BLOCK["y"], c.BLOCK["x"], c.BLOCK["z"]       # block: 16 along s, 20 along y, 18 along n
    W["block"] = c2.T_to_world(box(mx - bx / 2, -by / 2, n_piv - bz / 2, mx + bx / 2, by / 2, n_piv + bz / 2), alpha)
    tele_pl = box(c2.P_STUD - TELE["d"] / 2, -TELE["w"] / 2, 20.0 + c2.SEAT_T, c2.P_STUD + TELE["d"] / 2, TELE["w"] / 2, 20.0 + c2.SEAT_T + TELE["h"])
    tele_T = c2.affine(tele_pl, np.array([[math.cos(b), 0, -math.sin(b)], [0, 1, 0], [math.sin(b), 0, math.cos(b)]]),
                       [c2.S_A, 0, c2.N_A])
    W["tele"] = c2.T_to_world(tele_T, alpha)
    if delta is not None:
        import aligner_cam as cam
        from manifold3d import Manifold
        env, lens_front = cam.camera_envelopes()
        chain = lambda m: c2.T_to_world(c2.Pprint_to_T(cam.cradle_to_Pprint(m), beta), alpha)
        W["cradle"] = chain(cam.cradle_base())
        W["camplate"] = chain(cam.plate_local_to_cradle(cam.camera_plate(), delta))
        for k_, m_ in env.items():
            W["cam_" + k_] = chain(cam.plate_local_to_cradle(m_, delta))
        r_ = 700.0 * math.tan(math.radians(11.1))               # field of view: diagonal half-angle of the 16 mm lens, 11.1 deg
        cone = Manifold.cylinder(700.0, 0.0, r_, 48).translate((0, 0, lens_front))
        W["fov"] = chain(cam.plate_local_to_cradle(cone, delta))
    for k in W:
        W[k] = W[k].rotate((0, 0, theta))
    # azimuth preload spring: stadium from the rotating post (turns with theta) to the farthest fixed peg, hooks and screw heads
    ax_, ay_ = c.PRE_POST
    th_ = math.radians(theta)
    px_, py_ = ax_ * math.cos(th_) - ay_ * math.sin(th_), ax_ * math.sin(th_) + ay_ * math.cos(th_)
    z0_, z1_ = c.AZ_TOP, c.AZ_TOP + 10.0
    W["spring"] = (cylz(px_, py_, z0_, z1_, 8.0) + cylz(c.PRE_PEGS_X[-1], ay_, z0_, z1_, 8.0)).hull()
    return W


SKIP = {frozenset(p) for p in [
    ("azplate", "cheekL"), ("azplate", "cheekR"),           # bolted
    ("T1", "T2"), ("T1", "altL"), ("T1", "altR"),           # bolted
    ("T2", "altmotor"), ("rod", "altmotor"),                # motor, coupler and beam are one assembly
    ("rod", "block"),                                       # the rod runs through the nut
    ("P", "tele"), ("T1", "rod"), ("T2", "rod"), ("T1", "case"), ("spring", "azplate"), ("tower", "T2"), ("tower", "swlo"), ("tower", "swhi"), ("T2", "swlo"), ("T2", "swhi"),            # telescope sits on P; rod stands on the beam
]}
CAM_GROUP = ("cradle", "camplate", "cam_board", "cam_conn", "cam_boss", "cam_lens", "cam_shield", "fov")
for a_ in CAM_GROUP[1:]:
    for b_ in CAM_GROUP[1:]:
        if a_ != b_:
            SKIP.add(frozenset((a_, b_)))
SKIP.add(frozenset(("cradle", "P")))
SKIP.add(frozenset(("cradle", "fov")))


def gap(a, b):
    ba, bb = a.bounding_box(), b.bounding_box()
    sep = max(ba[0] - bb[3], bb[0] - ba[3], ba[1] - bb[4], bb[1] - ba[4], ba[2] - bb[5], bb[2] - ba[5])
    if sep > SEARCH:
        return SEARCH + 1
    inter = a ^ b
    if not inter.is_empty() and inter.volume() > 1e-3:
        return -inter.volume()
    return a.min_gap(b, SEARCH)


def cog_table(top, L):
    """Centre of gravity offset from the bearing axis, x toward the pole (mm), for several latitudes."""
    infill = 0.4
    rho = 1.27e-3                                   # g/mm^3
    rows = []
    for lat in (0, 25, 45, 65):
        alpha = 90 - lat
        masses, pts = [], []
        for name, m in (("T1", L["T1"]), ("T2", L["T2"])):
            w = c2.T_to_world(m, alpha)
            masses.append(w.volume() * rho * infill)
            bb = w.bounding_box(); pts.append(((bb[0] + bb[3]) / 2, (bb[2] + bb[5]) / 2))
        p = c2.T_to_world(c2.Pprint_to_T(top, 0), alpha)
        bb = p.bounding_box(); masses.append(p.volume() * rho * infill); pts.append(((bb[0] + bb[3]) / 2, (bb[2] + bb[5]) / 2))
        # telescope CoG: 100 mm above the seat on the stud axis
        tele = c2.T_to_world(c2.affine(box(-1, -1, -1, 1, 1, 1), np.eye(3), [c2.S_A + c2.P_STUD, 0, c2.N_A + 20.0 + 100.0]), alpha)
        bb = tele.bounding_box(); masses.append(2500.0); pts.append(((bb[0] + bb[3]) / 2, (bb[2] + bb[5]) / 2))
        cw = c2.T_to_world(L["case"], alpha); bb = cw.bounding_box()
        masses.append(450.0); pts.append(((bb[0] + bb[3]) / 2, (bb[2] + bb[5]) / 2))      # case, PCB, Pi, modules, motor
        # azimuth stage + cheeks + motors etc. are near the axis: add a fixed 600 g at the bearing axis
        masses.append(600.0); pts.append((0.0, 40.0))
        M = sum(masses)
        x = sum(m * p_[0] for m, p_ in zip(masses, pts)) / M
        z = sum(m * p_[1] for m, p_ in zip(masses, pts)) / M
        rows.append((lat, M / 1000, x, z))
    return rows


cheek_c = None


def main():
    global cheek_c
    L, _ = build_local()
    cheek_c = c2.coarse_cheek()
    top = c2.top_plate()
    spider = c.base_spider()
    azmotor = cc.motor_and_rod()
    sa = c.az_stop()
    bx0, bx1, by0, by1, bz0, bz1 = sa["body"]
    fixed_items = [("spider", spider), ("azmotor", azmotor), ("azswL", box(bx0, by0, bz0, bx1, by1, bz1)),
                   ("azswR", box(bx0, -by1, bz0, bx1, -by0, bz1))]
    worst = {}
    configs = [(a, b, 0.0) for a in ALPHAS for b in BETAS] + [(a, 0, t) for a in (25, 90) for t in THETAS_EXTRA]
    for (alpha, beta, theta) in configs:
        W = pose(L, None, top, None, alpha, beta, theta)
        names = list(W)
        for a_, b_ in itertools.combinations(names, 2):
            if frozenset((a_, b_)) in SKIP:
                continue
            g = gap(W[a_], W[b_])
            key = (a_, b_)
            if key not in worst or g < worst[key][0]:
                worst[key] = (g, alpha, beta, theta)
        for n in names:                                     # upper stack vs the fixed base (only matters near the azimuth stage)
            for fname, fm in fixed_items:
                if n == "spring" and fname == "spider":
                    continue          # the spring is hooked to the spider
                g = gap(W[n], fm)
                key = (n, fname)
                if key not in worst or g < worst[key][0]:
                    worst[key] = (g, alpha, beta, theta)
    cam_cfg = [(a, b, 0.0, d) for a in (100, 90, 60, 20) for b in (-6, 6) for d in (0, 10, 25, 40)]
    fov_blocked = {}
    for (alpha, beta, theta, delta) in cam_cfg:
        W = pose(L, None, top, None, alpha, beta, theta, delta=delta)
        cams = [n for n in W if n in CAM_GROUP]
        others = [n for n in W if n not in CAM_GROUP]
        for cn in cams:
            for on in others:
                if frozenset((cn, on)) in SKIP:
                    continue
                g = gap(W[cn], W[on])
                key = (cn, on)
                if cn == "fov":
                    if g <= 0:
                        fov_blocked.setdefault(on, set()).add(delta)
                    continue
                if key not in worst or g < worst[key][0]:
                    worst[key] = (g, alpha, beta, theta)
    bad = {k: v for k, v in worst.items() if v[0] <= 0}
    tight = {k: v for k, v in worst.items() if 0 < v[0] < 2.0}
    print(f"configs checked: {len(configs)}   pairs: {len(worst)}")
    print("\nCOLLISIONS (overlap volume mm^3, negative):" if bad else "\nno collisions found")
    for k, v in sorted(bad.items(), key=lambda kv: kv[1][0]):
        print(f"  {k[0]:9s} x {k[1]:9s} {v[0]:10.1f}   at tilt {v[1]} deg, beta {v[2]}, theta {v[3]}")
    print("\nTIGHT (0 < gap < 2 mm):" if tight else "\nnothing tighter than 2 mm")
    for k, v in sorted(tight.items(), key=lambda kv: kv[1][0]):
        print(f"  {k[0]:9s} x {k[1]:9s} {v[0]:6.2f} mm   at tilt {v[1]} deg, beta {v[2]}, theta {v[3]}")
    print("\nclosest remaining pairs (gap mm):")
    for k, v in sorted(worst.items(), key=lambda kv: kv[1][0])[:14]:
        if v[0] > 0:
            print(f"  {k[0]:9s} x {k[1]:9s} {v[0]:6.2f}")
    print(f"\ncamera sweep: {len(cam_cfg)} poses (tilt 0/10/25/40 deg); field of view (11.1 deg half-angle cone) obstructed by:",
          {k: sorted(v) for k, v in fov_blocked.items()} if fov_blocked else "nothing")
    print("\ncentre of gravity from the bearing axis (x toward the pole, z up):")
    for lat, kg, x, z in cog_table(top, L):
        print(f"  latitude {lat:2d}: total {kg:.2f} kg, CoG x = {x:6.1f} mm, z = {z:6.1f} mm")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())

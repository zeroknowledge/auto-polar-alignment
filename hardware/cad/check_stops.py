"""Do the end-stop switches trigger where they were designed to, with margin before anything is struck?

For each axis and direction, sweep the angle and report
  trigger   first angle at which the moving flag touches the roller
  hard      first angle at which it would touch the switch BODY (the roller is fully pressed by then)
  working   the working range the software is meant to use (+/-6 deg), which must stay clear of the trigger
Switch body and lever figures are assumptions (see README): a roller 1 mm off moves the trigger by about 0.7 deg on azimuth
and 0.3 deg on altitude, so the margins below are what matters, not the exact trigger values.
"""
import math
import sys

import numpy as np

import aligner_cad as c
import aligner_cad2 as c2
from aligner_cad import box, cylz, cyly

ROLLER_W = 4.0          # roller thickness along its axis (assumed)
WORKING = 6.0


def first_contact(items, angles):
    for a in angles:
        if any(g(a) <= 0.001 for g in items):
            return float(a)
    return None


def az_axis():
    st = c.az_stop()
    half = c.AZ_TAB["half"]
    z0, z1 = c.AZ_TOP - c.AZP_T, c.AZ_TOP
    tab = box(c.AZ_TAB["x0"], -half, z0, c.AZ_TAB["x1"], half, z1)
    out = {}
    for side, th_sign in (("-y switch", +1), ("+y switch", -1)):
        sg = -1 if side == "-y switch" else 1
        rx, ry, rz = st["roller"]
        roller = cylz(rx, sg * abs(ry), rz - ROLLER_W / 2, rz + ROLLER_W / 2, 2 * c.SW_ROLLER_R)
        x0, x1, y0, y1, bz0, bz1 = st["body"]
        ya, yb = sorted((sg * abs(y0), sg * abs(y1)))
        body = box(x0, ya, bz0, x1, yb, bz1)
        angs = np.arange(0.0, 16.0, 0.05)
        rot = lambda a: tab.rotate((0, 0, th_sign * a))
        trig = first_contact([lambda a: rot(a).min_gap(roller, 5.0) if (rot(a) ^ roller).volume() < 1e-6 else 0.0], angs)
        hard = first_contact([lambda a: rot(a).min_gap(body, 5.0) if (rot(a) ^ body).volume() < 1e-6 else 0.0], angs)
        out[side] = (trig, hard)
    return out


def alt_axis():
    st = c2.alt_stop()
    L, W, T = c.SW_BODY
    ear_pl = box(c2.EAR_P[0], c2.EAR_Y[0], 14.0, c2.EAR_P[1], c2.EAR_Y[1], 20.0)      # P-local (p, y, n')

    def ear_T(beta_deg):
        b = math.radians(beta_deg)
        R = np.array([[math.cos(b), 0, -math.sin(b)], [0, 1, 0], [math.sin(b), 0, math.cos(b)]])
        return c2.affine(ear_pl, R, [c2.S_A, 0, c2.N_A])

    yr, yw = st["y_roller"], st["y_wall"]
    out = {}
    for name, sgn, sw in (("lower switch (plate drops)", -1, "lo"), ("upper switch (plate rises)", +1, "hi")):
        roller = cyly(st["xb"] + c.SW_LEVER, st[sw]["roller"], yr - ROLLER_W / 2, yr + ROLLER_W / 2, 2 * c.SW_ROLLER_R)
        n0, n1 = st[sw]["body"]
        body = box(st["xb"] - L / 2, yw - T, n0, st["xb"] + L / 2, yw, n1)
        angs = np.arange(0.0, 14.0, 0.05)
        e = lambda a: ear_T(sgn * a)
        trig = first_contact([lambda a: e(a).min_gap(roller, 5.0) if (e(a) ^ roller).volume() < 1e-6 else 0.0], angs)
        hard = first_contact([lambda a: e(a).min_gap(body, 5.0) if (e(a) ^ body).volume() < 1e-6 else 0.0], angs)
        out[name] = (trig, hard)
    return out


def main():
    ok = True
    for axis, res, target in (("azimuth", az_axis(), c.AZ_TRIG), ("altitude", alt_axis(), c2.ALT_TRIG)):
        print(f"{axis} (designed trigger {target} deg, working range +/-{WORKING} deg)")
        for k, (trig, hard) in res.items():
            if trig is None:
                print(f"  {k:28s} never triggers within the sweep"); ok = False; continue
            margin_work = trig - WORKING
            margin_hard = None if hard is None else hard - trig
            flag = "OK " if (margin_work >= 1.0 and (margin_hard is None or margin_hard >= 0.5)) else "CHECK"
            ok &= flag == "OK "
            hs = "no body contact below 16 deg" if hard is None else f"body contact at {hard:.2f} deg ({margin_hard:.2f} deg after the trigger)"
            print(f"  {k:28s} trigger {trig:5.2f} deg ({margin_work:+.2f} past the working range); {hs}   {flag}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

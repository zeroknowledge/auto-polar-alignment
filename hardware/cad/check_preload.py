"""Azimuth preload spring: which peg to use, and what torque to expect, for a given extension spring.

Usage:  python check_preload.py                       (three sample springs)
        python check_preload.py L0 k F0               (free length hook-to-hook mm, rate N/mm, initial tension N)

The spring runs from the post on the rotating azimuth plate (angle 103.2 deg, radius 88 mm) to one of three pegs on the fixed
spider. The plate turns +/-6 deg. A peg is acceptable if the spring stays in tension over the whole travel, the torque about the
bearing axis never falls below the target, and the peak force stays modest. Clockwise preload: the screw is always loaded on the
same thread flank, so finish every azimuth move in the clockwise direction (decreasing angle, seen from above).
"""
import math
import sys

import aligner_cad as c

TORQUE_MIN = 0.10      # N.m: enough to hold the nut on one flank against bearing friction, cable drag and a light breeze (estimate)
FORCE_MAX = 10.0       # N: peak spring force I am willing to put on the plate post and the rod nut
MARGIN = 2.0           # mm of stretch the spring keeps at the most slack point


def evaluate(L0, k, F0, peg_x):
    ax, ay = c.PRE_POST
    rows = []
    for th in (-6.0, -3.0, 0.0, 3.0, 6.0):
        t = math.radians(th)
        px, py = ax * math.cos(t) - ay * math.sin(t), ax * math.sin(t) + ay * math.cos(t)
        dx, dy = peg_x - px, ay - py
        chord = math.hypot(dx, dy)
        stretch = chord - L0
        F = (F0 + k * stretch) if stretch > 0 else 0.0
        fx, fy = F * dx / chord, F * dy / chord
        torque = (px * fy - py * fx) / 1000.0           # N.m about the bearing axis, positive counter-clockwise
        rows.append((th, chord, stretch, F, torque))
    return rows


def report(name, L0, k, F0):
    print(f"spring {name}: free length {L0} mm, rate {k} N/mm, initial tension {F0} N")
    best = None
    for peg in c.PRE_PEGS_X:
        rows = evaluate(L0, k, F0, peg)
        smin = min(r[2] for r in rows)
        tmin = min(abs(r[4]) for r in rows)
        fmax = max(r[3] for r in rows)
        ok = smin >= MARGIN and tmin >= TORQUE_MIN and fmax <= FORCE_MAX
        print(f"  peg x={peg:4.0f}: stretch {smin:5.1f}..{max(r[2] for r in rows):5.1f} mm, force {min(r[3] for r in rows):4.1f}..{fmax:4.1f} N, "
              f"torque {tmin:.2f}..{max(abs(r[4]) for r in rows):.2f} N.m (clockwise)   {'OK' if ok else '--'}")
        if ok and best is None:
            best = peg
    print(f"  -> {'use the peg at x = %.0f' % best if best is not None else 'no peg works: pick a spring with a lower rate or a different length'}")
    return best


def main():
    if len(sys.argv) == 4:
        report("(yours)", *(float(v) for v in sys.argv[1:4]))
        return 0
    for name, L0, k, F0 in (("short", 18.0, 0.5, 0.5), ("medium", 25.0, 0.3, 0.7), ("long", 32.0, 0.2, 0.8)):
        report(name, L0, k, F0)
    return 0


if __name__ == "__main__":
    sys.exit(main())

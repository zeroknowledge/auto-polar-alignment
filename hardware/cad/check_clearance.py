"""Static + swept interference check for the azimuth stage (Batch 1 parts).

Assembled frame: origin on the bearing axis, z=0 at the bottom of the base spider.
Checks, for azimuth rotations of -6..+6 deg:
  1. spider (fixed) vs azimuth plate + cap (rotating)
  2. motor envelope + M6 rod (fixed) vs azimuth plate + cap (rotating)
  3. nut-trunnion block vs yoke posts/cap/tab, in the azimuth-plate frame (the block turns relative to the yoke)
Prints the minimum gap (mm) for each. A gap <= 0 means interference.
"""
import math
import sys

from manifold3d import Manifold

import aligner_cad as c

SEARCH = 30.0


def gap(a: Manifold, b: Manifold) -> float:
    inter = a ^ b
    if not inter.is_empty() and inter.volume() > 1e-6:
        return -inter.volume()  # negative number: overlap volume in mm^3
    return a.min_gap(b, SEARCH)


def az_stack():
    plate = c.az_plate().translate((0, 0, c.SPIDER_T + c.LS_H))
    cap_z = c.SPIDER_T + c.LS_H + c.AZP_T + c.GAP + c.BLOCK["x"] + c.GAP
    cap = c.az_cap().translate((0, 0, cap_z))
    return plate + cap


def motor_and_rod():
    half = c.NEMA17["sq"] / 2
    y0 = c.FACE_Y + 6.0
    body = c.box(c.ARM_AZ - half, y0, c.Z_ROD - half, c.ARM_AZ + half, y0 + 40.0, c.Z_ROD + half)
    rod = c.cyly(c.ARM_AZ, c.Z_ROD, -20.0, y0, 6.0)
    return body + rod


def block_world(y_off=0.0):
    """Nut-trunnion block with its rod axis along world +y, pivot axis vertical, centred at (ARM_AZ, y_off, Z_ROD)."""
    b = c.nut_trunnion().translate((0, 0, -c.BLOCK["z"] / 2))      # centre the block on the origin
    return b.rotate((-90, -90, 0)).translate((c.ARM_AZ, y_off, c.Z_ROD))


def main():
    spider = c.base_spider()
    stack = az_stack()
    mr = motor_and_rod()
    worst = {"spider": 1e9, "motor+rod": 1e9, "block": 1e9}
    for ang in (-6.0, -3.0, 0.0, 3.0, 6.0):
        rot = stack.rotate((0, 0, ang))
        worst["spider"] = min(worst["spider"], gap(spider, rot))
        worst["motor+rod"] = min(worst["motor+rod"], gap(mr, rot))
        # block relative to the yoke: nut sits on the radial line at 80/cos(ang), turned by ang
        th = math.radians(ang)
        blk = block_world(0.0).rotate((0, 0, ang), ) if False else None
        b = c.nut_trunnion().translate((0, 0, -c.BLOCK["z"] / 2)).rotate((-90, -90, 0))
        b = b.rotate((0, 0, ang)).translate((c.ARM_AZ / math.cos(th), 0, c.Z_ROD))
        worst["block"] = min(worst["block"], gap(b, stack))
    print("minimum gaps over -6..+6 deg azimuth (mm; negative = overlap volume in mm^3)")
    for k, v in worst.items():
        flag = "OK " if v > 1.0 else "TIGHT" if v > 0 else "COLLISION"
        print(f"  {k:10s} {v:8.2f}  {flag}")
    return 0 if all(v > 0 for v in worst.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

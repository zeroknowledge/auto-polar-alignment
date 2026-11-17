"""astrometry.net fallback (``solve-field``), a documented option, not the default.

Slower (seconds to tens of seconds on a Pi Zero 2 W, and it needs index files, ``astrometry-data-*``
from apt, matching a 4-8 deg wide quad scale), but very robust, and a useful cross-check when the
tetra3 database misbehaves.  We hand it the star list we already extracted (a FITS ``xyls`` table, so
its own source detector is not used) and read back the WCS.

Not exercised against a real ``solve-field`` here (it is not installed): the FITS writer and the
WCS-to-rotation geometry are unit-tested; the subprocess call is not.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from ..config import CameraConfig, SolverConfig
from ..extract.base import ExtractionResult
from .base import Solution, SolveOutcome


def _card(key: str, value, comment: str = "") -> bytes:
    if isinstance(value, bool):
        v = "T" if value else "F"
        s = f"{key:<8}= {v:>20}"
    elif isinstance(value, (int, float)):
        s = f"{key:<8}= {value:>20}"
    else:
        s = f"{key:<8}= '{value:<8}'"
    return f"{s} / {comment}".ljust(80)[:80].encode("ascii")


def _hdu(cards: list[bytes], data: bytes = b"") -> bytes:
    header = b"".join(cards) + b"END".ljust(80)
    header += b" " * ((-len(header)) % 2880)
    return header + data + b"\0" * ((-len(data)) % 2880)


def write_xyls(path: Path, x: np.ndarray, y: np.ndarray, flux: np.ndarray, width: int, height: int) -> None:
    """Minimal FITS file: empty primary HDU + binary table with columns X, Y, FLUX (float32)."""
    n = len(x)
    rows = np.column_stack([x + 1.0, y + 1.0, flux]).astype(">f4")          # FITS pixels are 1-based
    primary = _hdu([_card("SIMPLE", True), _card("BITPIX", 8), _card("NAXIS", 0), _card("EXTEND", True)])
    cards = [_card("XTENSION", "BINTABLE"), _card("BITPIX", 8), _card("NAXIS", 2), _card("NAXIS1", 12),
             _card("NAXIS2", n), _card("PCOUNT", 0), _card("GCOUNT", 1), _card("TFIELDS", 3),
             _card("TTYPE1", "X"), _card("TFORM1", "1E"), _card("TTYPE2", "Y"), _card("TFORM2", "1E"),
             _card("TTYPE3", "FLUX"), _card("TFORM3", "1E"), _card("IMAGEW", float(width)), _card("IMAGEH", float(height))]
    path.write_bytes(primary + _hdu(cards, rows.tobytes()))


def parse_wcs_header(raw: bytes) -> dict[str, float]:
    out: dict[str, float] = {}
    for i in range(0, len(raw), 80):
        card = raw[i:i + 80].decode("ascii", errors="ignore")
        if card.startswith("END"):
            break
        if len(card) > 10 and card[8] == "=":
            key = card[:8].strip()
            val = card[10:].split("/")[0].strip()
            try:
                out[key] = float(val)
            except ValueError:
                pass
    return out


def rotation_from_wcs(w: dict[str, float], width: int, height: int) -> np.ndarray:
    """Celestial->camera rotation (rows: boresight, image-left, image-up) from a TAN WCS whose pixel
    coordinates are (col + 1, row + 1)."""
    ra0, dec0 = math.radians(w["CRVAL1"]), math.radians(w["CRVAL2"])
    cd = np.array([[w["CD1_1"], w["CD1_2"]], [w["CD2_1"], w["CD2_2"]]])

    def sky(px: float, py: float) -> np.ndarray:
        xi, eta = np.radians(cd @ np.array([px - w["CRPIX1"], py - w["CRPIX2"]]))
        # inverse gnomonic projection about (ra0, dec0)
        d = math.sqrt(1.0 + xi * xi + eta * eta)
        east = np.array([-math.sin(ra0), math.cos(ra0), 0.0])
        north = np.array([-math.sin(dec0) * math.cos(ra0), -math.sin(dec0) * math.sin(ra0), math.cos(dec0)])
        bore = np.array([math.cos(dec0) * math.cos(ra0), math.cos(dec0) * math.sin(ra0), math.sin(dec0)])
        v = (bore + xi * east + eta * north) / d
        return v / np.linalg.norm(v)

    cx, cy = (width + 1) / 2.0, (height + 1) / 2.0
    b = sky(cx, cy)
    left = sky(cx - 1.0, cy) - sky(cx + 1.0, cy)
    left = left - float(left @ b) * b
    left /= np.linalg.norm(left)
    up = np.cross(b, left)
    return np.vstack([b, left, up])


class AstrometrySolver:
    name = "astrometry.net"

    def __init__(self, cfg: SolverConfig | None = None, camera: CameraConfig | None = None) -> None:
        self.cfg = cfg or SolverConfig()
        self.camera = camera or CameraConfig()
        self.binary = shutil.which(self.cfg.astrometry_binary)

    def solve(self, stars: ExtractionResult, image: np.ndarray | None = None) -> SolveOutcome:
        if self.binary is None:
            return SolveOutcome("error", detail=f"'{self.cfg.astrometry_binary}' not found (apt install astrometry.net astrometry-data-tycho2)")
        good = stars.good()
        order = np.argsort(-good.flux)[: self.cfg.max_stars]
        if len(order) < self.cfg.min_stars:
            return SolveOutcome("too_few", n_input=len(order))
        h, w = stars.image_shape
        t0 = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="polaralign-") as tmp:
            d = Path(tmp)
            write_xyls(d / "stars.xyls", good.x[order], good.y[order], good.flux[order], w, h)
            fov = self.camera.fov_h_deg
            cmd = [self.binary, "--overwrite", "--no-plots", "--no-verify-uniformize", "--parity", "both", "--dir", str(d),
                   "--x-column", "X", "--y-column", "Y", "--sort-column", "FLUX", "--width", str(w), "--height", str(h),
                   "--scale-units", "degwidth", "--scale-low", f"{fov * 0.9:.2f}", "--scale-high", f"{fov * 1.1:.2f}",
                   "--cpulimit", str(int(self.cfg.astrometry_timeout_s)), "--new-fits", "none", "--rdls", "none",
                   "--corr", "none", "--match", "none", "--index-xyls", "none", str(d / "stars.xyls")]
            try:
                subprocess.run(cmd, check=False, capture_output=True, timeout=self.cfg.astrometry_timeout_s + 10)
            except subprocess.TimeoutExpired:
                return SolveOutcome("timeout", n_input=len(order), t_ms=(time.perf_counter() - t0) * 1e3)
            wcs = d / "stars.wcs"
            if not wcs.exists():
                return SolveOutcome("no_match", n_input=len(order), t_ms=(time.perf_counter() - t0) * 1e3)
            hdr = parse_wcs_header(wcs.read_bytes())
        rot = rotation_from_wcs(hdr, w, h)
        ra = math.degrees(math.atan2(rot[0, 1], rot[0, 0])) % 360.0
        dec = math.degrees(math.asin(float(rot[0, 2])))
        roll = math.degrees(math.atan2(rot[1, 2], rot[2, 2])) % 360.0
        t_ms = (time.perf_counter() - t0) * 1e3
        sol = Solution(ra_deg=ra, dec_deg=dec, roll_deg=roll, fov_deg=fov, distortion=None, rmse_arcsec=0.0,
                       n_matches=len(order), prob=0.0, t_solve_ms=t_ms, rotation=rot)
        return SolveOutcome("ok", sol, n_input=len(order), t_ms=t_ms, detail="astrometry.net (no residual reported)")

"""Star catalogue used by the simulator (and available to tools).

The catalogue is taken from the star table inside a tetra3 / Cedar Solve database, so the simulator
and the solver agree on star positions by construction (ICRS/J2000, proper motions applied to the
database epoch).  The bundled ``default_database.npz`` that ships in the ``cedar-solve`` wheel holds
42,212 Hipparcos stars to magnitude 8.03 (about 15,500 stars brighter than 7); a database built with
``polaralign build-db`` carries its own table.

Limitation (stated in the README): because the simulator draws from the same table the solver
matches against, catalogue errors are not simulated.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .astro.frames import unit


@dataclass
class StarCatalog:
    ra: np.ndarray        # radians, J2000
    dec: np.ndarray       # radians
    mag: np.ndarray
    vec: np.ndarray       # (N, 3) unit vectors

    def __len__(self) -> int:
        return int(self.mag.shape[0])

    def cone(self, center: np.ndarray, radius_rad: float, max_mag: float | None = None) -> np.ndarray:
        """Indices of stars within ``radius_rad`` of unit vector ``center`` (brightest first)."""
        idx = np.nonzero(self.vec @ unit(center) >= np.cos(radius_rad))[0]
        if max_mag is not None:
            idx = idx[self.mag[idx] <= max_mag]
        return idx[np.argsort(self.mag[idx])]


def bundled_database_path() -> Path:
    import tetra3
    return Path(tetra3.__file__).resolve().parent / "data" / "default_database.npz"


def load_from_database(path: str | Path | None = None, max_mag: float | None = None) -> StarCatalog:
    """Read the star table out of a tetra3 database file (default: the bundled one)."""
    p = Path(path) if path else bundled_database_path()
    with np.load(p, allow_pickle=True) as d:
        table = np.asarray(d["star_table"], dtype=np.float64)
    ra, dec, mag = table[:, 0], table[:, 1], table[:, 5]
    if max_mag is not None:
        keep = mag <= max_mag
        ra, dec, mag = ra[keep], dec[keep], mag[keep]
    vec = np.stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)], axis=1)
    return StarCatalog(ra=ra, dec=dec, mag=mag, vec=vec)

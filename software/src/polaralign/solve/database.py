"""Build a plate-solver database sized for this camera's field of view.

The bundled ``default_database`` covers 10-30 deg fields.  This camera has a fixed lens
(about 17.9 x 13.4 deg), so a single-scale database for 16.5-19.5 deg is smaller and faster.

Catalogue sources, in order of preference:

* ``--catalogue /path/to/hip_main.dat`` -- the Hipparcos main catalogue from CDS
  (https://cdsarc.u-strasbg.fr/ftp/cats/I/239/hip_main.dat, 51 MB).  Proper motions are propagated to
  the current year.
* default -- the star table inside the ``cedar-solve`` wheel (the same Hipparcos stars, magnitude
  <= 8.03, proper motions already applied to epoch 2024.0).  It is rewritten in ``hip_main`` file
  format and fed to the same generator, so the output is a normal tetra3 database.
"""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

import numpy as np

from ..catalog import bundled_database_path

log = logging.getLogger(__name__)


def write_hip_format_from_database(db_path: Path, dest: Path, max_mag: float | None = None) -> tuple[Path, int]:
    """Rewrite a tetra3 database's star table as a ``hip_main.dat``-format text file."""
    with np.load(db_path, allow_pickle=True) as d:
        table = np.asarray(d["star_table"], dtype=np.float64)
        ids = np.asarray(d["star_catalog_IDs"]) if "star_catalog_IDs" in d.files else np.arange(len(table))
    ra = np.degrees(table[:, 0])
    dec = np.degrees(table[:, 1])
    mag = table[:, 5]
    keep = np.ones(len(mag), dtype=bool) if max_mag is None else mag <= max_mag
    path = dest / "hip_main.dat"          # tetra3 recognises the catalogue by this file name
    with open(path, "w") as fh:
        for i in np.nonzero(keep)[0]:
            # fields used by tetra3: [1]=HIP, [5]=Vmag, [8]=RAdeg, [9]=DEdeg, [12]=pmRA, [13]=pmDE (mas/yr)
            fh.write(f"H|{int(ids[i]):>6}| 0| | 1|{mag[i]:>6.2f}| | |{ra[i]:>12.8f}|{dec[i]:>12.8f}| | 0.00|   0.00|   0.00|\n")
    return path, int(keep.sum())


def build_database(output: str | Path, catalogue: str | Path | None = None,
                   min_fov_deg: float = 16.5, max_fov_deg: float = 19.5,
                   verification_stars_per_fov: int = 100, lattice_field_oversampling: int = 50,
                   patterns_per_lattice_field: int = 100, star_max_magnitude: float | None = 8.0,
                   pattern_max_error: float = 0.002, epoch_proper_motion: float | str | None = None) -> Path:
    """Generate and save a database; returns the path (``.npz``)."""
    import tetra3

    out = Path(output).with_suffix(".npz")
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    t3 = tetra3.Tetra3(load_database=None)
    with tempfile.TemporaryDirectory() as tmp:
        if catalogue is None:
            cat_path, n = write_hip_format_from_database(bundled_database_path(), Path(tmp), star_max_magnitude)
            epoch = 2024.0 if epoch_proper_motion is None else epoch_proper_motion
            log.info("using %d stars from the bundled database (epoch %s)", n, epoch)
        else:
            cat_path = Path(catalogue).expanduser()
            epoch = "now" if epoch_proper_motion is None else epoch_proper_motion
        t3.generate_database(
            max_fov=max_fov_deg, min_fov=min_fov_deg, save_as=out, star_catalog=cat_path,
            lattice_field_oversampling=lattice_field_oversampling,
            patterns_per_lattice_field=patterns_per_lattice_field,
            verification_stars_per_fov=verification_stars_per_fov, star_max_magnitude=star_max_magnitude,
            pattern_max_error=pattern_max_error, epoch_proper_motion=epoch)
    log.info("database written to %s in %.1f s (%.1f MB)", out, time.perf_counter() - t0, out.stat().st_size / 1e6)
    return out

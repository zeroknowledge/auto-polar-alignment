import logging
import os
import warnings

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")      # must precede the first numpy import (test modules import numpy first)

import pytest

warnings.filterwarnings("ignore", message=".*dubious year.*")
logging.getLogger("tetra3.Tetra3").setLevel(logging.WARNING)


@pytest.fixture(scope="session")
def catalog():
    from polaralign.catalog import load_from_database
    return load_from_database()


@pytest.fixture(scope="session")
def solver():
    """One solver (database loaded once) shared by every test that needs it."""
    from polaralign.config import CameraConfig, SolverConfig
    from polaralign.solve import get_solver
    return get_solver(SolverConfig(), CameraConfig())


@pytest.fixture()
def cfg():
    from polaralign.config import sim_config
    return sim_config()

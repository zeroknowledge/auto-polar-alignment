"""polaralign - automatic polar-alignment base controller."""
import os

# The numeric work here is many small matrix products (3x3 rotations, a few thousand stars).  Multi-threaded
# BLAS costs far more in synchronisation than it saves: measured on the test suite, 4x less CPU time with one
# thread, same wall time -- and on a 4-core Pi Zero 2 W the spare cores belong to the motion and web threads.
# setdefault: set these yourself before importing polaralign to override.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

__version__ = "0.1.0"

"""Cameras: real (picamera2), file/function replay (fake) and the simulator's camera.

The camera layer is deliberately thin: anything that implements :class:`Camera` (``capture`` returning a 2-D array
plus ``meta["bayer"]``) can replace the Waveshare IMX296 board, which is listed as discontinued.  Register another
board with :func:`register_camera` and select it with ``camera.backend``.
"""
from __future__ import annotations

from collections.abc import Callable

from ..config import CameraConfig
from .base import Camera, Frame
from .bayer import flip_pattern, pattern_from_format
from .fake import FakeCamera

_BACKENDS: dict[str, Callable[[CameraConfig], Camera]] = {}


def register_camera(name: str, factory: Callable[[CameraConfig], Camera]) -> None:
    _BACKENDS[name] = factory


def _picamera2(cfg: CameraConfig) -> Camera:
    from .picam import Picamera2Camera
    return Picamera2Camera(cfg)


register_camera("picamera2", _picamera2)
register_camera("fake", lambda cfg: FakeCamera(cfg, bayer=cfg.bayer_pattern if cfg.colour else None))


def make_camera(cfg: CameraConfig) -> Camera:
    """Camera for ``cfg.backend``.  ("sim" cameras are created by :func:`polaralign.sim.build_sim_hardware`.)"""
    try:
        return _BACKENDS[cfg.backend](cfg)
    except KeyError:
        raise ValueError(f"unknown camera backend {cfg.backend!r}; known: {sorted(_BACKENDS)}") from None


__all__ = ["Camera", "Frame", "FakeCamera", "make_camera", "register_camera", "pattern_from_format", "flip_pattern"]

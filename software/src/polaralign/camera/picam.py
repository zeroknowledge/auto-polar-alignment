"""Raspberry Pi camera through picamera2 / libcamera (IMX296 global shutter, COLOUR: Waveshare SKU 32501).

The user's camera is the Waveshare IMX296 Global Camera (A): a colour sensor (Bayer mosaic) with an integrated
IR-cut filter, not a monochrome board.  The raw stream is therefore a Bayer mosaic; this module hands it to
the extractor untouched, with the tile pattern in ``Frame.meta["bayer"]`` (the extractor sums 2x2 cells for detection
and centroids the mosaic itself; see ``polaralign.extract``).  For a monochrome board set ``camera.colour = false``.

UNTESTED on real hardware: written against the picamera2 manual and the libcamera IMX296 driver
documentation, on a machine that has neither.  Things to check first on the Pi:

* ``/boot/firmware/config.txt`` has ``dtoverlay=imx296`` (colour; ``,mono`` is only for monochrome boards) and
  ``camera_auto_detect=0`` if the overlay is not picked up;  ``rpicam-hello --list-cameras`` must list the sensor.
* the raw format name: this code asks the sensor for its largest mode and uses that mode's *unpacked*
  format string (e.g. ``SBGGR10``), takes the Bayer pattern from it (falling back to ``camera.bayer_pattern``),
  and corrects it for any software flip.  Check the pattern against a coloured target.
* raw values are 10 bit in a 16-bit container; ``saturation_adu`` in the extractor config assumes that.

picamera2 is installed from apt (``python3-picamera2``); create the venv with
``--system-site-packages`` so it can be imported.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import numpy as np

from ..config import CameraConfig
from .base import Frame
from .bayer import flip_pattern, pattern_from_format

log = logging.getLogger(__name__)


class Picamera2Camera:
    name = "picamera2"

    def __init__(self, cfg: CameraConfig) -> None:
        from picamera2 import Picamera2  # type: ignore[import-not-found]

        self.cfg = cfg
        self._lock = threading.Lock()
        self._picam = Picamera2()
        mode = self._pick_mode()
        self._size = tuple(mode["size"])
        # Bayer pattern of the raw stream (None: monochrome board, or the ISP's already-debayered Y plane)
        self._pattern: str | None = None
        if cfg.use_raw and cfg.colour:
            self._pattern = pattern_from_format(str(mode.get("unpacked", ""))) or cfg.bayer_pattern
        if cfg.use_raw:
            config = self._picam.create_still_configuration(
                raw={"format": mode["unpacked"], "size": self._size}, main={"size": self._size, "format": "YUV420"},
                buffer_count=2, queue=False)
        else:
            config = self._picam.create_still_configuration(main={"size": self._size, "format": "YUV420"},
                                                            buffer_count=2, queue=False)
        self._picam.configure(config)
        self._picam.start()
        self._exposure = None
        self._gain = None
        self._apply(cfg.exposure_s, cfg.gain)

    def _pick_mode(self) -> dict:
        modes = self._picam.sensor_modes
        want = (self.cfg.width, self.cfg.height)
        for m in modes:
            if tuple(m["size"]) == want:
                return m
        return max(modes, key=lambda m: m["size"][0] * m["size"][1])

    def _apply(self, exposure_s: float, gain: float) -> None:
        if (exposure_s, gain) == (self._exposure, self._gain):
            return
        us = int(exposure_s * 1e6)
        self._picam.set_controls({
            "AeEnable": False, "AwbEnable": False, "ExposureTime": us, "AnalogueGain": float(gain),
            "FrameDurationLimits": (max(33333, us + 10000), max(33333, us + 10000)),
            "NoiseReductionMode": 0,
        })
        self._exposure, self._gain = exposure_s, gain
        for _ in range(max(1, self.cfg.discard_frames) + 1):   # let the new controls take effect
            self._picam.capture_metadata()

    def capture(self, exposure_s: float | None = None, gain: float | None = None) -> Frame:
        exposure_s = self.cfg.exposure_s if exposure_s is None else exposure_s
        gain = self.cfg.gain if gain is None else gain
        with self._lock:
            self._apply(exposure_s, gain)
            t0 = time.time()
            if self.cfg.use_raw:
                arr = self._picam.capture_array("raw")
                if arr.dtype == np.uint8:           # packed format came back: unpack is not supported here
                    raise RuntimeError("raw stream returned packed data; choose an unpacked sensor format")
                pixels = arr.view(np.uint16).reshape(arr.shape[0], -1)[:, : self._size[0]]
            else:
                yuv = self._picam.capture_array("main")
                pixels = yuv[: self._size[1], : self._size[0]]
            if self.cfg.flip_horizontal:
                pixels = pixels[:, ::-1]
            if self.cfg.flip_vertical:
                pixels = pixels[::-1, :]
            pattern = flip_pattern(self._pattern, self.cfg.flip_horizontal, self.cfg.flip_vertical)
            return Frame(np.ascontiguousarray(pixels), exposure_s, gain, datetime.now(timezone.utc),
                         {"capture_s": time.time() - t0, "bayer": pattern})

    def close(self) -> None:
        try:
            self._picam.stop()
            self._picam.close()
        except Exception:  # pragma: no cover
            pass

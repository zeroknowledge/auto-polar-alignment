"""Configuration: plain dataclasses, loaded from an optional TOML file.

Everything that is a hardware fact (pins, mechanics) or a tuning choice lives here so that
nothing is hard-coded in the control code.  Pin numbers are BCM GPIO numbers taken from
``hardware/pcb/netlist.json`` (carrier PCB rev A).
"""
from __future__ import annotations

import dataclasses
import math
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ARCSEC_PER_DEG = 3600.0


# --------------------------------------------------------------------------------------
# Camera / optics
# --------------------------------------------------------------------------------------
@dataclass
class CameraConfig:
    backend: str = "picamera2"        # "picamera2" | "fake" (synthetic static) | "sim" (simulator)
    width: int = 1456                 # IMX296
    height: int = 1088
    exposure_s: float = 1.0           # colour sensor + IR-cut filter: ~2-3x less starlight than mono, so 1 s by default
    gain: float = 8.0                 # analogue gain multiplier (libcamera AnalogueGain)
    # The user's camera is the Waveshare IMX296 Global Camera (A), SKU 32501: a COLOUR sensor with an integrated
    # IR-cut filter (not the monochrome board the first brief assumed).  Raw frames are a Bayer mosaic.
    colour: bool = True               # False for a monochrome board (then also dtoverlay=imx296,mono)
    bayer_pattern: str = "RGGB"       # used when the camera backend cannot tell (picamera2 reads it from the raw format)
    lens_focal_mm: float = 16.0
    pixel_um: float = 3.45
    flip_horizontal: bool = False     # the solver cannot solve a mirrored image: fix it here
    flip_vertical: bool = False
    use_raw: bool = True              # raw (linear) stream; False = ISP "Y" plane (8 bit, tone mapped)
    discard_frames: int = 1           # frames dropped after an exposure/gain change

    @property
    def focal_px(self) -> float:
        return self.lens_focal_mm * 1000.0 / self.pixel_um

    @property
    def fov_h_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.width / 2.0 / self.focal_px))

    @property
    def fov_v_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.height / 2.0 / self.focal_px))

    @property
    def arcsec_per_px(self) -> float:
        return math.degrees(1.0 / self.focal_px) * ARCSEC_PER_DEG


@dataclass
class ExtractorConfig:
    backend: str = "numpy"            # swappable: see polaralign.extract.get_extractor
    # How a Bayer mosaic is reduced for centroiding (detection always uses the colour-agnostic 2x2 cell sum):
    #   "all":   centroid from every pixel (default: measured on simulated colour frames, 0.156 px rms and ~0.005 px
    #            colour bias even for extreme star colours; per-channel sky levels are removed first)
    #   "green": centroid from the green pixels only (one colour band, so a red or blue star cannot pull the
    #            centroid at all; costs light: 0.190 px rms and a third fewer stars found in the same test)
    bayer_mode: str = "all"
    threshold_sigma: float = 5.0      # detection threshold on the 2x2-binned, background-subtracted image
    max_stars: int = 80               # keep the brightest N
    bayer_pattern: str = ""           # normally taken from each frame; set to force a mosaic pattern ("" = mono)
    border_px: int = 6                # ignore detections closer than this to the edge
    bin_factor: int = 2               # detection is done on a binned image, centroids at full resolution
    bg_block_px: int = 32             # background mesh cell size (full-resolution pixels)
    window_radius_px: int = 4         # centroid window is (2r+1)^2
    centroid_sigma_px: float = 1.6    # Gaussian weight width for the windowed centroid
    min_peak_ratio: float = 0.18      # reject hot pixels: (3x3 neighbours sum)/(peak) sharpness test
    saturation_adu: int = 1000        # stars with pixels above this are flagged saturated (10 bit)


@dataclass
class SolverConfig:
    backend: str = "tetra3"           # "tetra3" (Cedar Solve, Apache-2.0) | "astrometry" (solve-field)
    database: str = "auto"            # "auto" | "default" (bundled) | path to a .npz from `polaralign build-db`
    fov_max_error_deg: float = 1.0
    match_radius: float = 0.01
    match_threshold: float = 1e-5
    solve_timeout_ms: int = 4000
    max_stars: int = 40               # brightest N centroids passed to the solver
    min_stars: int = 6
    max_rmse_arcsec: float = 60.0     # reject solutions with a worse residual
    min_matches: int = 8
    distortion_range: tuple[float, float] = (-0.06, 0.06)
    refine: bool = True               # robust 2 px re-match + least-squares refit after the pattern match
    refine_max_stars: int = 80
    astrometry_binary: str = "solve-field"
    astrometry_timeout_s: float = 20.0


# --------------------------------------------------------------------------------------
# Motion
# --------------------------------------------------------------------------------------
@dataclass
class AxisConfig:
    name: str = "az"
    # --- pins (BCM) ---
    step_pin: int = 17
    dir_pin: int = 27
    enable_pin: int = 22              # active low; pulled high externally => disabled at boot
    endstop_min_pin: int = 5          # internal pull-up enabled
    endstop_max_pin: int = 6
    # hardware/README.md: switches are wired common + normally-closed, so a pressed OR broken switch reads HIGH
    # (= trip) and an idle one reads LOW.  Use 0 for normally-open switches that pull the pin to GND when pressed.
    endstop_trip_level: int = 1
    uart_address: int = 0             # TMC2209 MS1/MS2 strapping: AZ = 0, ALT = 1
    # --- mechanics ---
    arm_mm: float = 80.0              # tangent-arm length
    pitch_mm: float = 1.0             # screw pitch (M6x1)
    full_steps_per_rev: int = 200
    travel_deg: float = 6.0           # +/- working range about the centre (soft limits)
    end_stop_deg: float = 8.05        # centre -> end-stop trigger, each side (az 8.05; alt 7.35 / 7.15, hardware/README.md)
    invert_dir: bool = False          # flip if positive steps move the wrong way
    # Every move ends in this direction (+1 = increasing step count).  Which way the spring pulls depends on motor
    # wiring, so it is a setting; see preload_sky for the automatic way.
    preload_dir: int = +1
    # "clockwise": the azimuth spring pulls the plate clockwise seen from above, so finish moves turning the plate
    # clockwise.  Needs the site (to know east); the loop then sets preload_dir from the sky motion it learned.
    preload_sky: str = ""
    backlash_overshoot_deg: float = 0.12   # how far past the target to go before approaching in preload_dir
    mechanics_confirmed: bool = True  # False => UI warns that arm/pitch are placeholders
    # --- limits / homing ---
    home_speed_ratio: float = 0.40    # fraction of max speed used for homing
    home_backoff_deg: float = 0.25    # back off the end stop after homing (and the margin kept from a learned stop)
    endstop_debounce_ms: float = 20.0

    @property
    def deg_per_rev(self) -> float:
        return math.degrees(self.pitch_mm / self.arm_mm)

    @property
    def deg_per_full_step(self) -> float:
        return self.deg_per_rev / self.full_steps_per_rev

    @property
    def arcsec_per_full_step(self) -> float:
        return self.deg_per_full_step * ARCSEC_PER_DEG


@dataclass
class MotionConfig:
    gpiochip: int = 0                 # /dev/gpiochip0 on Pi Zero 2 W / Pi 4; check `gpiodetect` on a Pi 5
    uart_port: str = "/dev/ttyAMA0"   # needs dtoverlay=disable-bt and the serial console off
    uart_baud: int = 115200
    microsteps: int = 16
    run_current_a: float = 0.5        # RMS; doc says 0.4-0.6 A
    hold_current_a: float = 0.0       # irrelevant: the driver is disabled after each move
    rsense_ohm: float = 0.11          # BIGTREETECH TMC2209 modules; check yours
    stealthchop: bool = True
    max_speed_rev_s: float = 1.0      # screw revolutions per second
    accel_rev_s2: float = 2.0
    start_speed_rev_s: float = 0.1
    step_pulse_us: float = 4.0        # STEP high time (TMC2209 needs >= 0.1 us)
    dir_setup_us: float = 20.0
    enable_settle_ms: float = 20.0
    realtime: bool = True             # False: do not sleep between steps (simulation/tests)
    az: AxisConfig = field(default_factory=lambda: AxisConfig(preload_sky="clockwise"))
    alt: AxisConfig = field(default_factory=lambda: AxisConfig(
        name="alt", step_pin=23, dir_pin=24, enable_pin=25, endstop_min_pin=13, endstop_max_pin=19,
        uart_address=1,
        # hardware/README.md (altitude drive): M6x1 rod on a 150 mm tangent arm = 6.9 arcsec per full step; the
        # switches trigger at 7.35 / 7.15 deg.  Design values, not measured, hence mechanics_confirmed = False.
        arm_mm=150.0, pitch_mm=1.0, end_stop_deg=7.25, mechanics_confirmed=False,
    ))


# --------------------------------------------------------------------------------------
# Alignment loop
# --------------------------------------------------------------------------------------
@dataclass
class AlignConfig:
    target_arcmin: float = 3.0        # converged when the error is below this (0.05 deg)
    polish_arcmin: float = 1.0        # keep correcting (iterations permitting) until below this; 0 = stop at target
    max_iterations: int = 8
    gain: float = 0.8                 # fraction of the computed correction applied per iteration
    settle_s: float = 1.5             # vibration settle time after a move
    learn_jog_deg: float = 0.30       # jog size used to learn the step-to-sky matrix
    learn_backlash: bool = True
    broyden_update: bool = True       # refine the matrix from every correction move
    solve_retries: int = 3
    retry_exposure_factor: float = 1.6   # a failed solve is retried with this much more exposure (haze, thin cloud, faint sky)
    max_exposure_s: float = 4.0       # ... up to this
    refraction: str = "model"         # "model" | "off"   (see polaralign.astro.refraction)
    frames_per_measurement: int = 1
    max_start_error_deg: float = 15.0 # refuse to start if the axis is further than this from the pole
    sky_error_check_deg: float = 25.0


@dataclass
class SiteConfig:
    latitude_deg: float | None = None   # None => from GNSS / phone / hemisphere auto-detect
    longitude_deg: float | None = None  # east positive
    pressure_hpa: float = 1010.0
    temperature_c: float = 10.0


# --------------------------------------------------------------------------------------
# Sensors, web, plugins
# --------------------------------------------------------------------------------------
@dataclass
class SensorsConfig:
    i2c_bus: int = 1
    imu_enabled: bool = True
    imu_address: int = 0x68            # 0x69 if AD0 is high
    imu_rate_hz: float = 50.0
    imu_axis_in_sensor: tuple[float, float, float] = (0.0, 0.0, 1.0)  # polar axis in IMU frame
    knock_threshold_g: float = 0.06
    gnss_enabled: bool = True
    gnss_address: int = 0x42           # u-blox DDC


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    token: str | None = None           # optional shared secret for POST endpoints (X-Token header)


@dataclass
class SeestarConfig:
    """Phase 4: optional verification against a Seestar's own polar-alignment result.

    The Seestar's JSON-over-TCP interface is unofficial and has broken on firmware updates, so nothing
    here is on by default and the method/field names are configuration, not assumptions.
    """
    enabled: bool = False              # isolated optional plugin, off by default
    host: str = ""
    port: int = 4700
    polar_align_method: str = ""       # JSON-RPC method that returns the polar-alignment error; UNVERIFIED, set after probing
    result_alt_key: str = ""           # dotted path into the reply's "result", e.g. "alt_err"
    result_az_key: str = ""
    units: str = "arcmin"              # units of the reported errors: arcsec | arcmin | deg
    sign_alt: int = +1                 # +1 if a positive value means "axis too high"; -1 if opposite
    sign_az: int = +1                  # +1 if a positive value means "axis too far east"
    trim_weight: float = 0.5           # fraction of the reported residual fed back into the calibration
    timeout_s: float = 10.0


@dataclass
class Config:
    hardware: str = "pi"               # "pi" | "sim"
    state_dir: str = ""                # calibration + logs; default ~/.local/share/polaralign
    camera: CameraConfig = field(default_factory=CameraConfig)
    extractor: ExtractorConfig = field(default_factory=ExtractorConfig)
    solver: SolverConfig = field(default_factory=SolverConfig)
    motion: MotionConfig = field(default_factory=MotionConfig)
    align: AlignConfig = field(default_factory=AlignConfig)
    site: SiteConfig = field(default_factory=SiteConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    web: WebConfig = field(default_factory=WebConfig)
    seestar: SeestarConfig = field(default_factory=SeestarConfig)

    @property
    def state_path(self) -> Path:
        p = Path(self.state_dir) if self.state_dir else Path.home() / ".local" / "share" / "polaralign"
        return p


# --------------------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------------------
def _merge(obj: Any, data: dict[str, Any], path: str = "") -> None:
    names = {f.name: f for f in dataclasses.fields(obj)}
    for key, value in data.items():
        if key not in names:
            raise ValueError(f"unknown config key: {path}{key}")
        current = getattr(obj, key)
        if dataclasses.is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"config section {path}{key} must be a table")
            _merge(current, value, f"{path}{key}.")
        else:
            if isinstance(current, tuple) and isinstance(value, list):
                value = tuple(value)
            setattr(obj, key, value)


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load defaults, then overlay a TOML file (``path`` or $POLARALIGN_CONFIG if set)."""
    cfg = Config()
    if path is None:
        path = os.environ.get("POLARALIGN_CONFIG")
    if path:
        with open(path, "rb") as fh:
            _merge(cfg, tomllib.load(fh))
    return cfg


def sim_config() -> Config:
    """Configuration used by the simulator and the tests: no real-time sleeping."""
    cfg = Config(hardware="sim")
    cfg.camera.backend = "sim"
    cfg.motion.realtime = False
    cfg.align.settle_s = 0.0
    cfg.sensors.imu_enabled = False
    cfg.sensors.gnss_enabled = False
    return cfg

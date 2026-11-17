# Architecture

```
                         +-------------------- web UI (plain JS) --------------------+
                         |  Align | live error | jog | solve now | declare aligned    |
                         +---------------------------+--------------------------------+
                                                     | REST + SSE (FastAPI)
                                                +----v-----+
                                                | Runtime  |  one job at a time, location/time sources, events
                                                +----+-----+
        +----------------------+-------------------+-------------------+----------------------+
        |                      |                   |                   |                      |
  +-----v------+       +-------v-------+   +-------v--------+   +-----v------+        +------v-------+
  |  camera    |       |  AlignEngine  |   | MotionController|   | sensors    |        | calibration  |
  | picamera2  |       | learn matrix, |   | 2x StepperAxis  |   | IMU, GNSS  |        | JSON store   |
  | fake / sim |       | 80% correction|   | + TMC2209 UART  |   | knock      |        | a_cam, trims |
  +-----+------+       +-------+-------+   +-------+--------+   +------------+        +--------------+
        |   frame              | pole error        | STEP/DIR/EN (lgpio | FakeGPIO)
  +-----v------+       +-------v-------+           v
  | extractor  |       |  astro:       |   SimMount (backlash, lost steps, scale errors) <- only in the simulator
  | (numpy)    |       |  pole of date,|
  +-----+------+       |  refraction   |
        | stars        +-------^-------+
  +-----v------+               | rotation (celestial -> camera)
  |  solver    +---------------+
  | tetra3 +   |
  | robust refit|
  +------------+
```

## Packages (`src/polaralign/`)

| Package | Role |
|---|---|
| `astro/` | Time scales, IAU 2006 precession + nutation (pole of date), refraction (Saemundsson/Bennett), the target pole and the alt/east error basis, camera <-> physical-axis conversion. Pure numpy; cross-checked against ERFA in the tests. |
| `extract/` | `StarExtractor` protocol (2-D array + optional Bayer pattern), our numpy/scipy extractor (monochrome or Bayer mosaic), an adapter for tetra3's own centroider, backend registry. |
| `solve/` | `Solver` protocol; `TetraSolver` (Cedar Solve) + `refine.py` (robust 2 px re-match and least-squares refit); `astrometry.py` fallback; `database.py` builder. |
| `camera/` | `Camera` protocol (frame = 2-D array + `meta["bayer"]`) and a `register_camera` registry so another board can replace the discontinued Waveshare IMX296 colour module; `Picamera2Camera`; `FakeCamera` (files or a callable); Bayer helpers. |
| `motion/` | `GPIOBackend` (lgpio / fake), `tmc2209.py` (UART datagrams, CRC, configuration, fake bus), `stepper.py` (trapezoid step generation, soft/hard limits, homing, backlash/preload), `controller.py`. |
| `align/` | `pipeline.py` (capture -> extract -> solve), `engine.py` (the section 10.2 sequence). |
| `sensors/` | ICM-20948 + tilt + knock detection; u-blox DDC + NMEA parser. |
| `sim/` | Catalogue star-field renderer with a sensor noise model, camera model, physical mount model, sky truth chain, ready-made hardware set, scenario runner. |
| `plugins/seestar/` | Phase 4, optional and isolated. |
| `web/` | FastAPI app and static single-page UI. |
| top level | `config.py` (dataclasses + TOML), `runtime.py`, `calibration.py`, `catalog.py`, `clock.py`, `cli.py`, `selftest.py`, `bench.py`. |

## Conventions that are easy to get wrong

* **Pixel coordinates:** centre of the top-left pixel is (0, 0); `x` = column, `y` = row. tetra3 wants (0.5, 0.5) and (row, col);
  the solver wrapper converts. A half-pixel error would be 22 arcsec of systematic offset.
* **Camera frame** (tetra3's): x = boresight, y = image *left*, z = image *up*; `R_cam` maps celestial -> camera; the
  returned (RA, Dec, Roll) are turned back into `R_cam` with `rotation_from_radec_roll` (verified against a least-squares
  fit in `tests/test_solver.py`).
* **Frames of the pole:** everything is in J2000-labelled celestial coordinates, because that is what the solver reports.
  The target is the pole *of date* expressed in J2000 (0.150 deg = 542 arcsec away in November 2026, nutation included).
* **Error sign:** `error = axis - target` in the target's tangent plane, components (up, east); positive "up" means the axis is
  too high, positive "east" too far east (sky angle; the azimuth dial angle is that divided by cos(altitude)).
* **Motor positions** are integer microsteps from the *reference* end stop (the switch homing reaches first when driving in the negative
  direction, whichever connector it is wired to); the working range is +/-6 deg about the centre, the switches are 8.05 / ~7.3 deg out.
  `preload_dir` (every move finishes in it) is a setting, or for azimuth is read off the sky motion (the spring pulls clockwise from above).
* **End-stop level:** switches are normally-closed (hardware/README.md), so HIGH = tripped; `endstop_trip_level = 0` for normally-open.

## Refraction: what is done and why

The Earth's sky appears to rotate about the *apparent* pole (the true pole displaced toward the zenith by R(latitude),
2.1' at 25 deg, 0.8' at 50 deg). SharpCap's "refraction compensation" makes the same choice. The solver reports where the
*true* positions of the stars it saw are, so:

1. the camera boresight is un-refracted with its own R (the camera may look 25 deg away from the pole, at another altitude),
2. the axis direction found through the stored calibration is compared with the *apparent* pole.

`align.refraction = "off"` aligns to the true pole instead. Because the stored camera-to-axis calibration is recorded in
the same convention, the choice only matters when the base is used at a different latitude from where it was calibrated:
`tests/test_align_sim.py::test_refraction_model_matters_when_the_base_travels` calibrates at 10 deg latitude (R = 5.4') and
aligns at 55 deg (R = 0.7'): the model keeps the true error under 0.03 deg, "off" leaves more than 0.05 deg.
Needs latitude, longitude and UTC to a few minutes; without a site the aligner skips refraction and says so.
Neglected: aberration (<= 20.5"), differential refraction across the 18 deg field (absorbed by the solver's fit).

## The loop (design document 10.2) as implemented

1. first solve -> axis vs pole of date; refuse if more than `max_start_error_deg` (15 deg) away;
2. `_learn`: for each axis, condition the backlash, jog `learn_jog_deg` (0.3 deg), solve; reverse raw and solve again to
   measure backlash; build the 2x2 matrix M (arcsec of error per microstep). Checks magnitude vs the configured mechanics
   and conditioning (the two columns must not be nearly parallel);
3. iterate (<= `max_iterations`, 8): `ds = -gain * M^-1 e` (gain 0.8), clip to soft limits (and say so), az then alt, each
   finishing in the preload direction, EN released, settle 1.5 s, solve; update M with a damped Broyden step; stop on growth;
4. success when the measured error is below `target_arcmin` (3'); the loop keeps correcting while it is above
   `polish_arcmin` (1') and iterations remain;
5. always: motor current cut, residual measured *after* the last move and reported.

Failure messages are written for the user: dead motor, blind camera, ill-conditioned matrix, axis too far from the pole,
fine travel exhausted, error growing, cancelled.

## Simulator truth

`SimWorld.sky_to_enu` takes a J2000 star through annual aberration, ERFA's bias-precession-nutation (own model if ERFA is absent),
sidereal time, ERFA's refraction model (own Saemundsson if absent) to the horizontal frame, then through the mount pose to the
camera and the renderer. The aligner uses none of the aberration and a different refraction formula, so model error is real.
`true_axis_error_deg()` is the angle between the mount's physical axis and the apparent pole: the number tests assert on.

# polaralign: software for the automatic polar-alignment base

Controller software for the base in `../Auto_Polar_Alignment_Base_Design.docx`: a Raspberry Pi Zero 2 W with an IMX296
colour global-shutter camera (16 mm lens, about 17.8 x 13.4 deg) plate-solves the sky and drives two stepper screws
(azimuth and altitude, +/-6 deg) until the telescope's rotation axis points at the celestial pole. It works in both
hemispheres (no Polaris), runs on a laptop for development, and includes a simulator so the whole loop is testable
without hardware.

> **Status in one paragraph.** Everything below was developed and tested on a laptop against a simulator. **Nothing has
> run on a Pi, a camera, a TMC2209, a stepper or a telescope.** `docs/HARDWARE_UNTESTED.md` lists, component by component,
> what that means and how to find out on the bench; `polaralign selftest` automates the first power-up checks.

## What is in the box

| Doc phase | Delivered |
|---|---|
| 0 Bench solver | camera capture (picamera2, Bayer RAW10 from the colour IMX296), own star extractor (numpy/scipy, sub-pixel, Bayer-aware), Cedar Solve wrapper with a database sized for this lens, "Solve now" in the web UI and `polaralign solve` |
| 1 Motors + jog UI | step generation, TMC2209 UART setup (current, microsteps, StealthChop), homing, soft/hard limits, backlash handling, finish-in-preload moves, current cut after every move, jog buttons |
| 2 Closed loop + simulator | the section 10.2 sequence (learn the 2x2 step-to-sky matrix, 80 % corrections, settle, iterate to 3 arcmin, max 8), pole of date + refraction, calibration store, simulator with noise/backlash/lost steps |
| 3 IMU/GNSS | ICM-20948 tilt and knock detection, u-blox time/position over I2C, phone-browser fallback for time and position |
| 4 Seestar (optional) | isolated plugin that trims the calibration from the telescope's own residual; protocol details are unverified and left unconfigured |
| Deployment | NetworkManager hotspot with fallback to known Wi-Fi, systemd unit, boot config, install script |

Design choices you asked for: **no Cedar Detect** (Functional Source License) anywhere (the extractor is our own code behind
a swappable interface); Cedar Solve / tetra3 (Apache-2.0) for solving, astrometry.net as a documented fallback;
lgpio (not pigpio); FastAPI plus plain JavaScript with no build step; the Seestar is an optional isolated plugin.

## Quick start on a laptop (macOS / Linux, Python 3.11+)

```bash
cd software
python3.11 -m venv .venv                 # the virtualenv lives inside software/
.venv/bin/pip install -e ".[dev]"        # numpy<2 is enforced: cedar-solve 0.5.1 fails on numpy 2.x
.venv/bin/python -m pytest               # 180 tests, about 80 s (157 in about 15 s with -m "not slow")
.venv/bin/polaralign sim-align           # one simulated session: 5 deg error -> converged
.venv/bin/polaralign serve --sim         # web UI at http://localhost:8080 with a virtual base
.venv/bin/polaralign bench               # extractor benchmark on a 1456x1088 frame
```

In the simulated web UI use the "Simulator controls" card in this order: **Home** -> **Hand-align** -> **Declare aligned**
-> **Knock base 5 deg off** -> **Align**. (Declaring while the simulated base is *not* aligned makes the loop chase a wrong
pole; it then ends with a message instead of a fault, which is exactly what the tests check.)

Other commands: `polaralign solve | home | jog az 0.5 | calibrate | selftest | build-db`; `--config FILE` and `--state-dir DIR`
go before the sub-command (`polaralign --config my.toml serve`). All settings are in `config/polaralign.example.toml`.

## Setup on Raspberry Pi OS (Lite 64-bit, Bookworm, headless)

All of this is untested on a Pi; read each script before running it.

1. **Hardware wiring** per `hardware/pcb/` (carrier PCB). Before first power read `docs/PIN_MAP_REVIEW.md`
   (especially the TMC2209 module pin-order and 5 V I2C cautions).
2. **Boot configuration**: append `deploy/boot-config.txt.snippet` to `/boot/firmware/config.txt`. The important lines:
   `dtoverlay=imx296` (camera; **no `,mono`**: this is the colour board) and `dtoverlay=disable-bt` + `enable_uart=1` (puts the PL011 UART on GPIO14/15 as
   `/dev/ttyAMA0` for the TMC2209s). **Bluetooth must be disabled and the serial login console switched off**
   (`sudo raspi-config nonint do_serial_cons 1`, remove `console=serial0,115200` from `cmdline.txt`,
   `sudo systemctl disable --now hciuart serial-getty@ttyAMA0`). Reboot.
3. **Install**: `./deploy/setup_pi.sh`. It takes numpy/scipy/Pillow/picamera2/lgpio from apt, creates the venv with
   `--system-site-packages` (picamera2 is apt-only), installs `cedar-solve` with `--no-deps` (its pins, Pillow<9 and
   numpy<2, are stricter than it needs; Pillow<9 has no Python 3.11 wheels) and the remaining pure-Python packages from PyPI.
4. **Check the hardware**: `.venv/bin/polaralign selftest` (moves nothing; first with 12 V off, then on). Then the
   bench order in `docs/HARDWARE_UNTESTED.md` section 1: jog with the load disconnected, press each end stop, home.
5. **Mechanics and switches** (a TOML file, see `config/polaralign.example.toml`): the defaults follow `hardware/README.md` (azimuth
   M6x1 on 80 mm = 12.9"/full step; altitude M6x1 on a **150 mm** arm = 6.9"/full step; end stops at 8.05 deg / about 7.3 deg
   from the centre of the +/-6 deg working range; switches wired common + normally-closed, so **HIGH = tripped**
   (`endstop_trip_level = 0` for normally-open ones)). The altitude values are design figures, so the UI keeps warning until you set
   `motion.alt.mechanics_confirmed = true`. The loop learns the real step size by jogging, and `POST /api/home?measure_span=true`
   measures the true stop-to-stop travel. Homing watches **both** switches and works out which connector is at which end, so
   MIN/MAX wiring does not matter. The azimuth spring pulls clockwise seen from above: the loop finds out which sign of step
   count that is from the learned sky motion (needs a location); set `motion.alt.preload_dir` by hand for the altitude springs.
6. **Network**: `sudo ./deploy/setup_network.sh` creates the hotspot `PolarAlign` (192.168.4.1) with NetworkManager priority
   -100, so any known Wi-Fi in range wins and the hotspot is the fallback. Add known networks with `nmcli`.
7. **Run as a service**: copy `deploy/polaralign.service` to `/etc/systemd/system/`, adjust `User=`/paths, `enable --now`.
   Browse to `http://192.168.4.1:8080` (hotspot) or `http://polaralign.local:8080`.
   There is **no authentication** unless `web.token` is set: anyone on the hotspot can move the motors.
8. Run `polaralign bench` on the Pi and note the number (see "What could not be measured").

## Using it

1. **Rough set-up** (anything within a few degrees): set the coarse tilt to the latitude shown by the IMU readout, point the
   base roughly north (or south). Give the Pi a location and time: GNSS if fitted, otherwise **Use phone location & time**
   (Chrome/Safari refuse geolocation on plain-http pages; the UI then falls back to typed latitude/longitude and still
   takes the phone's clock).
2. **One-time calibration** (design doc 10.3): align by hand with the telescope's own polar-alignment routine until it
   reports the smallest error it can, then press **Declare aligned**. The base records where the telescope axis is in the
   camera's frame (a unit vector; roll about the axis is irrelevant). Repeat on two or three nights; entries are averaged and
   the scatter is shown. Keep the telescope seated the same way every time (keyed seat).
3. **Align**: one button. (The first session of a day should **Home** first, about 40 s worst case with both axes in parallel at 0.4 rev/s; the screws are self-locking, so the last position is remembered and homing is optional afterwards.) The base solves, jogs each axis to learn the step-to-sky matrix and the backlash, applies 80 % of
   the correction on both axes, cuts the motor current, waits 1.5 s, solves again, and repeats until the error is below
   3 arcmin (it keeps going to 1 arcmin if iterations remain), at most 8 times. The residual is measured *after* the last move.
4. Run the telescope's own alignment check to enable EQ mode.

## Camera: the colour IMX296 (Waveshare IMX296 Global Camera (A), SKU 32501)

The camera is a **colour** sensor (Bayer mosaic) with an **integrated IR-cut filter**, not a monochrome board. Consequences,
all handled in software but none verified on the real board:

* **Overlay:** `dtoverlay=imx296` (no `,mono`). Raw frames are Bayer RAW10, 1456 x 1088, 3.45 um pixels; picamera2's raw stream
  is requested and the tile pattern (`RGGB`, `BGGR`, ...) is read from the sensor-mode format name, falling back to
  `camera.bayer_pattern`, and corrected for any software flip (`flip_horizontal/vertical`).
* **Extractor:** the 2-D array goes straight in, with the pattern as an extra argument (`extract(image, bayer="RGGB")`).
  Detection sums 2x2 cells (the same for every pattern and independent of star colour). Centroiding removes the per-channel
  sky offsets and then uses every pixel (`extractor.bayer_mode = "all"`, default) or only the green ones (`"green"`).
  On simulated colour frames with random, even extreme star colours "all" gave 0.156 px rms with about 0.005 px (0.2 arcsec)
  of colour bias and found a third more stars than "green" (0.190 px rms); the bias cannot matter at the 3 arcmin level, and the
  camera-to-axis calibration absorbs any constant part. FWHM on a mosaic comes from the second moment (flux/peak is meaningless there).
* **Light:** the filter array and IR-cut cost roughly 2-3x of starlight. The simulator's colour model transmits 0.35 / 0.50 / 0.30
  (R / G / B, average 0.41 = 2.4x less than mono). So the default exposure is now **1.0 s** (was 0.5 s); `camera.exposure_s` and
  `camera.gain` are settings and can be changed live in the web UI. At 1 s the colour sensor finds about as many stars as the mono
  model did at 0.5 s (tested in `tests/test_bayer.py`). Whether that holds with the real lens and sky is a phase-0 question.
* **Replaceable:** Waveshare lists the board as discontinued. The camera layer is a small interface (`capture` -> 2-D array plus
  `meta["bayer"]`); another board, mono or colour, plugs in with `register_camera(name, factory)` and `camera.backend = name`
  (`camera.colour = false` for a mono board, with `dtoverlay=imx296,mono` if it is an IMX296).

## Measured results (laptop only; Apple M4 Max, Python 3.11, single-threaded numpy)

### Closed loop in the simulator

`scripts/sim_campaign.py` (output in `docs/sim_campaign_output.txt`): 64 simulated sessions across 8 sites in both
hemispheres (9 to 58 deg latitude, north and south), random initial errors of 4.0-5.5 deg in reachable directions, random motor
wiring directions, backlash 0.03-0.12 deg, screw scale errors up to 4 % / 12 %, lost-step bursts, 0.004 deg shift when the
motors release, camera 15-35 deg off-axis, sloppy hand alignment up to 0.03 deg, sky brightness and limiting magnitude varied,
annual aberration and an *independent* refraction model (ERFA) in the simulated sky. The simulated sensor is the **colour** IMX296:
a Bayer RGGB mosaic with random star colours, 2.4x less light than mono, 1 s exposures.

| Result | Value |
|---|---|
| Sessions converged (loop's own 3' criterion) | 64 / 64 |
| True error under 0.05 deg (measured against simulator ground truth) | 64 / 64 |
| Final true error | median 0.017 deg, 90th percentile 0.030 deg, max 0.039 deg |
| Iterations | 4 in 62 sessions, 5 in two (limit 8) |
| Solves per session | 12 (13 once) |
| Time per session | about 32 s of exposures + settling plus about 17 s of motor travel at 1 rev/s, so roughly 50-55 s (the doc's target is under 2 min). Homing is extra and only needed once (see below) |

Most of the 0.017 deg is the simulated *calibration* error (the hand alignment), which the loop cannot see; what the loop
itself adds is a few arcseconds. The tests also run the individual scenarios (`tests/test_align_sim.py`) including reversed
motor directions, a faint sky, near-equator and high-latitude sites, a dead motor, a blind camera, a cancel, a knock during a
measurement and an unreachable pole.

### Star extractor on a 1456 x 1088 frame (`polaralign bench`, `docs/bench_extractor_output.json`)

Synthetic frames of the **colour** sensor (Bayer RGGB, 1.0 s, random star colours) and, for comparison, a monochrome sensor (0.5 s):

| | colour, `bayer_mode = "all"` (default) | colour, `"green"` | monochrome |
|---|---|---|---|
| Time per frame, M4 Max core, median (min / p95 / max), 60 runs | **4.7 ms** (4.2 / 5.0 / 5.2) | 4.5 ms | 4.3 ms |
| Stages (median) | bin 0.6, background mesh 2.0, candidates 0.9, measurement 1.2 ms | | measurement 0.8 ms |
| Stars found (`max_stars` 200), median | 181 | 98 | 140 |
| Recall of catalogue stars brighter than mag 7.5 | 84 % | 60 % | 79 % |
| Centroid error vs. truth (all detections, faint included) | RMS 0.18 / 0.175 px (x / y), median 0.15 px | 0.16 / 0.18 px | 0.16 / 0.17 px |

No systematic half-pixel offset (tested). On simulated frames with extreme star colours the colour-induced centroid bias is about
0.005 px (0.2 arcsec). tetra3's own (Apache-2.0) centroider took 20.5 ms and found 35 stars on the monochrome frames (it has no mosaic support;
the adapter sums 2x2 cells first).

**What could not be measured:** the time on a real **Pi Zero 2 W**. A 1 GHz Cortex-A53 with slow LPDDR2 should be roughly
15-40x slower than an M4 Max core on this memory-bound numpy work, i.e. very roughly **70-180 ms** per frame: that is an
extrapolation, not a measurement. The design avoids full-resolution passes (it bins straight from uint16 and only touches
small windows at full resolution) precisely because of that, but the real number needs `polaralign bench` on the Pi. Also not
measured on a real sensor: detection performance on real star images (focus, coma, hot pixels, sky glow).

### Solver database (built from the star table in the cedar-solve wheel)

`polaralign build-db` builds a single-scale 16.5-19.5 deg database. 100 random simulated pointings (including the poles),
extractor frames from the **colour** sensor model at two sky qualities (about 60 and 39 stars at 1 s; "hard" is 4x fainter):

| Database | File | Patterns | Arrays | RSS | Solved (normal / hard sky) | Median solve | Boresight error |
|---|---|---|---|---|---|---|---|
| bundled `default_database` (10-30 deg, mag 8) | 8.1 MB | 712,068 | 15.3 MB | +17.9 MB | 100 / 94 | 5 ms | median 3.7", p99 10" |
| **shipped `data/polaralign_db.npz`** | 4.0 MB | 311,302 | 10.3 MB | +13.0 MB | 100 / 92 | 6 ms | median 3.7", p99 10" |
| single-scale, smaller (tried, not shipped; measured earlier on monochrome frames) | 2.0 MB | 112,426 | 4.4 MB | +6.2 MB | 97 / 97 | 6 ms | median 4.4", p99 11" |

In the "hard" colour case (about 20-30 stars at 1 s) a single frame fails to solve 6-8 % of the time; the loop then retries with
1.6x the exposure (up to 4 s), which restores the solve (simulated brightness sweep: sky 8x fainter than the default still solves at 2.6-4 s;
`tests/test_align_sim.py::test_faint_sky_is_handled_by_exposing_longer...`).

The whole `polaralign serve --sim` process measured 172 MB RSS idle and 229 MB after a full simulated session on macOS
(Linux/aarch64 unmeasured). Solve times are laptop times; the Pi's are unmeasured.

**Catalogue caveat.** You approved downloading `hip_main.dat` (51 MB) from CDS, but `cdsarc.u-strasbg.fr` and its alias
`cdsarc.cds.unistra.fr` timed out from the build machine on every scheme (other hosts, including PyPI and
`vizier.cds.unistra.fr`, answered). I did not substitute another source. The shipped database is therefore built from
the same Hipparcos stars (magnitude <= 8.03, proper motions applied to 2024.0) that ship inside the `cedar-solve` wheel.
To rebuild from the real catalogue: `polaralign build-db --catalogue /path/to/hip_main.dat`. Hipparcos data are free to use
with acknowledgement (ESA 1997); check the terms before shipping a derived database in a product.

## Decisions and findings that need your attention

1. **Pole of date.** The solver reports J2000; in November 2026 the pole of date is 539" (0.150 deg) away by precession alone
   (542" with nutation). The target is the pole of date (IAU 2006 precession, leading nutation terms), cross-checked
   against ERFA to < 0.001" (precession) and 0.2" (with the short nutation series) in `tests/test_astro.py`.
2. **Refraction (a choice, documented in `docs/ARCHITECTURE.md`).** By default (`align.refraction = "model"`) the axis is aligned to
   the *apparent* pole (the pole raised by R(latitude): 2.1' = 0.035 deg at 25 deg latitude), the point the refracted sky
   rotates about, and the camera boresight (which may look 25 deg away from the pole) is un-refracted with its own R.
   `"off"` aligns to the true pole. The stored calibration absorbs whichever convention the telescope's own routine uses
   *at the calibration site*; the model matters when a base calibrated at one latitude is used at another (simulated: calibrate at
   10 deg latitude, use at 55 deg: error < 0.03 deg with the model, > 0.05 deg without). It needs latitude, longitude and UTC
   to a few minutes; without a site, refraction is skipped and the UI says so.
3. **The camera-to-axis calibration is a stored rotation** recorded at "Declare aligned", averaged over nights, persisted
   atomically with a backup, and trimmable by a telescope residual (`plugins/seestar`).
4. **The azimuth stage moves the axis only cos(latitude) per degree of rotation** (usable +/-5.75 deg gives +/-5.2 deg of
   east-west reach at 25 N, +/-3.8 at 48 N, +/-2.7 at 62 N). The doc's "+/-6 deg absorbs a rough set-up" gets tight above
   ~45 deg latitude. The loop reports "fine travel exhausted" instead of hitting a stop; the scenarios in the tests choose
   directions that are reachable for that reason.
5. **Hard stops teach limits.** An end stop reached in normal travel is not a fault: the axis learns the real limit, backs off, and
   the loop ends with a message. (Found by driving the UI with a wrong calibration.)
6. **cedar-solve 0.5.1 breaks on numpy 2.x** (verified: solves return `None`); `pyproject.toml` pins `numpy<2` and the solver
   wrapper refuses to start on numpy >= 2 with a clear message. Its Pillow<9 pin is why `setup_pi.sh` uses `--no-deps`.
   Its bundled `tetra3-gen-db` CLI references an undefined argument and crashes; `polaralign build-db` calls the Python API.
7. **No pin-map error found** in `hardware/` (it was only read). Cautions are in `docs/PIN_MAP_REVIEW.md`.
8. **The camera is colour, not mono** (correction received during the work: Waveshare IMX296 Global Camera (A), SKU 32501, Bayer + IR-cut,
   discontinued). Handled end to end, see "Camera" above; `dtoverlay=imx296` without `,mono`.
9. **BLAS threads.** Multi-threaded BLAS made the test suite burn 18x the CPU time for the same wall time; `polaralign`
   sets `OPENBLAS_NUM_THREADS` etc. to 1 at import (override by setting them first).

## Tests

`pytest` runs 180 tests in about 80 s: astronomy vs ERFA, extractor accuracy and rejection, real tetra3 solves, TMC2209
datagrams against a fake bus, motion against fake GPIO, ICM-20948/NMEA/DDC, calibration persistence, the web API with a
simulated base, the Seestar plugin against a mock, the simulator's own physics, a cross-check of the software's pin
defaults against `hardware/pcb/netlist.json`, and the end-to-end alignment scenarios (marked `slow`, about 20 s; skip with
`-m "not slow"`). Two things the tests cannot be: evidence about real hardware, or evidence about the real sky.

## Licences

* **Cedar Solve / tetra3**: Apache-2.0 (ESA + Steven Rosenthal). **Cedar Detect is not used or imported**; the repository
  contains no code derived from it (the extractor is original; tetra3's own Apache-licensed centroider is only an optional comparison backend).
* **Hipparcos** star data (ESA 1997) inside the database: free with acknowledgement.
* pyerfa (BSD-3) is a test/simulator-truth dependency only (`.[dev]`), never needed on the Pi.
* `pyproject.toml` leaves the licence of polaralign itself as "all rights reserved" until you choose.

## Layout

```
software/
  src/polaralign/   astro/ extract/ solve/ camera/ motion/ align/ sensors/ sim/ plugins/seestar/ web/  + runtime, config, cli
  tests/            180 tests (see above)          scripts/sim_campaign.py   Monte-Carlo campaign
  config/           polaralign.example.toml        data/polaralign_db.npz    solver database for this lens
  deploy/           boot-config snippet, systemd unit, hotspot + install scripts
  docs/             ARCHITECTURE.md  HARDWARE_UNTESTED.md  PIN_MAP_REVIEW.md  benchmark and campaign output
```

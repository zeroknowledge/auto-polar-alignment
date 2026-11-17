# Auto Polar Aligner: Build Guide and User Manual

Nov 17, 2026

## Overview

The Auto Polar Aligner is a motorised base that points a Seestar S50's rotation axis at the celestial pole by itself: a small camera plate-solves the sky, and two stepper-driven fine screws nudge the telescope until the pole error is below 3 arcminutes (0.05°). This guide is the complete design as it stands today, written **before anything has been printed, built or run on real hardware**.

**How one alignment works**

1. You set the coarse tilt to your latitude and point the base roughly north (or south in the southern hemisphere), anywhere within a few degrees.
2. The camera takes a 1 s exposure and the Pi solves it into a sky position. A stored calibration rotation says where the telescope's axis sits in the camera's frame, so the software knows how far the axis is from the pole of date.
3. It jogs each axis a little to learn how many motor steps move the sky image, and how much backlash there is.
4. It applies 80 % of the correction on both axes, cuts the motor current, waits 1.5 s, solves again, and repeats until the error is under 3 arcminutes (at most 8 rounds).
5. You run the telescope's own alignment check and switch to equatorial mode.

In the simulator a session takes about 50 to 55 s and ends with a median true error of 0.017° (see Specifications for what that does and does not prove).

*The online version of this guide has a system block diagram here. For the electrical wiring, see `hardware/pcb/diagrams/system_wiring.png`.*

The camera and sensors feed the Pi, which solves the sky and steps the two motors until the pole error is under 3 arcminutes; the end stops keep the screws inside their travel.

**What is in the box**

| Part | What it does | Key detail |
| --- | --- | --- |
| Printed mechanics (17 STLs) | Spider and azimuth plate on a lazy Susan, tall-hinge tilt stage, camera cradle, electronics case, telescope seat | PETG, about 33.5 h and 854 g, sliced for a Bambu X1C |
| Two screw drives | Azimuth and altitude fine adjustment, ±6° each | NEMA 17 + M6×1 rod; 12.9″ per full step (azimuth), 6.9″ (altitude) |
| Carrier PCB | Plugs onto the Pi; holds both TMC2209 drivers, 12 V protection, end-stop inputs, sensor headers | 85 × 60 mm, 2 layers, KiCad files and Gerbers included |
| Raspberry Pi Zero 2 W | Runs the solver, the motion code and the web UI | Own hotspot, phone browser as the interface |
| Camera | Sees the stars | Waveshare IMX296 colour global-shutter, 16 mm lens, tilts 0 to 40° (board discontinued) |
| IMU and GNSS | Reads coarse tilt; supplies time and position | ICM-20948 (I²C); u-blox GNSS optional, phone fallback |
| `polaralign` software | Star extractor, plate solver, alignment loop, calibration store, web UI | Python; own extractor, no Cedar Detect; 180 tests pass on a laptop |

**Where to go next:** *Read this first* before you spend money; *Parts, tools, and measurements* before you print; then build in the order of the sections that follow. Skim *Field use* now if you only want to know what operating it looks like.

## Read this first

Treat this as a design package, not a proven product: every accuracy figure below is a simulation result or an engineering estimate, and nothing has been printed, soldered or run on a Raspberry Pi, a camera, a motor or a telescope. Expect to find problems at the first print, the first power-up and the first night under the sky, and budget time for them.

**What has been checked, and how**

| Area | Check | Result |
| --- | --- | --- |
| Printed parts | Watertight meshes, bed fit, sweep of the azimuth stage (±6°), sweep of the whole stack (latitude −10 to 75°, both fine axes, camera tilt 0 to 40°) | 17 STLs watertight; no collisions in 303 part pairs over 34 stack poses plus 32 camera poses |
| G-code | Bed bounds, temperatures, start and end macros (`verify_gcode.py`) | 20 files pass; whether your printer accepts raw `.gcode` is untested |
| Carrier PCB | `check_independent.py`, computed from the KiCad and Gerber files | 8 of 8 pass: pin map equals netlist, minimum clearance 0.291 mm, all 35 non-GND nets connected, drills match, Gerbers fit the outline |
| Software | 180 automated tests; Monte-Carlo campaign against a simulator | 64 of 64 simulated sessions ended under 0.05° (median 0.017°, maximum 0.039°) |
| Pin map | Software defaults compared with the PCB netlist and a standard Pi header table | No mismatch found |

**What has not been checked**

- **Strength, stiffness and fit.** Nobody has tried your lazy Susan, motor, bearings and nuts in these parts. The coupon (`00_fit_test`) exists to settle the hole sizes.
- **KiCad ERC and DRC.** The KiCad files have never been opened in KiCad. Run both and fill the zones before you order boards.
- **TMC2209 module pin order.** The netlist assumes PDN\_UART is module pin A4, taken from a generic BIGTREETECH page. Some modules differ.
- **Guessed dimensions.** The end-stop switch lever, the Seestar S50's socket depth, the lens front-element size and the M2.5 insert pocket are assumptions.
- **Telescope re-seating.** How far the camera-to-axis calibration shifts when you re-seat the telescope is unknown; the 0.05° per tick figure rests on an assumed 0.2° internal tilt.
- **Speed on the Pi.** The star extractor took 4.7 ms on an Apple M4 Max; 70 to 180 ms on the Pi Zero 2 W is an extrapolation.
- **Real skies.** The camera, lens, focus, sky glow and star counts have only been simulated, and the camera board is discontinued.
- **Prices.** The BOM figures are estimates, not live-checked quotes.

**Safety and damage-avoidance**

- **Verify the TMC2209 pin order before you plug both modules in.** If pin A4 is an output on your module, tying it to the shared UART line fights two push-pull outputs and can damage the drivers.
- **Remove jumper JP1 whenever the Pi is powered over its own USB port.** The Pi Zero has no back-feed protection.
- **Power the IMU and GNSS from 3V3 (pin 2), not 5 V,** unless the breakout level-shifts. The Pi's GPIO is not 5 V tolerant.
- **Be ready to cut power the first time the motors home.** The screws are driven by a Python step loop that has never met a real end stop. The jackscrew's own hard limit is about 9°, and the switches trip at 7.15 to 8.05°.
- **Check the stud length before the first mount.** The stud stands above the seat disc by the bolt length minus 11 mm; it must be at least 2 mm shorter than the S50's socket is deep, or the telescope sits tilted.
- **Tighten the coarse lock with a wrench.** The tilt lock is friction only. Test it with a dead weight (a bag of sand or a brick near 2.5 kg, taped on) before the telescope goes on.
- **Open Wi-Fi, no password.** Unless you set `web.token`, anyone on the hotspot can move the motors.
- **Keep the electronics case dry.** Its cable slots are open, so it is not weatherproof.
- **Printed PETG creeps under load.** Inspect the motor face plate and the lock bolt area after the first few sessions.

## Specifications

The design aims for a pole error under 0.1° for a Seestar S50 carried on a base that works from latitude 0 to 65° in both hemispheres. The "Basis" column says how far to trust each line: *design* is what the drawings and constants say, *simulated* came out of the laptop simulator, *estimate* is my reasoning without a measurement.

| Quantity | Value | Basis |
| --- | --- | --- |
| Pole error target | under 0.1° overall; the loop stops at 3 arcmin (0.05°) and continues to 1 arcmin if rounds remain | design |
| Error after alignment | median 0.017°, 90th percentile 0.030°, maximum 0.039° over 64 sessions | simulated |
| Time per alignment | about 50 to 55 s; first-time homing adds up to about 40 s | simulated |
| Rounds per alignment | 4 typical, 8 at most | simulated |
| Coarse tilt (manual) | lock arc covers plate tilt 15 to 100°, i.e. latitude −10 to 75°; plate tilt = 90° − latitude | design |
| Fine travel, each axis | ±6° (soft limits ±5.75°) | design |
| Azimuth drive | M6×1 rod on an 80 mm arm; 12.9″ per full step; 0.716° per rod turn | design |
| Altitude drive | M6×1 rod on a 150 mm arm; 6.9″ per full step; ±15.8 mm of rod travel for ±6° | design |
| Azimuth reach on the sky | ±5.2° at 25° latitude, ±3.8° at 48°, ±2.7° at 62° (shrinks with cos(latitude)) | design |
| End-stop triggers | azimuth 8.05°; altitude 7.35° and 7.15° from the centre of travel | design, lever geometry assumed |
| Camera | 1456 × 1088 px, 3.45 µm pixels, 16 mm lens, about 17.8 × 13.4° field, 1.0 s default exposure (a design choice) | catalogue |
| Camera tilt | 0 to 40° usable (slots allow −5 to 50°) | design |
| Telescope | Seestar S50 on a 3/8-16 UNC stud, assumed 2.5 kg | design |
| Mass on the tripod head | about 3.8 kg all-in, with a 2.5 kg telescope and a 450 g electronics case | estimate |
| Printed parts | 17 parts, about 33.5 h and 854 g of PETG on a Bambu X1C (256 mm bed) | sliced |
| Electronics case | 139.4 × 81.8 × 42.7 mm, hangs under the main tilt plate | design |
| Carrier PCB | 85 × 60 mm, 2 layers, 1.6 mm FR4 | design |
| Power | 12 V from a USB-C PD power bank, 5 V from a buck module; PTC fuses 2 A hold on each rail | design |
| Solver database | 16.5 to 19.5° patterns, 4.0 MB, Hipparcos to magnitude 8 | built on laptop |
| Parts cost | $419.29 in all; $390.29 for phases 0 to 2; the budget was $300 | estimate, prices not live-checked |

**Centre of gravity.** The tilt stage must not tip the tripod. With the 2.5 kg telescope and the case, the combined centre of gravity measured from the bearing axis (positive toward the pole) moves with latitude:

| Latitude | CoG toward pole | CoG height |
| --- | --: | --: |
| 0° | +86 mm | 178 mm |
| 25° | +34 mm | 212 mm |
| 45° | −14 mm | 221 mm |
| 65° | −63 mm | 213 mm |

The case hangs on the side away from the pole and pulls the centre back by 20 to 30 mm. Point one tripod leg at the pole and spread the legs fully.

## Parts, tools and measurements

The full build costs an estimated $419.29 against the original $300 budget, with the USB-C PD power bank you already own excluded; $390.29 of that is everything except the IMU and GNSS. Prices are indicative and were not checked against live listings. Check that the Waveshare camera is still available before you buy anything else, because a different board needs a new camera plate.

### Bill of materials

| ID | Item | Qty | Est. USD | Note |
| --- | --- | --: | --: | --- |
| B01 | Raspberry Pi Zero 2 W, pre-soldered header | 1 | 18.00 | The WH variant saves soldering the 40-pin header |
| B02 | microSD 32 GB, A1/A2 | 1 | 8.00 | Raspberry Pi OS Lite 64-bit |
| B03 | Waveshare IMX296 Global Camera (A), SKU 32501 | 1 | 82.99 | Colour, IR-cut, discontinued; includes CSI cables and a C-CS adapter, no lens |
| B04 | CSI ribbon, 22-pin to 15-pin | 1 | 0.00 | Included with B03; the Zero has the small 22-pin port |
| B05 | 16 mm C-mount lens (39 × 50 mm, 134 g) | 1 | 22.00 | Cradle and dew shield are sized for it; price is my guess |
| B06 | NEMA 17 pancake stepper, 20 to 25 mm body | 2 | 26.00 | 5 mm D-shaft, up to 1 A per phase; run at 0.4 to 0.6 A |
| B07 | TMC2209 driver module, SilentStepStick format | 2 | 11.00 | Must expose MS1 and MS2; confirm pin order (see Read this first) |
| B08 | Micro limit switch with roller lever, KW12-3 class | 5 | 5.00 | Four used, one spare; confirm 20 × 10.5 × 6.5 mm body and 9.5 mm hole spacing |
| B09 | M2 × 8 self-tapping screws | 1 | 1.50 | Eight hold the four switches |
| B10 | Flexible shaft coupler, 5 mm to 6 mm | 2 | 5.00 | Absorbs the ±6° swing of the screw |
| B11 | M6×1 stainless threaded rod, 1 m | 1 | 7.00 | Do not substitute T8 lead screws; they back-drive |
| B12 | Brass hex nut M6, pack of 10 | 1 | 3.00 | Held in the printed trunnions |
| B13 | Extension springs, assorted pack | 1 | 8.00 | Altitude: two for about 74 mm between hooks. Azimuth: one near 25 mm free length, 0.3 N/mm |
| B14 | 608ZZ bearing, pack of 10 | 1 | 6.00 | Hinge pins and screw-end support |
| B15 | 8 mm ground steel rod, 300 mm | 1 | 6.00 | Cut one 124 mm and one 140 mm hinge pin; chamfer the ends |
| B16 | 6 in aluminium lazy-Susan bearing | 1 | 12.00 | The azimuth stage; measure its axial wobble |
| B17 | 3/8-16 × 3/4 in hex bolt (the telescope stud) | 2 | 4.00 | One spare; add a 1 in bolt if the S50 socket is deeper than 14 mm |
| B18 | 3/8-16 hex nut, standard thickness | 2 | 4.00 | About 8.3 mm thick; not a coupling nut |
| B19 | 3/8-16 to 1/4-20 reducer bushing | 2 | 5.00 | For photo tripods |
| B20 | Heat-set inserts, M3/M4/M5/M6 assortment | 1 | 12.00 | Brass |
| B21 | Fastener assortment, M3 to M6, washers, nuts, 3 mm dowel pins | 1 | 15.00 | Stainless for outdoor use |
| B22 | Wing nut or star knob, M6 | 2 | 3.00 | Coarse-tilt lock |
| B23 | PETG filament, 1 kg | 2 | 40.00 | 854 g for all parts; the second spool covers reprints. No PLA (it creeps) |
| B24 | Adhesive felt feet and black flocking paper | 1 | 5.00 | Feet and dew-shield lining |
| B25 | M2.5 heat-set inserts and M2.5 × 8 screws | 1 | 5.00 | Four of each hold the camera board |
| B26 | Cable ties, 2.5 × 100 mm | 1 | 2.50 | Hold the PD trigger and buck module in the case |
| B27 | M6 × 130 mm bolt and nut | 1 | 2.50 | The coarse tilt lock |
| B28 | USB-C PD trigger board, 12 V | 1 | 4.00 | Check your power bank really offers 12 V |
| B29 | 12 V to 5 V buck converter, 3 A, low noise | 1 | 8.00 | Pololu D24V22F5 class |
| B30 | 24 AWG silicone wire, ferrules, heat shrink | 1 | 6.00 | Motor, end-stop and power harness |
| B31 | ICM-20948 IMU breakout (I²C) | 1 | 15.00 | Coarse tilt and knock detection |
| B32 | u-blox M8/M9 GNSS breakout with I²C pins and antenna | 1 | 14.00 | Many cheap boards are UART-only and the Zero has no spare UART |
| B33 | Carrier PCB, 2 layers, 5 pcs | 1 | 23.00 | Upload `pcb/fab/carrier_gerbers.zip`; shipping dominates |
| B34 | Screw terminal 5.08 mm, 2-pin | 3 | 2.10 | 12 V in, 12 V to buck, 5 V from buck |
| B35 | JST-XH kit with crimp pins, 2-pin and 4-pin | 1 | 9.00 | Two 4-pin for motors, four 2-pin for end stops |
| B36 | 2.54 mm headers: 2×20 female, 4× 1×8 female, 2× 1×5, 1× 1×2 and jumper | 1 | 5.00 | Pi socket, driver sockets, sensor headers, JP1 |
| B37 | PTC fuse, 2 A hold, radial, 5.08 mm pitch, 30 V or more | 2 | 2.00 | One per rail; a 16 V part is too low on the 12 V rail |
| B38 | 1N5822 Schottky and 1.5KE18A TVS | 1 | 1.20 | Reverse-polarity and surge protection |
| B39 | Electrolytics: 220 µF/35 V and two 100 µF/35 V | 1 | 2.50 | Bulk capacitance at the input and each driver |
| B40 | 0805 assortment: 100 nF, 1 k, 10 k, red LED | 1 | 8.00 | Six capacitors, seven resistors, one LED |

By category: Compute $26.00, Camera $104.99, Motion $66.50, Structure $122.00, Power $18.00, Sensors $29.00, PCB $52.80. A perfboard instead of the PCB saves about $39 but drops the reverse-polarity protection and the end-stop filters unless you hand-wire them. Using fasteners, inserts and filament you already own saves up to $72, and an IMX462-class camera would save about $57 at the cost of a new camera plate; together those two bring the full build to about $290.

### Tools

- A 3D printer with a bed of at least 256 mm that can print PETG, ideally enclosed (the parts were sliced for a Bambu X1C), and OrcaSlicer or Bambu Studio.
- Digital calipers, ideally with a depth rod.
- A soldering iron with fine tip (heat-set inserts, through-hole parts, hand-soldered 0805 passives), a crimper for JST-XH, a multimeter.
- A hacksaw or rod cutter for the M6 rod and the 8 mm pins, a file, hex keys and a wrench for the M6 lock bolt.
- A laptop with Python 3.11 for CAD and the simulator; KiCad 8 to run ERC and DRC on the carrier PCB.

### Measure before you print

The spider and azimuth plate assume dimensions that could not be looked up. Edit the named constant in `hardware/cad/aligner_cad.py` (or `aligner_cad2.py`) if yours differ, regenerate, and re-slice.

| What | Assumed | Where it matters |
| --- | --- | --- |
| Lazy-Susan thickness (`LS_H`) | 12 mm | Spider and azimuth plate |
| Lazy-Susan bolt holes (`LS_SLOT`) | between r = 34 and 62 mm on the ±x and ±y axes | Slots must cover your pattern |
| NEMA 17 | 42.3 mm square, 31 mm hole spacing, 22.6 mm boss hole | Motor face plates |
| 3/8-16 nut | 14.3 mm across flats, 8.3 mm thick | Spider nut pocket |
| S50 socket depth | not published | Stud length rule: stand-up (bolt length − 11 mm) at least 2 mm less than the depth |
| End-stop switch | body 20 × 10.5 × 6.5 mm, 9.5 mm hole spacing, roller 14 mm past the body end and 3 mm off its face | Switch mounts and trigger angles |
| Lens front element | 30 mm assumed | Dew-shield bore of 41 mm and 25 mm length |
| M2.5 insert pocket | 3.6 × 4.5 mm | Camera plate; add it to the coupon to be sure |
| TMC2209 module | Pololu footprint, rows 12.70 mm apart, PDN\_UART on pin A4 | Carrier PCB sockets |
| PD power bank | offers 12 V | PD trigger board |

## Printing guide

Print the fit-test coupon first, correct the hole-size constants from it, then print the small parts, then the big plates: all 17 parts take about 33.5 h and 854 g of PETG. STLs are in print orientation in `hardware/stl/` and sliced G-code is in `hardware/gcode/`.

### Settings baked into the G-code

| Setting | Value |
| --- | --- |
| Printer and nozzle | Bambu Lab X1C, 0.4 mm |
| Filament | Bambu PETG Basic, 255 °C nozzle, 70 °C bed |
| Plate | Textured PEI (the profile does not allow Cool plate for PETG) |
| Layers and walls | 0.20 mm layers, 4 walls |
| Infill and supports | 30 % gyroid, no supports (the motor boss hole is a teardrop) |
| Brim | as the OrcaSlicer 2.5.0 X1C profile decides |
| Coupon only | 2 walls, 8 % infill, no brim |

- **Raw `.gcode` on a Bambu printer is untested.** Bambu printers normally take `.gcode.3mf` from Bambu Studio or OrcaSlicer. If yours refuses the files, open the STLs in Bambu Studio and apply the settings above.
- **Engineering plate:** change `curr_bed_type` in `slicer/profiles/*.json` and re-slice.
- **Brim at the bed edge:** on the tilt plate (X = 0.2 to 255.8 mm) and the spider (2.8 to 253.2 mm) the first-layer brim reaches the printable edge. If your printer objects, set `brim_type` to `no_brim` in `slicer/profiles/process.json` and re-slice.
- **Print in PETG, not PLA.** PLA creeps under a constant load.

### Step 1: print and read the fit-test coupon

`00_fit_test` takes about 48 min. Each row has three sizes, smallest on the left. Push the real part into each pocket and pick the smallest that it enters with a gentle push.

| Row | Left to right | Constant to edit in `cad/aligner_cad.py` |
| --- | --- | --- |
| 1 | M6 brass nut (three pockets), then the 8 mm hinge pin | `M6_NUT_AF` |
| 2 | 608 bearing | (check against the bearing seat) |
| 3 | 3/8-16 nut, 3 mm dowel pins, M3 heat-set insert | `HEX38_AF`, `DOWEL_PRESS`, `DOWEL_FREE`, `M3_INSERT` |

Then regenerate and re-slice:

```bash
cd hardware
python cad/aligner_cad2.py stl        # all STLs (batches 1 and 2a)
python cad/aligner_case.py stl        # electronics case and lid
python cad/aligner_cam.py stl         # camera cradle, plate and dew shield
./slicer/slice_all.sh                 # G-code; needs OrcaSlicer installed
python slicer/verify_gcode.py gcode/*.gcode
```

The CAD scripts need `manifold3d`, `numpy` and `trimesh`.

### Step 2: print in this order

Smaller parts first, so you learn how your printer and parts fit before committing to the 4 to 6 hour plates. Times and masses come from the slicer's own statistics.

| # | File | Time (h) | PETG (g) | Notes |
| --: | --- | --: | --: | --- |
| 1 | `00_fit_test` | 0.80 | 27.9 | Coupon; do this first |
| 2 | `01_nut_trunnion_x3` | 0.57 | 12.8 | Three trunnions; two used, one spare |
| 3 | `04_az_cap` | 0.15 | 3.2 |  |
| 4 | `03_az_plate` | 2.95 | 74.7 | Revised: six M4 holes for the coarse cheeks, end-stop tab, preload post |
| 5 | `02_base_spider` | 5.85 | 145.6 | 216 mm wide; azimuth end-stop extension; preload peg block |
| 6 | `05_coarse_cheek_x2` | 2.07 | 55.3 | Two cheeks |
| 7 | `08_alt_cheek_x2` | 1.16 | 30.6 | Two cheeks |
| 8 | `07_tilt_plate_2` | 1.81 | 49.8 | Motor beam; longer, with a wing for the end-stop tower |
| 9 | `06_tilt_plate_1` | 4.22 | 115.6 | Gained four screw holes for the electronics case; use the current file |
| 10 | `09_top_plate` | 4.68 | 124.8 | Printed upside down; 10 mm longer, four cradle inserts, end-stop ear, two dowel holes |
| 11 | `10_electronics_case` | 2.73 | 85.6 |  |
| 12 | `11_case_lid` | 0.80 | 28.9 |  |
| 13 | `12_cam_cradle` | 1.50 | 32.6 |  |
| 14 | `13_cam_plate` | 0.24 | 5.7 |  |
| 15 | `14_dew_shield` | 1.00 | 17.5 |  |
| 16 | `15_alt_endstop_tower` | 2.27 | 24.3 | 123 mm tall, printed standing; has a brim; watch the first hour |
| 17 | `16_telescope_seat` | 0.66 | 19.1 | Engraved face on the bed |

Single-part G-code (`01_nut_trunnion`, `05_coarse_cheek`, `08_alt_cheek`) is also in the folder for reprints.

**Parts changed after the first slices.** If you printed any earlier version, reprint `02_base_spider`, `03_az_plate`, `06_tilt_plate_1`, `07_tilt_plate_2` and `09_top_plate`; the files in the folder are current.

### What to check after each print

- **Trunnions, spider, azimuth plate:** the M6 nut and the 3/8-16 nut should enter their pockets with a gentle push, and the dowel pins should press in.
- **Motor face plates:** the layer lines run across the plate, and the lead screw loads it in bending. A rough estimate gives a few MPa against roughly 20 MPa typical layer adhesion with the gussets, but that is not a calculation of record: look for cracks along the layers after the first run.
- **Telescope seat:** lay a straightedge across the seat face; it should be as flat as your bed. An aluminium disc of the same drilling would be flatter.

## Mechanical assembly

Build from the bottom up, in five stages, and move each stage by hand through its full travel before you add the next. **This sequence is derived from the CAD models and their hole patterns. Nobody has carried it out on real parts.** If a step does not work on your parts, trust the part and edit the model rather than forcing it.

The frame used below: *x* points toward the pole, *z* is up, and the origin sits on the bearing axis at the bottom of the spider.

### 0. Prepare the parts

1. **Heat-set inserts.** Press them in with a soldering iron, straight and flush: M4 in the base and top edge of each coarse cheek and each altitude cheek, M4 in the motor beam (lap joint), M3 in the azimuth plate (cap posts and spring screw), M3 in the spider (three spring pegs), M3 in the top plate (cradle and spring anchors) and the motor beam (spring anchors), plus those in the case and camera plate.
2. **Trunnions.** Press a brass M6 nut into the hex pocket of each trunnion (two are used, one spare). Press a 3 mm dowel into each side hole; the dowels turn freely in the yoke holes.
3. **Hinge pins.** Cut the 8 mm ground rod to 124 mm (coarse hinge) and 140 mm (altitude hinge) and chamfer the ends.
4. **Rods.** Cut the M6 rods only when you reach each drive: stage 1 step 5 (azimuth) and stage 3 step 3 (altitude).

### 1. Azimuth stage

1. **Drop the 3/8-16 nut into the hub pocket** of `02_base_spider`. Do not rely on a printed thread.
2. **Fit the coarse cheeks to the azimuth plate before the plate goes on the bearing.** The six M4 screws (three per cheek) come up from beneath the plate into the cheek inserts, with their heads in 8.4 mm counterbores that are 3.5 mm deep. A socket-head M4 is about 4 mm tall, so use button-head or low-head screws, and check they clear the lazy Susan's top surface.
3. **Bolt the lazy Susan** to the spider through the four M4 slots (heads flush with the underside, so the base sits flat on the tripod head), then bolt the azimuth plate to its top ring through its four counterbored slots. The slots cover radii of 34 to 62 mm on the ±x and ±y axes; if your bolt pattern is different, measure and edit `LS_SLOT` first.
4. **Mount the azimuth motor** on the spider's face plate (four M3, 31 mm pattern, boss in the 22.6 mm hole). The rod runs along *y* at x = 80 mm, tangent to the bearing, entirely outside the 75 mm plate disc.
5. **Build the rod:** 5 to 6 mm flexible coupler on the motor shaft, M6 rod into the coupler and through the brass nut. Cut the rod so it reaches the nut with room for ±8.4 mm of travel (80 mm × tan 6°) plus the coupler.
6. **Seat the trunnion in the yoke:** lower dowel into the azimuth plate's pivot hole, the rod through the nut, then close the yoke with `04_az_cap` using two M3 screws. The cap holds the upper dowel; the block pivots about a vertical axis with 0.3 to 0.5 mm of clearance.
7. **Fit the preload spring** (see below) and the two azimuth end-stop switches (see Electronics).
8. **Check by hand** that the plate turns freely from −6° to +6° and that nothing rubs. Designed minimum gaps are 2.9 mm (spider to plate), 7.0 mm (motor and rod to plate) and 0.5 mm (trunnion block to yoke).

**Azimuth preload spring.** Screw an M3 screw with a washer into the insert on the plate's rim tab, hook the spring on it, and hook the other end on one of the three M3 pegs (x = 14, 22 or 30 mm) on the spider's +y arm. The spring pulls the plate clockwise seen from above. Pick the peg with your spring's figures:

```bash
python cad/check_preload.py 25 0.3 0.7    # free length mm, rate N/mm, initial tension N
```

A 25 mm spring at 0.3 N/mm and 0.7 N works on the middle peg (3 to 8.5 N, 0.27 to 0.72 N·m over the travel); a 32 mm, 0.2 N/mm spring wants the outer peg; avoid springs stiffer than about 0.4 N/mm. The script's 0.10 N·m minimum torque is an estimate, not a measurement.

### 2. Coarse tilt stage

1. **Join the two tilt plates.** Lap `07_tilt_plate_2` (the motor beam) under the end of `06_tilt_plate_1` with four M4 screws into the beam's inserts.
2. **Fit a 608 bearing** into the pocket on the outer face of each tilt-plate arm (22.15 mm bore, 7 mm deep).
3. **Hang the plate in the cheeks.** The arms sit between the cheeks, which hold the hinge axis 56 mm above the azimuth plate (86 mm above the bottom of the spider, at x = −20 mm). Pass the 124 mm pin through cheek, bearing, arm, arm, bearing and cheek, and clamp it with an M4 set screw in the top edge of each cheek.
4. **Fit the lock bolt:** the M6 × 130 mm bolt goes through both cheeks' arc slots and both arms' holes at a radius of 40 mm from the hinge, with the wing nut or star knob on the end. The slots cover plate tilts of 15 to 100°, which is latitude 75° down to −10° (plate tilt = 90° − latitude).
5. **Test the lock.** Set the plate at 65° (latitude 25°), tighten with a wrench, and push on the plate; it must not creep. The lock is friction only.

### 3. Altitude stage and top plate

1. **Bolt the altitude cheeks** to the top of the tilt plate with four M4 screws (two per cheek, from beneath into inserts in the cheek bases), 54 mm above the plate.
2. **Fit 608 bearings** into the top plate's lug pockets and set `09_top_plate` on the cheeks. It was printed upside down so its seat face is smooth. Pass the 140 mm pin through, and clamp it with the cheeks' M4 set screws.
3. **Mount the altitude motor** under the motor beam, shaft up, at 150 mm from the hinge (four M3 screws). Add the coupler, rod and trunnion. The trunnion's dowels go into the holes in the two yoke tabs on the top plate; flex the tabs only gently, and print a spare if one cracks. Cut the rod so its top stands about 10 mm above the top plate at mid travel (28 mm at the low end of the travel).
4. **Hook the two altitude springs** between the M3 anchors on the beam and on the top plate, about 74 mm apart. Choose springs that suit that length.
5. **Bolt on the end-stop tower** (`15_alt_endstop_tower`) to the beam's wing with four M4 bolts and nuts, then fit the two switches.
6. **Check by hand** that the top plate rocks ±6° smoothly with the rod engaged, at three coarse tilts.

### 4. Telescope seat

1. Push the **3/8-16 bolt head** into the hex pocket under the top plate, shaft up through the 9.8 mm hole. The stud stands (bolt length − 11 mm) above the disc; for the 19 mm bolt that is 8 mm.
2. **Measure the S50's socket depth** with calipers. The stand-up must be at least 2 mm less. If the socket is shallower than about 10 mm, shorten the bolt rather than let the telescope bottom out and sit tilted.
3. Press **two 3 × 8 mm dowels** into the top plate's blind holes (4 mm deep) and lay `16_telescope_seat` over them, engraved face up. The arrow points toward the camera end.

### 5. Camera, case and mounting

1. **Camera plate:** press four M2.5 inserts into `13_cam_plate`, seat the board on its rear face with the boss through the 32 mm hole, and fix it with four M2.5 × 8 screws. The ribbon connector faces the rod side.
2. **Cradle:** bolt `12_cam_cradle` to the top plate with four M3 screws from the top face into inserts below, beyond the altitude rod. Hang the camera plate on two M4 pivot bolts and clamp the angle with two more M4 bolts in the arc slots (tilt −5 to 50°).
3. **Lens and shield:** screw the 16 mm lens in, then clamp the dew shield on the barrel with its M3 bolt. The shield is 28 mm over the barrel and 25 mm beyond the front.
4. **Electronics case:** build up the case (see Electronics) and hang it under the main tilt plate with four M4 screws coming down through the plate into inserts in the case floor. It tilts with the plate, so the IMU reads the plate tilt directly.
5. **Tripod head:** screw the base onto the tripod's 3/8-16 stud. Use the reducer bushing for a 1/4-20 photo tripod.

### Fastener map

| Joint | Fastener | Count |
| --- | --- | --: |
| Lazy Susan to spider, and to azimuth plate | M4, counterbored slots | 4 + 4 |
| Coarse cheeks to azimuth plate | M4 up from beneath, low-head | 6 |
| Hinge pins (both hinges) | M4 set screw in top edge of each cheek | 4 |
| Tilt plate 1 to motor beam | M4 into inserts | 4 |
| Altitude cheeks to tilt plate | M4 from beneath into cheek inserts | 4 |
| End-stop tower to motor beam | M4 with nut below | 4 |
| Electronics case to tilt plate | M4 into case inserts | 4 |
| Azimuth cap | M3 into inserts in the yoke posts | 2 |
| Motors to face plate and beam | M3, 31 mm pattern | 8 |
| Spring anchors (azimuth post and peg, altitude beam and plate) | M3 (about 10 mm) with washer | 2 + 4 |
| Camera cradle to top plate | M3 into inserts | 4 |
| Camera plate pivot and clamp | M4 | 2 + 2 |
| Camera board to plate | M2.5 × 8 into inserts | 4 |
| End-stop switches | M2 × 8 self-tapping | 8 |
| Coarse lock | M6 × 130 with wing nut or knob | 1 |

## Electronics and first power-up

The carrier PCB plugs onto the Pi Zero 2 W and holds both TMC2209 drivers, the power protection, four filtered end-stop inputs and two sensor headers. Build and test it in stages, with the two driver modules left out until the board's power rails read correctly. **The board has never been opened in KiCad, ordered, or powered.** All drawings are in `hardware/pcb/diagrams/` (three schematic sheets and `system_wiring`, each as SVG, PDF and PNG).

### 1. Check the files, then order the board

1. Open `hardware/pcb/carrier.kicad_pcb` in KiCad 8, press **B** to fill all zones, and run **ERC** and **DRC**. This has never been done.
2. Confirm your TMC2209 module against the pin table in the Appendices: the module pin order (PDN\_UART on pin A4) comes from a generic BIGTREETECH page and is not confirmed for the V1.3 board.
3. Upload `hardware/pcb/fab/carrier_gerbers.zip`: 85 × 60 mm, 2 layers, 1.6 mm FR4, 1 oz copper, HASL or ENIG. Five boards is the usual minimum. Order PTC fuses rated 30 V or more.
4. For hand assembly, `carrier_bom.csv` groups the parts; `carrier_cpl.csv` is SMD pick-and-place only, with rotations that were not checked against any assembly service.

### 2. Solder the board

Solder in this order, lowest part first, and keep the Pi socket J1 on the **bottom** side.

1. **0805 parts:** R1, R4 to R8 (1 k), R2 and R3 (10 k), C4 to C9 (100 nF), LED1 (red, anode toward the 1 k resistor R8).
2. **Diodes:** D1 (1N5822), anode on the fused side, cathode on +12V. D2 (1.5KE18A TVS), cathode on +12V, anode on GND. Mind the bands.
3. **Headers and connectors:** J7 to J10 (JST-XH 2-pin), J5 and J6 (JST-XH 4-pin), J11 and J12 (1 × 5), JP1 (1 × 2), then the two 1 × 8 sockets for each driver (rows 12.70 mm apart) and the 2 × 20 socket J1.
4. **Tall parts last:** F1 and F2 (PTC), C1 (220 µF), C2 and C3 (100 µF; mind the polarity marks), the screw terminals J2 to J4.
5. **Do not fit the TMC2209 modules yet.** Square pads mark pin 1 of every header; "PI PIN 1" is printed on the silkscreen, so compare it with your Pi before power. Some silkscreen labels overlap or were left out for space; use the pin tables, not the board text, when in doubt.

### 3. Wire the power

| From | To | Notes |
| --- | --- | --- |
| USB-C PD trigger board (12 V) | J2 (pin 1 = 12 V, pin 2 = GND) | Check the power bank really offers 12 V |
| J3 (+12V, GND) | Buck converter input | Taken after the PTC, the Schottky and the TVS |
| Buck converter 5 V output | J4 (pin 1 = 5 V, pin 2 = GND) | Check it reads 5.0 V with no load before you connect it |
| JP1 jumper | Links the fused 5 V to the Pi's 5 V pins | **Remove it whenever the Pi is powered by its own USB port** |

The motor rail sits about 0.4 to 0.5 V below the PD voltage because of D1. Test points: TP1 = +12V, TP2 = 5V\_F, TP3 = 3V3, TP4 = GND, TP5 = spare (GPIO26).

### 4. Wire the motors, end stops and sensors

- **Motors:** J5 (azimuth) and J6 (altitude) are JST-XH 4-pin. Pins 1 to 4 are the coil A pair, then the coil B pair. Find the two coil pairs with a multimeter (each pair reads a few ohms; the two pairs do not connect), and put one pair on pins 1 and 2, the other on 3 and 4. A reversed motor is fixed later in software (`invert_dir`), not by rewiring.
- **End stops:** J7 = azimuth min, J8 = azimuth max, J9 = altitude min, J10 = altitude max. Pin 1 is signal, pin 2 is GND. Wire each switch **common and normally-closed**: the line idles low, and a pressed or broken switch reads high, which counts as tripped. The software default assumes this. Which connector is "min" and which "max" does not matter; homing works it out.
- **IMU (J11) and GNSS (J12):** pin 1 GND, pin 2 3V3, pin 3 5V, pin 4 SDA, pin 5 SCL. **Power the breakout from pin 2 (3V3).** A 5 V-powered breakout with its own pull-ups puts 5 V on SDA and SCL and can destroy the Pi's GPIO. The GNSS board must expose its I²C (DDC) pins.

### 5. Build the electronics case

The case (139.4 × 81.8 × 42.7 mm) holds the carrier on four 14 mm posts with its parts facing the lid.

- Press eight M3 inserts: four for the PCB posts, four for the lid. Screw the carrier down with four M3 × 6.
- The Pi Zero hangs beneath the carrier on the socket, overhanging the PCB's south edge by about 14.5 mm, which the case allows for.
- The PD trigger and the buck module sit in the 38 mm bay on the east side, tied down with cable ties through the floor slots.
- Cables leave through open slots: power terminals and motor connectors on the north wall; the 5 V terminal and sensor headers on the west wall; the four end-stop connectors on the south wall.
- **Two slots are guesses:** the camera ribbon (south wall, at Pi level) and the USB-C opening for the PD trigger (east wall). Enlarge them with a knife, or edit `cad/aligner_case.py`.
- Close the lid with four M3 × 10. The case is not weatherproof: keep it out of dew and rain, or add your own seal.

### 6. First power-up, in stages

Do each stage with power off between them, and stop at the first reading that is wrong.

| Stage | Set-up | Expect |
| --- | --- | --- |
| 1. Bare board | No Pi, no drivers, no power. Multimeter from TP1, TP2 and TP3 to TP4 (GND) | No continuous short. A low reading that climbs is just the capacitors charging |
| 2. Rails | 12 V on J2, buck connected, JP1 **out**, no Pi, no drivers | TP1 about 11.5 V; TP2 5.0 V; LED1 lit; nothing warm. TP3 stays at 0 V: the Pi supplies the 3.3 V |
| 3. Pi | Power off. Seat the Pi, JP1 **out**, power the Pi from its own USB port, then switch 12 V on | TP3 3.3 V; the Pi boots; `polaralign selftest` finds the IMU and GNSS if fitted |
| 4. Drivers | Power off. Verify the module pin order first, then fit U1 only, then U2 | `selftest` with 12 V on finds both drivers on UART addresses 0 and 1 (IOIN version 0x21) |
| 5. Single supply | Power off. Fit JP1, unplug the Pi's USB, power from the PD bank only | Same readings; the Pi boots from the buck's 5 V |

Motors, end stops, and the software side of these checks are in Commissioning.

## Software installation

The controller is a Python package called `polaralign` in `software/`; it runs a web interface on the Pi that you open from a phone or laptop. **It has run only on a laptop against a simulator, never on a Pi,** so read each script in `software/deploy/` before you run it, and expect to fix package names or boot options.

### Try it on a laptop first (macOS or Linux, Python 3.11 or newer)

This checks the whole loop with no hardware and takes a few minutes.

```bash
cd software
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"      # numpy below 2 is enforced: cedar-solve 0.5.1 fails on numpy 2
.venv/bin/python -m pytest             # 180 tests, about 80 s (157 in about 15 s with -m "not slow")
.venv/bin/polaralign sim-align         # one simulated session: 5 deg error, ends converged
.venv/bin/polaralign serve --sim       # web interface at http://localhost:8080 with a virtual base
.venv/bin/polaralign bench             # star-extractor timing on a 1456 x 1088 frame
```

In the simulated interface use the **Simulator controls** card in this order: **Home**, **Hand-align**, **Declare aligned**, **Knock base 5° off**, **Align**. Declaring aligned while the simulated base is not aligned makes the loop chase a wrong pole; it then ends with a message rather than a fault.

### Set up the Raspberry Pi

1. **Flash the microSD** with Raspberry Pi OS Lite, 64-bit (Bookworm). In the imager, set the hostname to `polaralign`, create your user, enable SSH, and add your home Wi-Fi so you can reach it before the hotspot exists.
2. **Edit the boot configuration.** Append `software/deploy/boot-config.txt.snippet` to `/boot/firmware/config.txt`. The lines that matter:

   | Line | Why |
   | --- | --- |
   | `camera_auto_detect=0` and `dtoverlay=imx296` | The camera. **No `,mono`:** this board is colour |
   | `enable_uart=1` and `dtoverlay=disable-bt` | Puts the PL011 UART on GPIO14 and 15 as `/dev/ttyAMA0`, which the TMC2209 drivers use. Bluetooth is lost |
   | `dtparam=i2c_arm=on` and `dtparam=i2c_arm_baudrate=100000` | The IMU and GNSS; the slow clock avoids the Pi's clock-stretching bug |
   | `dtparam=audio=off` | Optional, saves a little power |
3. **Switch off the serial login console,** or the drivers never answer:

   ```bash
   sudo raspi-config nonint do_serial_cons 1
   sudo systemctl disable --now hciuart.service serial-getty@ttyAMA0.service
   ```

   Also remove `console=serial0,115200` from `/boot/firmware/cmdline.txt`, then reboot.
4. **Connect the camera** with the 22-pin to 15-pin ribbon (the Zero has the small connector), contacts the right way round, with the Pi powered off.
5. **Install.** Copy `software/` to the Pi (for example to `/opt/polaralign/software`) and run:

   ```bash
   cd /opt/polaralign/software
   ./deploy/setup_pi.sh
   ```

   It installs numpy, scipy, Pillow, picamera2 and lgpio from apt; creates the virtual environment with `--system-site-packages` (picamera2 exists only on apt); installs `cedar-solve` with `--no-deps` because its Pillow and numpy pins are stricter than it needs; and builds the solver database if `data/polaralign_db.npz` is missing. Log out and in so the new `gpio`, `i2c`, `dialout` and `video` groups apply.
6. **Settings file.** Copy `config/polaralign.example.toml` to `/etc/polaralign.toml` and edit only what you need; every key is optional. The service reads it through `POLARALIGN_CONFIG`.
7. **Hotspot.** `sudo ./deploy/setup_network.sh` creates a hotspot called `PolarAlign` at 192.168.4.1 with NetworkManager priority −100, so any known Wi-Fi in range wins and the hotspot is the fallback. Add known networks with `nmcli`. After the hotspot comes up, NetworkManager does not look for known networks again until a reboot.
8. **Service.** Copy `deploy/polaralign.service` to `/etc/systemd/system/`, fix `User=` and the paths, then enable it:

   ```bash
   sudo cp deploy/polaralign.service /etc/systemd/system/
   sudo systemctl enable --now polaralign
   ```

   Browse to `http://192.168.4.1:8080` on the hotspot, or `http://polaralign.local:8080` on a known network.
9. **Measure the real speed.** On the Pi run `.venv/bin/polaralign bench` and note the number. The design assumes 70 to 180 ms per frame; if it is much slower, the loop still works but each round gets longer.

### Settings you should look at

The full list is in the Appendices. Four need attention at install time:

- **`web.token`.** Unset by default, which means anyone on the hotspot can move the motors. Set it (the interface reads `?token=` once).
- **`endstop_trip_level`.** The default is 1 (high = tripped) for normally-closed switches. Use 0 for normally-open ones.
- **`motion.alt.mechanics_confirmed`.** Stays false, and the interface keeps warning, until you have confirmed the altitude screw's scale on the bench.
- **`site`.** A fixed latitude and longitude are optional. Without them the base uses GNSS, the phone, or typed values. Without any site, refraction is skipped and the interface says so.

### Camera set-up

The camera is a colour Bayer sensor with an IR-cut filter, so it collects roughly 2 to 3 times less starlight than a mono board. The software handles the mosaic itself: it reads the tile pattern from the raw format and sums 2 × 2 cells for detection. The default exposure is 1.0 s at gain 8. If your camera is not the Waveshare board, set `camera.backend` and `camera.colour = false` for a mono sensor (and use `dtoverlay=imx296,mono` if it is an IMX296). A mirrored image cannot be solved: set `camera.flip_horizontal` or `flip_vertical`.

## Commissioning

Commission in eight stages and do not skip ahead: each stage proves something the next one relies on. Every stage below is an untested plan, because nothing here has met real hardware; the pass criteria come from the software's design notes unless marked as my own.

| # | Stage | What you do | Pass looks like | If not |
| --: | --- | --- | --- | --- |
| 1 | Self-test, 12 V off | `polaralign selftest` with no motor power. It moves nothing | GPIO opens, a camera frame arrives, the I²C devices answer. End stops read tripped until their switches are wired. The TMC2209 checks fail: that is expected without 12 V | Read the message: "UART echo missing" or "no answer" means the UART is not on `/dev/ttyAMA0` |
| 2 | Self-test, 12 V on | `selftest` again | Both drivers answer, on UART addresses 0 and 1, with IOIN version 0x21 | Recheck the module pin order (PDN\_UART on A4), the serial console, `disable-bt` |
| 3 | Camera and solver | Point the camera at a dark sky. In the interface press **Solve now**; adjust **Exposure** and **Gain** and press **Set**. Run `polaralign solve` from the shell if you prefer | A frame appears, stars are detected, and the solve succeeds with a residual of a few arcseconds. The simulator gave about 40 to 60 stars at 1 s; above about 25 to 30 should still solve | See "no solve" under Troubleshooting. Check the image is not mirrored |
| 4 | Motors, no load | Disconnect the screws from the load. `polaralign jog az 0.2`, then `jog alt 0.2` | Each moves the correct way; the motor freewheels when idle (EN is high); the interface shows the position | A wrong way: set `invert_dir = true`. A stall or buzz: lower `max_speed_rev_s` or `run_current_a` |
| 5 | End stops by hand | Press each switch by hand and read `/api/status` (`min_switch`, `max_switch`) | Each switch changes only its own reading when pressed | One reads constantly: wire fault or `endstop_trip_level` is wrong for your switch type |
| 6 | Homing | Reconnect the screws, with the plates on the bench and the dead weight on. `polaralign home`. **Be ready to pull power.** | Both screws stop at the switches; the software works out which connector is at which end | If a screw runs the wrong way into the wrong switch, set `invert_dir = true` for that axis or swap its MIN and MAX connectors |
| 7 | Travel and springs | Move each axis to ±6° by jog. Run `POST /api/home?measure_span=true` once | Smooth motion; no rubbing; the plate never goes slack against the spring; the measured span agrees with the switch positions (about ±8.05° azimuth and ±7.2° altitude from the centre) | If the altitude scale is off, the loop learns it, but set `motion.alt.mechanics_confirmed = true` only after you have checked it |
| 8 | Closed loop | After the calibration in the next sections, knock the base 3 to 5° off by hand and press **Align** | Ends below 3 arcmin in at most 8 rounds, and the telescope's own check agrees | See Troubleshooting |

### Notes on each stage

**Stage 3: the camera.** Focus the 16 mm lens at infinity on a bright star or distant light, then lock the ring. This is the first time real optics meet the extractor, so it is the biggest open question in the design. The extractor and solver were tested to degrade gracefully down to about 25 to 30 detected stars; whether your sky gives that many at 1 s is unknown. If a frame fails to solve, the loop retries with 1.6 times the exposure, up to 4 s. A daytime or cloudy frame will not solve, so wait for a clear night.

**Stage 4: step timing.** The step pulses come from a Python loop with absolute deadlines. Nobody has measured its jitter on a Pi Zero 2 W under web-server load. If a motor stalls or loses steps, lower `max_speed_rev_s` (default 1.0 rev/s), raise `accel_rev_s2` (default 2.0), or ask for stepping to move into its own process.

**Stage 5: switches.** With the recommended normally-closed wiring, a disconnected or broken switch reads as tripped, which is the safe way round. The 1 k and 100 nF filter has a release time constant near 5 ms through the Pi's internal pull-up; the software debounces with two readings one full step apart, so do not shorten `endstop_debounce_ms`.

**Stage 6: homing.** Homing watches both switches, does a short safe move first if it starts on a switch, and relabels MIN and MAX if the connector you called MIN trips first at the other end. The azimuth switches trigger at 8.05°; the altitude switches at 7.35° and 7.15°. The jackscrew's own hard limit is about 9°, so the software must stop at a switch.

**Stage 7: the preload springs.** The azimuth spring pulls the plate clockwise seen from above. Once a site is known, the loop works out which sign of step count that is from the sky motion it learns and sets `preload_dir`. The altitude springs' direction is not documented, so set `motion.alt.preload_dir` by watching the bench: every move should finish in the direction the springs pull against.

**IMU check (any time after stage 2).** Compare the IMU's tilt readout with a phone inclinometer on the tilt plate at two or three coarse angles. The IMU is bolted under the main tilt plate and its axes are not aligned to it, so the offset has to be calibrated; `sensors.imu_axis_in_sensor` (default `[0, 0, 1]`) names the polar axis in the IMU's own frame. The knock threshold of 0.06 g is a guess; stepper vibration may need tuning.

**Acceptance test (my criterion, not the design's).** After calibration, knock the base 3 to 5° off in different directions at least five times and align each time. Record the final error the software reports and, separately, the telescope's own polar-alignment error. The design target is 0.1°; if the two disagree by more than that, suspect the calibration or the telescope seating, not the loop.

## Field use

In the field you set the coarse tilt and aim the base roughly at the pole, then press one button; the base does the rest in about a minute. This procedure assumes the aligner has been commissioned and calibrated (see Commissioning and Calibration), and it has not yet been tried under a real sky.

### Before you go

- Charge the USB-C PD power bank (it must offer 12 V) and the telescope.
- Note the tick on the seat disc where you normally set the telescope (see Calibration), and have a paint pen ready.
- Check that the coarse lock bolt, the hinge set screws and the camera clamp bolts are tight.

### Setting up

1. **Place the tripod** with one leg pointing toward the pole (north in the northern hemisphere, south in the southern) and the legs fully spread. The centre of gravity moves toward or away from the pole with latitude; the case on the side away from the pole counterbalances the telescope.
2. **Screw the base onto the tripod stud.** Roughly level the head by eye or with a bubble level; the fine travel has to absorb whatever is left (this is my advice, not a design figure).
3. **Power up.** Connect the PD power bank. Wait for the Pi to boot, then join the `PolarAlign` hotspot, or your known Wi-Fi, on a phone and open `http://192.168.4.1:8080` (or `http://polaralign.local:8080`). If you set `web.token`, open the link with `?token=` once.
4. **Set the coarse tilt.** Loosen the lock bolt, tilt the plate until the interface's IMU readout shows your latitude, and tighten the lock with a wrench. The plate is then tilted 90° minus the latitude from horizontal. The IMU reads the plate tilt, which is the polar axis elevation only to within the ±6° altitude stage, so it is good for this coarse step and not for the final alignment.
5. **Aim the base roughly at the pole.** Turn the whole base until the stage points north (or south) as closely as you can with a compass or the tripod leg. The tolerance depends on your latitude, because one degree of stage rotation moves the axis only cos(latitude) degrees on the sky:

   | Latitude | East-west reach of the azimuth stage |
   | --- | --- |
   | 25° | ±5.2° |
   | 48° | ±3.8° |
   | 62° | ±2.7° |

   Above about 45° latitude aim carefully, within a few degrees. If the pole is out of reach, the loop reports "fine travel exhausted" and stops before it hits a switch; re-aim by hand and press Align again.
6. **Give it a place and a time.** With a GNSS module fitted, wait for the fix. Otherwise press **Use phone location & time** in the Location card. Chrome and Safari refuse the browser's geolocation on a plain `http` page, so it will probably ask you to type latitude and longitude instead, and it still takes the phone's clock. The base needs latitude, longitude and the time (to a few minutes) to compute the pole of date and refraction; without a site it skips refraction and says so.
7. **Seat the telescope** on the disc (see Calibration for the procedure), hand-tight, with the paint-pen dot on the same tick as before. A paper strip must not slide between the telescope's base and the disc.
8. **Home the axes** (first session of the day only). Press **Home both axes**. It takes up to about 40 s with both axes in parallel at 0.4 rev/s. The screws are self-locking, so the last position is remembered and homing is optional afterwards.

### Aligning

1. **Check the camera sees sky.** Its field is about 17.8 × 13.4°. Press **Solve now**; the preview should show stars and the solve fields should fill. Do not change the camera's tilt now: the calibration depends on it.
2. **Press Align.** The big readout shows the pole error and the phase line says what it is doing. Do not touch the tripod or the telescope while it runs, and avoid wind and footsteps; the IMU detects a knock, discards a frame exposed during it, and waits for the structure to settle.
3. **Watch the rounds.** Each round lists its error. The base learns the step-to-sky matrix on the first round, applies 80 % of the correction on both axes, waits 1.5 s, and solves again. It stops when the error is below 3 arcminutes (0.05°) and keeps polishing toward 1 arcminute while rounds remain, at most 8. The residual is measured after the last move.
4. **Read the ending.** "Converged" means the final error is below target. A message instead ("fine travel exhausted", a hard stop reached, no solve) means it stopped on purpose; the Log card says why. See Troubleshooting.
5. **Check with the telescope.** Run the telescope's own polar-alignment check, then enable equatorial mode.

### Packing up

Press **Release motors** (it is also done after every move), power down, loosen nothing on the coarse lock unless you are changing latitude, and keep the case dry. Note the seat tick you used.

## Calibration

Calibration teaches the base where the telescope's rotation axis sits in the camera's field of view, and it is the biggest unknown in the 0.1° error budget. The loop only measures where the camera points, so any error in this stored rotation goes straight into the final pole error. Do it once for each camera angle and telescope seating, repeat it on two or three nights, and redo it when something listed below changes.

### What is stored

The base stores one rotation: the unit vector of the telescope's axis in the camera's frame. Roll about the axis does not matter. Each time you press **Declare aligned**, an entry is recorded; entries are averaged, the scatter between them is shown in the Calibration card, and the file is written atomically with a backup.

### Procedure

1. **Fix the geometry first.** Set the camera tilt, clamp it, and settle on one seat tick for the telescope. Changing either later means calibrating again.
2. **Seat the telescope the same way every time.** Put a paint-pen dot on the S50's base at a fixed feature, for example the front. Screw it down hand-tight and note which 15° tick on the seat disc the dot lands on. Aim to end on the same tick, within one or two, every time, and write that tick next to the calibration. A strip of paper (about 0.05 mm) must not slide between the base and the disc anywhere around the edge.
3. **Align by hand.** On a clear night, set up as in Field use, then use the telescope's own polar-alignment routine until it reports the smallest error it can. Do not touch the base afterwards.
4. **Press Declare aligned.** The base solves a frame and records where the axis is in it. The Calibration card then lists the entry.
5. **Repeat on two or three nights,** with the telescope re-seated each time. The averaged value gets better, and the scatter tells you how repeatable your seating and your telescope's own routine are. If the scatter approaches the 0.1° target, the seating is the first thing to suspect.
6. **Verify.** Knock the base off by 3 to 5°, press **Align**, then run the telescope's check. The two should agree to within the target.

### What invalidates the calibration

| Change | Calibrate again? | Why |
| --- | --- | --- |
| Camera tilt, cradle clamp, camera plate, lens or board | Yes | The camera's view moves relative to the axis |
| Telescope on a different tick | Not always | Re-seating at another yaw shifts the calibration by about t × the yaw difference, where t is the small tilt between the telescope's axis and its own base. At an assumed t of 0.2°, one 15° tick costs about 0.05° and two ticks about 0.1°. The t figure is my assumption, not a measurement |
| A different telescope | Yes | Its internal tilt is its own |
| A different latitude, same hardware | No, keep `align.refraction = "model"` | The stored value absorbs the convention your telescope's routine uses at the calibration site. In the simulator, calibrating at 10° latitude and using at 55° gave under 0.03° of error with the model on and over 0.05° with it off |
| Knock or bend of the cradle or top plate | Yes | The geometry changed |

To throw the stored calibration away, press **Clear**.

### Pole of date and refraction

The solver reports positions in J2000. The pole of date is about 539″ (0.150°) away from the J2000 pole in November 2026, so the software aligns to the pole of date, using the IAU 2006 precession and the leading nutation terms. By default it aligns the axis to the apparent, refraction-raised pole (about 2.1′ or 0.035° at 25° latitude); set `align.refraction = "off"` to align to the true pole instead. Both need the site and the time.

### Optional: trim from the telescope's own residual

The software has an isolated plugin that trims the stored calibration using the pole error the Seestar itself reports. The mathematics is tested: in the simulator, a sloppy 0.06° hand alignment corrected to under 0.025° on the next session. **The connection to a real Seestar is untested and deliberately left unconfigured** (`seestar.enabled = false`): the method name, the field names and the units are unknown, and the community protocol has been broken by firmware updates before. The safe alternative is to read the residual from the Seestar app and feed it to the trim function by hand.

## Troubleshooting

The causes below are the ones the design notes anticipate. Because nothing has run on real hardware, expect other faults too; the Log card in the interface and `journalctl -u polaralign` are the first places to look, and `polaralign selftest` re-checks the electronics without moving anything.

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| **Electronics.** `selftest` says "UART echo missing" or "no answer" | The UART is not on `/dev/ttyAMA0`: Bluetooth still on, serial console still on. Or 12 V is off, or the driver pin order differs | Check `dtoverlay=disable-bt`, `enable_uart=1`, `console=serial0` removed from `cmdline.txt`, `hciuart` and `serial-getty` disabled. Switch 12 V on. Check pin A4 on your module |
| Only one driver answers, or both answer on the same address | Address straps wrong | U1 needs MS1 and MS2 on GND (address 0); U2 needs MS1 on 3V3 and MS2 on GND (address 1) |
| Pi will not boot, or runs hot, with USB and the PD bank both connected | JP1 fitted while the Pi is on USB | Remove JP1 whenever the Pi has its own USB supply |
| IMU or GNSS returns garbage | Pi I²C clock-stretching bug; wrong address; 5 V on SDA/SCL | Keep `i2c_arm_baudrate=100000`; try address 0x69 for the IMU; power breakouts from 3V3 |
| No GNSS data | Many cheap boards are UART-only | Use a u-blox board that exposes SDA and SCL, or use the phone's location |
| **Motors.** Motor does not move, only hums | Coil pairs crossed, or current too low | Check which wires make each pair (a few ohms) and put each pair on its own two pins; keep `run_current_a` within 0.4 to 0.6 A |
| Motor moves the wrong way | Direction convention | Set `invert_dir = true` for that axis. The loop learns signs anyway, but homing needs the right way |
| Motor stalls, buzzes or loses steps | Step timing jitter in the Python loop; speed too high | Lower `max_speed_rev_s` (default 1.0), raise `accel_rev_s2` (default 2.0), or ask for stepping to move to its own process |
| Motor warm when idle | The driver should be disabled (EN high) after every move | Check EN wiring and its 10 k pull-up; press **Release motors** |
| **End stops.** A switch always reads tripped | Normally-closed wiring and the switch is unplugged, or the wrong trip level | Connect it. For normally-open switches, set `endstop_trip_level = 0` |
| Homing runs a screw into the wrong switch | Direction or connector order | Cut power. Set `invert_dir = true` for that axis, or swap its MIN and MAX connectors |
| A hard stop is reached during normal travel | Scale or mechanics wrong | This is not a fault: the axis learns the limit and backs off. Run `POST /api/home?measure_span=true`, and check the altitude screw's scale |
| **Camera and solver.** No frame, or a camera error | Overlay or ribbon | Check `camera_auto_detect=0` and `dtoverlay=imx296` (no `,mono`), that the 22-pin to 15-pin ribbon is the right way round, and that `python3-picamera2` is installed |
| Stars visible but no solve | Mirrored image; out of focus; exposure too short; too few stars; cloud or dew | Set `camera.flip_horizontal` or `flip_vertical`. Refocus and lock the ring. Raise the exposure (the loop retries up to 4 s). Wait for clear sky; fit the dew shield |
| The solver refuses to start | numpy 2 or newer is installed (cedar-solve breaks on it) | Install numpy below 2; the software says so |
| **Alignment.** Rounds keep going without converging | The calibration was declared while the base was not aligned, so the loop chases a wrong pole | Press **Clear**, and repeat the Calibration procedure |
| Ends with "fine travel exhausted" | The pole is outside the stage's reach, especially above 45° latitude | Re-aim the base by hand, closer to north or south, and press **Align** again |
| Result worse than expected, or flips between sessions | Calibration scatter; telescope re-seated on a different tick; camera tilt changed; spring direction wrong | Check the scatter in the Calibration card, use the same seat tick, recalibrate, and set `motion.alt.preload_dir` correctly |
| Final error disagrees with the telescope's own check | The telescope's convention (true or apparent pole) or its own error | Check `align.refraction` and recalibrate at this site; see Calibration |
| The interface keeps warning about the altitude drive | `motion.alt.mechanics_confirmed` is still false | Confirm the screw scale on the bench, then set it to true |
| **Interface.** Cannot reach the page | Hotspot not up, service not running, or on the wrong network | `sudo systemctl status polaralign`; reboot the Pi (NetworkManager does not look for known networks again after the hotspot is up); try `http://192.168.4.1:8080` |
| Buttons do nothing | `web.token` set and not supplied | Open the link with `?token=` once |
| **Location** button refused | Chrome and Safari block geolocation on plain `http` | Type the latitude and longitude; the phone's time is still used |
| **Mechanics.** The telescope sits tilted on the seat | The stud bottomed in the socket | Use a shorter bolt: stand-up (bolt length − 11 mm) at least 2 mm less than the socket depth |
| Coarse tilt creeps | The lock is only friction | Tighten with a wrench, check the bolt is square through both cheeks and arms, and test with dead weight |
| Azimuth plate wobbles | Lazy-Susan axial play | Measure it; above about 0.05° consider a cross-roller slewing ring |
| A printed part cracks | Layer-line failure on a loaded face, especially the motor face plate | Reprint with more walls or a change of orientation, and consider the aluminium plate set |
| The printer refuses raw `.gcode` | Bambu printers expect `.gcode.3mf` | Open the STL in Bambu Studio with the settings from the Printing guide |

## Maintenance, limits and open assumptions

The design has eleven known limits you should accept before you build it, and about twenty-five assumptions that only a real build can confirm. The checklist at the end is for you to tick off as you verify each one.

### Maintenance

- **Before each trip:** check the coarse lock bolt, the four hinge set screws and the camera clamp bolts. Look at the motor face plates and the lock bolt area for cracks along the layer lines. PETG creeps and softens with heat, so do not leave the base in a hot car.
- **Moving parts:** check the trunnion dowels for wear, the brass nuts for slop on the rod, and that the springs still hook firmly and keep their length.
- **Cables:** check the motor and end-stop connectors are seated, and that no cable pulls on a JST header. Keep the case dry.
- **Calibration:** look at the scatter in the Calibration card now and then. The state directory (`~/.local/share/polaralign` by default) holds the calibration and its backup; copy it somewhere safe.
- **Software and database:** rebuild the solver database from the real Hipparcos catalogue when you can reach it: `polaralign build-db --catalogue /path/to/hip_main.dat`.
- **After editing any CAD constant:** regenerate the STLs, re-slice, and re-run `check_assembly.py`.

### Known limits

- **Azimuth reach shrinks with latitude.** ±5.2° at 25°, ±3.8° at 48° and ±2.7° at 62° on the sky. The decision was to keep ±6° of travel; the rod and arm would allow more, and the end stops would move with it.
- **Coarse tilt is manual and friction-locked.** It covers latitude −10° to 75°, set by hand with the IMU readout.
- **No stall detection.** The PCB routes no DIAG pin, so homing relies on the mechanical switches only.
- **No mechanical key on the telescope seat.** The engraved index is good to a tick or two, which costs about 0.05° per tick if the telescope's internal tilt is the assumed 0.2°.
- **The camera is colour, with an IR-cut filter,** so it needs longer exposures, and the board is discontinued. A different board needs a new camera plate.
- **No authentication by default.** Anyone on the hotspot can move the motors until you set `web.token`.
- **Not weatherproof.** The case has open cable slots.
- **The IMU is only a coarse guide.** It sits under the main tilt plate, so it reads the plate tilt, not the final polar axis elevation, and its compass is rough.
- **Seestar plugin unverified.** The protocol is assumed; leave it off until you have probed your firmware.
- **Single-telescope design.** The seat is made for the S50's 3/8-16 socket.
- **Cost and licences.** The full build is an estimated $419.29 against a $300 budget. The Hipparcos-derived database is free to use with acknowledgement; check the terms before shipping a derived database in a product. The software's own licence is "all rights reserved" until you choose one, and the repository has no LICENSE file.

### Unverified assumptions: tick each one as you confirm it

**Electronics**

- [ ] TMC2209 module pin A4 is PDN\_UART and not an output. Check the vendor drawing and continuity before plugging both in.
- [ ] The module's pin rows are 12.70 mm apart. Measure with calipers before ordering the PCB.
- [ ] KiCad ERC and DRC pass, and the GND zones fill.
- [ ] "PI PIN 1" on the silkscreen matches your Pi's orientation.
- [ ] The PTC, capacitor, terminal and module heights (assumed 14, 11 to 12, 10 and 17.1 mm) fit the case with the 2.0 mm lid clearance.
- [ ] The PD trigger, buck module and the case's USB-C and camera-ribbon openings (all guesses) fit the real parts.
- [ ] The shared UART runs reliably at 115200 baud through the 1 k resistor, and the 0.11 Ω sense value matches your module.

**Mechanics**

- [ ] Lazy-Susan thickness and bolt pattern match `LS_H` and `LS_SLOT`; its axial wobble is under about 0.05°.
- [ ] Your NEMA 17 matches the 42.3 mm face, 31 mm pattern and 22.6 mm boss.
- [ ] End-stop switch body, hole spacing and lever match the assumed 20 × 10.5 × 6.5 mm, 9.5 mm and 14 mm roller offset. A roller 1 mm off moves the azimuth trigger by about 0.7° and the altitude trigger by about 0.3°.
- [ ] The S50's socket is deep enough for the stud stand-up (bolt length − 11 mm, at least 2 mm less than the depth).
- [ ] The lens front element is no larger than the 30 mm assumed behind the 41 mm dew-shield bore, and the M2.5 insert pocket (3.6 × 4.5 mm) fits.
- [ ] The spring you bought works on the peg `check_preload.py` picks, and the 0.10 N·m minimum torque is enough in practice.
- [ ] The altitude springs' direction is known and `motion.alt.preload_dir` is set.
- [ ] The coarse lock holds the stack without creep: about 85 N is needed at latitude 0 against an estimated 500 N available.
- [ ] The printed motor face plates do not crack under the lead-screw load, and the 123 mm end-stop tower does not sway.
- [ ] A raw `.gcode` file is accepted by your Bambu printer, or the STLs print with the same settings.

**Software and optics**

- [ ] `polaralign bench` on the Pi gives a time close to the extrapolated 70 to 180 ms.
- [ ] A real sky gives at least 25 to 30 stars per frame at 1 s, with the real lens focused.
- [ ] The camera's raw format, Bayer pattern and image orientation match what the software assumes.
- [ ] Step-pulse timing is steady on the Pi Zero 2 W under web load.
- [ ] The IMU's axis, the knock threshold (0.06 g) and the GNSS fix over I²C work as assumed.
- [ ] The hotspot comes up and falls back correctly; the interface works on a phone.
- [ ] The telescope's yaw repeatability (t, assumed 0.2°) is measured, using your own re-seating tests.
- [ ] Prices and camera availability still hold.

## Appendices

Reference tables for wiring, settings, files and terms. All source files are in the public repository [zeroknowledge/auto-polar-alignment](https://github.com/zeroknowledge/auto-polar-alignment), which has `hardware/` and `software/` folders and the original design document.

### A. Raspberry Pi header and signals

BCM numbers are the ones the software uses. 27 header pins are used and 13 are unconnected.

| Signal | GPIO (BCM) | Header pin | Notes |
| --- | --: | --: | --- |
| STEP\_AZ | 17 | 11 |  |
| DIR\_AZ | 27 | 13 |  |
| EN\_AZ | 22 | 15 | 10 k pull-up: driver off at boot |
| STEP\_ALT | 23 | 16 |  |
| DIR\_ALT | 24 | 18 |  |
| EN\_ALT | 25 | 22 | 10 k pull-up |
| ES\_AZ\_MIN | 5 | 29 | 1 k + 100 nF filter |
| ES\_AZ\_MAX | 6 | 31 |  |
| ES\_ALT\_MIN | 13 | 33 |  |
| ES\_ALT\_MAX | 19 | 35 |  |
| SDA | 2 | 3 | The Pi's own pull-ups serve it; none on the PCB |
| SCL | 3 | 5 |  |
| UART TX | 14 | 8 | Through R1 (1 k) onto the shared bus |
| UART RX | 15 | 10 | Direct to the shared bus |
| SPARE | 26 | 37 | Test point TP5 only |
| 3V3 |  | 1, 17 |  |
| 5V from JP1 |  | 2, 4 |  |
| GND |  | 6, 9, 14, 20, 25, 30, 34, 39 |  |

Not connected: pins 7, 12, 19, 21, 23, 24, 26, 27, 28, 32, 36, 38 and 40.

### B. TMC2209 module sockets

Each module plugs into two 1 × 8 sockets 12.70 mm apart. **The pin order is unconfirmed for the BIGTREETECH V1.3: check it first.**

| Row A pin | Signal | Row B pin | Signal |
| --- | --- | --- | --- |
| A1 | EN | B1 | VM (+12 V) |
| A2 | MS1: GND on U1 (address 0), 3V3 on U2 (address 1) | B2 | GND |
| A3 | MS2: GND | B3 | Coil A2 |
| A4 | PDN\_UART: shared bus | B4 | Coil A1 |
| A5 | PDN\_UART alternate: not connected | B5 | Coil B1 |
| A6 | CLK: GND (internal clock) | B6 | Coil B2 |
| A7 | STEP | B7 | VIO (3V3) |
| A8 | DIR | B8 | GND |

### C. Connectors

| Ref | What | Pins |
| --- | --- | --- |
| J1 | Pi 2 × 20 socket, bottom side | See table A |
| J2 | 12 V in (screw terminal) | 1 = 12 V, 2 = GND |
| J3 | 12 V out to the buck | 1 = +12 V, 2 = GND |
| J4 | 5 V in from the buck | 1 = 5 V, 2 = GND |
| J5, J6 | Azimuth and altitude motor (JST-XH 4-pin) | Coil A pair, then coil B pair |
| J7 to J10 | End stops: AZ min, AZ max, ALT min, ALT max (JST-XH 2-pin) | 1 = signal, 2 = GND |
| J11, J12 | IMU and GNSS (1 × 5) | 1 GND, 2 3V3, 3 5V, 4 SDA, 5 SCL |
| JP1 | Fused 5 V to Pi 5 V pins | Remove on USB power |
| TP1 to TP5 | +12V, 5V\_F, 3V3, GND, SPARE |  |

### D. Key settings and where to change them

Set these in the TOML file (`/etc/polaralign.toml`, through `POLARALIGN_CONFIG`; the example is `software/config/polaralign.example.toml`). Every key is optional.

| Setting | Default | Meaning |
| --- | --- | --- |
| `camera.exposure_s`, `camera.gain` | 1.0 s, 8.0 | Exposure and analogue gain; also live in the interface |
| `camera.colour`, `camera.bayer_pattern` | true, RGGB | Colour board; the real pattern is read from the raw format |
| `camera.flip_horizontal`, `flip_vertical` | false | Fix a mirrored image |
| `extractor.threshold_sigma`, `bayer_mode` | 5.0, `all` | Star detection |
| `solver.solve_timeout_ms` | 4000 | Per-solve limit |
| `motion.microsteps`, `run_current_a` | 16, 0.5 A | 0.4 to 0.6 A RMS; EN is high after every move |
| `motion.rsense_ohm` | 0.11 | Check your module's sense resistors |
| `motion.max_speed_rev_s`, `accel_rev_s2` | 1.0, 2.0 | Lower the speed if steps are lost |
| `motion.az.arm_mm`, `motion.alt.arm_mm` | 80, 150 | Tangent arms: 12.9″ and 6.9″ per full step |
| `travel_deg`, `end_stop_deg` | 6.0; 8.05 (az), 7.25 (alt) | Working range and switch trigger angle |
| `endstop_trip_level` | 1 | 1 = high is tripped (normally closed); 0 for normally open |
| `invert_dir`, `preload_dir` | false, 1 | Direction fixes and the spring direction |
| `backlash_overshoot_deg` | 0.12 | Azimuth backlash move |
| `motion.alt.mechanics_confirmed` | false | Set true after you confirm the altitude scale |
| `align.target_arcmin`, `polish_arcmin` | 3.0, 1.0 | Success and polishing thresholds |
| `align.max_iterations`, `gain`, `settle_s` | 8, 0.8, 1.5 s | Rounds, fraction applied, wait |
| `align.refraction` | `model` | `off` aligns to the true pole |
| `sensors.knock_threshold_g` | 0.06 | A guess; may need tuning for stepper vibration |
| `web.port`, `web.token` | 8080, unset | Set a token to require `X-Token` on POST requests |
| `seestar.enabled` | false | Leave off unless you have probed your firmware |

### E. Where things are

| Path | What |
| --- | --- |
| `hardware/README.md`, `BOM.md`, `bom.csv` | Master build notes and the bill of materials |
| `hardware/cad/` | Parametric CAD and checks: `aligner_cad.py`, `aligner_cad2.py`, `aligner_case.py`, `aligner_cam.py`, `check_clearance.py`, `check_assembly.py`, `check_stops.py`, `check_preload.py` |
| `hardware/stl/`, `hardware/gcode/` | 17 printable STLs; sliced G-code and statistics |
| `hardware/slicer/` | Bambu X1C PETG profiles, `slice_all.sh`, `verify_gcode.py` |
| `hardware/pcb/` | KiCad project, Gerbers (`fab/carrier_gerbers.zip`), BOM, pick-and-place, DXF, board STL, diagrams, `SPEC.md`, `README.md` |
| `software/src/polaralign/` | The package: alignment engine, astronomy, camera, extractor, motion, sensors, simulator, web interface |
| `software/docs/` | `ARCHITECTURE.md`, `HARDWARE_UNTESTED.md`, `PIN_MAP_REVIEW.md`, simulation and benchmark output |
| `software/deploy/` | Boot snippet, systemd unit, hotspot and install scripts |
| `software/tests/` | 180 tests |

### F. Command reference

```bash
polaralign serve               # web interface (add --sim for a virtual base)
polaralign selftest            # checks GPIO, TMC2209 UART, camera and I2C; moves nothing
polaralign solve               # one plate solve of the current camera frame
polaralign home                # find both end stops
polaralign jog az 0.5          # move one axis by a number of degrees
polaralign calibrate           # record the camera-to-axis calibration from the shell
polaralign sim-align           # one simulated session
polaralign build-db            # rebuild the solver database
polaralign bench               # extractor timing
```

Put `--config FILE` and `--state-dir DIR` before the sub-command, for example `polaralign --config my.toml serve`.

### G. Glossary

- **Azimuth, altitude.** The two fine adjustments: turning the base about a vertical axis, and tilting the telescope's axis up or down.
- **Backlash.** Play in a screw and nut; the base finishes every move in the spring's direction to take it up.
- **Bayer, colour sensor.** A sensor with a red, green and blue mosaic over its pixels; the software sums 2 × 2 cells to find stars.
- **End stop.** A micro switch that tells the software a stage has reached the end of its travel.
- **J2000, pole of date.** J2000 is the sky's reference frame at the year 2000; the pole of date is where the pole actually is today, 0.150° away in November 2026.
- **Lazy Susan.** The turntable bearing under the azimuth plate.
- **Plate solving.** Matching a photograph's stars against a catalogue to find where the camera points.
- **Preload.** A spring that keeps one thread flank loaded so the screw drives without play.
- **Refraction.** The air bends starlight; the apparent pole sits slightly higher than the true one.
- **TMC2209.** A silent stepper-driver chip, driven here over a single-wire UART with an address for each axis.
- **Trunnion.** The pivoting block that holds the brass nut and lets the rod swing as the stage rotates.

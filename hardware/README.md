# Auto polar aligner: hardware

Printed parts, BOM and carrier PCB for the base described in `../Auto_Polar_Alignment_Base_Design.docx`.

| Folder | What |
|---|---|
| `BOM.md`, `bom.csv` | Bill of materials (generated from one table) |
| `cad/aligner_cad.py` | Parametric CAD (Python + manifold3d). Edit constants at the top, rerun to regenerate STLs |
| `cad/aligner_cad2.py` | Batch 2 parametric CAD: the tall-hinge tilt stage (cheeks, tilt plates, top plate) |
| `cad/check_clearance.py` | Swept interference check for the azimuth stage (-6..+6 deg) |
| `cad/check_assembly.py` | Whole-stack sweep: latitude -10..75 deg, altitude and azimuth travel, telescope-sized block, centre of gravity |
| `stl/` | Printable models, in print orientation |
| `slicer/` | Bambu X1C / PETG profiles, `slice_all.sh`, `verify_gcode.py` |
| `gcode/` | Sliced G-code and per-part statistics |
| `pcb/` | Carrier PCB: KiCad files, Gerbers, drills, BOM, pick-and-place, DXF, board STL, renders (see `pcb/README.md`) |
| `pcb/diagrams/` | Circuit diagrams: three schematic sheets and a system wiring diagram, each as SVG, PDF and PNG |
| `pcb/check_independent.py` | Independent PCB checks (pin map, clearances, connectivity, drills vs KiCad, Gerber extents) |

## What is here and what is not (read this first)

**Everything is printable now.** The telescope seat has an engraved index rather than a mechanical key, for the reason given below. Batch 1: the tolerance coupon, nut trunnions, base spider with the azimuth motor
mount, azimuth plate and cap. Batch 2a: the tall-hinge tilt stage (two coarse cheeks, the tilt plate in two pieces, two
altitude cheeks, the top plate). The electronics case and lid and the camera cradle, plate and dew shield are done too. **Not built:** a mechanical key on the telescope seat (needs a measurement of the S50's underside): see the end of this file for what each one needs.

**`03_az_plate` changed after Batch 1:** it gained six M4 holes for the coarse cheeks. If you already printed the old one,
print the new one.

None of this has been printed or assembled. Geometry checks passed (watertight meshes, bed fit, azimuth sweep, whole-stack
sweep below). Strength, stiffness and fit with your actual lazy Susan, motor, bearings and nuts are **not** checked.

## First steps, in order

1. **Measure these on the parts you have or will buy** and, if they differ, edit the constants in `cad/aligner_cad.py` (or
   `aligner_cad2.py`), then rerun the commands at the end of this file: the lazy-Susan height and bolt pattern, your NEMA 17's
   boss and hole spacing, a 3/8-16 nut, the **S50's socket depth** (for the stud length rule), and the lever and roller of the
   end-stop switches.
2. **Print `00_fit_test`** and update the hole-size constants from it before printing anything large.
3. **Print in the order listed below.** Do the two big plates and the end-stop tower only after the smaller parts fit.
4. **Order parts from `BOM.md`.** The Waveshare camera is listed as discontinued: check availability before anything else, because
   a different board means a new camera plate.
5. **Order the PCB** from `pcb/fab/carrier_gerbers.zip`, but first open `pcb/carrier.kicad_pcb` in KiCad and run its ERC/DRC and fill
   the zones (this has never been done), and confirm your TMC2209 module's pinout against `pcb/README.md`.
6. **Assemble and test one axis at a time** before the software closes the loop, and test the end-stop switches by hand before
   the motors ever drive toward them.

## Print order

1. **`00_fit_test`** (48 min, 28 g). Print this first. Each row has three sizes, smallest on the left. Push the real part in:
   M6 brass nut (row 1, left three pockets), 8 mm hinge pin (row 1, right), 608 bearing (row 2), 3/8-16 nut (row 3 left),
   3 mm dowel pins (row 3 middle), M3 heat-set insert (row 3 right). Pick the smallest hole that the part enters with a gentle
   push, then edit the matching constant in `cad/aligner_cad.py` (`M6_NUT_AF`, `DOWEL_PRESS`, `DOWEL_FREE`, `HEX38_AF`,
   `M3_INSERT`) and rerun `python cad/aligner_cad.py stl` and `slicer/slice_all.sh`.
2. **`01_nut_trunnion_x3`** (34 min, 13 g): three trunnions, two used and one spare.
3. **`04_az_cap`** (9 min, 3 g).
4. **`03_az_plate`** (2.9 h, 73 g), the revised one.
5. **`02_base_spider`** (4.6 h, 113 g).
6. **`05_coarse_cheek_x2`** (2.1 h, 55 g), **`08_alt_cheek_x2`** (1.2 h, 31 g), **`07_tilt_plate_2`** (1.0 h, 28 g).
7. **`06_tilt_plate_1`** (4.2 h, 116 g) and **`09_top_plate`** (4.6 h, 124 g): the two big ones. The tilt plate gained four
   screw holes for the electronics case after the first Batch 2 slice, so use the current file.
8. **`10_electronics_case`** (2.7 h, 86 g) and **`11_case_lid`** (0.8 h, 29 g).
9. **`12_cam_cradle`** (1.5 h, 33 g), **`13_cam_plate`** (15 min, 6 g), **`14_dew_shield`** (1.0 h, 18 g).

10. **`15_alt_endstop_tower`** (2.3 h, 24 g): 123 mm tall, printed standing; it has a brim, but watch the first hour.
11. **`16_telescope_seat`** (40 min, 19 g): print it with the engraved face on the bed.

Four parts changed after the earlier slices, so use the current files: `02_base_spider` (now 216 mm wide, with the azimuth
end-stop extension and the preload peg block), `03_az_plate` (end-stop tab and preload post), `07_tilt_plate_2` (longer, with a wing for the tower) and `09_top_plate`
(10 mm longer, four cradle inserts, the altitude end-stop ear, two dowel holes for the telescope seat).

Total about 34 h and 854 g of PETG, including the coupon. The tilt plate and top plate are 227 x 144 mm and 210 x 144 mm:
the parts sit inside the bed, but the first-layer brim reaches the printable edge (X = 0.2 to 255.8 mm on the tilt plate, 2.8 to 253.2 on the spider).
If your printer objects, set `brim_type` to `no_brim` in `slicer/profiles/process.json` and re-slice.

## Print settings baked into the G-code

Bambu Lab X1C, 0.4 mm nozzle, Bambu PETG Basic (255 C nozzle, 70 C bed), **Textured PEI plate**, 0.20 mm layers, 4 walls,
30% gyroid, no supports (the motor boss hole is a teardrop so it needs none), brim as the profile decides. The profile is
OrcaSlicer 2.5.0's own X1C profile (see `slicer/profiles`), fetched from the official OrcaSlicer repository at tag v2.5.0.
The coupon uses a lighter variant (2 walls, 8% infill, no brim).

Notes:
- If you print on the Engineering plate, change `curr_bed_type` in `slicer/profiles/*.json` and re-slice. Bambu's PETG profile
  does not allow the Cool plate.
- **Raw `.gcode` on a Bambu printer is untested.** Bambu printers normally run `.gcode.3mf` sent from Bambu Studio or
  OrcaSlicer. If your printer refuses the raw files, open the STLs in Bambu Studio and apply the settings above instead.
  `verify_gcode.py` confirms bed bounds, temperatures and the start/end macros, not that your firmware accepts the file.
- The print orientation puts layer lines across the motor face plate, which is loaded in bending by the lead screw. A
  back-of-envelope estimate gives a few MPa at the plate root against roughly 20 MPa typical PETG layer adhesion, with
  gussets. That is a rough figure, not a calculation of record: inspect the part after the first run.

## Measure before printing the big parts

The spider and azimuth plate assume things I could not look up. Measure on your parts and edit `cad/aligner_cad.py`:

| Constant | Assumed | Measure |
|---|---|---|
| `LS_H` | 12 mm | lazy-Susan thickness |
| `LS_SLOT` | bolts between r = 34 and 62 mm on the +/-x and +/-y axes | bolt-hole radius and where the holes sit (slots cover a range) |
| `NEMA17` | 42.3 mm square, 31 mm hole spacing, 22.6 mm boss hole | your motor |
| 3/8-16 nut | 14.3 mm across flats, 8.3 mm thick | your nut |

## Design decisions worth knowing

- **Azimuth drive.** The rod runs horizontally at radius 80 mm, tangent to the azimuth bearing and entirely outside the 75 mm
  plate disc. The motor sits on the fixed spider, the nut trunnion on the rotating plate. Resolution is 12.9 arcsec per full
  step (M6x1 on an 80 mm arm). The nut block pivots +/-6 deg about a vertical axis.
- **Spider is 12 mm thick** so the single 3/8-16 nut fits inside it without the hub touching the azimuth plate. An earlier
  24 mm hub collided with the plate; the clearance check caught it.
- **Clearance results** (minimum gap over -6..+6 deg): spider to azimuth plate 2.9 mm, motor and rod to plate 7.0 mm, nut block
  to yoke 0.5 mm (designed running clearance).
- **Azimuth reach shrinks with latitude.** Turning the azimuth stage by 1 degree moves the polar axis only cos(latitude) degrees
  on the sky, so the +/-5.75 degree usable travel gives about +/-5.2 degrees of east-west reach at 25 N, +/-3.8 at 48 N and +/-2.7 at
  62 N (from the software review). The design doc's "+/-6 degrees absorbs a rough set-up" gets tight above about 45 degrees
  latitude: set the base within a few degrees of north by compass there, or widen the azimuth travel (the rod and arm allow more;
  the end stops would move with it). **Decision: the travel stays at +/-6 degrees.** The software reports "fine travel exhausted"
  rather than hitting a stop.
- **Azimuth preload** is a spring between a post on the azimuth plate's rim and one of three pegs on the spider: see below.
- **Dowel pins:** each trunnion needs two 3 mm steel dowels, about 8-9 mm long (one per side), so four for the two trunnions
  in use. The BOM's fastener line covers them.

## Tall-hinge tilt stage (Batch 2a)

Chosen over a commercial wedge because it keeps everything printed and inside the budget. From the bottom up:

- **Coarse hinge.** Two printed cheeks bolt to the azimuth plate (x = -20 mm, 56 mm above the plate). An 8 mm steel pin,
  124 mm long, runs through them and through 608 bearings in the tilt-plate arms. Tilt is locked by one M6 bolt (about
  130 mm long) through both cheeks and both arms; it rides in an arc slot of radius 40 mm that covers plate tilts of 15 to
  100 degrees, which is latitude 75 down to -10. Friction clamping only: tighten it with a wrench, not just a wing nut.
- **Tilt plate** (two printed pieces, because one would be longer than the bed). The plate hangs *below* the hinge so it
  prints flat with no supports. The second piece is the motor beam, lapped under the end of the first and bolted with four M4.
- **Altitude hinge.** Two more cheeks, bolted on top of the tilt plate, 54 mm above it. 8 mm pin, 140 mm long. The top plate
  is printed upside down so its seat face is the smooth bed side and its lugs and tabs need no supports.
- **Altitude drive.** M6x1 rod on a 150 mm tangent arm: 6.9 arcsec per full step, +/-6 deg is +/-15.8 mm of travel. The
  NEMA 17 hangs under the motor beam with its shaft up, so the stack above the plate is coupler, rod, then the nut block.
  The arm is long so the rod stands outside the telescope's footprint. Cut the rod so its top is about 10 mm above the top plate at
  mid travel (28 mm above it at the low end of the travel); it only has to clear the nut at full raise.
- **Telescope seat.** A 3/8-16 bolt, head held in a hex pocket under the plate, with a 4 mm seat disc on top: see below.
- **Preload.** Two extension springs between the beam and the top plate (about 74 mm apart, so choose springs that suit that
  length). The azimuth axis has no preload parts yet.

**Whole-stack sweep** (`cad/check_assembly.py`): 34 poses covering latitude -10 to 75 degrees in 10-degree steps, altitude
-6/0/+6 degrees, azimuth -6/0/+6 degrees at the extremes, with a 142 x 130 x 257 mm box standing in for the Seestar S50.
No collisions. It did find one real clash at the first attempt (the tilt-plate arm tip clipped the azimuth plate by 0.9 mm at
latitude 25 with the hinge 82 mm up), fixed by raising the hinge to 86 mm. Deliberate gaps are 0.30 mm (nut block in its
yoke), 0.50 mm (arms against cheeks) and 1.0 mm (hinge lugs against altitude cheeks); every other pair is at least 2.5 mm apart.

**Centre of gravity** (about 3.75 kg all-in with a 2.5 kg telescope and the electronics case; printed parts at 40% effective
infill; telescope CoG assumed 100 mm above the seat; case with electronics assumed 450 g), measured from the bearing axis,
x toward the pole:

| Latitude | CoG x | CoG height |
|---|---:|---:|
| 0 | +86 mm | 178 mm |
| 25 | +34 mm | 212 mm |
| 45 | -14 mm | 221 mm |
| 65 | -63 mm | 213 mm |

The case hangs on the side away from the pole, so it counterbalances the telescope and pulls the CoG back by 20-30 mm.
Set one tripod leg pointing toward the pole (north in the northern hemisphere, south in the southern) and spread the legs fully.
A friction-lock estimate (rough, not a calculation of record): about 3 N.m of tilting moment at latitude 0 needs about 85 N at
the 40 mm lock radius, against roughly 500 N of clamp from a hand-tightened M6 bolt over four printed interfaces at a
friction coefficient near 0.3.

**Limits of these checks:** the motors, coupler, rod, nut block and telescope are simplified boxes and cylinders; pins,
bearings, screws and springs are not modelled; the telescope box is bigger than the real S50, so that check is conservative.

## Electronics case (`10_electronics_case`, `11_case_lid`)

139.4 x 81.8 x 42.7 mm. It hangs **under the main tilt plate** (four M4 screws come down through the plate into heat-set
inserts in the case floor) and tilts with it, so the IMU on the carrier reads the plate tilt directly. It is not weatherproof:
the cable slots are open, so keep it out of dew and rain, or add your own seal.

- **Inside:** the carrier PCB on four 14 mm posts, parts facing the lid; the Pi Zero 2 W hangs beneath it on its socket (it
  overhangs the PCB's south edge by about 14.5 mm, which the case allows for); a 38 mm bay on the east side for the PD trigger
  and buck modules, held with tie-wraps through slots in the floor.
- **Fit, measured on the models:** the PCB envelope (including the 17.1 mm tall TMC2209 with heatsink, an assumed height) and
  the Pi envelope have zero overlap with the case; 2.0 mm to the lid, 2.4 mm under the Pi, 1.5 mm from the Pi to the south wall.
- **Cable slots** follow the real connector positions read from the PCB (`pcb/connectors.json`): power terminals and motor
  connectors on the north wall, the 5 V terminal and the sensor headers on the west wall, the four end-stop connectors on the
  south wall. Slots are 12 mm tall above the PCB surface.
- **Guesses to check when the parts arrive:** the camera ribbon slot (south wall, at Pi level), the USB-C opening for the PD
  trigger (east wall), and the size and position of the two modules. Enlarge slots with a knife or edit
  `cad/aligner_case.py`.
- **Hardware:** 4 x M4 heat-set inserts and screws for the plate, 8 x M3 inserts (4 for the PCB posts, 4 for the lid),
  4 x M3 x 6 for the PCB and 4 x M3 x 10 for the lid. The IMU's axes are not aligned to the plate by design; the software must
  calibrate the offset.
- **Whole-stack sweep with the case:** still no collisions; the case stays more than 6 mm from every other part.

## Camera cradle, camera plate and dew shield (`12_cam_cradle`, `13_cam_plate`, `14_dew_shield`)

Built for the **Waveshare IMX296 Global Camera (A)** and its 16 mm C-mount lens. Camera dimensions are from Waveshare's own outline
drawing: board 38 x 38 mm, 1.6 mm thick; four 2.5 mm holes on a 30 x 30 mm square; a 28.5 mm mount boss 12.5 mm above the board
(CS mount, before the included 5 mm C-CS adapter, which gives the standard 17.5 mm C-mount flange distance); a 15-pin connector
2.5 mm deep on the back. The Waveshare 16 mm lens is 39 mm across and 50 mm long, about 134 g.

**Read this about the camera:** Waveshare's page lists it as a **colour** sensor with an **integrated IR-cut filter**, not the monochrome
IMX296 the design doc assumed, and shows it as **DISCONTINUED**. A colour Bayer sensor with an IR-cut filter collects noticeably
less starlight than mono, which the software has to absorb with longer exposures. It still plate-solves. If you want mono, a
different board needs a different plate (the cradle and dew shield would still fit).

- **Cradle.** Bolts to the top plate with four M3 screws into inserts under the plate, standing beyond the altitude rod (the
  rod is 4.9 mm from the cradle in the sweep). Two cheeks hold the 44 x 44 x 6 mm camera plate on two M4 pivot bolts; two more
  M4 bolts ride in arc slots (tilt -5 to 50 degrees) and clamp the angle. It tilts toward the far end of the plate, away from the
  rod and the telescope and up toward the sky for northern sites.
- **Camera plate.** The board sits on its rear face on four M2.5 heat-set inserts, with the boss passing through the 32 mm hole.
  The ribbon connector faces the rod side; the cable leaves at the board edge.
- **Dew shield.** A slit tube that clamps on the lens barrel with one M3 bolt: 28 mm over the barrel and 25 mm beyond the front.
  I sized the 25 mm so a 41 mm bore does not clip the lens's 22.3 degree diagonal field, assuming a 30 mm front element (about
  12.4 degrees of clear half-angle against the 11.1 needed). I could not confirm the front-element size; check on the real lens.
- **Checks.** The sweep now includes the board, boss, lens, shield and a cone for the camera's field of view, at 0, 10, 25 and 40
  degrees tilt over 32 poses of the whole stack: no collisions, and nothing blocks the field of view (the telescope box included).
  The lock holds a 165 g camera and lens a few centimetres from the pivot, about 0.07 N.m, which two clamped bolts should
  manage; that is an estimate, not tested.
- **Guesses to confirm:** the M2.5 insert pocket size (3.6 x 4.5 mm, add it to the fit-test coupon if you want to be sure), and
  the lens front-element size above.

## End stops (`15_alt_endstop_tower` plus features on the spider, azimuth plate, motor beam and top plate)

Four micro limit switches, two per axis, wired to the carrier's J7 to J10. Which one is "min" and which is "max" depends on your
motor wiring, so let the software find out (home toward a known direction and see which one trips). The PCB reads each switch
against its internal pull-up, so wire **common and normally-closed** to the connector: a pressed or broken switch then reads as
a trip, which is the safe way round.

**Switch assumptions, not confirmed:** body about 20 x 10.5 x 6.5 mm (two seller datasheets give 20 x 10 x 6 and 20 x 10.5 x 6.5),
9.5 mm hole spacing, and a lever with the roller 14 mm past the body end and 3 mm off its face. The switches screw down with
M2 self-tapping screws into 1.9 mm pilot holes. I could not find a drawing for the lever, so if yours differs the trigger angles
move: a roller 1 mm off shifts the azimuth trigger by about 0.7 degrees and the altitude trigger by about 0.3.

- **Azimuth.** A tab on the rim of the azimuth plate (on the -x side) swings between two switch blocks on an extension of the
  spider's -x arm (the spider is now 216 mm wide). The blocks stop 1.5 mm under the azimuth plate. Trigger at **8.05 degrees**,
  2.05 past the +/-6 working range; the tab would touch a switch body at 11.0 degrees.
- **Altitude.** An ear on the far end of the top plate swings between two switches on a 123 mm tower bolted to a widened motor
  beam (+y side). The lower switch is pressed by the ear's underside when the plate drops, the upper by its top face when the plate
  rises. Triggers at **7.35 and 7.15 degrees**, with body contact at 9.35 and 9.15. The jackscrew's own hard limit is about 9
  degrees (the nut block reaches the coupler), so the software must stop at the switch, not run into it.

`cad/check_stops.py` sweeps each axis and prints the trigger and body-contact angles; the whole-stack sweep now includes the tower,
the switch bodies and the spider extension (278 part pairs, no collisions; the ear tip is 1.5 mm from the tower wall by design).
Not verified: the lever figures above, and how stiff a 123 mm printed tower is under vibration (it only carries a 0.5 N switch,
but check that it does not sway).

## Azimuth preload spring

The azimuth screw has no gravity bias, so an extension spring keeps one thread flank loaded. It runs from an M3 screw (with a
washer to hold the hook) in an insert on a rim tab of the azimuth plate, to one of **three M3 pegs** on a block on the spider's +y
arm. It pulls the plate **clockwise** seen from above, so the software should finish every azimuth move in the clockwise
direction (decreasing angle) for the most repeatable result.

The spring's length changes by about 18 mm over the plate's +/-6 degrees, so the peg has to suit the spring: it must stay
stretched at the most slack point and not pull too hard at the other end. `cad/check_preload.py L0 k F0` (free length in mm,
rate in N/mm, initial tension in N) tells you which peg to use. For example a 25 mm spring at 0.3 N/mm and 0.7 N on the middle
peg (x = 22) gives 3 to 8.5 N and 0.27 to 0.72 N.m over the whole travel; a 32 mm spring at 0.2 N/mm wants the outer peg, and a
stiff 18 mm spring at 0.5 N/mm suits none, so avoid springs stiffer than about 0.4 N/mm. The 0.10 N.m minimum torque that the
script requires is my estimate of what holds the nut against bearing friction and cable drag, not a measured figure. The
whole-stack sweep now includes the spring (303 part pairs, no collisions).

## Telescope seat (`16_telescope_seat`)

**Why an index and not a key.** The S50's azimuth axis is its thread axis, so turning the telescope on the stud does not change
where that axis points. What does change is the small tilt between the telescope's axis and its own base, which turns with it:
reseating at a different yaw shifts the camera-to-axis calibration by roughly t x (yaw difference in radians), where t is that
internal tilt. I do not know t for the S50; at an assumed 0.2 degrees, landing within one 15-degree tick costs about 0.05
degrees and within two ticks about 0.1, against a 0.1 degree target. That is my reasoning and an assumption, not a
measurement, and it is why a mark good to a tick or two is enough. A true mechanical key needs the shape of the S50's underside,
which I could not find published (details below).

- **The disc.** 90 mm across, 4 mm thick, printed with its seat face on the bed so that face is as flat as the printer's bed.
  It has a 9.8 mm centre hole for the stud, two 3 mm dowel pins (3 x 8 mm) that go into blind holes in the top plate and
  locate it so its arrow always points toward the camera end (+p), ticks every 15 degrees with longer ones every 90, and an arrow.
  An aluminium disc of the same drilling would be flatter still.
- **Procedure.** Put a paint-pen dot on the S50's base at a fixed feature (for example the front), screw the telescope down
  hand-tight, and note which tick the dot lands on. Aim to end on the same tick, within one or two, every time, and record that
  tick next to the calibration.
- **Stud length rule (do this before the first mount).** The stud must not bottom in the S50's socket before its base touches
  the disc, or the telescope will sit tilted. The stud stands **bolt length minus 11 mm** above the disc, so the 19 mm bolt
  stands 8 mm. Measure the socket depth with calipers or a depth gauge; the stand-up must be at least 2 mm less than it. The
  socket depth is not published for the S50 and I have not confirmed it. The thread is 3/8-16 UNC (the ZWO manual and several
  user reports), not 3/8-20.
- **Check the seating.** After tightening, a strip of paper (about 0.05 mm) should not slide in between the telescope's base and
  the disc anywhere around the edge.
- **What a mechanical key would need.** The diameter of the S50's flat bearing surface and whether it has a recess, rubber feet, a
  notch or pins. If you can measure those (a photo of the underside with a ruler is enough), I can add a locating feature to the
  disc.

## Still not built

Nothing that can be built without a measurement. A mechanical key on the telescope seat was considered and declined: the index
disc is the design, and a key would need the S50's underside geometry (see the seat section). Every other part in the original
list is built.

## Regenerate everything

```bash
cd hardware
python cad/aligner_cad2.py stl        # all STLs (Batch 1 and Batch 2a)
python cad/check_clearance.py         # azimuth interference check
python cad/aligner_case.py stl        # electronics case and lid
python cad/aligner_cam.py stl         # camera cradle, plate and dew shield
python cad/check_stops.py             # end-stop trigger angles and margins
python cad/check_preload.py 25 0.3 0.7   # which azimuth spring peg suits your spring
python cad/check_assembly.py          # whole-stack sweep, latitude -10..75
./slicer/slice_all.sh                 # G-code (needs OrcaSlicer installed)
python slicer/verify_gcode.py gcode/*.gcode
```

The CAD script needs `manifold3d`, `numpy` and `trimesh`.

## Carrier PCB (summary)

An 85 x 60 mm two-layer board that plugs onto the Pi Zero 2 W header and carries both TMC2209 drivers, the 12 V protection,
the shared UART, four filtered end-stop inputs and two I2C sensor headers. It was judged necessary rather than optional; the
doc's perfboard would do for a first bench test (the BOM prices both). Everything is in `pcb/`.

Verified by `pcb/check_independent.py` (8 of 8 pass, computed from the KiCad and Gerber files): pin map equals the netlist,
25 standard footprint dimensions, minimum clearance 0.291 mm, copper at least 1.7 mm from the edge, all 35 non-GND nets
connected with no shorts, every hole matches the drill files, Gerbers fit the outline.

**Cautions found by the software review (act on these before powering the board):**
- **TMC2209 pin order.** The netlist puts PDN_UART on module pin A4. On some SilentStepStick-format boards pins 4 and 5 are
  DIAG/INDEX *outputs* and PDN_UART is reached through a solder bridge; tying such an output to the shared UART bus fights two
  push-pull outputs. Check your module against its drawing and a multimeter **before plugging both in**.
- **5 V on the I2C headers.** J11 and J12 carry 5V_F on pin 3. A breakout powered from 5 V that has its own pull-ups to VCC puts
  5 V on SDA/SCL, which the Pi's 3.3 V GPIO will not survive. Power the IMU and GNSS from 3V3 (pin 2) unless the board is known to
  level-shift or pull up to 3.3 V.
- **End-stop wiring.** Wire common and normally-closed, as described under End stops. The software defaults to that (HIGH =
  tripped), so its self-test reports a stop as tripped until the switch is connected.
- **No stall-detect pin is routed**, so homing relies on the mechanical switches only.

**Not verified:** KiCad's own ERC/DRC (KiCad is not installed here, so the KiCad files have never been opened in it; press
B in KiCad to fill the GND pours); GND pour continuity; that your TMC2209 modules use the Pololu footprint and pin order (the
source was a generic BTT wiki page); the Pi header orientation (compare "PI PIN 1" on the silkscreen with your Pi before power);
heights of the PTC, capacitors and terminals (assumed typical). Some silkscreen labels overlap or were omitted for space.
Order PTC fuses rated 30 V or more, and check the lead pitch on the part you buy.

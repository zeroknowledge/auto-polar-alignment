# Bill of materials

Prices are indicative USD estimates, **not checked against live listings**. The USB-C PD power bank is already owned and excluded.
Source of truth: `bom.csv` (this file is generated from the same table).

| ID | Category | Item | Qty | Unit | Ext | Phase | Notes |
|---|---|---|---:|---:|---:|---:|---|
| B01 | Compute | Raspberry Pi Zero 2 W (pre-soldered header) | 1 | 18.00 | 18.00 | 0 | WH variant avoids soldering the 40-pin header. 512 MB RAM. |
| B02 | Compute | microSD 32 GB, A1/A2 | 1 | 8.00 | 8.00 | 0 | Raspberry Pi OS Lite 64-bit, headless. |
| B03 | Camera | Waveshare IMX296 Global Camera (A), SKU 32501 | 1 | 82.99 | 82.99 | 0 | COLOUR sensor with an integrated IR-cut filter (not mono as the design doc assumed). Listed DISCONTINUED on waveshare.com when checked; $82.99 list price. Includes a 15-to-22-pin and a 15-pin CSI cable, the C-CS adapter and a dust cap; no lens. Needs dtoverlay=imx296 (no mono). |
| B04 | Camera | CSI ribbon cable, 22-pin to 15-pin | 1 | 0.00 | 0.00 | 0 | Included with the Waveshare camera (the Zero has the small 22-pin port). |
| B05 | Camera | 16 mm C-mount lens (Waveshare 16 mm telephoto: dia 39 x 50 mm, 134 g, f/1.4-16) | 1 | 22.00 | 22.00 | 0 | The cradle and dew shield are sized for this lens. Price is my estimate, not checked. |
| B06 | Motion | NEMA 17 pancake stepper, 20-25 mm body, <=1 A/phase | 2 | 13.00 | 26.00 | 1 | Run at 0.4-0.6 A. Take 5 mm D-shaft. |
| B07 | Motion | TMC2209 driver module (SilentStepStick format) | 2 | 5.50 | 11.00 | 1 | Pick a board that exposes MS1/MS2 so both drivers share one UART via addresses 0 and 1. |
| B08 | Motion | Micro limit switch with roller lever (KW12-3 class) | 5 | 1.00 | 5.00 | 1 | 4 used: two per axis. 5 bought, 1 spare. The mounts assume a body of about 20 x 10.5 x 6.5 mm with 9.5 mm hole spacing and a roller lever; confirm on the switches you buy. |
| B09 | Motion | M2 x 8 self-tapping screws, small pack | 1 | 1.50 | 1.50 | 1 | Eight hold the four end-stop switches into their pilot holes. |
| B10 | Motion | Flexible shaft coupler 5 mm to 6 mm | 2 | 2.50 | 5.00 | 1 | Absorbs the +/-6 deg swing of the screw as the arm turns. |
| B11 | Motion | M6x1 stainless threaded rod, 1 m | 1 | 7.00 | 7.00 | 1 | M6 coarse pitch is 1.0 mm: 0.716 deg/turn on an 80 mm arm. Do NOT substitute T8x8 (8 mm lead, back-drives). |
| B12 | Motion | Brass hex nut M6, pack of 10 | 1 | 3.00 | 3.00 | 1 | Brass on stainless for low friction. Held in a printed trunnion. |
| B13 | Motion | Extension springs, assorted pack | 1 | 8.00 | 8.00 | 1 | Anti-backlash preload. Altitude: two springs that suit about 74 mm between hooks when installed. Azimuth: one spring of roughly 25 mm free length and 0.3 N/mm (run cad/check_preload.py with your spring's figures to pick the peg). Buy a pack with a spread of lengths and rates. |
| B14 | Structure | 608ZZ bearing, pack of 10 | 1 | 6.00 | 6.00 | 1 | Hinge pins and screw-end support. |
| B15 | Structure | 8 mm ground steel rod, 300 mm | 1 | 6.00 | 6.00 | 1 | Hinge pins: cut one 124 mm (coarse hinge) and one 140 mm (altitude hinge), 264 mm in all, and chamfer the ends. |
| B16 | Structure | 6 in aluminium lazy-Susan turntable bearing | 1 | 12.00 | 12.00 | 1 | Azimuth stage. Watch axial wobble: measure it. Upgrade path is a cross-roller slewing ring. |
| B17 | Structure | 3/8-16 x 3/4 in (19 mm) hex bolt (the telescope stud) | 2 | 2.00 | 4.00 | 1 | One used, one spare. The stud stands (length - 11 mm) above the seat disc, so 19 mm gives 8 mm. Measure the depth of your S50's socket first: the stud must stand up less than that, or the telescope will tilt on a bottomed stud. Order 1 in (25 mm) as well if the socket is deeper than 14 mm. |
| B18 | Structure | 3/8-16 hex nut, standard thickness (about 8.3 mm, 9/16 in across flats) | 2 | 2.00 | 4.00 | 1 | One sits in the hex pocket of the base spider and threads onto the tripod stud; the spare is for a miscut. Not a coupling nut (those are about 28 mm long and will not fit). Do not rely on a printed 3/8-16 thread. |
| B19 | Structure | 3/8-16 to 1/4-20 reducer bushing | 2 | 2.50 | 5.00 | 1 | For photo tripods; also the Dwarf 3 adapter if wanted. |
| B20 | Structure | Heat-set inserts M3/M4/M5/M6 assortment | 1 | 12.00 | 12.00 | 1 | Brass, for printed parts. |
| B21 | Structure | Fastener assortment: M3/M4/M5/M6 socket-head, washers, nuts, 3 mm dowel pins | 1 | 15.00 | 15.00 | 1 | Stainless where outdoors. |
| B22 | Structure | Wing nut or star knob M6 | 2 | 1.50 | 3.00 | 1 | Coarse-tilt lock. |
| B23 | Structure | PETG filament, 1 kg spool | 2 | 20.00 | 40.00 | 1 | 854 g for every printed part including the coupon; the second spool covers reprints and failed prints. Print with an enclosed X1C/P1S: no PLA (creep). |
| B24 | Structure | Adhesive felt feet + black flocking paper | 1 | 5.00 | 5.00 | 1 | Feet, and dew-shield lining. |
| B25 | Structure | M2.5 heat-set inserts + M2.5 x 8 screws, small pack | 1 | 5.00 | 5.00 | 1 | Four of each hold the camera board to its plate. |
| B26 | Structure | Cable ties 2.5 x 100 mm, assorted pack | 1 | 2.50 | 2.50 | 1 | Hold the PD trigger and buck modules in the case bay, and tidy the wiring. |
| B27 | Structure | M6 x 130 mm bolt + nut (coarse tilt lock) | 1 | 2.50 | 2.50 | 1 | Passes through both coarse cheeks and both tilt-plate arms; tighten with a wrench. |
| B28 | Power | USB-C PD trigger board, 12 V | 1 | 4.00 | 4.00 | 1 | Check the power bank really offers 12 V PD; many only offer 9/15/20 V. |
| B29 | Power | 12 V to 5 V buck converter, 3 A, low-noise | 1 | 8.00 | 8.00 | 1 | Pololu D24V22F5 class. Separate 5 V rail for the Pi. |
| B30 | Power | 24 AWG silicone wire, ferrules, heat shrink | 1 | 6.00 | 6.00 | 1 | Motor, end-stop and power harness. |
| B31 | Sensors | ICM-20948 IMU breakout (I2C) | 1 | 15.00 | 15.00 | 3 | Coarse tilt and knock detection. Compass is a rough guide only. |
| B32 | Sensors | u-blox M8/M9 GNSS breakout with I2C (DDC) pins and antenna | 1 | 14.00 | 14.00 | 3 | Verify the board exposes SDA/SCL before ordering: many cheap boards are UART-only and the Zero has no spare UART. |
| B33 | PCB | Carrier PCB, 2-layer ~85x60 mm, 5 pcs (fab order incl. shipping) | 1 | 23.00 | 23.00 | 1 | Upload pcb/fab/carrier_gerbers.zip. Five is the usual minimum order; shipping dominates the price. |
| B34 | PCB | Screw terminal 5.08 mm, 2-pin | 3 | 0.70 | 2.10 | 1 | 12 V in, 12 V to the buck module, 5 V from the buck module. |
| B35 | PCB | JST-XH kit with crimp pins (2-pin and 4-pin) | 1 | 9.00 | 9.00 | 1 | 2x 4-pin for motors, 4x 2-pin for end stops, plus the mating housings. |
| B36 | PCB | 2.54 mm headers: 1x 2x20 female, 4x 1x8 female, 2x 1x5, 1x 1x2 + jumper | 1 | 5.00 | 5.00 | 1 | Pi socket, TMC2209 sockets, I2C, JP1. |
| B37 | PCB | PTC resettable fuse, 2 A hold, radial, 5.08 mm lead pitch, rated 30 V or more | 2 | 1.00 | 2.00 | 1 | One on the 12 V rail, one on the 5 V rail. The TVS clamps near 25 V, so a 16 V-rated PTC is too low on the 12 V rail. Check lead pitch and rating on the part you buy. |
| B38 | PCB | 1N5822 Schottky + 1.5KE18A TVS | 1 | 1.20 | 1.20 | 1 | Reverse-polarity and surge protection on the 12 V input. |
| B39 | PCB | Electrolytic: 1x 220 uF/35 V, 2x 100 uF/35 V | 1 | 2.50 | 2.50 | 1 | Bulk capacitance at the input and at each driver's VM. |
| B40 | PCB | 0805 assortment: 100 nF, 1 k, 10 k, red LED | 1 | 8.00 | 8.00 | 1 | 6 capacitors, 7 resistors, 1 LED. Min packs are far larger than needed. |

**Total: $419.29** (design doc estimated $236; budget $300)

## Cumulative spend by phase

| Phase | New spend | Cumulative |
|---:|---:|---:|
| 0 | $130.99 | $130.99 |
| 1 | $259.30 | $390.29 |
| 3 | $29.00 | $419.29 |

## Optional / upgrade items (not in total)

| Item | Why | Est. |
|---|---|---:|
| SHT31 temperature/humidity sensor (I2C) | Dew warning. | 4.00 |
| 5 mm aluminium plate cut set (hinge leaves, top plate) | Phase-2 stiffness upgrade; I will supply DXF if the printed version sags. | 40.00 |
| Cross-roller slewing ring ~100 mm | If lazy-Susan wobble exceeds about 0.05 deg. | 45.00 |
| Pi heatsink | Gulf summer. | 2.00 |

## Budget check (honest version)

- Buying everything new, in real pack sizes, is **$419.29**: $119.29 over the $300 budget and $183.29 over the doc's $236.
- **Phases 0-2 (everything except IMU/GNSS) cost $390.29**, $90.29 over the budget. Phase 3 sensors add $29.00.
- The doc's lump sums ($30 motion hardware, $25 structure, $10 sundries) assume fasteners, inserts, filament and wire come from a parts bin. Itemised and bought as packs, those lines cost more.

| Category | Total |
|---|---:|
| Compute | $26.00 |
| Camera | $104.99 |
| Motion | $66.50 |
| Structure | $122.00 |
| Power | $18.00 |
| Sensors | $29.00 |
| PCB | $52.80 |

### Ways back under $300 for the full build

- Use fasteners, inserts and filament you already own: up to -$72.00 (heat-set inserts, fastener assortment, filament, felt and flocking paper).
- A $20-30 IMX462 colour module (doc estimate) instead of the $82.99 Waveshare IMX296: about -$57. Rolling shutter does not matter for a static star field, but it is a different board, so the camera plate would need a new design.
- Phone supplies location and time instead of the GNSS module: -$14 (the camera solve needs neither; only a rough date for precession).
- 28BYJ-48 motors instead of NEMA 17 (doc estimate): about -$25, at a stiffness and torque cost.
- Worked example (keeps the PCB and every sensor): parts-bin fasteners/filament (-$72) and an IMX462 camera instead (-$57, needs a different camera plate) bring the full build to $290.
- **Perfboard instead of the carrier PCB: about -$39.** The PCB route (fab order plus connectors, protection and passives) costs $52.80; a perfboard build is about $14 (board, JST-XH housings, wire). The PCB is the recommended route; the perfboard build skips the reverse-polarity/surge protection and the debounce filters unless you hand-wire them.

## Differences from the design doc BOM

- The camera is the Waveshare IMX296 Global Camera (A): a colour sensor at $82.99 (the doc priced a $55 mono board). It includes the 22-pin to 15-pin CSI cable the Zero needs.
- Specified M6x1 threaded rod and brass nuts; the doc also mentions T8 lead screws, which are 8 mm lead and would break the 0.01 deg resolution requirement.
- Added shaft couplers, a separate buck converter and an explicit azimuth bearing.
- Replaced the doc's perfboard with a carrier PCB (see `pcb/`), which adds protection, filtering and sockets the doc did not list.
- Filament/fasteners/inserts are itemised rather than a lump sum.

# Carrier PCB spec ("APA-CARRIER")

A 2-layer through-hole-first carrier that plugs onto a Raspberry Pi Zero 2 W 40-pin header and carries two TMC2209
stepper-driver modules, power distribution, four end-stop inputs and two I2C sensor headers.

**Why a PCB (not perfboard):** shared single-wire UART with address strapping, 12 V motor rail with bulk caps and
protection, four RC-filtered end-stop inputs, and a mechanically solid stack that survives field use and dew.

## Electrical design (authoritative; do not change pin assignments without flagging it)

### Pi header (J1, 2x20, 2.54 mm female socket, mounted on the BOTTOM side so the board stacks above the Pi)

Pin numbers are standard 40-pin numbering (pin 1 = 3V3, pin 2 = 5V).

| Pi pin | GPIO | Net | Notes |
|---|---|---|---|
| 1, 17 | | 3V3 | |
| 2, 4 | | 5V_PI | fed from 5V_F through jumper JP1 |
| 6, 9, 14, 20, 25, 30, 34, 39 | | GND | |
| 3 | GPIO2 SDA1 | SDA | Pi has on-board 1.8k pull-ups: add none |
| 5 | GPIO3 SCL1 | SCL | |
| 8 | GPIO14 TXD | UART_TX_RAW | goes through R1 (1k) into UART_BUS |
| 10 | GPIO15 RXD | UART_BUS | direct |
| 11 | GPIO17 | STEP_AZ | |
| 13 | GPIO27 | DIR_AZ | |
| 15 | GPIO22 | EN_AZ | R2 10k pull-up to 3V3 (driver disabled at boot) |
| 16 | GPIO23 | STEP_ALT | |
| 18 | GPIO24 | DIR_ALT | |
| 22 | GPIO25 | EN_ALT | R3 10k pull-up to 3V3 |
| 29 | GPIO5 | ES_AZ_MIN | via RC filter (see end stops) |
| 31 | GPIO6 | ES_AZ_MAX | |
| 33 | GPIO13 | ES_ALT_MIN | |
| 35 | GPIO19 | ES_ALT_MAX | |
| 37 | GPIO26 | SPARE | test point TP5 only |
| all others | | NC | leave unconnected |

### TMC2209 module sockets (U1 = azimuth, U2 = altitude)

Each module is plugged into two 1x8 female 2.54 mm sockets, rows **12.70 mm (0.5 in) apart** (SilentStepStick / Pololu
layout; 15.2 mm is the module's board width, not the row spacing, per Pololu's A4988 dimension drawing: 15.2 x 20.3 mm
board, 2.54 mm pitch, pins 1.27 mm in from each end). The BIGTREETECH TMC2209 is assumed to share this footprint:
unverified, flag it in the README. Pin order per the BIGTREETECH wiki (generic TMC2209 page; **not confirmed for the V1.3 revision, flag this in
the README**):

- Row A (pins A1..A8): EN, MS1, MS2, PDN_UART, PDN_UART_ALT (leave NC), CLK, STEP, DIR
- Row B (pins B1..B8): VM, GND, COIL_A2, COIL_A1, COIL_B1, COIL_B2, VIO, GND

Connections per module:

| Module pin | U1 (AZ) net | U2 (ALT) net |
|---|---|---|
| A1 EN | EN_AZ | EN_ALT |
| A2 MS1 | GND (UART address 0) | 3V3 (UART address 1) |
| A3 MS2 | GND | GND |
| A4 PDN_UART | UART_BUS | UART_BUS |
| A5 PDN_UART_ALT | NC | NC |
| A6 CLK | GND (internal clock) | GND |
| A7 STEP | STEP_AZ | STEP_ALT |
| A8 DIR | DIR_AZ | DIR_ALT |
| B1 VM | +12V | +12V |
| B2 GND | GND | GND |
| B3..B6 coils | to J5 pins 1..4 | to J6 pins 1..4 |
| B7 VIO | 3V3 | 3V3 |
| B8 GND | GND | GND |

R1 = 1 kOhm in series between UART_TX_RAW and UART_BUS. UART_BUS joins Pi RXD directly, both modules' PDN_UART pins.

### Power

- J2 (screw terminal 5.08 mm, 2-pin): pin 1 = 12V_RAW, pin 2 = GND. From the USB-C PD 12 V trigger board.
- F1 PTC (2 A hold) in series: 12V_RAW -> F1 -> 12V_FUSED.
- D1 Schottky (1N5822 or equivalent, 3 A / 40 V axial) reverse-polarity protection: anode 12V_FUSED, cathode +12V.
- D2 TVS 1.5KE18A (axial), cathode on +12V, anode on GND, placed right after D1.
- C1 220 uF/35 V, C2 100 uF/35 V (at U1 VM), C3 100 uF/35 V (at U2 VM): radial electrolytics, +12V to GND, polarity marked.
- J3 (screw terminal, 2-pin): pin 1 = +12V, pin 2 = GND. Output to the buck converter module's input.
- J4 (screw terminal, 2-pin): pin 1 = 5V_BUCK, pin 2 = GND. Input from the buck module's 5 V output.
- F2 PTC (2 A hold): 5V_BUCK -> F2 -> 5V_F.
- JP1 (1x2 header, jumper): 5V_F <-> 5V_PI. **Remove when powering the Pi over USB** (the Zero has no back-feed protection).
- LED1 (0805, red) + R8 1 kOhm from 5V_F to GND.
- Test points (1.0 mm drill pads): TP1 +12V, TP2 5V_F, TP3 3V3, TP4 GND, TP5 SPARE (GPIO26).

### Motor connectors

J5 (AZ) and J6 (ALT): JST-XH 4-pin, pin 1..4 = module pins B3..B6 (coil A pair then coil B pair).

### End stops (4 channels)

J7 ES_AZ_MIN, J8 ES_AZ_MAX, J9 ES_ALT_MIN, J10 ES_ALT_MAX: JST-XH 2-pin, pin 1 = signal, pin 2 = GND.
Each: signal -> R (1 kOhm, R4..R7) -> GPIO net; 100 nF (C4..C7) from the GPIO net to GND. (Pi internal pull-ups are
enabled in software.) **Wiring choice (decided after drafting): common + normally-closed**, so the line idles LOW and a pressed or
broken switch reads HIGH = tripped; the software default (`endstop_trip_level = 1`) assumes this. Normally-open switches that pull to
GND also work electrically but need that setting changed to 0.

### I2C sensor headers

J11 (IMU), J12 (GNSS): 1x5 2.54 mm header, pins: 1 GND, 2 3V3, 3 5V_F, 4 SDA, 5 SCL.

### Decoupling / misc

C8, C9: 100 nF (0805) 3V3 to GND, one near each module socket. Four mounting holes M3 (3.2 mm), plated or not.

## Parts and footprints (preferred)

| Ref | Part | Footprint |
|---|---|---|
| J1 | 2x20 female header 2.54, bottom side | THT |
| U1, U2 | 2x 1x8 female header 2.54, rows 12.70 mm apart | THT |
| J2, J3, J4 | screw terminal 5.08 mm, 2-pin | THT |
| J5, J6 | JST-XH B4B-XH-A (2.5 mm pitch, 4-pin, vertical) | THT |
| J7..J10 | JST-XH B2B-XH-A (2-pin) | THT |
| J11, J12 | 1x5 pin header 2.54 | THT |
| JP1 | 1x2 pin header 2.54 | THT |
| F1, F2 | radial PTC, 5.08 mm lead pitch, 2 A hold | THT |
| D1 | 1N5822 (DO-201AD) | THT |
| D2 | 1.5KE18A (DO-201AD) | THT |
| C1 | 220 uF 35 V radial, 8 mm dia, 3.5 mm pitch | THT |
| C2, C3 | 100 uF 35 V radial, 6.3 mm dia, 2.5 mm pitch | THT |
| C4..C9 | 100 nF 50 V X7R | 0805 |
| R1, R4..R8 | 1 kOhm | 0805 |
| R2, R3 | 10 kOhm | 0805 |
| LED1 | red LED | 0805 |
| TP1..TP5 | test point, 1.0 mm drill | THT |
| H1..H4 | M3 mounting hole | NPTH 3.2 mm |

## Board rules

- 2 layers, 1.6 mm FR4, 1 oz copper, HASL or ENIG.
- Outline: rectangular with 2 mm rounded corners; target 85 x 60 mm (grow if parts do not fit; keep every dimension <= 100 mm).
- Pi header strip: socket J1 along one long edge; also draw the Pi Zero 65 x 30 mm outline on silkscreen as an alignment guide
  (the board overhangs the Pi so USB/HDMI/camera connectors stay uncovered; the Zero's ports are on its bottom long edge and
  short edges, its GPIO header on the top long edge). Mark Pi pin 1 on the silkscreen. **Verify the Pi Zero header position
  against the official mechanical drawing and state the source or flag it as unverified.**
- Min track 0.25 mm, min clearance 0.25 mm, power tracks: 12 V and motor coil tracks 0.8 mm minimum, 5 V 0.8 mm, signals 0.25-0.3 mm.
  Vias 0.6 mm pad / 0.3 mm drill. Plated through-hole annular ring >= 0.3 mm. Keep >= 0.5 mm copper-to-edge.
- GND copper pour on both layers, stitched with vias; thermal reliefs on THT pins.
- Silkscreen: reference designators, net/function labels for every connector pin, polarity marks, board name/rev/date,
  "PI PIN 1" marker, a "JP1: remove when USB powered" note.

## Deliverables (all under hardware/pcb/, reproducible from one generator script)

1. `netlist.json` - single source of truth (parts, pins, nets), plus a KiCad-format `carrier.net` netlist.
2. Schematic diagrams: `carrier_schematic.svg`, `.pdf`, `.png` (readable, grouped by function) and a system-level wiring
   diagram `system_wiring.svg/.pdf/.png` (Pi, drivers, motors, end stops, IMU, GNSS, PD trigger, buck, power bank).
3. KiCad project: `carrier.kicad_pro`, `carrier.kicad_sch`, `carrier.kicad_pcb` (KiCad 8 file format).
4. Fabrication: Gerber RS-274X for F.Cu, B.Cu, F.Mask, B.Mask, F.Silkscreen, B.Silkscreen, Edge.Cuts; Excellon drill
   files (plated and non-plated); a single `fab/carrier_gerbers.zip`.
5. Assembly: `carrier_bom.csv` (grouped by value/footprint with refs and quantities), `carrier_cpl.csv` (pick and place, SMD only).
6. Mechanical: `carrier_outline.dxf` (outline, holes, connector keep-outs) and `carrier_board.stl` (extruded board plus simple
   boxes for tall parts) so the enclosure can be designed around it.
7. Renders: `carrier_top.png`, `carrier_bottom.png`.
8. `README.md` with the pin map, assumptions, what was verified and what was not.

## Verification the generator must perform and report (no hand-waving)

- Netlist: every net has at least two pins except the explicitly listed NC pins and test points; no pin on two nets; every
  pin in the tables above is placed.
- Layout: copper connectivity per net (each net's pads form one connected component, counting tracks, vias and pours);
  no clearance violations between different nets (report minimum clearance found); every drill/pad/outline respects the rules.
- Gerbers: re-read each Gerber file with a parser (gerbonara) and render it to confirm it parses and the extents match the outline.
- KiCad files: parse back with kiutils (or equivalent) and compare the pad/net table against netlist.json.
- State explicitly that KiCad itself was NOT available to open the files, so ERC/DRC by KiCad is still outstanding.

## Cautions added after review

- J11/J12 pin 3 is 5V_F: do not power a breakout that pulls SDA/SCL up to 5 V from it (the Pi's GPIO is 3.3 V only); use 3V3 on pin 2.
- The TMC2209 module pin order (PDN_UART on A4) is unconfirmed for your vendor: verify before plugging both modules in.

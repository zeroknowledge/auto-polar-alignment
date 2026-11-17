"""Generate hardware/bom.csv and hardware/BOM.md from one table so totals cannot drift."""
import csv, pathlib, sys

out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

# (category, item, spec / notes, qty, unit_usd, first_phase)
ROWS = [
 ("Compute", "Raspberry Pi Zero 2 W (pre-soldered header)", "WH variant avoids soldering the 40-pin header. 512 MB RAM.", 1, 18.00, 0),
 ("Compute", "microSD 32 GB, A1/A2", "Raspberry Pi OS Lite 64-bit, headless.", 1, 8.00, 0),
 ("Camera", "Waveshare IMX296 Global Camera (A), SKU 32501", "COLOUR sensor with an integrated IR-cut filter (not mono as the design doc assumed). Listed DISCONTINUED on waveshare.com when checked; $82.99 list price. Includes a 15-to-22-pin and a 15-pin CSI cable, the C-CS adapter and a dust cap; no lens. Needs dtoverlay=imx296 (no mono).", 1, 82.99, 0),
 ("Camera", "CSI ribbon cable, 22-pin to 15-pin", "Included with the Waveshare camera (the Zero has the small 22-pin port).", 1, 0.00, 0),
 ("Camera", "16 mm C-mount lens (Waveshare 16 mm telephoto: dia 39 x 50 mm, 134 g, f/1.4-16)", "The cradle and dew shield are sized for this lens. Price is my estimate, not checked.", 1, 22.00, 0),
 ("Motion", "NEMA 17 pancake stepper, 20-25 mm body, <=1 A/phase", "Run at 0.4-0.6 A. Take 5 mm D-shaft.", 2, 13.00, 1),
 ("Motion", "TMC2209 driver module (SilentStepStick format)", "Pick a board that exposes MS1/MS2 so both drivers share one UART via addresses 0 and 1.", 2, 5.50, 1),
 ("Motion", "Micro limit switch with roller lever (KW12-3 class)", "4 used: two per axis. 5 bought, 1 spare. The mounts assume a body of about 20 x 10.5 x 6.5 mm with 9.5 mm hole spacing and a roller lever; confirm on the switches you buy.", 5, 1.00, 1),
 ("Motion", "M2 x 8 self-tapping screws, small pack", "Eight hold the four end-stop switches into their pilot holes.", 1, 1.50, 1),
 ("Motion", "Flexible shaft coupler 5 mm to 6 mm", "Absorbs the +/-6 deg swing of the screw as the arm turns.", 2, 2.50, 1),
 ("Motion", "M6x1 stainless threaded rod, 1 m", "M6 coarse pitch is 1.0 mm: 0.716 deg/turn on an 80 mm arm. Do NOT substitute T8x8 (8 mm lead, back-drives).", 1, 7.00, 1),
 ("Motion", "Brass hex nut M6, pack of 10", "Brass on stainless for low friction. Held in a printed trunnion.", 1, 3.00, 1),
 ("Motion", "Extension springs, assorted pack", "Anti-backlash preload. Altitude: two springs that suit about 74 mm between hooks when installed. Azimuth: one spring of roughly 25 mm free length and 0.3 N/mm (run cad/check_preload.py with your spring's figures to pick the peg). Buy a pack with a spread of lengths and rates.", 1, 8.00, 1),
 ("Structure", "608ZZ bearing, pack of 10", "Hinge pins and screw-end support.", 1, 6.00, 1),
 ("Structure", "8 mm ground steel rod, 300 mm", "Hinge pins: cut one 124 mm (coarse hinge) and one 140 mm (altitude hinge), 264 mm in all, and chamfer the ends.", 1, 6.00, 1),
 ("Structure", "6 in aluminium lazy-Susan turntable bearing", "Azimuth stage. Watch axial wobble: measure it. Upgrade path is a cross-roller slewing ring.", 1, 12.00, 1),
 ("Structure", "3/8-16 x 3/4 in (19 mm) hex bolt (the telescope stud)", "One used, one spare. The stud stands (length - 11 mm) above the seat disc, so 19 mm gives 8 mm. Measure the depth of your S50's socket first: the stud must stand up less than that, or the telescope will tilt on a bottomed stud. Order 1 in (25 mm) as well if the socket is deeper than 14 mm.", 2, 2.00, 1),
 ("Structure", "3/8-16 hex nut, standard thickness (about 8.3 mm, 9/16 in across flats)", "One sits in the hex pocket of the base spider and threads onto the tripod stud; the spare is for a miscut. Not a coupling nut (those are about 28 mm long and will not fit). Do not rely on a printed 3/8-16 thread.", 2, 2.00, 1),
 ("Structure", "3/8-16 to 1/4-20 reducer bushing", "For photo tripods; also the Dwarf 3 adapter if wanted.", 2, 2.50, 1),
 ("Structure", "Heat-set inserts M3/M4/M5/M6 assortment", "Brass, for printed parts.", 1, 12.00, 1),
 ("Structure", "Fastener assortment: M3/M4/M5/M6 socket-head, washers, nuts, 3 mm dowel pins", "Stainless where outdoors.", 1, 15.00, 1),
 ("Structure", "Wing nut or star knob M6", "Coarse-tilt lock.", 2, 1.50, 1),
 ("Structure", "PETG filament, 1 kg spool", "854 g for every printed part including the coupon; the second spool covers reprints and failed prints. Print with an enclosed X1C/P1S: no PLA (creep).", 2, 20.00, 1),
 ("Structure", "Adhesive felt feet + black flocking paper", "Feet, and dew-shield lining.", 1, 5.00, 1),
 ("Structure", "M2.5 heat-set inserts + M2.5 x 8 screws, small pack", "Four of each hold the camera board to its plate.", 1, 5.00, 1),
 ("Structure", "Cable ties 2.5 x 100 mm, assorted pack", "Hold the PD trigger and buck modules in the case bay, and tidy the wiring.", 1, 2.50, 1),
 ("Structure", "M6 x 130 mm bolt + nut (coarse tilt lock)", "Passes through both coarse cheeks and both tilt-plate arms; tighten with a wrench.", 1, 2.50, 1),
 ("Power", "USB-C PD trigger board, 12 V", "Check the power bank really offers 12 V PD; many only offer 9/15/20 V.", 1, 4.00, 1),
 ("Power", "12 V to 5 V buck converter, 3 A, low-noise", "Pololu D24V22F5 class. Separate 5 V rail for the Pi.", 1, 8.00, 1),
 ("Power", "24 AWG silicone wire, ferrules, heat shrink", "Motor, end-stop and power harness.", 1, 6.00, 1),
 ("Sensors", "ICM-20948 IMU breakout (I2C)", "Coarse tilt and knock detection. Compass is a rough guide only.", 1, 15.00, 3),
 ("Sensors", "u-blox M8/M9 GNSS breakout with I2C (DDC) pins and antenna", "Verify the board exposes SDA/SCL before ordering: many cheap boards are UART-only and the Zero has no spare UART.", 1, 14.00, 3),
 # Carrier PCB (see pcb/SPEC.md). Part list follows the spec; exact quantities come from pcb/carrier_bom.csv.
 ("PCB", "Carrier PCB, 2-layer ~85x60 mm, 5 pcs (fab order incl. shipping)", "Upload pcb/fab/carrier_gerbers.zip. Five is the usual minimum order; shipping dominates the price.", 1, 23.00, 1),
 ("PCB", "Screw terminal 5.08 mm, 2-pin", "12 V in, 12 V to the buck module, 5 V from the buck module.", 3, 0.70, 1),
 ("PCB", "JST-XH kit with crimp pins (2-pin and 4-pin)", "2x 4-pin for motors, 4x 2-pin for end stops, plus the mating housings.", 1, 9.00, 1),
 ("PCB", "2.54 mm headers: 1x 2x20 female, 4x 1x8 female, 2x 1x5, 1x 1x2 + jumper", "Pi socket, TMC2209 sockets, I2C, JP1.", 1, 5.00, 1),
 ("PCB", "PTC resettable fuse, 2 A hold, radial, 5.08 mm lead pitch, rated 30 V or more", "One on the 12 V rail, one on the 5 V rail. The TVS clamps near 25 V, so a 16 V-rated PTC is too low on the 12 V rail. Check lead pitch and rating on the part you buy.", 2, 1.00, 1),
 ("PCB", "1N5822 Schottky + 1.5KE18A TVS", "Reverse-polarity and surge protection on the 12 V input.", 1, 1.20, 1),
 ("PCB", "Electrolytic: 1x 220 uF/35 V, 2x 100 uF/35 V", "Bulk capacitance at the input and at each driver's VM.", 1, 2.50, 1),
 ("PCB", "0805 assortment: 100 nF, 1 k, 10 k, red LED", "6 capacitors, 7 resistors, 1 LED. Min packs are far larger than needed.", 1, 8.00, 1),
]
OPTIONAL = [
 ("SHT31 temperature/humidity sensor (I2C)", "Dew warning.", 4.00),
 ("5 mm aluminium plate cut set (hinge leaves, top plate)", "Phase-2 stiffness upgrade; I will supply DXF if the printed version sags.", 40.00),
 ("Cross-roller slewing ring ~100 mm", "If lazy-Susan wobble exceeds about 0.05 deg.", 45.00),
 ("Pi heatsink", "Gulf summer.", 2.00),
]
PCB_TOTAL = None  # filled below

rows = []
for i, (cat, item, spec, qty, unit, ph) in enumerate(ROWS, 1):
    rows.append(dict(id=f"B{i:02d}", category=cat, item=item, spec=spec, qty=qty, unit_usd=f"{unit:.2f}", ext_usd=f"{qty*unit:.2f}", first_phase=ph))

total = sum(float(r["ext_usd"]) for r in rows)
by_phase = {}
for r in rows:
    by_phase[r["first_phase"]] = by_phase.get(r["first_phase"], 0) + float(r["ext_usd"])

with open(out / "bom.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

cum = 0
md = ["# Bill of materials", "",
      "Prices are indicative USD estimates, **not checked against live listings**. The USB-C PD power bank is already owned and excluded.",
      "Source of truth: `bom.csv` (this file is generated from the same table).", "",
      "| ID | Category | Item | Qty | Unit | Ext | Phase | Notes |", "|---|---|---|---:|---:|---:|---:|---|"]
for r in rows:
    md.append(f"| {r['id']} | {r['category']} | {r['item']} | {r['qty']} | {r['unit_usd']} | {r['ext_usd']} | {r['first_phase']} | {r['spec']} |")
md += ["", f"**Total: ${total:.2f}** (design doc estimated $236; budget $300)", "", "## Cumulative spend by phase", "", "| Phase | New spend | Cumulative |", "|---:|---:|---:|"]
for ph in sorted(by_phase):
    cum += by_phase[ph]
    md.append(f"| {ph} | ${by_phase[ph]:.2f} | ${cum:.2f} |")
md += ["", "## Optional / upgrade items (not in total)", "", "| Item | Why | Est. |", "|---|---|---:|"]
for item, why, c in OPTIONAL:
    md.append(f"| {item} | {why} | {c:.2f} |")
cat_tot = {}
for r in rows:
    cat_tot[r["category"]] = cat_tot.get(r["category"], 0) + float(r["ext_usd"])
phase02 = sum(v for p, v in by_phase.items() if p <= 2)
pcb_cost = sum(float(r["ext_usd"]) for r in rows if r["category"] == "PCB")
PARTS_BIN = ("Heat-set inserts M3/M4", "Fastener assortment", "PETG filament", "Adhesive felt")
fastener_packs = sum(float(r["ext_usd"]) for r in rows if r["item"].startswith(PARTS_BIN))
md += ["", "## Budget check (honest version)", "",
       f"- Buying everything new, in real pack sizes, is **${total:.2f}**: ${total-300:.2f} over the $300 budget and ${total-236:.2f} over the doc's $236.",
       f"- **Phases 0-2 (everything except IMU/GNSS) cost ${phase02:.2f}**, " + ("inside the budget" if phase02 <= 300 else f"${phase02-300:.2f} over the budget") + f". Phase 3 sensors add ${by_phase.get(3,0):.2f}.",
       "- The doc's lump sums ($30 motion hardware, $25 structure, $10 sundries) assume fasteners, inserts, filament and wire come from a parts bin. Itemised and bought as packs, those lines cost more.",
       "", "| Category | Total |", "|---|---:|"]
for c, v in cat_tot.items():
    md.append(f"| {c} | ${v:.2f} |")
md += ["", "### Ways back under $300 for the full build", "",
       f"- Use fasteners, inserts and filament you already own: up to -${fastener_packs:.2f} (heat-set inserts, fastener assortment, filament, felt and flocking paper).",
       "- A $20-30 IMX462 colour module (doc estimate) instead of the $82.99 Waveshare IMX296: about -$57. Rolling shutter does not matter for a static star field, but it is a different board, so the camera plate would need a new design.",
       "- Phone supplies location and time instead of the GNSS module: -$14 (the camera solve needs neither; only a rough date for precession).",
       "- 28BYJ-48 motors instead of NEMA 17 (doc estimate): about -$25, at a stiffness and torque cost.",
       f"- Worked example (keeps the PCB and every sensor): parts-bin fasteners/filament (-${fastener_packs:.0f}) and an IMX462 camera instead (-$57, needs a different camera plate) bring the full build to ${total-fastener_packs-57:.0f}.",
       f"- **Perfboard instead of the carrier PCB: about -${pcb_cost - 14:.0f}.** The PCB route (fab order plus connectors, protection and passives) costs ${pcb_cost:.2f}; a perfboard build is about $14 (board, JST-XH housings, wire). The PCB is the recommended route; the perfboard build skips the reverse-polarity/surge protection and the debounce filters unless you hand-wire them."]
md += ["", "## Differences from the design doc BOM", "",
       "- The camera is the Waveshare IMX296 Global Camera (A): a colour sensor at $82.99 (the doc priced a $55 mono board). It includes the 22-pin to 15-pin CSI cable the Zero needs.",
       "- Specified M6x1 threaded rod and brass nuts; the doc also mentions T8 lead screws, which are 8 mm lead and would break the 0.01 deg resolution requirement.",
       "- Added shaft couplers, a separate buck converter and an explicit azimuth bearing.",
       "- Replaced the doc's perfboard with a carrier PCB (see `pcb/`), which adds protection, filtering and sockets the doc did not list.",
       "- Filament/fasteners/inserts are itemised rather than a lump sum."]
(out / "BOM.md").write_text("\n".join(md) + "\n")
print(f"lines={len(rows)} total={total:.2f}")
for ph in sorted(by_phase): print(f"phase {ph}: {by_phase[ph]:.2f}")

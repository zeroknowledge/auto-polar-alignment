# Review of the carrier PCB pin map (read-only)

Sources read, never modified: `hardware/pcb/netlist.json`, `SPEC.md`, `README.md`, `hardware/README.md`, `hardware/BOM.md`.

## Verdict: no error found in the pin map

`software/tests/test_pin_map.py` checks, on every test run:

* each Pi header pin the netlist uses maps to the BCM GPIO the netlist claims, against an *independent* copy of the
  standard 40-pin header table (so a mistake in either the netlist's `pi_gpio_map` or my table would show up);
* the software defaults (STEP/DIR/EN for both axes, the four end stops, SPARE = GPIO26) equal the netlist;
* I2C bus 1 on GPIO2/3, UART on GPIO14 (TX, through R1 1 k) / GPIO15 (RX, direct on the bus);
* TMC2209 UART addresses follow the MS1/MS2 strapping (address = MS1 + 2*MS2): U1 azimuth = 0, U2 altitude = 1;
* EN lines have 10 k pull-ups (drivers off at boot) and each end-stop line has a series resistor and a filter capacitor.

## Inconsistency between the PCB spec and the hardware README (resolve before wiring switches)

`pcb/SPEC.md` says the end-stop switch "pulls to GND" (normally-open: pressed = LOW). The newer `hardware/README.md`
("End stops") says to wire **common and normally-closed**, so that "a pressed or broken switch reads as a trip" (idle =
LOW, pressed or wire off = HIGH via the pull-up). Both work with the PCB's pull-up + RC filter, but they are opposite in
software. The software default follows the newer text (`endstop_trip_level = 1`: HIGH = tripped); set it to 0 for
normally-open switches. A *disconnected* NC switch therefore reads as tripped: that is the safe way round, but `selftest`
will report a stop as tripped until its switch is wired. With NC wiring the slow RC edge (about 5 ms through the Pi's internal
pull-up) is the *trip* edge; the software's two-readings-one-full-step-apart debounce is comfortably longer.

Also from `hardware/README.md`, and now in the defaults: the switches trigger at 8.05 deg (azimuth) and 7.35 / 7.15 deg
(altitude) from the centre of the +/-6 deg working range, and "which one is min and which is max depends on your motor
wiring, so let the software find out": homing therefore watches *both* switches and relabels the pair if the one wired as MIN
trips first at the other end.

## Cautions (not errors) worth acting on before powering the board

1. **TMC2209 module pin order is unconfirmed (already flagged in `pcb/README.md`).** The netlist puts PDN_UART on
   module pin A4 and leaves A5 unconnected. Vendors disagree here: on some SilentStepStick-format boards pins 4/5 are
   DIAG/INDEX (outputs) and PDN_UART is reached through a solder bridge. If A4 is an output on your module, tying it
   to the shared UART bus (and to the other module's A4) fights two push-pull outputs. **Check the real module with a
   multimeter / the vendor drawing before plugging both in.** The software cannot detect this except by `selftest`
   failing to find the chips.
2. **Pi-side 5 V on the I2C headers.** J11/J12 carry 5V_F on pin 3 next to 3V3 on pin 2. If an IMU/GNSS breakout is
   powered from 5 V and has its own pull-ups to VCC, SDA/SCL swing to 5 V, which the Pi's GPIO (3.3 V, not 5 V tolerant)
   will not survive. Power breakouts from 3V3 unless the board is known to level-shift/pull up to 3.3 V.
3. **End-stop timing.** The 1 k + 100 nF filter is fast on press (about 0.1 ms) but on release the Pi's internal
   pull-up (~50 k) charges the capacitor with a ~5 ms time constant. That is fine because the software debounces (two
   consecutive readings one full step apart), but do not shorten `endstop_debounce_ms`/the check interval to chase speed.
4. **No DIAG/stall pin is routed.** The design document mentions stall detection as an alternative to end stops; this
   PCB cannot do it (and the software does not try). Homing relies on the mechanical switches only.
5. **JP1 back-feed.** As documented in the SPEC: remove JP1 when the Pi is USB-powered (the Zero has no back-feed protection).
6. **UART prerequisite on the Pi side** (software documentation, not a PCB issue): `dtoverlay=disable-bt` and no serial
   console, otherwise GPIO14/15 are not on `/dev/ttyAMA0` and the drivers stay at their power-on defaults
   (the software reports "UART echo missing"/"no answer" instead of silently continuing).

## Design observations that affect the software (not pin-map errors)

* **The azimuth stage moves the axis only `cos(latitude)` degrees on the sky per degree of stage rotation.** With
  +/-6 deg of fine travel (+/-5.75 deg usable inside the soft limits) the east-west reach is +/-5.2 deg at 25 N, +/-3.8 deg at
  48 N and +/-2.7 deg at 62 N. The design
  document's "+/-6 deg absorbs a rough set-up done with a phone compass" holds at low latitudes and gets tight above
  ~45. The closed loop detects an unreachable pole and says so ("fine travel exhausted") instead of hitting the stops.
* The altitude drive is now specified in `hardware/README.md` (M6x1 on a 150 mm arm, 6.9 arcsec per full step) and is the
  default, but remains a design value (`motion.alt.mechanics_confirmed = false` until measured); the loop learns the real
  scale from jogs, and `home(measure_span=True)` measures the true stop-to-stop travel (the simulator test for this uses a
  deliberately 8 % wrong altitude scale).
* **Spring direction.** The azimuth spring pulls the plate clockwise seen from above, so moves should finish clockwise. Which
  sign of step count that is depends on motor wiring; the loop reads it off the sky motion it learns (needs a site to know
  "east"; the hemisphere flips the sign) and sets `preload_dir`. The altitude springs' direction is not stated, so
  `motion.alt.preload_dir` is a plain setting.
* **IMU position.** The electronics case (and the carrier with the IMU) hangs under the *main tilt plate*, so the IMU reads the
  coarse tilt, which is the polar axis' elevation only to within the +/-6 deg fine altitude stage. Good for setting the
  coarse tilt to the latitude (its purpose), not for the final alignment.

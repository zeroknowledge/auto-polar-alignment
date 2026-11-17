"""``polaralign selftest``: checks to run the first time the hardware is powered.  Moves nothing.

Every check reports PASS / FAIL / SKIP with the reason.  This is the quickest way to find out which
part of the (untested) hardware path is wrong: pin map, UART, driver strapping, end-stop wiring,
camera overlay, I2C devices.
"""
from __future__ import annotations

import time

from .config import Config


def _line(status: str, name: str, detail: str = "") -> bool:
    print(f"[{status:<4}] {name}" + (f": {detail}" if detail else ""))
    return status != "FAIL"


def run_selftest(cfg: Config) -> int:
    ok = True
    print("polaralign self-test (nothing will move)\n")

    # --- GPIO + end stops -------------------------------------------------------------------
    gpio = None
    try:
        from .motion.gpio import FakeGPIO, LgpioBackend
        gpio = FakeGPIO() if cfg.hardware == "sim" else LgpioBackend(cfg.motion.gpiochip)
        _line("PASS", "GPIO chip opened", f"gpiochip{cfg.motion.gpiochip}")
    except Exception as exc:  # noqa: BLE001
        ok &= _line("FAIL", "GPIO (lgpio)", f"{exc}  (apt install python3-lgpio; venv needs --system-site-packages)")
    if gpio is not None:
        for ax in (cfg.motion.az, cfg.motion.alt):
            gpio.setup_output(ax.enable_pin, 1)          # disabled
            gpio.setup_output(ax.step_pin, 0)
            gpio.setup_output(ax.dir_pin, 0)
            for which, pin in (("MIN", ax.endstop_min_pin), ("MAX", ax.endstop_max_pin)):
                gpio.setup_input(pin, True, int(ax.endstop_debounce_ms * 1000))
                time.sleep(0.05)
                lvl = gpio.read(pin)
                idle = 1 - ax.endstop_trip_level
                ok &= _line("PASS" if lvl == idle else "FAIL", f"{ax.name} {which} end stop (GPIO{pin}) reads idle ({idle})",
                            "" if lvl == idle else f"reads {lvl} with nothing pressed: switch pressed? wire broken (a broken NC "
                                                   "switch reads as tripped)? or set endstop_trip_level for your wiring")
        _line("INFO", "press each end-stop switch now and run `polaralign selftest` again to see it read low")

    # --- TMC2209 UART ----------------------------------------------------------------------
    try:
        import serial
        from .motion.tmc2209 import Tmc2209, Tmc2209Error
        ser = serial.Serial(cfg.motion.uart_port, cfg.motion.uart_baud, timeout=0.1)
        for ax in (cfg.motion.az, cfg.motion.alt):
            try:
                ver = Tmc2209(ser, ax.uart_address, cfg.motion.rsense_ohm).check_present()
                _line("PASS", f"TMC2209 address {ax.uart_address} ({ax.name})", f"IOIN version 0x{ver:02x}")
            except Tmc2209Error as exc:
                ok &= _line("FAIL", f"TMC2209 address {ax.uart_address} ({ax.name})", str(exc))
    except Exception as exc:  # noqa: BLE001
        ok &= _line("FAIL", f"UART {cfg.motion.uart_port}", f"{exc}  (dtoverlay=disable-bt, serial console off, 12 V present?)")

    # --- camera ------------------------------------------------------------------------------
    try:
        from .camera import make_camera
        cam = make_camera(cfg.camera)
        t0 = time.time()
        fr = cam.capture()
        ok &= _line("PASS", "camera frame", f"{fr.pixels.shape[1]}x{fr.pixels.shape[0]} {fr.pixels.dtype}, "
                    f"{'Bayer ' + fr.meta['bayer'] if fr.meta.get('bayer') else 'monochrome'}, "
                    f"median {int(__import__('numpy').median(fr.pixels))}, max {int(fr.pixels.max())}, {time.time() - t0:.2f} s")
        cam.close()
    except Exception as exc:  # noqa: BLE001
        ok &= _line("FAIL", "camera", f"{exc}  (dtoverlay=imx296 in config.txt (add ,mono only for a monochrome board)? rpicam-hello --list-cameras ?)")

    # --- I2C -----------------------------------------------------------------------------------
    try:
        from smbus2 import SMBus
        bus = SMBus(cfg.sensors.i2c_bus)
        from .sensors import Icm20948
        try:
            imu = Icm20948(bus, cfg.sensors.imu_address)
            imu.init()
            s = imu.read()
            _line("PASS", "ICM-20948 IMU", f"|a| = {float(__import__('numpy').linalg.norm(s.accel_g)):.3f} g, {s.temp_c:.1f} C")
        except Exception as exc:  # noqa: BLE001
            _line("SKIP", "ICM-20948 IMU", str(exc))
        try:
            hi, lo = bus.read_i2c_block_data(cfg.sensors.gnss_address, 0xFD, 2)
            _line("PASS", "u-blox GNSS (DDC)", f"{(hi << 8) | lo} bytes waiting")
        except Exception as exc:  # noqa: BLE001
            _line("SKIP", "u-blox GNSS (DDC)", str(exc))
    except Exception as exc:  # noqa: BLE001
        _line("SKIP", "I2C bus", str(exc))

    print("\n" + ("all required checks passed" if ok else "some checks FAILED"))
    return 0 if ok else 1

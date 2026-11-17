"""Command line: ``polaralign <command>``.  See README.md."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from .config import Config, load_config, sim_config


def _cfg(args) -> Config:
    cfg = load_config(args.config) if args.config else load_config()
    if getattr(args, "sim", False):
        base = sim_config()
        cfg.hardware = "sim"
        cfg.camera.backend = "sim"
        cfg.motion.realtime = False
        cfg.align.settle_s = base.align.settle_s
        cfg.sensors.imu_enabled = False
        cfg.sensors.gnss_enabled = False
    if getattr(args, "state_dir", None):
        cfg.state_dir = args.state_dir
    return cfg


def cmd_serve(args) -> int:
    import uvicorn

    from .runtime import Runtime
    from .web.app import create_app

    cfg = _cfg(args)
    if args.host:
        cfg.web.host = args.host
    if args.port:
        cfg.web.port = args.port
    rt = Runtime(cfg)
    for n in rt.startup_notes:
        logging.warning(n)
    app = create_app(rt)
    if cfg.seestar.enabled:
        from .plugins.seestar import register_routes
        register_routes(app, rt)
    try:
        uvicorn.run(app, host=cfg.web.host, port=cfg.web.port, log_level="info")
    finally:
        rt.close()
    return 0


def cmd_sim_align(args) -> int:
    from .astro import Site
    from .sim.scenario import run_scenario

    cfg = _cfg(args)
    site = Site(args.lat, args.lon)
    t0 = time.time()
    res = run_scenario(seed=args.seed, site=site, initial_error_deg=args.error_deg, direction_deg=args.direction,
                       calibration_error_deg=args.cal_error, config=cfg, refraction=args.refraction)
    r = res.report
    print(f"{r.message}")
    print(f"  initial true error {res.initial_true_error_deg:.3f} deg -> final {res.final_true_error_deg:.4f} deg "
          f"(vs unrefracted pole {res.final_vs_true_pole_deg:.4f} deg)")
    print(f"  measured residual {r.residual_arcmin:.2f}' | iterations {r.iterations} | solves {r.solves} | "
          f"backlash {r.backlash_deg} | wall {time.time() - t0:.1f} s (simulated time, no sleeping)")
    for h in r.history:
        print(f"    iteration {h['iteration']}: {h['total_arcmin']:.2f}'")
    return 0 if r.success else 1


def cmd_solve(args) -> int:
    from .runtime import Runtime

    rt = Runtime(_cfg(args))
    job = rt.start_measure()
    rt.wait(60)
    print(json.dumps(job.result or {"error": job.error}, indent=2, default=str))
    rt.close()
    return 0 if job.result and job.result.get("status") == "ok" else 1


def cmd_home(args) -> int:
    from .runtime import Runtime
    rt = Runtime(_cfg(args))
    rt.motion.home()
    print(json.dumps(rt.motion.status(), indent=2))
    rt.close()
    return 0


def cmd_jog(args) -> int:
    from .runtime import Runtime
    rt = Runtime(_cfg(args))
    res = rt.motion.move_relative_deg(args.axis, args.deg)
    print(f"moved {res.done} microsteps, position {rt.motion.axes[args.axis].position_deg:+.3f} deg")
    rt.close()
    return 0


def cmd_calibrate(args) -> int:
    from .runtime import Runtime
    rt = Runtime(_cfg(args))
    job = rt.start_declare_aligned()
    rt.wait(120)
    print(job.error or json.dumps(rt.calibration.summary(), indent=2))
    rt.close()
    return 0 if not job.error else 1


def cmd_build_db(args) -> int:
    from .solve.database import build_database
    logging.basicConfig(level=logging.INFO)
    cfg = _cfg(args)
    fov = cfg.camera.fov_h_deg
    out = build_database(args.out, args.catalogue, min_fov_deg=args.min_fov or round(fov * 0.92, 1),
                         max_fov_deg=args.max_fov or round(fov * 1.09, 1))
    print(out)
    return 0


def cmd_selftest(args) -> int:
    """First-power-up hardware checks.  Moves nothing."""
    from .selftest import run_selftest
    return run_selftest(_cfg(args))


def cmd_bench(args) -> int:
    from .bench import main as bench_main
    return bench_main(args.runs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="polaralign", description="Automatic polar-alignment base controller")
    p.add_argument("--config", help="TOML config file (default: $POLARALIGN_CONFIG)")
    p.add_argument("--state-dir", help="calibration/log directory")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the web UI")
    s.add_argument("--sim", action="store_true", help="virtual hardware")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("sim-align", help="run one simulated alignment and print the result")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--lat", type=float, default=25.2)
    s.add_argument("--lon", type=float, default=55.3)
    s.add_argument("--error-deg", type=float, default=5.0)
    s.add_argument("--direction", type=float, default=130.0)
    s.add_argument("--cal-error", type=float, default=0.015)
    s.add_argument("--refraction", choices=["model", "off"], default="model")
    s.set_defaults(fn=cmd_sim_align, sim=True)

    for name, fn, hlp in (("solve", cmd_solve, "capture, extract and solve once"),
                          ("home", cmd_home, "home both axes"), ("calibrate", cmd_calibrate, "declare the telescope aligned"),
                          ("selftest", cmd_selftest, "hardware self-test (moves nothing)")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("--sim", action="store_true")
        s.set_defaults(fn=fn)
    s = sub.add_parser("jog", help="move one axis")
    s.add_argument("axis", choices=["az", "alt"])
    s.add_argument("deg", type=float)
    s.add_argument("--sim", action="store_true")
    s.set_defaults(fn=cmd_jog)
    s = sub.add_parser("build-db", help="build the plate-solver database for this lens")
    s.add_argument("--out", default="data/polaralign_db.npz")
    s.add_argument("--catalogue", help="path to hip_main.dat (default: derive from the star table bundled with cedar-solve)")
    s.add_argument("--min-fov", type=float)
    s.add_argument("--max-fov", type=float)
    s.set_defaults(fn=cmd_build_db)
    s = sub.add_parser("bench", help="benchmark the star extractor on a 1456x1088 frame")
    s.add_argument("--runs", type=int, default=30)
    s.set_defaults(fn=cmd_bench)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("tetra3.Tetra3").setLevel(logging.WARNING)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())

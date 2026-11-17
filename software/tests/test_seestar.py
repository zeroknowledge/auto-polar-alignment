"""Phase 4 plugin.  The TCP/JSON framing is *assumed* (see plugins/seestar/client.py): these tests prove our plumbing
against a mock that speaks that assumed framing, not that a real Seestar does.  The calibration-trim maths is
tested end to end in the simulator and does not depend on the protocol."""
import json
import math
import socket
import threading

import numpy as np
import pytest

from polaralign.align.engine import AlignEngine
from polaralign.align.pipeline import Measurer
from polaralign.astro import ARCSEC
from polaralign.calibration import CalibrationStore
from polaralign.config import SeestarConfig, sim_config
from polaralign.extract import get_extractor
from polaralign.plugins.seestar import NotConfigured, PolarErrorReport, SeestarReader, trim_calibration
from polaralign.plugins.seestar.client import SeestarClient, SeestarError
from polaralign.sim import MountParams, build_sim_hardware


class MockSeestar:
    """JSON-lines server: replies to each request with the same id; also pushes an unsolicited event."""

    def __init__(self, replies):
        self.replies = replies
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.requests = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.srv.accept()
        conn.sendall(b'{"Event":"PiStatus","temp":41.0}\r\n')
        buf = b""
        while True:
            data = conn.recv(4096)
            if not data:
                return
            buf += data
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                req = json.loads(line)
                self.requests.append(req)
                rep = self.replies.get(req["method"], {"code": 103, "error": "method not found"})
                conn.sendall((json.dumps({"jsonrpc": "2.0", "id": req["id"], **rep}) + "\r\n").encode())


def cfg_for(port, **kw):
    return SeestarConfig(enabled=True, host="127.0.0.1", port=port, polar_align_method="probe_polar_error",
                         result_alt_key="alt_err", result_az_key="nested.az_err", units="arcmin", timeout_s=2.0, **kw)


def test_client_matches_replies_by_id_and_collects_events():
    srv = MockSeestar({"ping": {"code": 0, "result": "pong"}})
    c = SeestarClient("127.0.0.1", srv.port, 2.0)
    c.connect()
    assert c.call("ping")["result"] == "pong"
    with pytest.raises(SeestarError, match="code 103"):
        c.call("nope")
    ev = c.events.get(timeout=1)
    assert ev["Event"] == "PiStatus"
    c.close()


def test_reader_converts_units_and_signs():
    srv = MockSeestar({"probe_polar_error": {"code": 0, "result": {"alt_err": 3.0, "nested": {"az_err": -6.0}}}})
    rep = SeestarReader(cfg_for(srv.port, sign_az=-1)).read()
    assert rep.alt_rad == pytest.approx(3 * 60 * ARCSEC) and rep.east_rad == pytest.approx(+6 * 60 * ARCSEC)
    assert rep.total_arcmin == pytest.approx(math.hypot(3, 6))


def test_reader_refuses_when_unconfigured_and_reports_bad_replies():
    with pytest.raises(NotConfigured, match="not documented"):
        SeestarReader(SeestarConfig(enabled=True, host="x")).read()
    srv = MockSeestar({"probe_polar_error": {"code": 0, "result": {"other": 1}}})
    with pytest.raises(SeestarError, match="could not find"):
        SeestarReader(cfg_for(srv.port)).read()


def test_trim_makes_the_next_session_land_where_the_telescope_says_aligned(solver):
    """The user hand-aligned only to ~0.06 deg.  The telescope reports its residual; feeding it back trims the
    stored camera-to-axis vector so the next automatic alignment is much closer to the pole."""
    cfg = sim_config()
    hw = build_sim_hardware(cfg, seed=61, mount=MountParams(seed=161, stall_prob_per_move=0.0))
    hw.motion.home()
    site = hw.world.site
    cal = CalibrationStore(None)
    eng = AlignEngine(cfg, Measurer(hw.camera, get_extractor(cfg.extractor), solver), hw.motion, cal, hw.time_source, lambda: site)
    hw.world.set_coarse(0.06, 40.0)                       # sloppy hand alignment...
    eng.declare_aligned()                                 # ...declared as "aligned"
    hw.world.set_coarse(4.0, 20.0)
    assert eng.run().success
    err1 = hw.world.true_axis_error_deg()
    assert 0.03 < err1 < 0.09                              # inherits the sloppy calibration

    # what the telescope would report: the axis' true offset from the apparent pole, in its own up/east frame
    s = eng.sample()
    p = hw.world.apparent_pole_enu()
    a = hw.world.mount.axis_enu()
    up = np.array([0, 0, 1.0]) - (np.array([0, 0, 1.0]) @ p) * p
    up /= np.linalg.norm(up)
    east = np.array([1.0, 0, 0]) - (np.array([1.0, 0, 0]) @ p) * p
    east /= np.linalg.norm(east)
    noise = np.random.default_rng(0).normal(0, math.radians(0.008), 2)           # telescope's own measurement noise
    rep = PolarErrorReport(alt_rad=float((a - p) @ up) + noise[0], east_rad=float((a - p) @ east) + noise[1])
    info = trim_calibration(cal, rep, s.measurement.rotation, s.target, weight=1.0)
    assert info["applied_arcsec"] > 60

    hw.world.set_coarse(4.0, 200.0)                        # next night: base knocked again
    assert eng.run().success
    err2 = hw.world.true_axis_error_deg()
    assert err2 < 0.025 and err2 < 0.5 * err1, (err1, err2)


def test_trim_needs_a_calibration():
    with pytest.raises(ValueError):
        trim_calibration(CalibrationStore(None), PolarErrorReport(0, 0), np.eye(3), None)

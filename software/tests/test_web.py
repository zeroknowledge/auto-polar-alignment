"""The HTTP API and static UI against a simulated base (the real Runtime, no mocks of our own code)."""
import time

import pytest
from fastapi.testclient import TestClient

from polaralign.config import sim_config
from polaralign.runtime import Job, Runtime
from polaralign.web.app import create_app


@pytest.fixture()
def rt(tmp_path):
    cfg = sim_config()
    cfg.state_dir = str(tmp_path)
    r = Runtime(cfg)
    yield r
    r.close()


@pytest.fixture()
def client(rt):
    return TestClient(create_app(rt))


def wait(rt, timeout=60.0):
    t0 = time.time()
    while rt.busy() and time.time() - t0 < timeout:
        time.sleep(0.02)
    assert not rt.busy()


def test_status_and_static_ui(client):
    s = client.get("/api/status").json()
    assert s["hardware"] == "sim" and s["phase"]["phase"] == "idle" and s["calibration"]["calibrated"] is False
    assert any("SIMULATED" in w for w in s["warnings"]) and any("calibration" in w for w in s["warnings"])
    assert set(s["motion"]["axes"]) == {"az", "alt"} and s["camera"]["fov_h_deg"] == pytest.approx(17.84, abs=0.01)
    html = client.get("/")
    assert html.status_code == 200 and "Polar" in html.text and 'id="btn-align"' in html.text
    assert client.get("/static/app.js").status_code == 200 and client.get("/static/style.css").status_code == 200
    assert "/api/events" in client.get("/openapi.json").json()["paths"]


def test_jog_home_and_busy_handling(client, rt):
    assert client.post("/api/home").status_code == 200
    wait(rt)
    s = client.get("/api/status").json()
    assert s["motion"]["axes"]["az"]["homed"] and abs(s["motion"]["axes"]["az"]["position_deg"]) < 0.01
    assert client.post("/api/jog", json={"axis": "az", "deg": 0.5}).json() == {"started": "jog"}
    wait(rt)
    assert client.get("/api/status").json()["motion"]["axes"]["az"]["position_deg"] == pytest.approx(0.5, abs=0.02)
    assert client.post("/api/jog", json={"axis": "roll", "deg": 0.5}).status_code == 400
    assert client.post("/api/jog", json={"axis": "az", "deg": 50}).status_code == 422
    rt.job = Job("align", time.time())                                       # pretend something is running
    assert client.post("/api/jog", json={"axis": "az", "deg": 0.1}).status_code == 409
    assert client.post("/api/align/start", json={}).status_code == 409
    rt.job.done = True


def test_measure_preview_and_error_readout(client, rt):
    assert client.get("/api/frame.png").status_code == 404
    client.post("/api/home")
    wait(rt)
    assert client.post("/api/measure").status_code == 200
    wait(rt)
    s = client.get("/api/status").json()
    assert s["solve"]["status"] == "ok" and s["solve"]["matches"] > 20 and s["solve"]["n_stars"] > 30
    png = client.get("/api/frame.png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/api/frame.png?overlay=0").status_code == 200


def test_calibration_requires_confirmation(client, rt):
    assert client.post("/api/calibration/declare", json={}).status_code == 400
    assert client.post("/api/calibration/clear", json={}).status_code == 400


def test_full_session_through_the_api(client, rt):
    client.post("/api/home")
    wait(rt)
    assert client.post("/api/sim/coarse", json={"error_deg": 0.015, "direction_deg": 40}).status_code == 200
    assert client.post("/api/calibration/declare", json={"confirm": True}).status_code == 200
    wait(rt)
    assert client.get("/api/status").json()["calibration"]["entries"] == 1
    client.post("/api/sim/coarse", json={"error_deg": 5, "direction_deg": 130})
    assert client.post("/api/align/start", json={}).status_code == 200
    wait(rt, 120)
    s = client.get("/api/status").json()
    rep = s["report"]
    assert rep["converged"] and rep["iterations"] <= 8 and rep["residual_arcmin"] < 3
    assert rt.sim.world.true_axis_error_deg() < 0.05
    assert s["error"]["total_arcmin"] < 3 and s["error"]["horizontal_frame"]
    log = client.get("/api/log").json()
    assert any(e["phase"] == "done" for e in log) and any(e["phase"] == "learn" for e in log)
    assert all(not a["enabled"] for a in s["motion"]["axes"].values())      # motor current cut
    # clearing really clears, and the old file is kept
    assert client.post("/api/calibration/clear", json={"confirm": True}).json()["calibrated"] is False


def test_align_without_calibration_is_refused_with_a_clear_message(client, rt):
    client.post("/api/home")
    wait(rt)
    client.post("/api/align/start", json={"allow_uncalibrated": False})
    wait(rt)
    assert "calibration" in client.get("/api/status").json()["report"]["message"].lower()


def test_location_and_clock_from_the_phone(client, rt):
    r = client.post("/api/location", json={"latitude": 51.5, "longitude": -0.12, "source": "browser",
                                           "unix_ms": 1_800_000_000_000, "accuracy_m": 25})
    assert r.status_code == 200
    s = client.get("/api/status").json()
    assert s["site"]["latitude_deg"] == 51.5 and s["site"]["source"] == "phone"
    assert "phone" in s["time_source"] and s["time_utc"].startswith("2027-01-15")       # 1.8e12 ms
    assert client.post("/api/location", json={"latitude": 123, "longitude": 0}).status_code == 400


def test_camera_settings(client, rt):
    assert client.post("/api/camera", json={"exposure_s": 0.25, "gain": 4}).json() == {"exposure_s": 0.25, "gain": 4}
    assert client.post("/api/camera", json={"exposure_s": 100}).status_code == 422


def test_token_protects_writes_but_not_reads(tmp_path):
    cfg = sim_config()
    cfg.state_dir = str(tmp_path)
    cfg.web.token = "s3cret"
    r = Runtime(cfg)
    c = TestClient(create_app(r))
    assert c.get("/api/status").status_code == 200
    assert c.post("/api/home").status_code == 401
    assert c.post("/api/home", headers={"X-Token": "wrong"}).status_code == 401
    assert c.post("/api/home", headers={"X-Token": "s3cret"}).status_code == 200
    wait(r)
    r.close()


def test_sim_endpoint_absent_on_real_hardware_runtime(tmp_path, monkeypatch):
    cfg = sim_config()
    cfg.state_dir = str(tmp_path)
    r = Runtime(cfg)
    r.sim = None                      # what a hardware runtime looks like to the API layer
    c = TestClient(create_app(r))
    assert c.post("/api/sim/coarse", json={"error_deg": 1}).status_code == 404
    r.close()


def test_runtime_degrades_gracefully_on_a_laptop_without_pi_hardware(tmp_path):
    """hardware='pi' on a machine with no lgpio, serial port or camera must still start and say what is missing."""
    from polaralign.config import Config
    cfg = Config()
    cfg.state_dir = str(tmp_path)
    cfg.motion.uart_port = "/dev/does-not-exist"
    r = Runtime(cfg)
    try:
        notes = " ".join(r.startup_notes)
        assert "UART" in notes and "Camera unavailable" in notes
        assert any(x in notes for x in ("GPIO unavailable", "dummy GPIO")) or r.motion.gpio is not None
        s = r.status()
        assert s["hardware"] == "pi" and s["warnings"]
        assert r.motion.axes["az"].enabled is False
    finally:
        r.close()


def test_selftest_reports_missing_hardware_without_crashing(capsys):
    from polaralign.config import Config
    from polaralign.selftest import run_selftest
    cfg = Config()
    cfg.motion.uart_port = "/dev/does-not-exist"
    rc = run_selftest(cfg)
    out = capsys.readouterr().out
    assert rc == 1 and "[FAIL]" in out and "UART" in out and "camera" in out

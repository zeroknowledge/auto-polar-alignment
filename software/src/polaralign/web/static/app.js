// Polar Align UI. Plain ES module, no build step, no dependencies.
const $ = (id) => document.getElementById(id);
const token = new URLSearchParams(location.search).get("token") || localStorage.getItem("pa-token") || "";
if (token) localStorage.setItem("pa-token", token);

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { "X-Token": token } : {}) },
    body: JSON.stringify(body),
  };
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* not json */ }
    throw new Error(msg);
  }
  return r.json();
}
const act = async (fn) => { try { await fn(); } catch (e) { alert(e.message); } };
const fmt = (v, d = 2) => (v === null || v === undefined ? "–" : Number(v).toFixed(d));
const kv = (el, rows) => { el.innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join(""); };

// ---- jog panel -------------------------------------------------------------------------------
const STEPS = [-1, -0.1, -0.01, 0.01, 0.1, 1];
$("jogs").innerHTML = ["az", "alt"].map((a) => `
  <div class="axis" data-axis="${a}">
    <div class="name">${a === "az" ? "Azimuth" : "Altitude"}</div>
    <div class="btns">${STEPS.map((s) => `<button data-deg="${s}">${s > 0 ? "+" : ""}${s}&deg;</button>`).join("")}</div>
    <div class="pos" id="pos-${a}"></div>
  </div>`).join("");
$("jogs").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-deg]");
  if (!b) return;
  const axis = b.closest(".axis").dataset.axis;
  act(() => api("/api/jog", { axis, deg: Number(b.dataset.deg) }));
});

// ---- buttons ---------------------------------------------------------------------------------
let busy = null;
$("btn-align").onclick = () => act(async () => {
  if (busy === "align") return api("/api/align/cancel", {});
  if (!lastStatus?.calibration?.calibrated) {
    if (!confirm("No camera-to-axis calibration yet.\n\nContinue anyway, using the camera boresight as the axis (bench mode)?")) return;
    return api("/api/align/start", { allow_uncalibrated: true });
  }
  return api("/api/align/start", { allow_uncalibrated: false });
});
$("btn-measure").onclick = () => act(() => api("/api/measure", {}));
$("btn-home").onclick = () => act(() => api("/api/home", {}));
$("btn-release").onclick = () => act(() => api("/api/release", {}));
$("btn-cam").onclick = () => act(() => api("/api/camera", { exposure_s: Number($("exp").value), gain: Number($("gain").value) }));
$("btn-declare").onclick = () => act(async () => {
  if (!confirm("Record the CURRENT pointing as 'telescope aligned'?\n\nOnly do this after the telescope's own polar-alignment routine reports the smallest error it can.")) return;
  await api("/api/calibration/declare", { confirm: true });
});
$("btn-clearcal").onclick = () => act(async () => {
  if (!confirm("Forget the stored camera-to-axis calibration?")) return;
  await api("/api/calibration/clear", { confirm: true });
});
$("btn-manual").onclick = () => act(() => api("/api/location", {
  latitude: Number($("lat").value), longitude: Number($("lon").value), source: "manual", unix_ms: Date.now() }));
$("btn-phone").onclick = () => act(async () => {
  if (!navigator.geolocation || !window.isSecureContext) {
    $("geo-hint").textContent =
      "This browser blocks location on plain http pages (not a secure context). Enter latitude/longitude below; the clock is still taken from this device.";
    await api("/api/location", { latitude: Number($("lat").value || 0), longitude: Number($("lon").value || 0), source: "manual", unix_ms: Date.now() })
      .catch(() => {});
    return;
  }
  const pos = await new Promise((res, rej) => navigator.geolocation.getCurrentPosition(res, rej, { enableHighAccuracy: true, timeout: 15000 }));
  await api("/api/location", { latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy_m: pos.coords.accuracy,
                               source: "browser", unix_ms: Date.now() });
});

$("sim-hand").onclick = () => act(() => api("/api/sim/coarse", { error_deg: 0.015, direction_deg: 40 }));
$("sim-knock").onclick = () => act(() => api("/api/sim/coarse", { error_deg: 5, direction_deg: 130 }));

// ---- rendering -------------------------------------------------------------------------------
let lastStatus = null;
let lastFrameKey = "";
function render(s) {
  lastStatus = s;
  busy = s.job && !s.job.done ? s.job.name : null;
  $("badge-hw").textContent = s.hardware === "sim" ? "SIMULATOR" : "";
  $("sim-card").hidden = s.hardware !== "sim";
  const ab = $("btn-align");
  ab.textContent = busy === "align" ? "Cancel" : "Align";
  ab.classList.toggle("cancel", busy === "align");
  ab.disabled = busy !== null && busy !== "align";
  for (const id of ["btn-measure", "btn-home", "btn-declare"]) $(id).disabled = busy !== null;
  document.querySelectorAll("#jogs button").forEach((b) => (b.disabled = busy !== null));

  const e = s.error;
  const big = $("err-total");
  if (e) {
    const m = e.total_arcmin;
    big.textContent = m < 100 ? `${m.toFixed(m < 10 ? 2 : 1)}′` : `${(m / 60).toFixed(2)}°`;
    big.className = "big " + (m < s.config.target_arcmin ? "ok" : m < 15 ? "mid" : "far");
    $("err-deg").textContent = `${(m / 60).toFixed(3)}° from the ${e.hemisphere > 0 ? "north" : "south"} celestial pole of date`;
    const upDown = e.alt_arcmin >= 0 ? "too high" : "too low";
    const eastWest = e.east_arcmin >= 0 ? "east" : "west";
    $("err-detail").textContent = e.horizontal_frame
      ? `altitude ${Math.abs(e.alt_arcmin).toFixed(1)}′ ${upDown} · azimuth ${Math.abs(e.az_dial_arcmin).toFixed(1)}′ too far ${eastWest}`
      : `sky frame: ${e.alt_arcmin.toFixed(1)}′, ${e.east_arcmin.toFixed(1)}′ (set a location for alt/az)`;
  } else {
    big.textContent = "–"; big.className = "big"; $("err-deg").textContent = ""; $("err-detail").textContent = "Press “Solve now” or “Align”.";
  }
  $("phase").textContent = `${s.phase.phase}: ${s.phase.message}`;
  const hist = s.report?.history || [];
  $("iters").innerHTML = hist.map((h) => `<li>${h.iteration}: ${h.total_arcmin.toFixed(2)}′</li>`).join("");

  // solve panel
  const sv = s.solve;
  kv($("solve"), sv ? [
    ["sensor", s.camera.sensor], ["status", sv.status + (sv.detail ? ` (${sv.detail})` : "")], ["stars found", sv.n_stars],
    ["matched", sv.matches ?? "–"], ["RA / Dec (J2000)", sv.ra_deg !== undefined ? `${fmt(sv.ra_deg, 3)}° / ${fmt(sv.dec_deg, 3)}°` : "–"],
    ["fit residual", sv.rmse_arcsec !== undefined ? `${fmt(sv.rmse_arcsec, 1)}″` : "–"],
    ["FOV", sv.fov_deg !== undefined ? `${fmt(sv.fov_deg, 2)}°` : "–"],
    ["timing (ms)", sv.timings_ms ? Object.entries(sv.timings_ms).map(([k, v]) => `${k} ${v}`).join(" · ") : "–"],
    ["sky background", sv.background_adu !== undefined ? `${sv.background_adu} ADU, noise ${sv.noise_adu}` : "–"],
  ] : [["status", "no solve yet"]]);
  if (sv && sv.time && sv.time !== lastFrameKey) {
    lastFrameKey = sv.time;
    $("preview").src = `/api/frame.png?t=${encodeURIComponent(sv.time)}`;
    $("preview").hidden = false;
  }

  // jog positions
  for (const a of ["az", "alt"]) {
    const ax = s.motion.axes[a];
    $("pos-" + a).textContent = `${ax.position_deg >= 0 ? "+" : ""}${ax.position_deg.toFixed(3)}° (±${ax.limit_deg}°) · ` +
      `${ax.homed ? "homed" : "not homed"}${ax.fault ? " · FAULT: " + ax.fault : ""}` +
      `${ax.min_switch ? " · MIN switch" : ""}${ax.max_switch ? " · MAX switch" : ""}`;
  }

  // calibration
  const c = s.calibration;
  kv($("cal"), [["calibrated", c.calibrated ? "yes" : "no"], ["entries", c.entries], ["repeatability", c.spread_arcsec != null ? `${c.spread_arcsec.toFixed(0)}″` : "–"],
                ["last", c.last || "–"]]);

  // site / sensors
  const site = s.site;
  const imu = s.imu, g = s.gnss;
  kv($("site"), [
    ["location", site ? `${fmt(site.latitude_deg, 4)}, ${fmt(site.longitude_deg, 4)} (${site.source})` : "unknown"],
    ["time (UTC)", `${s.time_utc.replace("T", " ").replace("+00:00", "")} (${s.time_source})`],
    ["GNSS", g.available ? (g.valid ? `fix, ${g.satellites} sats` : "searching…") : "not present"],
    ["axis elevation (IMU)", imu.available && imu.axis_elevation_deg != null ? `${imu.axis_elevation_deg.toFixed(1)}°` +
        (site ? `  → set coarse tilt to ${Math.abs(site.latitude_deg).toFixed(1)}°` : "") : "n/a"],
    ["knocks", imu.available ? imu.knocks : "n/a"],
  ]);

  const w = $("warnings");
  w.hidden = !s.warnings.length;
  w.innerHTML = s.warnings.length ? "<ul>" + s.warnings.map((x) => `<li>${x}</li>`).join("") + "</ul>" : "";
  if (s.log) $("log").textContent = s.log.slice(-40).map((l) => `${new Date(l.t * 1000).toLocaleTimeString()}  ${l.phase}: ${l.message}`).join("\n");
  if (s.camera) { if (document.activeElement !== $("exp")) $("exp").value = s.camera.exposure_s; if (document.activeElement !== $("gain")) $("gain").value = s.camera.gain; }
}

// ---- live updates: SSE with polling fallback --------------------------------------------------
function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = (m) => { $("conn").classList.add("on"); render(JSON.parse(m.data)); };
  es.onerror = () => {
    $("conn").classList.remove("on");
    es.close();
    poll();
  };
}
async function poll() {
  try { render(await api("/api/status")); $("conn").classList.add("on"); } catch (_) { $("conn").classList.remove("on"); }
  setTimeout(() => (window.EventSource ? connect() : poll()), 2000);
}
window.EventSource ? connect() : poll();

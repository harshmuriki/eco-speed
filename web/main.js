// App wiring: screens, settings, GPS or simulator, wake lock, spoken cues.
import { GpsProcessor, startGeolocation } from "./gps.js";
import { GpsLog, TripStore } from "./savings.js";
import { TripSession } from "./session.js";
import { Simulator, simOptionsFromURL } from "./simulate.js";
import * as ui from "./ui.js";

const { $ } = ui;
const SIM = simOptionsFromURL();
const SETTINGS_KEY = "ecoSpeed.settings";
const DISCLAIMER_KEY = "ecoSpeed.disclaimerAccepted";

function storage() { try { localStorage.getItem("x"); return localStorage; } catch { return null; } }
const store = storage();
const getJSON = (k, d) => { try { return JSON.parse(store?.getItem(k) ?? "null") ?? d; } catch { return d; } };
const setJSON = (k, v) => { try { store?.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } };

const routes = {};
let settings = null;
let session = null;
let stopSource = null;
let lastSummary = null;

// ------------------------------------------------------------ spoken cues
const speaker = {
  last: null, lastAt: 0,
  say(text) {
    if (!settings.audio || !("speechSynthesis" in window)) return;
    const now = performance.now();
    if (text === this.last || now - this.lastAt < 15000) return; // only on change, max every 15 s
    this.last = text; this.lastAt = now;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  },
  reset() { this.last = null; this.lastAt = 0; },
};

// ------------------------------------------------------------ wake lock
let wakeLock = null;
async function lockScreen() {
  try { wakeLock = await navigator.wakeLock?.request("screen"); } catch { wakeLock = null; }
}
document.addEventListener("visibilitychange", () => {
  if (session && !session.ended && document.visibilityState === "visible") lockScreen();
});

// ------------------------------------------------------------ data + settings
async function loadRoutes() {
  for (const d of ["northbound", "southbound"]) {
    try {
      const r = await fetch(`data/route_${d}.json`, { cache: "no-cache" });
      if (r.ok) routes[d] = await r.json();
    } catch { /* missing direction */ }
  }
  if (!routes.northbound && !routes.southbound) throw new Error("No route data found in web/data/.");
}

function defaultSettings() {
  const vp = (routes.northbound ?? routes.southbound).vehicle_params;
  return { fuelPrice: vp.fuel_price_usd_per_gal ?? 3.2, direction: "auto", audio: true };
}

function refreshHome() {
  const trips = new TripStore(store);
  const mine = trips.all().filter((t) => !!t.simulated === !!SIM);
  ui.renderHome({ routes, settings, sim: !!SIM, month: trips.monthTotals(new Date(), !!SIM),
                  lastTrip: mine.at(-1) ?? null });
}

// ------------------------------------------------------------ trip lifecycle
function startTrip() {
  speaker.reset();
  ui.renderDriveWaiting(SIM ? "Starting simulation…" : "Waiting for GPS…");
  ui.setMuteButton(settings.audio);
  ui.show("drive");
  lockScreen();

  session = new TripSession({
    routes, direction: settings.direction, fuelPrice: settings.fuelPrice, storage: store,
    simulated: !!SIM,
    onUpdate: (u) => {
      ui.renderDrive(u, { sim: !!SIM });
      if (u.advice) speaker.say(u.advice.cue);
    },
    onEnd: (summary, reason) => finishTrip(summary, reason),
  });
  const gps = new GpsProcessor({ onFix: (f) => session.handleFix(f) });

  if (SIM) {
    const dir = settings.direction === "auto" ? (routes.northbound ? "northbound" : "southbound") : settings.direction;
    const sim = new Simulator(routes[dir], SIM);
    stopSource = sim.start((pos) => gps.ingest(pos), () => session?.end("sim_done"));
  } else {
    stopSource = startGeolocation(gps, (err) => {
      ui.renderDriveWaiting(err.code === 1 ? "Location permission denied — enable it to use the app"
                                          : `GPS: ${err.message || "no signal"}`);
    });
  }
}

function finishTrip(summary, reason) {
  stopSource?.(); stopSource = null;
  wakeLock?.release?.().catch(() => {}); wakeLock = null;
  window.speechSynthesis?.cancel();
  lastSummary = summary;
  ui.renderSummary(summary, reason);
  ui.show("summary");
  if (settings.audio && summary?.segments && "speechSynthesis" in window) {
    const s = summary;
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(
      `Trip complete. About ${Math.round(s.mpg)} miles per gallon.`));
  }
}

// ------------------------------------------------------------ events
function bind() {
  $("btn-accept").onclick = () => { setJSON(DISCLAIMER_KEY, true); refreshHome(); ui.show("home"); };
  $("btn-start").onclick = startTrip;
  $("btn-end").onclick = () => session?.end("manual");
  $("btn-mute").onclick = () => {
    settings.audio = !settings.audio; setJSON(SETTINGS_KEY, settings);
    ui.setMuteButton(settings.audio);
    if (!settings.audio) window.speechSynthesis?.cancel();
  };
  $("btn-done").onclick = () => { session = null; refreshHome(); ui.show("home"); };
  $("btn-settings").onclick = () => { ui.fillSettings(settings); ui.show("settings"); };
  $("btn-settings-done").onclick = () => {
    settings = ui.readSettings(settings); setJSON(SETTINGS_KEY, settings); refreshHome(); ui.show("home");
  };
  $("btn-export").onclick = () => {
    const log = new GpsLog(store).load();
    if (!log) { alert("No GPS log yet. One is saved for the most recent trip."); return; }
    const blob = new Blob([JSON.stringify(log, null, 1)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(blob), download: `eco-speed-gpslog-${(log.meta?.startedAt ?? "trip").slice(0, 19)}.json`,
    });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  $("btn-clear").onclick = () => {
    if (confirm("Delete all saved trips from this phone?")) { new TripStore(store).clear(); refreshHome(); }
  };
}

async function main() {
  bind();
  try {
    await loadRoutes();
  } catch (e) {
    document.body.innerHTML = `<section class="screen"><div class="panel"><h1>No route data</h1>
      <p>${e.message} Run <code>python -m pipeline.run_all</code> first.</p></div></section>`;
    return;
  }
  settings = { ...defaultSettings(), ...getJSON(SETTINGS_KEY, {}) };
  refreshHome();
  ui.show(getJSON(DISCLAIMER_KEY, false) ? "home" : "disclaimer");
  window.__eco = { routes, get settings() { return settings; }, get session() { return session; },
                   get lastSummary() { return lastSummary; } }; // for debugging / automated tests
}

main();

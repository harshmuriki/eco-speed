// DOM rendering only. No app logic here.
import { CUE } from "./advisor.js";
import { MS_TO_MPH } from "./gps.js";
import { ML_PER_GAL } from "./savings.js";

const $ = (id) => document.getElementById(id);
const SCREENS = ["disclaimer", "home", "drive", "summary", "settings"];

export function show(name) {
  for (const s of SCREENS) $(`screen-${s}`).hidden = s !== name;
  window.scrollTo(0, 0);
}

const fmt = {
  gal: (g) => `${g >= 0 ? "" : "−"}${Math.abs(g).toFixed(3)} gal`,
  usd: (d) => `${d < 0 ? "−" : ""}$${Math.abs(d).toFixed(2)}`,
  min: (m) => `${m >= 0 ? "+" : "−"}${Math.abs(m).toFixed(1)} min`,
  mph: (v) => (v == null ? "--" : Math.round(v * MS_TO_MPH).toString()),
};
const stat = (value, label, cls = "") => `<div class="stat"><b class="${cls}">${value}</b><small>${label}</small></div>`;
const dirName = (d) => (d === "northbound" ? "Northbound → Marietta" : d === "southbound" ? "Southbound → Georgia Tech" : "Auto-detect");

export function renderHome({ routes, settings, month, lastTrip, sim }) {
  const anyRoute = routes.northbound || routes.southbound;
  $("home-vehicle").textContent = `${anyRoute?.vehicle ?? "Vehicle"} · I-75`;
  const badges = [];
  if (sim) badges.push(`<span class="badge sim">Simulation mode</span>`);
  if (anyRoute?.data_source === "synthetic") badges.push(`<span class="badge">Demo route data</span>`);
  $("home-badges").innerHTML = badges.join("");
  $("home-direction").textContent = `Direction: ${dirName(settings.direction)}`;

  $("home-month").innerHTML =
    stat(month.trips, sim ? "sim trips" : "trips") +
    stat(fmt.usd(month.savedUsd), "saved", month.savedUsd >= 0 ? "good" : "bad") +
    stat(`${month.savedGal.toFixed(2)}`, "gal saved");

  $("home-last-card").hidden = !lastTrip;
  if (lastTrip) {
    $("home-last").innerHTML =
      stat(lastTrip.mpg.toFixed(1), "mpg") +
      stat(fmt.usd(lastTrip.savedUsd), "saved", lastTrip.savedUsd >= 0 ? "good" : "bad") +
      stat(fmt.min(lastTrip.timeDiffMin), "vs limit");
  }

  const r = routes[settings.direction] ?? routes.northbound ?? routes.southbound;
  if (r) {
    const t = r.totals;
    const gal = (t.base_fuel_ml - t.opt_fuel_ml) / ML_PER_GAL;
    $("home-plan").innerHTML =
      stat(`${(t.distance_m / 1609.344).toFixed(1)} mi`, r.direction) +
      stat(fmt.usd(gal * settings.fuelPrice), "potential/trip", "good") +
      stat(fmt.min((t.opt_time_s - t.base_time_s) / 60), "time cost");
  }
}

const CUE_CLASS = { [CUE.HOLD]: "cue-hold", [CUE.UP]: "cue-up", [CUE.DOWN]: "cue-down" };

export function renderDrive({ fix, match, advice, live, route }, { sim } = {}) {
  $("drive-speed").textContent = fmt.mph(fix.speed);
  const status = $("drive-status");
  const cue = $("drive-cue");
  const gpsTxt = `GPS ±${Math.round(fix.accuracy)} m`;

  if (match.status === "on_route" && advice) {
    const leftMi = ((route.totals.distance_m - match.distAlongM) / 1609.344).toFixed(1);
    status.textContent = `${route.direction === "northbound" ? "NB" : "SB"} · ${leftMi} mi left · ${gpsTxt}${sim ? " · SIM" : ""}`;
    status.classList.remove("warn");
    $("drive-target").textContent = fmt.mph(advice.targetMs);
    $("drive-limit").textContent = fmt.mph(advice.limitMs);
    cue.textContent = advice.cue;
    cue.className = `cue ${CUE_CLASS[advice.cue]}`;
  } else {
    status.textContent = match.status === "detecting" ? `Finding route… · ${gpsTxt}` : `Off route · ${gpsTxt}`;
    status.classList.toggle("warn", match.status === "off_route");
    $("drive-target").textContent = "--";
    $("drive-limit").textContent = "--";
    cue.textContent = match.status === "detecting" ? "Finding route" : "Off route — no advice";
    cue.className = "cue cue-none";
  }
  if (live) {
    $("drive-mpg").textContent = live.mpg > 0 && live.miles > 0.2 ? live.mpg.toFixed(1) : "--";
    $("drive-saved").textContent = `${live.savedGal >= 0 ? "" : "−"}${Math.abs(live.savedGal).toFixed(3)}`;
  }
}

export function renderDriveWaiting(msg = "Waiting for GPS…") {
  $("drive-status").textContent = msg;
  $("drive-speed").textContent = "--";
  $("drive-target").textContent = "--";
  $("drive-limit").textContent = "--";
  $("drive-mpg").textContent = "--";
  $("drive-saved").textContent = "--";
  const cue = $("drive-cue"); cue.textContent = "—"; cue.className = "cue cue-none";
}

export function setMuteButton(audioOn) {
  const b = $("btn-mute");
  b.textContent = audioOn ? "Sound on" : "Muted";
  b.setAttribute("aria-pressed", String(!audioOn));
}

const REASONS = { arrived: "Arrived at the end of the route", stopped: "Ended after stopping for 2+ minutes",
                  manual: "Ended manually", sim_done: "Simulation finished" };

export function renderSummary(s, reason) {
  if (!s || s.segments === 0) {
    $("sum-sub").textContent = "No route segments were completed, so there's nothing to compare.";
    $("sum-stats").innerHTML = "";
    $("sum-note").textContent = "";
    return;
  }
  $("sum-sub").textContent = `${dirName(s.direction)} · ${s.miles.toFixed(1)} mi · ${REASONS[reason] ?? ""}`;
  $("sum-stats").innerHTML =
    stat(s.mpg.toFixed(1), "trip mpg (estimated)") +
    stat(fmt.gal(s.savedGal), "fuel saved vs limit", s.savedGal >= 0 ? "good" : "bad") +
    stat(fmt.usd(s.savedUsd), `saved at $${s.fuelPrice.toFixed(2)}/gal`, s.savedUsd >= 0 ? "good" : "bad") +
    stat(fmt.min(s.timeDiffMin), "time vs limit") +
    stat(fmt.usd(s.potentialUsd), "if target followed exactly", "good") +
    stat(fmt.min(s.potentialTimeDiffMin), "time cost of target");
  $("sum-note").textContent = (s.simulated ? "Simulated trip. " : "") +
    "Fuel is estimated from GPS speed with a physics model, not measured." +
    (s.dataSource === "synthetic" ? " Route data is the offline demo." : "");
}

export function fillSettings(settings) {
  $("set-price").value = settings.fuelPrice.toFixed(2);
  $("set-direction").value = settings.direction;
  $("set-audio").checked = settings.audio;
}

export function readSettings(prev) {
  const price = parseFloat($("set-price").value);
  return { ...prev, fuelPrice: Number.isFinite(price) && price > 0 ? price : prev.fuelPrice,
           direction: $("set-direction").value, audio: $("set-audio").checked };
}

export { $ };

// Headless check of the web app's drive loop (Milestone 5 logic) with the simulator.
// Run: node --test tests/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { CUE } from "../web/advisor.js";
import { GpsProcessor, MS_TO_MPH } from "../web/gps.js";
import { fuelRateMls } from "../web/savings.js";
import { TripSession } from "../web/session.js";
import { Simulator } from "../web/simulate.js";

const load = (d) => JSON.parse(readFileSync(new URL(`../web/data/route_${d}.json`, import.meta.url)));
const routes = { northbound: load("northbound"), southbound: load("southbound") };

class MemStorage {
  constructor() { this.m = new Map(); }
  getItem(k) { return this.m.has(k) ? this.m.get(k) : null; }
  setItem(k, v) { this.m.set(k, String(v)); }
  removeItem(k) { this.m.delete(k); }
}

function drive(direction, simOpts = {}, sessionDir = "auto") {
  const storage = new MemStorage();
  const updates = [];
  let summary = null, reason = null;
  const session = new TripSession({
    routes, direction: sessionDir, fuelPrice: 3.2, storage, simulated: true,
    onUpdate: (u) => updates.push(u), onEnd: (s, r) => { summary = s; reason = r; },
  });
  const gps = new GpsProcessor({ onFix: (f) => session.handleFix(f) });
  const sim = new Simulator(routes[direction], { seed: 7, ...simOpts });
  for (let i = 0; i < 20000 && !session.ended; i++) {
    const pos = sim.step();
    if (!pos) break;
    gps.ingest(pos);
  }
  if (!session.ended) session.end("sim_done");
  return { updates, summary, reason, storage, session };
}

test("JS fuel model matches the Python export (65 mph flat ~ EPA mpg)", () => {
  const p = routes.northbound.vehicle_params;
  const v = 65 * 0.44704;
  const mpg = 3785.411784 / ((fuelRateMls(v, 0, 0, p) / v) * 1609.344);
  assert.ok(Math.abs(mpg - p.epa_hwy_mpg) < 0.5, `mpg ${mpg}`);
});

for (const dir of ["northbound", "southbound"]) {
  test(`${dir}: auto-detects direction, map-matches, cues, ends on arrival`, () => {
    const { updates, summary, reason } = drive(dir);
    const on = updates.filter((u) => u.match.status === "on_route");
    assert.equal(updates.at(-1).match.direction, dir);
    assert.ok(on.length / updates.length > 0.95, "mostly on route");
    // segment index never jumps backwards by more than the search window
    for (let i = 1; i < on.length; i++) assert.ok(on[i].match.segIdx >= on[i - 1].match.segIdx - 2);
    for (const u of on) {
      assert.ok(u.advice.targetMs <= u.advice.limitMs + 1e-9, "target above limit");
      assert.ok(u.advice.targetMs * MS_TO_MPH >= 45 - 1e-6, "target below min speed");
      assert.ok(u.match.dist < 30, "match distance");
    }
    const cues = new Set(on.map((u) => u.advice.cue));
    assert.ok(cues.has(CUE.HOLD) && cues.size >= 2, [...cues].join());
    assert.equal(reason, "arrived");
    assert.ok(summary.segments >= routes[dir].segments.length - 3, `segments ${summary.segments}`);
    assert.ok(summary.mpg > 30 && summary.mpg < 60, `mpg ${summary.mpg}`);
    // a driver roughly following the eco target saves fuel vs the limit baseline
    assert.ok(summary.savedGal > 0, `saved ${summary.savedGal}`);
    assert.ok(Math.abs(summary.savedGal - summary.potentialGal) < 0.03);
  });
}

test("driving at the limit saves roughly nothing and is faster", () => {
  const { summary } = drive("northbound", { profile: "limit" });
  assert.ok(Math.abs(summary.savedGal) < 0.02, `saved ${summary.savedGal}`);
  assert.ok(summary.timeDiffMin < 0.5, `time ${summary.timeDiffMin}`);
  assert.ok(summary.potentialGal > 0.03);
});

test("stopping for over 2 minutes ends the trip", () => {
  const { reason, summary } = drive("northbound", { stopAtM: 5000 });
  assert.equal(reason, "stopped");
  assert.ok(summary.miles > 2.5 && summary.miles < 4, `miles ${summary.miles}`);
});

test("manual direction + off-route fixes give no advice", () => {
  const storage = new MemStorage();
  const out = [];
  const s = new TripSession({ routes, direction: "northbound", fuelPrice: 3.2, storage,
                              onUpdate: (u) => out.push(u) });
  s.handleFix({ t: 0, lat: 33.70, lon: -84.20, speed: 25, accel: 0, accuracy: 5, heading: 0 });
  assert.equal(out[0].match.status, "off_route");
  assert.equal(out[0].advice, null);
});

test("completed trips are stored and GPS log is exportable", () => {
  const { storage } = drive("southbound");
  const trips = JSON.parse(storage.getItem("ecoSpeed.trips"));
  assert.equal(trips.length, 1);
  const log = JSON.parse(storage.getItem("ecoSpeed.gpsLog"));
  assert.ok(log.fixes.length > 500);
});

test("GPS processor drops inaccurate fixes and derives speed when missing", () => {
  const got = [];
  const g = new GpsProcessor({ onFix: (f) => got.push(f) });
  g.ingest({ timestamp: 0, coords: { latitude: 33.8, longitude: -84.4, accuracy: 50, speed: 20 } });
  assert.equal(got.length, 0);
  g.ingest({ timestamp: 0, coords: { latitude: 33.8, longitude: -84.4, accuracy: 5, speed: null } });
  g.ingest({ timestamp: 1000, coords: { latitude: 33.8002, longitude: -84.4, accuracy: 5, speed: null } });
  assert.equal(got.length, 2);
  assert.ok(got[1].rawSpeed > 21 && got[1].rawSpeed < 24, `raw ${got[1].rawSpeed}`);
  assert.ok(Math.abs(got[1].speed - 0.3 * got[1].rawSpeed) < 1e-9); // EMA from 0
});

test("advisor: cues, +-2 mph band, hysteresis, blending, never above limit", async () => {
  const { Advisor } = await import("../web/advisor.js");
  const mph = 0.44704;
  const route = { segments: [
    { target_speed_ms: 50 * mph, speed_limit_ms: 55 * mph },
    { target_speed_ms: 60 * mph, speed_limit_ms: 55 * mph },   // bad data: target > limit
  ] };
  const a = new Advisor();
  const m = (frac) => ({ segIdx: 0, frac });
  assert.equal(a.advise(route, m(0.1), 51.5 * mph).cue, CUE.HOLD);   // within band
  assert.equal(a.advise(route, m(0.1), 52.5 * mph).cue, CUE.DOWN);   // > +2 mph
  assert.equal(a.advise(route, m(0.1), 51.5 * mph).cue, CUE.DOWN);   // hysteresis: still easing
  assert.equal(a.advise(route, m(0.1), 50.5 * mph).cue, CUE.HOLD);   // back within 1 mph
  assert.equal(a.advise(route, m(0.1), 47.5 * mph).cue, CUE.UP);     // < -2 mph
  // blending over last 30% of the segment toward next target, capped at the limit
  assert.ok(Math.abs(a.targetFor(route, 0, 0.5) - 50 * mph) < 1e-9);
  assert.ok(Math.abs(a.targetFor(route, 0, 0.85) - 55 * mph) < 1e-9);
  assert.ok(Math.abs(a.targetFor(route, 1, 0.2) - 55 * mph) < 1e-9);
});

// Fuel model (JS port of pipeline/fuel_model.py), per-trip savings, trip storage.

const G = 9.81;
export const ML_PER_GAL = 3785.411784;
export const M_PER_MILE = 1609.344;

/** Instantaneous fuel rate (mL/s); identical maths to fuel_rate_mls in Python. */
export function fuelRateMls(v, a, grade, p) {
  const theta = Math.atan(grade);
  const m = p.mass_kg;
  const F = m * p.rot_factor * a
    + 0.5 * p.air_density * p.cd * p.frontal_area_m2 * v * v
    + p.crr * m * G * Math.cos(theta)
    + m * G * Math.sin(theta);
  const eFuel = (p.fuel_mj_per_l * 1e6) / 1000; // J/mL
  return p.idle_fuel_mls + Math.max(F * v, 0) / (p.engine_eff * eFuel);
}

export class TripTracker {
  constructor(route, { fuelPrice }) {
    this.route = route;
    this.vp = route.vehicle_params;
    this.fuelPrice = fuelPrice;
    this.startT = null; this.lastT = null;
    this.firstSeg = null; this.lastSeg = null;
    this.driverFuelMl = 0; this.driverTimeS = 0; this.driverDistM = 0;
    // totals over *completed* segments only, so the comparison is like-for-like
    this.done = { n: 0, baseFuel: 0, optFuel: 0, baseTime: 0, optTime: 0, lengthM: 0,
                  driverFuel: 0, driverTime: 0 };
    this.stoppedSince = null;
  }

  /** Feed every fix with its match result. */
  update(fix, match) {
    if (this.startT == null) this.startT = fix.t;
    const dt = this.lastT == null ? 0 : Math.min(Math.max(fix.t - this.lastT, 0), 5); // cap GPS gaps
    this.lastT = fix.t;

    this.stoppedSince = fix.speed < 1.0 ? (this.stoppedSince ?? fix.t) : null;
    if (match.status !== "on_route") return;

    const seg = this.route.segments[match.segIdx];
    const a = Math.max(-3, Math.min(3, fix.accel || 0));
    this.driverFuelMl += fuelRateMls(fix.speed, a, seg.grade, this.vp) * dt;
    this.driverTimeS += dt;
    this.driverDistM += fix.speed * dt;

    if (this.firstSeg == null) { this.firstSeg = this.lastSeg = match.segIdx; return; }
    if (match.segIdx > this.lastSeg) {
      for (let i = this.lastSeg; i < match.segIdx; i++) this.completeSegment(i);
      this.lastSeg = match.segIdx;
      this.done.driverFuel = this.driverFuelMl;
      this.done.driverTime = this.driverTimeS;
    }
  }

  completeSegment(i) {
    const s = this.route.segments[i];
    this.done.n++;
    this.done.baseFuel += s.base_fuel_ml; this.done.optFuel += s.opt_fuel_ml;
    this.done.baseTime += s.base_time_s; this.done.optTime += s.opt_time_s;
    this.done.lengthM += s.length_m;
  }

  /** Count the final segment when the trip ends on it. */
  finish(match) {
    if (match && match.status === "on_route" && this.lastSeg != null &&
        match.segIdx === this.route.segments.length - 1 && match.frac > 0.5 &&
        this.done.n < this.route.segments.length - this.firstSeg) {
      this.completeSegment(match.segIdx);
      this.done.driverFuel = this.driverFuelMl;
      this.done.driverTime = this.driverTimeS;
    }
    return this.summary();
  }

  stoppedForS(t) { return this.stoppedSince == null ? 0 : t - this.stoppedSince; }

  summary() {
    const d = this.done;
    const gal = (ml) => ml / ML_PER_GAL;
    const miles = d.lengthM / M_PER_MILE;
    const driverGal = gal(d.driverFuel), baseGal = gal(d.baseFuel), optGal = gal(d.optFuel);
    return {
      direction: this.route.direction,
      endedAt: new Date().toISOString(),
      segments: d.n,
      miles,
      driverGal, baseGal, optGal,
      mpg: driverGal > 0 ? miles / driverGal : 0,
      savedGal: baseGal - driverGal,
      savedUsd: (baseGal - driverGal) * this.fuelPrice,
      timeDiffMin: (d.driverTime - d.baseTime) / 60,     // + = slower than baseline
      potentialGal: baseGal - optGal,
      potentialUsd: (baseGal - optGal) * this.fuelPrice,
      potentialTimeDiffMin: (d.optTime - d.baseTime) / 60,
      fuelPrice: this.fuelPrice,
      dataSource: this.route.data_source,
    };
  }

  /** Live numbers for the driving screen (distance-based, includes the current segment). */
  live() {
    const miles = this.driverDistM / M_PER_MILE;
    const gal = this.driverFuelMl / ML_PER_GAL;
    return { miles, mpg: gal > 0 ? miles / gal : 0, savedGal: this.summary().savedGal };
  }
}

// ------------------------------------------------------------------ storage
function safeStorage(storage) {
  try { const s = storage ?? globalThis.localStorage; s.getItem("x"); return s; }
  catch { return null; }
}

export class TripStore {
  constructor(storage) { this.s = safeStorage(storage); this.key = "ecoSpeed.trips"; }
  all() {
    try { return JSON.parse(this.s?.getItem(this.key) || "[]"); } catch { return []; }
  }
  save(trip) {
    const trips = this.all(); trips.push(trip);
    try { this.s?.setItem(this.key, JSON.stringify(trips.slice(-500))); } catch { /* full */ }
  }
  clear() { try { this.s?.removeItem(this.key); } catch { /* ignore */ } }
  /** Totals for the current month; real trips only unless `simulated` is true (sim mode). */
  monthTotals(now = new Date(), simulated = false) {
    const ym = now.toISOString().slice(0, 7);
    const trips = this.all().filter((t) => (t.endedAt || "").slice(0, 7) === ym && !!t.simulated === simulated);
    return trips.reduce((a, t) => ({ trips: a.trips + 1, savedGal: a.savedGal + t.savedGal,
                                     savedUsd: a.savedUsd + t.savedUsd, timeDiffMin: a.timeDiffMin + t.timeDiffMin }),
                        { trips: 0, savedGal: 0, savedUsd: 0, timeDiffMin: 0 });
  }
}

/** GPS fix log for debugging real drives (last trip only), exportable as JSON. */
export class GpsLog {
  constructor(storage) { this.s = safeStorage(storage); this.key = "ecoSpeed.gpsLog"; this.buf = []; }
  start(meta) { this.buf = []; this.meta = { ...meta, startedAt: new Date().toISOString() }; }
  add(fix, match, advice) {
    this.buf.push({ t: +fix.t.toFixed(2), lat: +fix.lat.toFixed(6), lon: +fix.lon.toFixed(6),
                    acc: Math.round(fix.accuracy), v: +fix.speed.toFixed(2), raw: +(fix.rawSpeed ?? 0).toFixed(2),
                    hdg: fix.heading == null ? null : Math.round(fix.heading),
                    seg: match?.segIdx ?? null, d: match?.dist == null ? null : Math.round(match.dist),
                    st: match?.status, tgt: advice ? +advice.targetMs.toFixed(2) : null, cue: advice?.cue });
    if (this.buf.length % 30 === 0) this.flush();
  }
  flush() {
    try { this.s?.setItem(this.key, JSON.stringify({ meta: this.meta, fixes: this.buf })); } catch { /* full */ }
  }
  load() { try { return JSON.parse(this.s?.getItem(this.key) || "null"); } catch { return null; } }
}

// Dev mode (?sim=1): replay a fake drive along the route, emitting synthetic
// GeolocationPosition-like objects into the normal GPS pipeline.
//
// URL options:
//   sim=1            enable simulation
//   rate=10          playback speed (x real time), default 10
//   profile=target   driver follows eco target with some wobble (default)
//          =limit    driver drives at the speed limit
//          =const    driver holds a constant speed (mph=60)
//   mph=60           speed for profile=const
//   noise=3          GPS position noise (m)
//   stopat=5         park for 130 s at this km (tests auto-end on stop)

const M_PER_DEG_LAT = 111320;

export function simOptionsFromURL(search = globalThis.location?.search ?? "") {
  const q = new URLSearchParams(search);
  if (q.get("sim") !== "1") return null;
  return {
    rate: +(q.get("rate") ?? 10),
    profile: q.get("profile") ?? "target",
    constMph: +(q.get("mph") ?? 60),
    noiseM: +(q.get("noise") ?? 3),
    stopAtM: q.get("stopat") != null ? +q.get("stopat") * 1000 : null,
    seed: +(q.get("seed") ?? 1),
  };
}

function rng(seed) { // mulberry32: deterministic noise so sim runs are repeatable
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Position and heading at distance s (m) along the route. */
export function pointAt(route, s) {
  const segs = route.segments;
  let i = 0;
  while (i < segs.length - 1 && segs[i + 1].start_dist_m <= s) i++;
  const seg = segs[i];
  const frac = Math.max(0, Math.min(1, (s - seg.start_dist_m) / seg.length_m));
  const p = seg.polyline;
  const lat0 = p[0][0], k = Math.cos((lat0 * Math.PI) / 180);
  const lens = [];
  let total = 0;
  for (let j = 0; j < p.length - 1; j++) {
    const l = Math.hypot((p[j + 1][1] - p[j][1]) * k, p[j + 1][0] - p[j][0]);
    lens.push(l); total += l;
  }
  let target = frac * total, j = 0;
  while (j < lens.length - 1 && target > lens[j]) { target -= lens[j]; j++; }
  const t = lens[j] > 0 ? Math.min(1, target / lens[j]) : 0;
  const lat = p[j][0] + t * (p[j + 1][0] - p[j][0]);
  const lon = p[j][1] + t * (p[j + 1][1] - p[j][1]);
  const hdg = (Math.atan2((p[j + 1][1] - p[j][1]) * k, p[j + 1][0] - p[j][0]) * 180 / Math.PI + 360) % 360;
  return { lat, lon, heading: hdg, seg, segIdx: i };
}

export class Simulator {
  constructor(route, opts = {}) {
    this.route = route;
    this.o = { rate: 10, profile: "target", constMph: 60, noiseM: 3, stopAtM: null, seed: 1, hz: 1, ...opts };
    this.rand = rng(this.o.seed);
    this.total = route.segments.reduce((a, s) => a + s.length_m, 0);
    this.s = 0;
    this.v = 55 * 0.44704; // merge speed
    this.t = Date.now() / 1000;
    this.wobble = 0;
    this.parkedFor = 0;
    this.timer = null;
  }

  desiredSpeed(seg) {
    const mph = 0.44704;
    if (this.o.profile === "limit") return seg.speed_limit_ms;
    if (this.o.profile === "const") return this.o.constMph * mph;
    // human-ish driver: target plus a slowly wandering error of up to +-4 mph
    this.wobble += (this.rand() - 0.5) * 0.6;
    this.wobble = Math.max(-4, Math.min(4, this.wobble * 0.98));
    return seg.target_speed_ms + this.wobble * mph;
  }

  /** Advance one tick and return a GeolocationPosition-like object, or null when done. */
  step() {
    const dt = 1 / this.o.hz;
    if (this.s >= this.total - 1) return null;
    const here = pointAt(this.route, this.s);
    let desired = this.desiredSpeed(here.seg);
    if (this.o.stopAtM != null && this.s >= this.o.stopAtM && this.parkedFor < 130) {
      desired = 0;
      if (this.v < 0.3) this.parkedFor += dt;
    }
    const a = Math.max(-2.0, Math.min(1.0, (desired - this.v) / 3));
    this.v = Math.max(0, this.v + a * dt);
    this.s = Math.min(this.total, this.s + this.v * dt);
    this.t += dt;
    const p = pointAt(this.route, this.s);
    const n = this.o.noiseM, k = Math.cos((p.lat * Math.PI) / 180);
    const dn = (this.rand() - 0.5) * 2 * n, de = (this.rand() - 0.5) * 2 * n;
    return {
      timestamp: Math.round(this.t * 1000),
      coords: {
        latitude: p.lat + dn / M_PER_DEG_LAT,
        longitude: p.lon + de / (M_PER_DEG_LAT * k),
        accuracy: 4 + this.rand() * 4,
        speed: Math.max(0, this.v + (this.rand() - 0.5) * 0.4),
        heading: this.v > 1 ? p.heading : null,
        altitude: null, altitudeAccuracy: null,
      },
    };
  }

  start(onPosition, onDone) {
    const interval = 1000 / (this.o.hz * this.o.rate);
    this.timer = setInterval(() => {
      const pos = this.step();
      if (!pos) { this.stop(); onDone?.(); return; }
      onPosition(pos);
    }, interval);
    return () => this.stop();
  }

  stop() { if (this.timer) clearInterval(this.timer); this.timer = null; }
}

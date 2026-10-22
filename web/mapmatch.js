// Map-matching: GPS fix -> route segment (+ fraction through it), direction detection.
import { bearingDeg, haversineM } from "./gps.js";

const M_PER_DEG_LAT = 111320;

function toXY(lat, lon, lat0) {
  return [lon * M_PER_DEG_LAT * Math.cos((lat0 * Math.PI) / 180), lat * M_PER_DEG_LAT];
}

/** Distance from point to a segment polyline and the fraction of the polyline before it. */
export function pointToPolyline(lat, lon, poly) {
  const lat0 = poly[0][0];
  const [px, py] = toXY(lat, lon, lat0);
  const pts = poly.map(([a, o]) => toXY(a, o, lat0));
  let best = Infinity, bestAlong = 0, total = 0;
  const lens = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const l = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
    lens.push(l); total += l;
  }
  let acc = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1];
    const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy || 1e-9;
    const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2));
    const d = Math.hypot(ax + t * dx - px, ay + t * dy - py);
    if (d < best) { best = d; bestAlong = acc + t * lens[i]; }
    acc += lens[i];
  }
  return { dist: best, frac: total > 0 ? bestAlong / total : 0 };
}

function segBearing(seg) {
  const p = seg.polyline, a = p[0], b = p[p.length - 1];
  return bearingDeg(a[0], a[1], b[0], b[1]);
}

const angDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);

export class MapMatcher {
  /**
   * @param {{northbound?: object, southbound?: object}} routes  exported route JSONs
   * @param {"auto"|"northbound"|"southbound"} direction
   */
  constructor(routes, direction = "auto", opts = {}) {
    this.routes = routes;
    this.windowBack = opts.windowBack ?? 2;
    this.windowFwd = opts.windowFwd ?? 10;
    this.fallbackM = opts.fallbackM ?? 50;
    this.offRouteM = opts.offRouteM ?? 75;
    this.detectMinM = opts.detectMinM ?? 60;
    this.direction = direction === "auto" ? null : direction;
    this.lastIdx = null;
    this.firstFix = null;
  }

  get route() { return this.direction ? this.routes[this.direction] : null; }

  setDirection(dir) {
    this.direction = dir === "auto" ? null : dir;
    this.lastIdx = null; this.firstFix = null;
  }

  nearest(route, lat, lon, lo = 0, hi = route.segments.length - 1) {
    let best = { idx: -1, dist: Infinity, frac: 0 };
    for (let i = Math.max(0, lo); i <= Math.min(route.segments.length - 1, hi); i++) {
      const r = pointToPolyline(lat, lon, route.segments[i].polyline);
      if (r.dist < best.dist) best = { idx: i, dist: r.dist, frac: r.frac };
    }
    return best;
  }

  /** Pick a direction from heading over the first few fixes. Returns direction or null. */
  detect(fix) {
    if (!this.firstFix) this.firstFix = fix;
    const moved = haversineM(this.firstFix.lat, this.firstFix.lon, fix.lat, fix.lon);
    if (moved < this.detectMinM) return null;
    const travel = bearingDeg(this.firstFix.lat, this.firstFix.lon, fix.lat, fix.lon);
    let best = null, bestScore = Infinity;
    for (const [dir, route] of Object.entries(this.routes)) {
      if (!route) continue;
      const n = this.nearest(route, fix.lat, fix.lon);
      if (n.dist > this.offRouteM) continue;
      const score = angDiff(travel, segBearing(route.segments[n.idx]));
      if (score < bestScore) { bestScore = score; best = dir; }
    }
    if (best && bestScore < 60) { this.direction = best; this.lastIdx = null; }
    return this.direction;
  }

  /**
   * @returns {{status: "detecting"|"off_route"|"on_route", direction, segIdx, dist, frac, distAlongM}}
   */
  match(fix) {
    if (!this.direction && !this.detect(fix)) {
      return { status: "detecting", direction: null, segIdx: null, dist: null, frac: 0 };
    }
    const route = this.route;
    let m;
    if (this.lastIdx != null) {
      m = this.nearest(route, fix.lat, fix.lon, this.lastIdx - this.windowBack, this.lastIdx + this.windowFwd);
      if (m.dist > this.fallbackM) m = this.nearest(route, fix.lat, fix.lon);
    } else {
      m = this.nearest(route, fix.lat, fix.lon);
    }
    const base = { direction: this.direction, segIdx: m.idx, dist: m.dist, frac: m.frac };
    if (m.dist > this.offRouteM) return { ...base, status: "off_route" };
    this.lastIdx = m.idx;
    const seg = route.segments[m.idx];
    return { ...base, status: "on_route", distAlongM: seg.start_dist_m + m.frac * seg.length_m };
  }
}

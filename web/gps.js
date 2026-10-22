// GPS input: watchPosition -> filtered, smoothed fixes.
// The simulator feeds fake positions into the same GpsProcessor.ingest().

export const MS_TO_MPH = 2.2369362920544;

const R_EARTH = 6371000;
const rad = (d) => (d * Math.PI) / 180;

export function haversineM(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1), p2 = rad(lat2);
  const dp = p2 - p1, dl = rad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R_EARTH * Math.asin(Math.sqrt(a));
}

export function bearingDeg(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1), p2 = rad(lat2), dl = rad(lon2 - lon1);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

export class GpsProcessor {
  /**
   * @param {object} opts
   * @param {(fix: object) => void} opts.onFix   called with each accepted fix
   * @param {(pos: object, why: string) => void} [opts.onReject]
   */
  constructor({ onFix, onReject = () => {}, alpha = 0.3, maxAccuracyM = 30 }) {
    this.onFix = onFix;
    this.onReject = onReject;
    this.alpha = alpha;
    this.maxAccuracyM = maxAccuracyM;
    this.prev = null;
  }

  reset() { this.prev = null; }

  ingest(pos) {
    const c = pos.coords;
    if (c.accuracy == null || c.accuracy > this.maxAccuracyM) {
      this.onReject(pos, "accuracy");
      return null;
    }
    const t = pos.timestamp / 1000; // seconds
    const prev = this.prev;
    const dt = prev ? t - prev.t : 0;
    if (prev && dt <= 0.05) return null; // duplicate fix

    let raw = c.speed != null && c.speed >= 0 && Number.isFinite(c.speed) ? c.speed : null;
    if (raw == null) raw = prev ? haversineM(prev.lat, prev.lon, c.latitude, c.longitude) / dt : 0;

    const speed = prev ? this.alpha * raw + (1 - this.alpha) * prev.speed : raw;
    const accel = prev && dt > 0 ? (speed - prev.speed) / dt : 0;

    let heading = null;
    if (c.heading != null && Number.isFinite(c.heading) && speed > 2) heading = c.heading;
    else if (prev && haversineM(prev.lat, prev.lon, c.latitude, c.longitude) > 5)
      heading = bearingDeg(prev.lat, prev.lon, c.latitude, c.longitude);
    else if (prev) heading = prev.heading;

    const fix = { t, lat: c.latitude, lon: c.longitude, accuracy: c.accuracy,
                  speed, rawSpeed: raw, accel, heading, dt };
    this.prev = fix;
    this.onFix(fix);
    return fix;
  }
}

/** Start the real GPS. Returns a stop() function. */
export function startGeolocation(processor, onError) {
  if (!("geolocation" in navigator)) {
    onError?.(new Error("Geolocation is not available in this browser."));
    return () => {};
  }
  const id = navigator.geolocation.watchPosition(
    (pos) => processor.ingest(pos),
    (err) => onError?.(err),
    { enableHighAccuracy: true, maximumAge: 0, timeout: 5000 },
  );
  return () => navigator.geolocation.clearWatch(id);
}

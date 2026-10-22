// Target speed + cue for the current position.
import { MS_TO_MPH } from "./gps.js";

export const CUE = { HOLD: "Hold", UP: "Speed up", DOWN: "Ease off" };

export class Advisor {
  /**
   * Cue thresholds: enter "Speed up"/"Ease off" when more than `bandMph` away from
   * target; return to "Hold" once back within `exitMph` (hysteresis stops flicker).
   */
  constructor({ bandMph = 2, exitMph = 1, blendFrom = 0.7 } = {}) {
    this.bandMph = bandMph;
    this.exitMph = exitMph;
    this.blendFrom = blendFrom;
    this.cue = CUE.HOLD;
  }

  reset() { this.cue = CUE.HOLD; }

  targetFor(route, segIdx, frac) {
    const segs = route.segments, seg = segs[segIdx];
    let target = seg.target_speed_ms;
    const next = segs[segIdx + 1];
    if (next && frac > this.blendFrom) {
      const w = (frac - this.blendFrom) / (1 - this.blendFrom);
      target = target + w * (next.target_speed_ms - target);
    }
    return Math.min(target, seg.speed_limit_ms); // never advise above the limit
  }

  /** @returns {{targetMs, limitMs, cue, deltaMph}} */
  advise(route, match, speedMs) {
    const seg = route.segments[match.segIdx];
    const targetMs = this.targetFor(route, match.segIdx, match.frac);
    const deltaMph = (speedMs - targetMs) * MS_TO_MPH; // + = faster than target
    const absd = Math.abs(deltaMph);
    if (deltaMph > this.bandMph) this.cue = CUE.DOWN;
    else if (deltaMph < -this.bandMph) this.cue = CUE.UP;
    else if (absd <= this.exitMph) this.cue = CUE.HOLD;
    else if ((this.cue === CUE.DOWN && deltaMph < 0) || (this.cue === CUE.UP && deltaMph > 0))
      this.cue = CUE.HOLD; // crossed the target
    return { targetMs, limitMs: seg.speed_limit_ms, cue: this.cue, deltaMph };
  }
}

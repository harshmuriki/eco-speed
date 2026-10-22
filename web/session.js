// One trip: fix -> map-match -> advice -> savings, plus auto-end. No DOM here,
// so the whole drive loop can be tested headlessly (see tests/web_sim.test.mjs).
import { Advisor } from "./advisor.js";
import { MapMatcher } from "./mapmatch.js";
import { GpsLog, TripStore, TripTracker } from "./savings.js";

export const STOP_END_S = 120;

export class TripSession {
  constructor({ routes, direction = "auto", fuelPrice, onUpdate = () => {}, onEnd = () => {},
                storage, simulated = false }) {
    this.routes = routes;
    this.fuelPrice = fuelPrice;
    this.onUpdate = onUpdate;
    this.onEnd = onEnd;
    this.simulated = simulated;
    this.matcher = new MapMatcher(routes, direction);
    this.advisor = new Advisor();
    this.store = new TripStore(storage);
    this.log = new GpsLog(storage);
    this.log.start({ direction, simulated });
    this.tracker = null;
    this.lastMatch = null;
    this.ended = false;
    this.lastOnRouteT = null;
  }

  handleFix(fix) {
    if (this.ended) return null;
    const match = this.matcher.match(fix);
    if (!this.tracker && this.matcher.route) {
      this.tracker = new TripTracker(this.matcher.route, { fuelPrice: this.fuelPrice });
    }
    let advice = null;
    if (match.status === "on_route") {
      advice = this.advisor.advise(this.matcher.route, match, fix.speed);
      this.lastOnRouteT = fix.t;
    }
    this.tracker?.update(fix, match);
    this.log.add(fix, match, advice);
    this.lastMatch = match;

    const update = { fix, match, advice, live: this.tracker?.live() ?? null,
                     route: this.matcher.route };
    this.onUpdate(update);

    const segs = this.matcher.route?.segments;
    if (match.status === "on_route" && match.segIdx === segs.length - 1 && match.frac > 0.8) {
      this.end("arrived");
    } else if (this.tracker && this.tracker.stoppedForS(fix.t) > STOP_END_S) {
      this.end("stopped");
    }
    return update;
  }

  end(reason = "manual") {
    if (this.ended) return null;
    this.ended = true;
    this.log.flush();
    const summary = this.tracker ? this.tracker.finish(this.lastMatch) : null;
    if (summary) {
      summary.reason = reason;
      summary.simulated = this.simulated;
      if (summary.segments > 0) this.store.save(summary);
    }
    this.onEnd(summary, reason);
    return summary;
  }
}

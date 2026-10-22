"""Run the whole offline pipeline for both directions and print a summary.

    python -m pipeline.run_all              # real data (OSRM + Overpass + USGS), cached
    python -m pipeline.run_all --offline    # demo route, no network needed
    python -m pipeline.run_all --plot       # also save web/data/profile_<dir>.png
"""
from __future__ import annotations

import argparse
import logging

import numpy as np

from .baseline import baseline
from .common import ML_PER_GAL, WEB_DATA_DIR, load_route, load_vehicle, to_mph
from .export import build_export, write_export
from .fetch_elevation import get_elevations
from .fetch_route import get_route
from .fuel_model import load_params, steady_mpg
from .optimizer import choose_time_weight, optimize
from .segment import build_segments, resample, smooth_elevation

DIRECTIONS = ("northbound", "southbound")
TRIPS_PER_DAY, WORKDAYS_PER_MONTH = 2, 22


def build_direction(direction, route_cfg, params, offline, time_weight=None, verbose=True):
    pts = get_route(direction, route_cfg, offline=offline)
    samples = resample(pts, route_cfg["resample_step_m"])
    raw = get_elevations(samples["lat"], samples["lon"], route_cfg, direction, offline=offline)
    elev = smooth_elevation(raw, route_cfg["resample_step_m"], route_cfg["elevation_smoothing_m"],
                            dist=samples["dist"])
    segments = build_segments(samples, elev, route_cfg["segment_length_m"], route_cfg["max_abs_grade"])
    base = baseline(segments, params)
    if verbose:
        print(f"\n[{direction}] {len(segments)} segments, {samples['dist'][-1] / 1000:.2f} km; "
              f"time-weight sweep:")
    if time_weight is None:
        opt = choose_time_weight(segments, params, base, params.get("max_extra_time_s", 120), verbose)
    else:
        opt = optimize(segments, params, time_weight)
    doc = build_export(direction, segments, params, opt, base,
                       "synthetic" if offline else "osm", route_cfg.get("name", ""))
    return doc, segments, opt, base


def summarize(doc, price):
    t = doc["totals"]
    of, bf = t["opt_fuel_ml"] / ML_PER_GAL, t["base_fuel_ml"] / ML_PER_GAL
    miles = t["distance_m"] / 1609.344
    saved_gal = bf - of
    print(f"\n== {doc['direction']} ({doc['data_source']} data, time_weight={doc['time_weight']}) ==")
    print(f"  distance          {t['distance_m'] / 1000:6.2f} km ({miles:.2f} mi)")
    print(f"  baseline          {bf:6.3f} gal  {t['base_time_s'] / 60:6.2f} min  {miles / bf:5.1f} mpg")
    print(f"  optimised         {of:6.3f} gal  {t['opt_time_s'] / 60:6.2f} min  {miles / of:5.1f} mpg")
    print(f"  saving per trip   {saved_gal:6.3f} gal  ${saved_gal * price:.3f}  "
          f"({100 * saved_gal / bf:.1f}%), +{(t['opt_time_s'] - t['base_time_s']) / 60:.2f} min")
    return saved_gal


def plot_profile(doc, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not installed; skipping plot)")
        return
    segs = doc["segments"]
    d = np.array([s["start_dist_m"] for s in segs]) / 1000
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    a1.plot(d, [s["elevation_m"] for s in segs], color="#666")
    a1.set_ylabel("elevation (m)"); a1.set_title(f"{doc['direction']} ({doc['data_source']} data)")
    a2.step(d, [to_mph(s["speed_limit_ms"]) for s in segs], where="post", label="limit", color="#c33")
    a2.plot(d, [to_mph(s["target_speed_ms"]) for s in segs], label="eco target", color="#27a")
    a2.set_ylabel("mph"); a2.set_xlabel("distance (km)"); a2.legend()
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)
    print(f"  plot -> {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use the built-in demo route (no network)")
    ap.add_argument("--direction", choices=DIRECTIONS)
    ap.add_argument("--time-weight", type=float, help="override the automatic trade-off")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    route_cfg, vehicle = load_route(), load_vehicle()
    params = load_params(vehicle)
    tw = args.time_weight if args.time_weight is not None else vehicle.get("time_weight")
    price = params["fuel_price_usd_per_gal"]
    print(f"Vehicle: {params['vehicle_name']}; engine_eff calibrated "
          f"{params.get('engine_eff_uncalibrated', params['engine_eff']):.3f} -> {params['engine_eff']:.3f} "
          f"(65 mph flat = {steady_mpg(29.0576, params):.1f} mpg)")

    saved = {}
    for direction in ([args.direction] if args.direction else DIRECTIONS):
        doc, *_ = build_direction(direction, route_cfg, params, args.offline, tw, not args.quiet)
        path = write_export(doc)
        print(f"  wrote {path}")
        saved[direction] = summarize(doc, price)
        if args.plot:
            plot_profile(doc, WEB_DATA_DIR / f"profile_{direction}.png")

    per_day = sum(saved.values()) if len(saved) == 2 else next(iter(saved.values())) * TRIPS_PER_DAY
    month = per_day * WORKDAYS_PER_MONTH
    print(f"\nMonthly estimate ({TRIPS_PER_DAY} trips/day x {WORKDAYS_PER_MONTH} days): "
          f"{month:.2f} gal, ${month * price:.2f} at ${price:.2f}/gal")


if __name__ == "__main__":
    main()

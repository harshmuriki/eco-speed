"""Pipeline step 5b: export one JSON per direction to web/data/."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .common import WEB_DATA_DIR

# Parameters the web app needs to run the same fuel model in JS.
JS_PARAM_KEYS = ["mass_kg", "cd", "frontal_area_m2", "crr", "rot_factor", "idle_fuel_mls",
                 "engine_eff", "fuel_mj_per_l", "air_density", "epa_hwy_mpg",
                 "fuel_price_usd_per_gal", "min_speed_mph", "max_accel_ms2", "max_decel_ms2"]


def build_export(direction, segments, params, opt, base, data_source, route_name=""):
    segs = []
    for i, s in enumerate(segments):
        segs.append({
            "id": s["id"], "start_dist_m": s["start_dist_m"], "length_m": s["length_m"],
            "lat": s["lat"], "lon": s["lon"], "polyline": s["polyline"],
            "elevation_m": s["elevation_m"], "grade": s["grade"],
            "speed_limit_ms": s["speed_limit_ms"],
            "target_speed_ms": round(float(opt["target_speed_ms"][i]), 3),
            "opt_fuel_ml": round(float(opt["seg_fuel_ml"][i]), 3),
            "base_fuel_ml": round(float(base["seg_fuel_ml"][i]), 3),
            "opt_time_s": round(float(opt["seg_time_s"][i]), 3),
            "base_time_s": round(float(base["seg_time_s"][i]), 3),
        })
    return {
        "direction": direction,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vehicle": params.get("vehicle_name", "2026 Kia Sportage 2.5L"),
        "route_name": route_name,
        "data_source": data_source,  # "osm" or "synthetic"
        "time_weight": opt["time_weight"],
        "vehicle_params": {k: params[k] for k in JS_PARAM_KEYS if k in params},
        "totals": {
            "distance_m": round(sum(s["length_m"] for s in segments), 1),
            "opt_fuel_ml": round(opt["total_fuel_ml"], 2),
            "opt_time_s": round(opt["total_time_s"], 2),
            "base_fuel_ml": round(base["total_fuel_ml"], 2),
            "base_time_s": round(base["total_time_s"], 2),
        },
        "segments": segs,
    }


def write_export(doc: dict, out_dir: Path = WEB_DATA_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"route_{doc['direction']}.json"
    path.write_text(json.dumps(doc, separators=(",", ":")))
    return path

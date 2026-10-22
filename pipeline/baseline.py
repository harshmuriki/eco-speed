"""Pipeline step 5a: speed-limit baseline.

Drive at the posted limit everywhere, changing speed at limit changes with the same
comfort acceleration/deceleration limits as the optimiser (accelerate after an
increase, start slowing before a decrease). Same fuel model as the optimiser.
"""
from __future__ import annotations

import numpy as np

from .common import mph
from .fuel_model import segment_fuel_ml
from .optimizer import node_caps


def baseline(segments: list[dict], params: dict) -> dict:
    caps = node_caps(segments)
    L = np.array([s["length_m"] for s in segments])
    gr = np.array([s["grade"] for s in segments])
    v = caps.copy()
    v[0] = min(mph(params.get("merge_speed_mph", 55)), caps[0])
    for k in range(len(L)):                     # forward pass: acceleration limit
        v[k + 1] = min(v[k + 1], np.sqrt(v[k] ** 2 + 2 * params["max_accel_ms2"] * L[k]))
    for k in range(len(L) - 1, -1, -1):         # backward pass: deceleration limit
        v[k] = min(v[k], np.sqrt(v[k + 1] ** 2 + 2 * params["max_decel_ms2"] * L[k]))
    fuel, time = segment_fuel_ml(v[:-1], v[1:], L, gr, params)
    return {
        "node_speed_ms": v,
        "seg_fuel_ml": np.asarray(fuel),
        "seg_time_s": np.asarray(time),
        "total_fuel_ml": float(np.sum(fuel)),
        "total_time_s": float(np.sum(time)),
    }

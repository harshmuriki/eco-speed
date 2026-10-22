"""Pipeline step 4: look-ahead eco-driving speed optimiser (dynamic programming).

Nodes k = 0..N sit at segment boundaries; node k is the entry of segment k and the
exit of segment k-1. State = (node index, speed on a 1 mph grid). Each stage chooses
the exit speed of segment i subject to:
  * speed limit:   speed at a node <= limit of every segment touching it
  * minimum speed: grid starts at min_speed_mph
  * comfort:       -max_decel <= (v_out^2 - v_in^2) / (2 L) <= max_accel
Stage cost = fuel_ml + time_weight * time_s. Entry speed at node 0 is the merge speed,
exit speed at node N is free. Solved backwards (cost-to-go), traced forwards.
"""
from __future__ import annotations

import numpy as np

from .common import ML_PER_GAL, mph, to_mph
from .fuel_model import segment_fuel_ml


LIMIT_TOL = 0.01  # m/s; limits are stored rounded to 3 decimals


def node_caps(segments: list[dict]) -> np.ndarray:
    lim = np.array([s["speed_limit_ms"] for s in segments])
    caps = np.empty(len(lim) + 1)
    caps[0], caps[-1] = lim[0], lim[-1]
    caps[1:-1] = np.minimum(lim[:-1], lim[1:])
    return caps


def speed_grid(segments: list[dict], params: dict) -> np.ndarray:
    top = int(round(to_mph(max(s["speed_limit_ms"] for s in segments))))
    lo = int(params["min_speed_mph"])
    return mph(np.arange(lo, max(top, lo) + 1, 1.0))


def optimize(segments: list[dict], params: dict, time_weight: float) -> dict:
    V = speed_grid(segments, params)
    n, N = len(V), len(segments)
    caps = node_caps(segments)
    L = np.array([s["length_m"] for s in segments])[:, None, None]
    gr = np.array([s["grade"] for s in segments])[:, None, None]
    vin, vout = V[None, :, None], V[None, None, :]

    fuel, time = segment_fuel_ml(vin, vout, L, gr, params)          # (N, n, n)
    acc = (vout ** 2 - vin ** 2) / (2.0 * L)
    ok = (acc <= params["max_accel_ms2"] + 1e-9) & (acc >= -params["max_decel_ms2"] - 1e-9)
    ok &= (V[None, :, None] <= caps[:-1, None, None] + LIMIT_TOL)       # entry within limit
    ok &= (V[None, None, :] <= caps[1:, None, None] + LIMIT_TOL)        # exit within limit
    cost = np.where(ok, fuel + time_weight * time, np.inf)

    J = np.zeros(n)
    J[V > caps[-1] + LIMIT_TOL] = np.inf
    choice = np.zeros((N, n), dtype=int)
    for i in range(N - 1, -1, -1):
        total = cost[i] + J[None, :]
        choice[i] = np.argmin(total, axis=1)
        J = total[np.arange(n), choice[i]]

    v0 = min(mph(params.get("merge_speed_mph", 55)), caps[0] + LIMIT_TOL)
    start = int(np.argmin(np.abs(V - v0)))
    if not np.isfinite(J[start]):
        feas = np.nonzero(np.isfinite(J))[0]
        if not len(feas):
            raise RuntimeError("optimiser found no feasible speed profile; check limits/accel")
        start = int(feas[np.argmin(np.abs(V[feas] - v0))])

    idx = [start]
    for i in range(N):
        idx.append(int(choice[i, idx[-1]]))
    idx = np.array(idx)
    node_v = V[idx]
    seg_fuel = fuel[np.arange(N), idx[:-1], idx[1:]]
    seg_time = time[np.arange(N), idx[:-1], idx[1:]]
    return {
        "time_weight": float(time_weight),
        "node_speed_ms": node_v,
        "target_speed_ms": 0.5 * (node_v[:-1] + node_v[1:]),
        "seg_fuel_ml": seg_fuel,
        "seg_time_s": seg_time,
        "total_fuel_ml": float(seg_fuel.sum()),
        "total_time_s": float(seg_time.sum()),
    }


def sweep_time_weight(segments, params, weights=None, baseline=None, verbose=True):
    """Run several time weights and print total fuel vs total time."""
    if weights is None:
        weights = [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]
    rows = []
    for w in weights:
        r = optimize(segments, params, w)
        rows.append(r)
        if verbose:
            line = (f"  w={w:5.2f}  fuel={r['total_fuel_ml'] / ML_PER_GAL:7.4f} gal"
                    f"  time={r['total_time_s'] / 60:6.2f} min")
            if baseline is not None:
                line += (f"  saved={(baseline['total_fuel_ml'] - r['total_fuel_ml']) / ML_PER_GAL:+.4f} gal"
                         f"  extra={(r['total_time_s'] - baseline['total_time_s']):+6.1f} s")
            print(line)
    return rows


def choose_time_weight(segments, params, baseline, max_extra_s=120.0, verbose=True):
    """Weight that saves the most fuel while adding at most max_extra_s vs baseline."""
    rows = sweep_time_weight(segments, params, baseline=baseline, verbose=verbose)
    ok = [r for r in rows if r["total_time_s"] - baseline["total_time_s"] <= max_extra_s]
    if not ok:
        return max(rows, key=lambda r: r["time_weight"])
    return min(ok, key=lambda r: r["total_fuel_ml"])

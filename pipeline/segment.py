"""Pipeline step 2b: resample, smooth elevation, compute grade, build ~100 m segments."""
from __future__ import annotations

import logging

import numpy as np
from scipy.signal import savgol_filter

from .common import to_latlon, to_xy

log = logging.getLogger("eco_speed.segment")


def resample(points: list[dict], step_m: float = 25.0) -> dict:
    """Resample the route polyline every `step_m` metres (measured in UTM 16N).

    Returns arrays: dist (m), lat, lon, speed_limit_ms. The speed limit of each
    sample is the limit of the original polyline piece it falls on.
    """
    lats = np.array([p["lat"] for p in points]); lons = np.array([p["lon"] for p in points])
    lim = np.array([p["speed_limit_ms"] for p in points])
    xs, ys = map(np.asarray, to_xy(lats, lons))
    seg = np.hypot(np.diff(xs), np.diff(ys))
    keep = np.concatenate([[True], seg > 1e-6])  # drop duplicate points
    xs, ys, lim = xs[keep], ys[keep], lim[keep]
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xs), np.diff(ys)))])
    total = cum[-1]
    n = max(int(np.floor(total / step_m)), 1)
    d = np.linspace(0.0, n * step_m, n + 1)
    if total - d[-1] > 1.0:
        d = np.append(d, total)  # keep the true end point
    rx = np.interp(d, cum, xs); ry = np.interp(d, cum, ys)
    piece = np.clip(np.searchsorted(cum, d, side="right") - 1, 0, len(lim) - 1)
    rlat, rlon = to_latlon(rx, ry)
    return {"dist": d, "lat": np.asarray(rlat), "lon": np.asarray(rlon),
            "speed_limit_ms": lim[piece], "x": rx, "y": ry}


def smooth_elevation(elev: np.ndarray, step_m: float = 25.0, window_m: float = 200.0,
                     dist: np.ndarray | None = None) -> np.ndarray:
    """Savitzky-Golay smoothing over ~window_m to remove DEM noise (bridges, overpasses).

    If `dist` is given (sample distances, possibly with a short final step), the profile
    is smoothed on a uniform grid and interpolated back, since Savitzky-Golay assumes
    equal spacing.
    """
    elev = np.asarray(elev, dtype=float)
    win = max(int(round(window_m / step_m)) | 1, 5)  # odd number of samples
    if dist is not None:
        dist = np.asarray(dist, dtype=float)
        grid = np.linspace(0.0, dist[-1], max(int(round(dist[-1] / step_m)), 1) + 1)
        on_grid = np.interp(grid, dist, elev)
        if len(on_grid) < win:
            return elev
        sm = savgol_filter(on_grid, win, polyorder=2, mode="interp")
        return np.interp(dist, grid, sm)
    if len(elev) < win:
        return elev
    return savgol_filter(elev, win, polyorder=2, mode="interp")


def build_segments(samples: dict, elev: np.ndarray, seg_len_m: float = 100.0,
                   max_abs_grade: float = 0.06) -> list[dict]:
    """Aggregate resampled points into ~seg_len_m segments with grade and limit."""
    d = samples["dist"]
    total = d[-1]
    n = max(int(round(total / seg_len_m)), 1)
    edges = np.linspace(0.0, total, n + 1)  # equal-length segments close to seg_len_m
    e_at = np.interp(edges, d, elev)
    segs, n_suspect = [], 0
    for i in range(n):
        a, b = edges[i], edges[i + 1]
        length = b - a
        inside = (d >= a - 1e-6) & (d <= b + 1e-6)
        idx = np.nonzero(inside)[0]
        # polyline: segment start, interior samples, segment end (2-5 points)
        pd = np.unique(np.concatenate([[a], d[idx], [b]]))
        if len(pd) > 5:
            pd = np.linspace(a, b, 5)
        px = np.interp(pd, d, samples["x"]); py = np.interp(pd, d, samples["y"])
        plat, plon = to_latlon(px, py)
        mx = np.interp((a + b) / 2, d, samples["x"]); my = np.interp((a + b) / 2, d, samples["y"])
        mlat, mlon = to_latlon(mx, my)
        grade = (e_at[i + 1] - e_at[i]) / length
        if abs(grade) > max_abs_grade:
            n_suspect += 1
            log.warning("segment %d grade %.1f%% beyond +-%.0f%% (suspect data); clamped",
                        i, grade * 100, max_abs_grade * 100)
            grade = float(np.clip(grade, -max_abs_grade, max_abs_grade))
        # Conservative: the lowest limit touching the segment applies to all of it.
        lim_idx = idx if len(idx) else [int(np.searchsorted(d, a))]
        limit = float(np.min(samples["speed_limit_ms"][lim_idx]))
        segs.append({
            "id": i,
            "start_dist_m": round(float(a), 1),
            "length_m": round(float(length), 2),
            "lat": round(float(mlat), 6),
            "lon": round(float(mlon), 6),
            "polyline": [[round(float(la), 6), round(float(lo), 6)] for la, lo in zip(plat, plon)],
            "elevation_m": round(float((e_at[i] + e_at[i + 1]) / 2), 2),
            "grade": round(float(grade), 5),
            "speed_limit_ms": round(limit, 3),
        })
    if n_suspect:
        log.warning("%d segments had suspect grades", n_suspect)
    return segs

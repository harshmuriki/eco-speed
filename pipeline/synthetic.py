"""Offline DEMO route for when the OSM / OSRM / elevation APIs are unreachable.

This is NOT surveyed data. It follows the I-75 corridor from the Downtown Connector
at North Ave to Exit 263 through hand-placed waypoints (~1 km apart), with
approximate elevations and the I-285 speed-limit rule. It exists so the pipeline,
tests and web app can run end to end without network access. Exports built from it
are tagged `"data_source": "synthetic"` and the app shows a "demo data" badge.

Run `python -m pipeline.run_all` (without --offline) on a networked machine to
replace it with real OSM geometry, speed limits and USGS elevation.
"""
from __future__ import annotations

import numpy as np

from .common import mph, to_xy

# (lat, lon, approx elevation m, speed limit mph) in NORTHBOUND order.
WAYPOINTS_NB = [
    (33.7716, -84.3891, 288, 55),  # Downtown Connector at North Ave
    (33.7800, -84.3890, 283, 55),  # 10th St
    (33.7880, -84.3900, 275, 55),  # 14th / 17th St
    (33.7960, -84.3925, 262, 55),  # Brookwood split (I-75 leaves I-85)
    (33.8020, -84.3990, 255, 55),
    (33.8070, -84.4070, 248, 55),  # Northside Dr / Peachtree Creek
    (33.8150, -84.4170, 262, 55),
    (33.8250, -84.4250, 275, 55),  # Moores Mill Rd
    (33.8380, -84.4330, 268, 55),  # Mt Paran Rd
    (33.8500, -84.4430, 250, 55),
    (33.8600, -84.4530, 236, 55),  # Chattahoochee River
    (33.8710, -84.4590, 255, 55),
    (33.8830, -84.4660, 278, 65),  # I-285 (Cobb Cloverleaf)
    (33.8960, -84.4740, 290, 65),
    (33.9080, -84.4810, 300, 65),  # Windy Hill Rd
    (33.9200, -84.4920, 296, 65),  # Delk Rd
    (33.9330, -84.5030, 305, 65),
    (33.9457, -84.5162, 318, 65),  # Exit 263, GA 120 Loop
]


def _waypoints(direction: str):
    return WAYPOINTS_NB if direction == "northbound" else list(reversed(WAYPOINTS_NB))


def synthetic_route(direction: str, cfg: dict | None = None) -> list[dict]:
    """Points {lat, lon, speed_limit_ms}. Each waypoint's limit applies from it onward
    (northbound); for southbound, the limit of the segment's northbound owner is kept."""
    wps = _waypoints(direction)
    pts = []
    for i, (lat, lon, _elev, lim) in enumerate(wps):
        if direction == "southbound" and i + 1 < len(wps):
            lim = wps[i + 1][3]  # the same physical stretch keeps its limit
        pts.append({"lat": lat, "lon": lon, "speed_limit_ms": mph(lim)})
    return pts


def synthetic_elevation(lats, lons, direction: str) -> np.ndarray:
    """Approximate elevation (m) for arbitrary points near the demo route."""
    wps = _waypoints(direction)
    wx, wy = to_xy([w[0] for w in wps], [w[1] for w in wps])
    wx, wy = np.asarray(wx), np.asarray(wy)
    wd = np.concatenate([[0], np.cumsum(np.hypot(np.diff(wx), np.diff(wy)))])
    we = np.asarray([w[2] for w in wps], dtype=float)

    px, py = map(np.asarray, to_xy(list(lats), list(lons)))
    dist = np.empty(len(px))
    for k in range(len(px)):
        best, best_d = np.inf, 0.0
        for i in range(len(wx) - 1):
            dx, dy = wx[i + 1] - wx[i], wy[i + 1] - wy[i]
            l2 = dx * dx + dy * dy
            t = np.clip(((px[k] - wx[i]) * dx + (py[k] - wy[i]) * dy) / l2, 0, 1)
            d = np.hypot(wx[i] + t * dx - px[k], wy[i] + t * dy - py[k])
            if d < best:
                best, best_d = d, wd[i] + t * np.sqrt(l2)
        dist[k] = best_d
    # Smooth backbone plus gentle rolling terrain (+-4 m, ~1.5 km wavelength).
    # The rolling phase is tied to northbound distance so both directions agree.
    nb_dist = dist if direction == "northbound" else wd[-1] - dist
    return np.interp(dist, wd, we) + 4.0 * np.sin(2 * np.pi * nb_dist / 1500.0)

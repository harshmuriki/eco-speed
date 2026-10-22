"""Pipeline step 2a: elevation for each resampled route point (batched + cached)."""
from __future__ import annotations

import logging

import numpy as np

from .common import cached_request

log = logging.getLogger("eco_speed.fetch_elevation")

EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"


def _epqs(lats, lons) -> np.ndarray:
    """USGS Elevation Point Query Service: one point per request (each cached)."""
    out = np.empty(len(lats))
    for i, (lat, lon) in enumerate(zip(lats, lons)):
        data = cached_request("GET", EPQS_URL, params={
            "x": round(lon, 6), "y": round(lat, 6), "units": "Meters", "wkid": 4326,
            "includeDate": "false"})
        val = data.get("value")
        try:
            out[i] = float(val)
        except (TypeError, ValueError):
            out[i] = np.nan
        if i and i % 100 == 0:
            log.info("EPQS: %d/%d points", i, len(lats))
    return out


def _open_elevation(lats, lons, batch: int = 100) -> np.ndarray:
    out = []
    for s in range(0, len(lats), batch):
        body = {"locations": [{"latitude": round(a, 6), "longitude": round(o, 6)}
                              for a, o in zip(lats[s:s + batch], lons[s:s + batch])]}
        data = cached_request("POST", OPEN_ELEVATION_URL, json_body=body)
        out.extend(r.get("elevation", np.nan) for r in data["results"])
    return np.asarray(out, dtype=float)


def get_elevations(lats, lons, cfg: dict, direction: str, offline: bool = False) -> np.ndarray:
    lats, lons = list(lats), list(lons)
    if offline:
        from .synthetic import synthetic_elevation
        return synthetic_elevation(lats, lons, direction)
    provider = cfg.get("elevation_provider", "epqs")
    elev = _epqs(lats, lons) if provider == "epqs" else _open_elevation(lats, lons)
    bad = ~np.isfinite(elev) | (elev < -100)  # EPQS returns -1000000 for no data
    if bad.any():
        log.warning("%d elevation points missing; interpolating", int(bad.sum()))
        idx = np.arange(len(elev))
        elev[bad] = np.interp(idx[bad], idx[~bad], elev[~bad])
    return elev

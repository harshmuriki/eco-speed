"""Shared helpers: config loading, unit conversion, HTTP cache, projection."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
WEB_DATA_DIR = ROOT / "web" / "data"

MPH_TO_MS = 0.44704
G = 9.81
ML_PER_GAL = 3785.411784
M_PER_MILE = 1609.344

log = logging.getLogger("eco_speed")


def mph(v_mph: float) -> float:
    return v_mph * MPH_TO_MS


def to_mph(v_ms: float) -> float:
    return v_ms / MPH_TO_MS


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name) as f:
        return yaml.safe_load(f)


def load_vehicle(name: str = "sportage_2026.yaml") -> dict:
    return load_yaml(name)


def load_route(name: str = "route.yaml") -> dict:
    return load_yaml(name)


# ---------------------------------------------------------------- HTTP cache
def cached_request(method: str, url: str, *, params=None, data=None, json_body=None,
                   timeout: float = 90, retries: int = 3) -> dict:
    """GET/POST with an on-disk JSON cache so reruns never hit the APIs twice."""
    import requests  # imported lazily so offline runs don't need network libs

    key_src = json.dumps([method, url, params, data, json_body], sort_keys=True)
    key = hashlib.sha256(key_src.encode()).hexdigest()[:24]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())

    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.request(method, url, params=params, data=data, json=json_body,
                                    timeout=timeout,
                                    headers={"User-Agent": "eco-speed-advisor/0.1 (personal project)"})
            resp.raise_for_status()
            out = resp.json()
            path.write_text(json.dumps(out))
            return out
        except Exception as e:  # noqa: BLE001 - retry on any network/parse error
            last_err = e
            wait = 2 ** attempt
            log.warning("request failed (%s), retrying in %ss: %s", url, wait, e)
            time.sleep(wait)
    raise RuntimeError(f"request to {url} failed after {retries} attempts: {last_err}")


# ---------------------------------------------------------------- projection
_TO_UTM = None
_TO_LL = None


def transformers():
    """WGS84 <-> UTM zone 16N (EPSG:32616) for metric distances."""
    global _TO_UTM, _TO_LL
    if _TO_UTM is None:
        from pyproj import Transformer
        _TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32616", always_xy=True)
        _TO_LL = Transformer.from_crs("EPSG:32616", "EPSG:4326", always_xy=True)
    return _TO_UTM, _TO_LL


def to_xy(lats, lons):
    fwd, _ = transformers()
    return fwd.transform(lons, lats)


def to_latlon(xs, ys):
    _, inv = transformers()
    lons, lats = inv.transform(xs, ys)
    return lats, lons

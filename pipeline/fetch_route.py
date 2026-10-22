"""Pipeline step 1: route geometry and posted speed limits.

Geometry comes from OSRM (start -> optional via points -> end from config/route.yaml),
which gives one ordered, correctly-directed polyline per direction. Speed limits come
from OpenStreetMap via Overpass: each route point takes the `maxspeed` of the nearest
I-75 motorway way that runs in the same direction. Express-lane (toll) ways are
ignored so V0 only uses the general-purpose mainline.

Output per direction: list of points {lat, lon, speed_limit_ms}.
"""
from __future__ import annotations

import logging
import math
import re

import numpy as np
from shapely.geometry import Point, Polygon

from .common import cached_request, load_route, mph, to_xy

log = logging.getLogger("eco_speed.fetch_route")

# Rough I-285 perimeter polygon (lat, lon). Only used to pick a default limit
# when OSM has no maxspeed tag, so ~1 km accuracy is plenty.
I285_RING = [
    (33.8840, -84.4660),  # I-75 / I-285 (Cobb Cloverleaf)
    (33.9100, -84.3900),
    (33.9240, -84.3480),  # GA-400
    (33.9100, -84.2800),
    (33.8900, -84.2560),  # I-85 (Spaghetti Junction)
    (33.7800, -84.2300),
    (33.6900, -84.2600),  # I-20 east
    (33.6450, -84.3300),
    (33.6400, -84.4100),  # I-75 south
    (33.6700, -84.5000),
    (33.7550, -84.5250),  # I-20 west
    (33.8300, -84.5000),
]
_I285_POLY = Polygon([(lon, lat) for lat, lon in I285_RING])


def inside_i285(lat: float, lon: float) -> bool:
    return _I285_POLY.contains(Point(lon, lat))


def parse_maxspeed(tag: str | None) -> float | None:
    """OSM maxspeed -> m/s. '55 mph' -> mph; bare number -> km/h. None if unusable."""
    if not tag:
        return None
    tag = tag.strip().lower().split(";")[0]
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?$", tag)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "mph":
        return mph(val)
    return val / 3.6


def default_limit_ms(lat: float, lon: float, cfg: dict) -> float:
    if inside_i285(lat, lon):
        return mph(cfg["default_limit_inside_i285_mph"])
    return mph(cfg["default_limit_outside_i285_mph"])


# ---------------------------------------------------------------- OSRM geometry
def fetch_osrm_geometry(cfg: dict, direction: str) -> list[tuple[float, float]]:
    start, end = cfg["start"], cfg["end"]
    via = list(cfg.get("via_northbound") or [])
    if direction == "southbound":
        start, end = end, start
        via = list(cfg.get("via_southbound") or reversed(via))
    pts = [start, *via, end]
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in pts)
    url = f"{cfg['osrm_url'].rstrip('/')}/route/v1/driving/{coords}"
    data = cached_request("GET", url, params={"overview": "full", "geometries": "geojson",
                                              "steps": "false", "continue_straight": "true"})
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM returned no route: {data.get('code')} {data.get('message')}")
    route = data["routes"][0]
    line = [(lat, lon) for lon, lat in route["geometry"]["coordinates"]]
    log.info("OSRM %s: %.1f km, %d points", direction, route["distance"] / 1000, len(line))
    return line


# ---------------------------------------------------------------- Overpass limits
def fetch_overpass_ways(cfg: dict) -> list[dict]:
    s, w, n, e = cfg["bbox"]
    query = f"""
[out:json][timeout:90];
way["highway"="motorway"]["ref"~"I 75"]({s},{w},{n},{e});
out tags geom;
"""
    data = cached_request("POST", cfg["overpass_url"], data={"data": query})
    ways = [el for el in data.get("elements", []) if el.get("type") == "way" and el.get("geometry")]
    log.info("Overpass: %d I-75 motorway ways", len(ways))
    return ways


def _is_express(tags: dict) -> bool:
    name = (tags.get("name") or "").lower()
    return (tags.get("toll") == "yes" or "express" in name
            or tags.get("hov") in ("designated", "lane") or tags.get("hot") == "yes")


def _bearing_deg(x1, y1, x2, y2):
    return (np.degrees(np.arctan2(x2 - x1, y2 - y1)) + 360.0) % 360.0


def attach_speed_limits(line: list[tuple[float, float]], ways: list[dict], cfg: dict,
                        max_match_m: float = 30.0) -> list[dict]:
    """For each route point, take maxspeed from the nearest same-direction I-75 way."""
    # Flatten every way into directed line pieces in UTM metres.
    seg_x1, seg_y1, seg_x2, seg_y2, seg_v = [], [], [], [], []
    for w in ways:
        tags = w.get("tags", {})
        if _is_express(tags):
            continue
        v = parse_maxspeed(tags.get("maxspeed"))
        geom = w["geometry"]
        if tags.get("oneway") == "-1":
            geom = list(reversed(geom))
        xs, ys = to_xy([g["lat"] for g in geom], [g["lon"] for g in geom])
        for i in range(len(xs) - 1):
            seg_x1.append(xs[i]); seg_y1.append(ys[i])
            seg_x2.append(xs[i + 1]); seg_y2.append(ys[i + 1])
            seg_v.append(np.nan if v is None else v)
    have_ways = len(seg_x1) > 0
    if have_ways:
        x1, y1, x2, y2 = map(np.asarray, (seg_x1, seg_y1, seg_x2, seg_y2))
        sv = np.asarray(seg_v)
        seg_brg = _bearing_deg(x1, y1, x2, y2)
        dx, dy = x2 - x1, y2 - y1
        len2 = np.maximum(dx * dx + dy * dy, 1e-9)

    lats = [p[0] for p in line]; lons = [p[1] for p in line]
    px, py = map(np.asarray, to_xy(lats, lons))
    out, n_default = [], 0
    for i in range(len(line)):
        j = min(i + 1, len(line) - 1); k = j - 1 if j == i else i
        route_brg = _bearing_deg(px[k], py[k], px[j], py[j])
        limit = None
        if have_ways:
            t = np.clip(((px[i] - x1) * dx + (py[i] - y1) * dy) / len2, 0, 1)
            d = np.hypot(x1 + t * dx - px[i], y1 + t * dy - py[i])
            diff = np.abs((seg_brg - route_brg + 180) % 360 - 180)
            d = np.where(diff < 45, d, np.inf)
            best = int(np.argmin(d))
            if d[best] <= max_match_m and not np.isnan(sv[best]):
                limit = float(sv[best])
        if limit is None:
            limit = default_limit_ms(lats[i], lons[i], cfg)
            n_default += 1
        out.append({"lat": lats[i], "lon": lons[i], "speed_limit_ms": limit})
    if n_default:
        log.warning("%d/%d route points had no matching OSM maxspeed; used I-285 rule defaults",
                    n_default, len(line))
    return out


def get_route(direction: str, cfg: dict | None = None, offline: bool = False) -> list[dict]:
    """Ordered route points {lat, lon, speed_limit_ms} for 'northbound' or 'southbound'."""
    cfg = cfg or load_route()
    if offline:
        from .synthetic import synthetic_route
        return synthetic_route(direction, cfg)
    line = fetch_osrm_geometry(cfg, direction)
    ways = fetch_overpass_ways(cfg)
    return attach_speed_limits(line, ways, cfg)


def route_length_m(points: list[dict]) -> float:
    xs, ys = to_xy([p["lat"] for p in points], [p["lon"] for p in points])
    return float(np.sum(np.hypot(np.diff(xs), np.diff(ys))))


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

import numpy as np

from pipeline.common import mph, to_xy
from pipeline.segment import build_segments, resample, smooth_elevation


def _line(n=11, dlat=0.003):
    """A straight line due north, ~333 m per point, limit changes halfway."""
    return [{"lat": 33.80 + i * dlat, "lon": -84.40,
             "speed_limit_ms": mph(55 if i < n // 2 else 65)} for i in range(n)]


def test_resample_spacing_and_length():
    s = resample(_line(), 25.0)
    steps = np.diff(s["dist"])
    assert np.allclose(steps[:-1], 25.0)
    assert steps[-1] <= 25.0 + 1e-6
    # resampled points really are 25 m apart on the ground
    xs, ys = to_xy(s["lat"], s["lon"])
    assert np.allclose(np.hypot(np.diff(xs), np.diff(ys))[:-1], 25.0, atol=0.05)
    assert 3200 < s["dist"][-1] < 3400


def test_linear_grade_and_segment_lengths():
    s = resample(_line(), 25.0)
    elev = 100 + 0.02 * s["dist"]           # constant 2% climb
    segs = build_segments(s, smooth_elevation(elev, 25.0, 200.0, dist=s["dist"]), 100.0)
    assert abs(sum(x["length_m"] for x in segs) - s["dist"][-1]) < 0.5
    assert all(90 <= x["length_m"] <= 110 for x in segs)
    assert all(abs(x["grade"] - 0.02) < 1e-3 for x in segs)
    assert all(2 <= len(x["polyline"]) <= 5 for x in segs)
    assert segs[0]["speed_limit_ms"] < segs[-1]["speed_limit_ms"]


def test_grade_is_clamped():
    s = resample(_line(), 25.0)
    segs = build_segments(s, 0.10 * s["dist"], 100.0, max_abs_grade=0.06)
    assert all(abs(x["grade"]) <= 0.06 + 1e-9 for x in segs)


def test_smoothing_removes_spike():
    elev = np.full(80, 250.0)
    elev[40] = 270.0                         # bridge-deck DEM spike
    sm = smooth_elevation(elev, 25.0, 200.0)
    assert sm.max() - 250.0 < 10.0


def test_parse_maxspeed_and_i285_rule():
    from pipeline.fetch_route import inside_i285, parse_maxspeed
    assert abs(parse_maxspeed("55 mph") - mph(55)) < 1e-9
    assert abs(parse_maxspeed("100") - 100 / 3.6) < 1e-9
    assert parse_maxspeed("signals") is None and parse_maxspeed(None) is None
    assert inside_i285(33.7756, -84.3963)      # Georgia Tech
    assert not inside_i285(33.9457, -84.5162)  # Marietta, Exit 263


def test_offline_pipeline_end_to_end(params):
    """Milestones 1 + 4 on the demo route: plausible length, grades within +-6%,
    target never above the limit or below min speed, optimised fuel <= baseline."""
    import logging
    logging.disable(logging.CRITICAL)
    from pipeline.common import load_route
    from pipeline.run_all import build_direction
    cfg = load_route()
    for direction in ("northbound", "southbound"):
        doc, segs, opt, base = build_direction(direction, cfg, params, True, 1.0, verbose=False)
        assert 18_000 < doc["totals"]["distance_m"] < 40_000
        assert all(abs(s["grade"]) <= 0.06 for s in doc["segments"])
        for s in doc["segments"]:
            assert s["target_speed_ms"] <= s["speed_limit_ms"] + 0.01
            assert s["target_speed_ms"] >= mph(params["min_speed_mph"]) - 1e-6
        assert doc["totals"]["opt_fuel_ml"] <= doc["totals"]["base_fuel_ml"]
    logging.disable(logging.NOTSET)

import numpy as np
import pytest

from pipeline.baseline import baseline
from pipeline.common import mph
from pipeline.optimizer import optimize

from .conftest import make_segments

LIM = mph(65)
# 2 km flat, 2 km climb at +4%, 2 km descent at -4%, 2 km flat
HILL = [0.0] * 20 + [0.04] * 20 + [-0.04] * 20 + [0.0] * 20
TW = 1.0


@pytest.fixture(scope="module")
def hill(params):
    segs = make_segments(HILL, [LIM] * len(HILL))
    return segs, optimize(segs, params, TW), baseline(segs, params)


def test_respects_limits_and_min_speed(hill, params):
    segs, opt, _ = hill
    v = opt["node_speed_ms"]
    assert np.all(v <= LIM + 0.01)
    assert np.all(v >= mph(params["min_speed_mph"]) - 1e-9)
    assert np.all(opt["target_speed_ms"] <= LIM + 0.01)


def test_respects_acceleration_bounds(hill, params):
    segs, opt, _ = hill
    v = opt["node_speed_ms"]
    a = (v[1:] ** 2 - v[:-1] ** 2) / (2 * 100.0)
    assert a.max() <= params["max_accel_ms2"] + 1e-9
    assert a.min() >= -params["max_decel_ms2"] - 1e-9


def test_slows_on_climb_speeds_up_on_descent(hill):
    _, opt, _ = hill
    t = opt["target_speed_ms"]
    flat_before, climb, descent = t[5:18].mean(), t[20:40], t[40:60]
    assert climb.min() < flat_before          # eases off on the climb
    assert descent.max() > flat_before        # gains speed on the descent
    assert descent.mean() > climb.mean()


def test_optimised_fuel_not_above_baseline(hill):
    _, opt, base = hill
    assert opt["total_fuel_ml"] <= base["total_fuel_ml"] + 1e-6


def test_limit_drop_is_respected_with_decel(params):
    lims = [mph(65)] * 30 + [mph(55)] * 30
    segs = make_segments([0.0] * 60, lims)
    opt = optimize(segs, params, 5.0)         # strong time weight -> drives near limits
    v = opt["node_speed_ms"]
    assert np.all(v[30:] <= mph(55) + 0.01)
    base = baseline(segs, params)
    assert np.all(base["node_speed_ms"][30:] <= mph(55) + 1e-6)
    a = (base["node_speed_ms"][1:] ** 2 - base["node_speed_ms"][:-1] ** 2) / 200.0
    assert a.min() >= -params["max_decel_ms2"] - 1e-9


def test_high_time_weight_approaches_baseline_time(params):
    segs = make_segments([0.0] * 50, [mph(65)] * 50)
    opt, base = optimize(segs, params, 50.0), baseline(segs, params)
    assert opt["total_time_s"] - base["total_time_s"] < 1.0

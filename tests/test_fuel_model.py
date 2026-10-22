import numpy as np

from pipeline.common import M_PER_MILE, mph
from pipeline.fuel_model import fuel_rate_mls, segment_fuel_ml, steady_mpg


def test_calibrated_65mph_matches_epa(params):
    mpg = steady_mpg(mph(65), params)
    assert abs(mpg - params["epa_hwy_mpg"]) / params["epa_hwy_mpg"] < 0.05


def test_fuel_per_distance_rises_with_speed_above_50(params):
    speeds = mph(np.arange(50, 81, 5))
    per_mile = fuel_rate_mls(speeds, 0.0, 0.0, params) / speeds * M_PER_MILE
    assert np.all(np.diff(per_mile) > 0)


def test_fuel_rises_with_positive_grade(params):
    v = mph(60)
    rates = [fuel_rate_mls(v, 0.0, g, params) for g in (-0.01, 0.0, 0.02, 0.04)]
    assert all(b > a for a, b in zip(rates, rates[1:]))


def test_idle_only_when_power_negative(params):
    # steep descent at modest speed: gravity exceeds drag -> fuel cut -> idle flow
    assert fuel_rate_mls(mph(45), 0.0, -0.05, params) == params["idle_fuel_mls"]
    assert fuel_rate_mls(mph(60), -1.0, 0.0, params) == params["idle_fuel_mls"]


def test_segment_fuel_constant_speed_consistent(params):
    v = mph(60)
    fuel, t = segment_fuel_ml(v, v, 100.0, 0.0, params)
    assert abs(t - 100.0 / v) < 1e-9
    assert abs(fuel - fuel_rate_mls(v, 0.0, 0.0, params) * t) < 1e-9


def test_accelerating_costs_more(params):
    f_hold, _ = segment_fuel_ml(mph(55), mph(55), 100.0, 0.0, params)
    f_acc, _ = segment_fuel_ml(mph(55), mph(60), 100.0, 0.0, params)
    assert f_acc > f_hold

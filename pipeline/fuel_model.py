"""Pipeline step 3: physics-based fuel model with an idle term.

Tractive force:
    F = m*r*a + 0.5*rho*Cd*A*v^2 + Crr*m*g*cos(theta) + m*g*sin(theta)
Fuel rate (mL/s):
    f = f_idle + max(F*v, 0) / (eta * E_fuel)        E_fuel in J/mL
Negative power -> fuel cut on overrun -> idle flow only.

All functions accept numpy arrays (broadcasting) as well as floats.
VT-Micro (Ahn, Rakha et al., 2002) can be added later behind the same interface.
"""
from __future__ import annotations

import copy

import numpy as np

from .common import G, M_PER_MILE, ML_PER_GAL, mph


def e_fuel_j_per_ml(params: dict) -> float:
    return params["fuel_mj_per_l"] * 1e6 / 1000.0


def tractive_force_n(v_ms, a_ms2, grade, params):
    v = np.asarray(v_ms, dtype=float)
    theta = np.arctan(np.asarray(grade, dtype=float))
    m = params["mass_kg"]
    return (m * params["rot_factor"] * np.asarray(a_ms2, dtype=float)
            + 0.5 * params["air_density"] * params["cd"] * params["frontal_area_m2"] * v * v
            + params["crr"] * m * G * np.cos(theta)
            + m * G * np.sin(theta))


def fuel_rate_mls(v_ms, a_ms2, grade, params):
    """Instantaneous fuel rate in mL/s."""
    v = np.asarray(v_ms, dtype=float)
    power = tractive_force_n(v, a_ms2, grade, params) * v
    out = params["idle_fuel_mls"] + np.maximum(power, 0.0) / (params["engine_eff"] * e_fuel_j_per_ml(params))
    return float(out) if np.ndim(out) == 0 else out


def segment_fuel_ml(v_in, v_out, length_m, grade, params):
    """Fuel (mL) and time (s) to cover a segment with constant acceleration.

    a = (v_out^2 - v_in^2) / (2 L); average speed (v_in + v_out) / 2; time = L / v_avg.
    """
    v_in = np.asarray(v_in, dtype=float); v_out = np.asarray(v_out, dtype=float)
    a = (v_out ** 2 - v_in ** 2) / (2.0 * length_m)
    v_avg = 0.5 * (v_in + v_out)
    t = length_m / np.maximum(v_avg, 0.1)
    fuel = fuel_rate_mls(v_avg, a, grade, params) * t
    if np.ndim(fuel) == 0:
        return float(fuel), float(t)
    return fuel, t


def steady_mpg(v_ms: float, params: dict, grade: float = 0.0) -> float:
    rate = fuel_rate_mls(v_ms, 0.0, grade, params)  # mL/s
    ml_per_mile = rate / v_ms * M_PER_MILE
    return ML_PER_GAL / ml_per_mile


def calibrate(params: dict) -> dict:
    """Return a copy with engine_eff scaled so steady flat cruise gives epa_hwy_mpg."""
    p = copy.deepcopy(params)
    v = mph(p.get("calibration_speed_mph", 65))
    needed_rate = v * ML_PER_GAL / (M_PER_MILE * p["epa_hwy_mpg"])  # mL/s
    power = float(tractive_force_n(v, 0.0, 0.0, p)) * v
    margin = needed_rate - p["idle_fuel_mls"]
    if margin <= 0:
        raise ValueError("idle fuel rate alone exceeds the EPA highway rate; check config")
    p["engine_eff_uncalibrated"] = p["engine_eff"]
    p["engine_eff"] = power / (e_fuel_j_per_ml(p) * margin)
    return p


def load_params(vehicle_cfg: dict) -> dict:
    return calibrate(vehicle_cfg) if vehicle_cfg.get("calibrate", True) else dict(vehicle_cfg)

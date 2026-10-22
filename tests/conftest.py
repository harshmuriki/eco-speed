import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.common import load_vehicle  # noqa: E402
from pipeline.fuel_model import load_params  # noqa: E402


@pytest.fixture(scope="session")
def params():
    return load_params(load_vehicle())


def make_segments(grades, limits_ms, length=100.0):
    """Synthetic straight-line segments for optimiser/baseline tests."""
    segs = []
    for i, (g, lim) in enumerate(zip(grades, limits_ms)):
        segs.append({"id": i, "start_dist_m": i * length, "length_m": length,
                     "lat": 33.8, "lon": -84.4, "polyline": [[33.8, -84.4], [33.8009, -84.4]],
                     "elevation_m": 0.0, "grade": g, "speed_limit_ms": lim})
    return segs

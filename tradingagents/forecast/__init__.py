"""Price forecasting backends.

``TimesFMForecaster`` wraps Google Research's TimesFM foundation model when the
optional ``timesfm`` package is installed. ``NaiveForecaster`` is a
dependency-free fallback (drift plus volatility cone) so every code path, test,
and serverless deployment has a working forecaster. Both produce the same
``ForecastResult`` so callers never depend on a specific backend.
"""

from .base import ForecastResult, Forecaster, forecast_from_points, get_forecaster
from .naive import NaiveForecaster
from .timesfm_backend import TimesFMForecaster, timesfm_available

__all__ = [
    "ForecastResult",
    "Forecaster",
    "NaiveForecaster",
    "TimesFMForecaster",
    "forecast_from_points",
    "get_forecaster",
    "timesfm_available",
]

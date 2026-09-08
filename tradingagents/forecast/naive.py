"""Dependency-free drift/volatility forecaster used as the default backend."""

from __future__ import annotations

from math import erf, exp, log, sqrt
from statistics import mean, pstdev
from typing import Sequence

from .base import DEFAULT_QUANTILES, ForecastResult


_Z_SCORES = {
    0.1: -1.2815515655,
    0.25: -0.6744897502,
    0.5: 0.0,
    0.75: 0.6744897502,
    0.9: 1.2815515655,
}


class NaiveForecaster:
    """Log-return drift with a lognormal volatility cone.

    Drift blends the recent 20-day and 60-day mean log returns and is shrunk
    toward zero, which keeps the fallback conservative. Quantile paths widen
    with ``sqrt(t)`` so they can be rendered the same way as TimesFM output.
    """

    name = "naive"

    def __init__(self, *, drift_shrinkage: float = 0.5, min_context: int = 20):
        if not 0 <= drift_shrinkage <= 1:
            raise ValueError("drift_shrinkage must be between 0 and 1")
        self.drift_shrinkage = drift_shrinkage
        self.min_context = min_context

    def forecast(self, closes: Sequence[float], *, horizon: int = 20) -> ForecastResult:
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        cleaned = [float(value) for value in closes if value is not None and float(value) > 0]
        if len(cleaned) < 2:
            raise ValueError("at least two positive close prices are required")
        log_returns = [log(current / previous) for previous, current in zip(cleaned[:-1], cleaned[1:])]
        notes: list[str] = []
        if len(cleaned) < self.min_context:
            notes.append(f"context shorter than {self.min_context} points; forecast is low confidence")

        recent = log_returns[-20:]
        longer = log_returns[-60:]
        drift = (0.6 * mean(recent) + 0.4 * mean(longer)) * (1 - self.drift_shrinkage)
        sigma = pstdev(longer) if len(longer) >= 2 else 0.0
        last_close = cleaned[-1]

        median_path: list[float] = []
        quantile_paths = {str(q): [] for q in DEFAULT_QUANTILES}
        for step in range(1, horizon + 1):
            centre = log(last_close) + drift * step
            spread = sigma * sqrt(step)
            median_path.append(round(exp(centre), 4))
            for quantile in DEFAULT_QUANTILES:
                quantile_paths[str(quantile)].append(round(exp(centre + _Z_SCORES[quantile] * spread), 4))

        expected_return = (median_path[-1] / last_close) - 1
        total_spread = sigma * sqrt(horizon)
        probability_up = 0.5 if total_spread == 0 else 0.5 * (1 + erf((drift * horizon) / (total_spread * sqrt(2))))
        return ForecastResult(
            backend=self.name,
            horizon=horizon,
            last_close=last_close,
            median_path=median_path,
            quantile_paths=quantile_paths,
            expected_return=round(expected_return, 6),
            probability_up=round(probability_up, 4),
            context_length=len(cleaned),
            notes=notes,
        )

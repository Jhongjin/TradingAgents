"""Shared forecast contract and backend selection."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol, Sequence


DEFAULT_QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)


@dataclass(frozen=True)
class ForecastResult:
    backend: str
    horizon: int
    last_close: float
    median_path: list[float]
    quantile_paths: dict[str, list[float]] = field(default_factory=dict)
    expected_return: float | None = None
    probability_up: float | None = None
    context_length: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def target_close(self) -> float | None:
        return self.median_path[-1] if self.median_path else None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target_close"] = self.target_close
        return payload

    def summary_ko(self) -> str:
        if not self.median_path:
            return "예측 결과가 없습니다."
        parts = [
            f"백엔드 {self.backend}, {self.horizon}거래일 예측",
            f"현재 종가 {self.last_close:,.0f} → 중앙값 {self.target_close:,.0f}",
        ]
        if self.expected_return is not None:
            parts.append(f"기대수익률 {self.expected_return:+.2%}")
        if self.probability_up is not None:
            parts.append(f"상승 확률 {self.probability_up:.0%}")
        low = self.quantile_paths.get("0.1")
        high = self.quantile_paths.get("0.9")
        if low and high:
            parts.append(f"10~90% 구간 {low[-1]:,.0f}~{high[-1]:,.0f}")
        return ", ".join(parts)


class Forecaster(Protocol):
    name: str

    def forecast(self, closes: Sequence[float], *, horizon: int = 20) -> ForecastResult: ...


def get_forecaster(backend: str | None = None, **kwargs: Any) -> Forecaster:
    """Return the configured forecaster, falling back to the naive backend.

    ``TRADINGAGENTS_FORECAST_BACKEND`` selects ``naive`` (default), ``timesfm``,
    or ``auto`` (TimesFM when importable, otherwise naive).
    """

    from .naive import NaiveForecaster
    from .timesfm_backend import TimesFMForecaster, timesfm_available

    selected = (backend or os.getenv("TRADINGAGENTS_FORECAST_BACKEND") or "naive").strip().lower()
    if selected == "timesfm":
        return TimesFMForecaster(**kwargs)
    if selected == "auto":
        if timesfm_available():
            return TimesFMForecaster(**kwargs)
        return NaiveForecaster()
    if selected == "naive":
        return NaiveForecaster()
    raise ValueError(f"Unsupported forecast backend: {backend!r}. Choose naive, timesfm, or auto.")


def forecast_from_points(
    points: Sequence[Mapping[str, Any]],
    *,
    horizon: int = 20,
    forecaster: Forecaster | None = None,
    backend: str | None = None,
) -> ForecastResult:
    """Forecast from ascending OHLCV point dicts (the chart_data shape)."""

    closes = [float(point["close"]) for point in points if point.get("close") is not None and float(point["close"]) > 0]
    selected = forecaster or get_forecaster(backend)
    return selected.forecast(closes, horizon=horizon)

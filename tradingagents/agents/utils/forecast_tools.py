"""LLM tools exposing the forecaster and factor scores to analyst agents."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.chart_data import get_ohlcv_chart_series
from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker
from tradingagents.forecast import forecast_from_points
from tradingagents.screener import compute_factor_scores


@tool
def get_price_forecast(
    symbol: Annotated[str, "Korean 6-digit ticker symbol, e.g. 005930"],
    curr_date: Annotated[str, "Current trading date in YYYY-mm-dd format"],
    horizon_days: Annotated[int, "Forecast horizon in trading days (1-60)"] = 20,
) -> str:
    """
    Return a statistical close-price forecast (median path, 10/90% band, expected
    return, probability of finishing higher) for a Korean stock. Uses TimesFM when
    TRADINGAGENTS_FORECAST_BACKEND=timesfm is configured, otherwise a drift/volatility
    model. Treat the output as one input among many, not as a prediction of truth.
    """

    if not is_kr_ticker(symbol):
        return f"Price forecast currently supports Korean 6-digit tickers only: {symbol!r}"
    horizon = max(1, min(int(horizon_days), 60))
    end = datetime.strptime(curr_date, "%Y-%m-%d").date()
    start = end - timedelta(days=400)
    try:
        series = get_ohlcv_chart_series(symbol, start.isoformat(), end.isoformat(), vendor="pykrx")
        points = [point.as_dict() for point in series.points]
        forecast = forecast_from_points(points, horizon=horizon)
        factors = compute_factor_scores(points)
    except Exception as exc:
        return f"Price forecast unavailable for {symbol}: {exc.__class__.__name__}: {exc}"

    resolved = resolve_kr_ticker(symbol, lookup_pykrx=False)
    lines = [
        f"# Price forecast for {resolved.name} ({resolved.code}, {resolved.market})",
        f"# As of {curr_date}, horizon {horizon} trading days, backend {forecast.backend}, context {forecast.context_length} points",
        f"Last close: {forecast.last_close:,.0f} KRW",
        f"Median forecast at horizon: {forecast.target_close:,.0f} KRW (expected return {forecast.expected_return:+.2%})",
    ]
    if forecast.probability_up is not None:
        lines.append(f"Probability of closing above last close: {forecast.probability_up:.0%}")
    low = forecast.quantile_paths.get("0.1")
    high = forecast.quantile_paths.get("0.9")
    if low and high:
        lines.append(f"10%-90% band at horizon: {low[-1]:,.0f} ~ {high[-1]:,.0f} KRW")
    lines.append("")
    lines.append("## Factor snapshot")
    lines.append(f"composite {factors.composite:+.3f}; momentum_20d {factors.momentum_20d:+.2%}; ma_alignment {factors.ma_alignment:+.2f}; rsi_14 {factors.rsi_14}; volume_surge {factors.volume_surge}; volatility_20d {factors.volatility_20d}")
    lines.append("labels: " + ", ".join(factors.labels))
    if forecast.notes:
        lines.append("")
        lines.append("notes: " + "; ".join(forecast.notes))
    return "\n".join(lines)

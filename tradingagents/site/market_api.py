"""Market-data payload builders for site/API use."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.chart_data import get_latest_close_price, get_ohlcv_chart_series

from .public_api import _json_ready, _public_error


def build_latest_prices_payload(
    tickers: list[str],
    *,
    end_date: str | None = None,
    lookback_days: int = 14,
    vendor: str = "pykrx",
    ignore_errors: bool = True,
    max_tickers: int = 20,
) -> dict[str, Any]:
    """Build latest close-price snapshots keyed by normalized ticker code."""

    requested = _clean_tickers(tickers)
    if not requested:
        raise ValueError("tickers must include at least one ticker")
    if max_tickers <= 0:
        raise ValueError("max_tickers must be positive")
    if len(requested) > max_tickers:
        raise ValueError(f"tickers cannot contain more than {max_tickers} symbols")

    date_value = end_date or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    prices = {}
    errors = {}
    for ticker in requested:
        try:
            price = get_latest_close_price(
                ticker,
                date_value,
                lookback_days=lookback_days,
                vendor=vendor,
            )
        except Exception as exc:
            if not ignore_errors:
                raise
            errors[ticker] = _public_error(exc)
            continue
        prices[price.ticker_code] = price.as_dict()

    status = "available"
    if not prices:
        status = "missing"
    elif errors:
        status = "partial"

    return _json_ready(
        {
            "status": status,
            "as_of_date": date_value,
            "vendor": vendor,
            "requested_tickers": requested,
            "prices": prices,
            "errors": errors,
        }
    )


def _clean_tickers(tickers: list[str]) -> list[str]:
    return [ticker.strip() for ticker in tickers if ticker and ticker.strip()]


SPARKLINE_CACHE_SECONDS = 600
_sparkline_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}


def build_sparkline_payload(
    tickers: list[str],
    *,
    days: int = 60,
    end_date: str | None = None,
    vendor: str = "pykrx",
    max_tickers: int = 20,
    series_loader: Any | None = None,
) -> dict[str, Any]:
    """Daily closes for tiny inline charts, keyed by ticker; memoised per process.

    Fetches run concurrently and vendor failures are per ticker (``errors``), so
    one bad symbol never blanks the others.
    """

    import time
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta

    requested = _clean_tickers(tickers)
    if not requested:
        raise ValueError("tickers must include at least one ticker")
    if len(requested) > max_tickers:
        raise ValueError(f"tickers cannot contain more than {max_tickers} symbols")
    days = max(5, min(int(days), 250))
    end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else datetime.now(ZoneInfo("Asia/Seoul")).date()
    start = end - timedelta(days=int(days * 1.6) + 7)
    loader = series_loader or (lambda code: get_ohlcv_chart_series(code, start.isoformat(), end.isoformat(), vendor=vendor))

    now = time.monotonic()
    series: dict[str, Any] = {}
    errors: dict[str, str] = {}
    missing: list[str] = []
    for code in requested:
        cached = _sparkline_cache.get((code, days))
        if cached and now - cached[0] < SPARKLINE_CACHE_SECONDS:
            series[code] = cached[1]
        else:
            missing.append(code)

    def load(code: str):
        try:
            chart = loader(code)
            closes = [(point.date, float(point.close)) for point in chart.points if point.close is not None][-days:]
            return code, {"ticker_code": chart.ticker_code, "ticker_name": chart.ticker_name, "dates": [d for d, _ in closes], "closes": [c for _, c in closes], "vendor": chart.vendor}, None
        except Exception as exc:  # per-ticker failure
            return code, None, _public_error(exc)

    if missing:
        with ThreadPoolExecutor(max_workers=min(8, len(missing)), thread_name_prefix="sparkline") as pool:
            for code, payload, error in pool.map(load, missing):
                if payload is not None and payload["closes"]:
                    series[payload["ticker_code"]] = payload
                    _sparkline_cache[(code, days)] = (time.monotonic(), payload)
                else:
                    errors[code] = error or "no data"

    status = "available" if series and not errors else ("partial" if series else "missing")
    return _json_ready({"status": status, "days": days, "series": series, "errors": errors})

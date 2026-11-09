"""Market-data payload builders for site/API use."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.chart_data import get_latest_close_price, get_ohlcv_chart_series

from .public_api import _json_ready, _public_error


LATEST_PRICE_FETCH_TIMEOUT_SECONDS = 8.0


def build_latest_prices_payload(
    tickers: list[str],
    *,
    end_date: str | None = None,
    lookback_days: int = 14,
    vendor: str = "pykrx",
    ignore_errors: bool = True,
    max_tickers: int = 20,
) -> dict[str, Any]:
    """Build latest close-price snapshots keyed by normalized ticker code.

    One ticker's close price does not depend on another's, so these are
    fetched concurrently (the same ThreadPoolExecutor idiom as
    ``build_sparkline_payload`` below) instead of one at a time — measured
    2026-11-09: a paper account with 7-9 held tickers spent 18-19s here,
    serially, before every other part of the page or API response. A pool
    thread that is still stuck on a slow vendor past
    ``LATEST_PRICE_FETCH_TIMEOUT_SECONDS`` is abandoned via
    ``shutdown(wait=False)`` rather than awaited, for the same reason
    ``tradingagents.dataflows.deadline`` prefers a daemon thread over a pool
    for its own, longer, deadline: a pool's default ``__exit__`` blocks until
    every submitted call returns, which would silently undo the timeout.
    """

    requested = _clean_tickers(tickers)
    if not requested:
        raise ValueError("tickers must include at least one ticker")
    if max_tickers <= 0:
        raise ValueError("max_tickers must be positive")
    if len(requested) > max_tickers:
        raise ValueError(f"tickers cannot contain more than {max_tickers} symbols")

    date_value = end_date or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()

    def fetch_one(ticker: str):
        return get_latest_close_price(ticker, date_value, lookback_days=lookback_days, vendor=vendor)

    prices: dict[str, Any] = {}
    errors: dict[str, str] = {}
    if len(requested) == 1:
        ticker = requested[0]
        try:
            price = fetch_one(ticker)
            prices[price.ticker_code] = price.as_dict()
        except Exception as exc:
            if not ignore_errors:
                raise
            errors[ticker] = _public_error(exc)
    else:
        from concurrent.futures import ThreadPoolExecutor

        pool = ThreadPoolExecutor(max_workers=min(8, len(requested)), thread_name_prefix="latest-price")
        future_by_ticker = {ticker: pool.submit(fetch_one, ticker) for ticker in requested}
        # One deadline for the whole batch: waiting the full timeout per ticker
        # would add up again when several vendors stall together.
        import time as _time

        deadline = _time.monotonic() + LATEST_PRICE_FETCH_TIMEOUT_SECONDS
        try:
            for ticker in requested:
                try:
                    price = future_by_ticker[ticker].result(timeout=max(0.0, deadline - _time.monotonic()))
                except Exception as exc:
                    if not ignore_errors:
                        raise
                    errors[ticker] = _public_error(exc)
                    continue
                prices[price.ticker_code] = price.as_dict()
        finally:
            pool.shutdown(wait=False)

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

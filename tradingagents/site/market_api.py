"""Market-data payload builders for site/API use."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.chart_data import get_latest_close_price

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

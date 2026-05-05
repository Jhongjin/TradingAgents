"""API-friendly OHLCV chart data providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .errors import VendorUnavailableError
from .kr_tickers import is_kr_ticker, resolve_kr_ticker
from . import pykrx_vendor


@dataclass(frozen=True)
class OhlcvPoint:
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    value: float | None = None
    change_rate: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "value": self.value,
            "change_rate": self.change_rate,
        }


@dataclass(frozen=True)
class ChartSeries:
    ticker_code: str
    ticker_name: str
    market: str
    currency: str
    vendor: str
    points: list[OhlcvPoint]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker_code": self.ticker_code,
            "ticker_name": self.ticker_name,
            "market": self.market,
            "currency": self.currency,
            "vendor": self.vendor,
            "points": [point.as_dict() for point in self.points],
        }


@dataclass(frozen=True)
class LatestPrice:
    ticker_code: str
    ticker_name: str
    market: str
    currency: str
    vendor: str
    date: str
    close: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker_code": self.ticker_code,
            "ticker_name": self.ticker_name,
            "market": self.market,
            "currency": self.currency,
            "vendor": self.vendor,
            "date": self.date,
            "close": self.close,
        }


def get_ohlcv_chart_series(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    vendor: str = "pykrx",
) -> ChartSeries:
    """Return normalized Korean OHLCV chart data.

    The shape is intentionally independent from pykrx so a KRX Open API-backed
    implementation can replace the vendor later without changing the web layer.
    """

    if not is_kr_ticker(symbol):
        raise VendorUnavailableError(f"chart data currently supports Korean 6-digit tickers only: {symbol!r}")

    resolved = resolve_kr_ticker(symbol, lookup_pykrx=False)
    selected_vendor = vendor.strip().lower()
    if selected_vendor in {"auto", "pykrx"}:
        frame = pykrx_vendor.get_ohlcv_frame(resolved.code, start_date, end_date)
        selected_vendor = "pykrx"
    else:
        raise VendorUnavailableError(f"Unsupported chart data vendor: {vendor!r}")

    return ChartSeries(
        ticker_code=resolved.code,
        ticker_name=resolved.name,
        market=resolved.market,
        currency="KRW",
        vendor=selected_vendor,
        points=_points_from_frame(frame),
    )


def get_latest_close_price(
    symbol: str,
    end_date: str,
    *,
    lookback_days: int = 14,
    vendor: str = "pykrx",
) -> LatestPrice:
    """Return the latest available close price on or before end_date."""

    if lookback_days < 0:
        raise ValueError("lookback_days must be non-negative")

    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=lookback_days)
    series = get_ohlcv_chart_series(
        symbol,
        start.isoformat(),
        end.isoformat(),
        vendor=vendor,
    )
    for point in reversed(series.points):
        if point.close is not None:
            return LatestPrice(
                ticker_code=series.ticker_code,
                ticker_name=series.ticker_name,
                market=series.market,
                currency=series.currency,
                vendor=series.vendor,
                date=point.date,
                close=point.close,
            )

    raise VendorUnavailableError(f"No close price found for {series.ticker_code} on or before {end_date}")


def get_latest_close_prices(
    symbols: list[str],
    end_date: str,
    *,
    lookback_days: int = 14,
    vendor: str = "pykrx",
    ignore_errors: bool = False,
) -> dict[str, LatestPrice]:
    """Return latest close prices keyed by normalized ticker code."""

    prices: dict[str, LatestPrice] = {}
    for symbol in symbols:
        try:
            price = get_latest_close_price(
                symbol,
                end_date,
                lookback_days=lookback_days,
                vendor=vendor,
            )
        except Exception:
            if ignore_errors:
                continue
            raise
        prices[price.ticker_code] = price
    return prices


def _points_from_frame(frame: pd.DataFrame) -> list[OhlcvPoint]:
    if frame is None or frame.empty:
        return []

    normalized = frame.sort_index()
    points: list[OhlcvPoint] = []
    for index, row in normalized.iterrows():
        points.append(
            OhlcvPoint(
                date=pd.to_datetime(index).strftime("%Y-%m-%d"),
                open=_float_or_none(row, "Open"),
                high=_float_or_none(row, "High"),
                low=_float_or_none(row, "Low"),
                close=_float_or_none(row, "Close"),
                volume=_int_or_none(row, "Volume"),
                value=_float_or_none(row, "Value"),
                change_rate=_float_or_none(row, "ChangeRate"),
            )
        )
    return points


def _float_or_none(row: pd.Series, name: str) -> float | None:
    if name not in row.index or pd.isna(row[name]):
        return None
    return float(row[name])


def _int_or_none(row: pd.Series, name: str) -> int | None:
    if name not in row.index or pd.isna(row[name]):
        return None
    return int(row[name])

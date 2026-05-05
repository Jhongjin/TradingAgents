"""Korean-market return and benchmark-alpha helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd

from .errors import VendorUnavailableError
from .kr_tickers import is_kr_ticker, resolve_kr_ticker
from .pykrx_vendor import _compact_date, _normalize_ohlcv


_INDEX_CODE_BY_MARKET = {
    "KOSPI": "1001",
    "KOSDAQ": "2001",
    "KONEX": "1001",
    "UNKNOWN": "1001",
}


def fetch_korean_returns(
    ticker: str,
    trade_date: str,
    holding_days: int = 5,
) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """Fetch stock return and benchmark alpha from pykrx.

    Returns ``(raw_return, alpha_return, actual_holding_days)``. The benchmark
    is KOSPI for KOSPI/unknown names and KOSDAQ for KOSDAQ names.
    """

    if not is_kr_ticker(ticker):
        raise VendorUnavailableError(f"{ticker!r} is not a Korean ticker")
    if holding_days <= 0:
        raise ValueError("holding_days must be positive")

    resolved = resolve_kr_ticker(ticker)
    index_code = _INDEX_CODE_BY_MARKET.get(resolved.market, "1001")
    start = datetime.strptime(trade_date, "%Y-%m-%d")
    end = start + timedelta(days=holding_days + 14)
    start_compact = _compact_date(trade_date)
    end_compact = end.strftime("%Y%m%d")
    stock = _get_pykrx_stock_module()

    stock_frame = stock.get_market_ohlcv_by_date(start_compact, end_compact, resolved.code)
    index_frame = stock.get_index_ohlcv_by_date(start_compact, end_compact, index_code)
    stock_close = _close_series(stock_frame, "stock")
    benchmark_close = _close_series(index_frame, "benchmark")
    combined = pd.concat([stock_close, benchmark_close], axis=1, join="inner").dropna().sort_index()
    if len(combined) < 2:
        return None, None, None

    actual_days = min(holding_days, len(combined) - 1)
    start_stock = float(combined["stock"].iloc[0])
    end_stock = float(combined["stock"].iloc[actual_days])
    start_benchmark = float(combined["benchmark"].iloc[0])
    end_benchmark = float(combined["benchmark"].iloc[actual_days])
    if start_stock <= 0 or start_benchmark <= 0:
        return None, None, None

    raw_return = (end_stock / start_stock) - 1
    benchmark_return = (end_benchmark / start_benchmark) - 1
    return raw_return, raw_return - benchmark_return, actual_days


def _close_series(frame: pd.DataFrame | None, name: str) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64", name=name)
    normalized = _normalize_ohlcv(frame)
    if "Close" not in normalized.columns:
        raise VendorUnavailableError("pykrx OHLCV data does not include a close column")
    close = pd.to_numeric(normalized["Close"], errors="coerce")
    close.name = name
    return close


def _get_pykrx_stock_module():
    try:
        from pykrx import stock
    except Exception as exc:
        raise VendorUnavailableError("pykrx is not installed") from exc
    return stock

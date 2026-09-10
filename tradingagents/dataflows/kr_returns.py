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
    stock_close = _close_series(stock_frame, "stock")
    try:
        index_frame = stock.get_index_ohlcv_by_date(start_compact, end_compact, index_code)
        benchmark_close = _close_series(index_frame, "benchmark")
    except Exception:
        # pykrx index data comes from data.krx.co.kr, which is blocked on some
        # networks (TLS interception, cloud IPs). Fall back to the Yahoo index.
        benchmark_close = _yfinance_benchmark_close(resolved.benchmark_symbol, trade_date, end.strftime("%Y-%m-%d"))
    if benchmark_close.empty:
        benchmark_close = _yfinance_benchmark_close(resolved.benchmark_symbol, trade_date, end.strftime("%Y-%m-%d"))
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


def fetch_benchmark_close(symbol: str = "^KS11", *, on_date: str, lookback_days: int = 12) -> float | None:
    """Latest index close on or before ``on_date``.

    pykrx reads data.krx.co.kr, which some networks block, so Yahoo is the
    fallback. Returns ``None`` rather than raising: a missing benchmark must
    not stop the account snapshot from being written.
    """

    end = datetime.strptime(on_date[:10], "%Y-%m-%d")
    start = end - timedelta(days=max(lookback_days, 3))
    index_code = "2001" if symbol.upper() in {"^KQ11", "KQ11"} else "1001"
    try:
        stock = _get_pykrx_stock_module()
        frame = stock.get_index_ohlcv_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), index_code)
        closes = _close_series(frame, "benchmark").dropna()
        if not closes.empty:
            return float(closes.iloc[-1])
    except Exception:
        pass
    try:
        closes = _yfinance_benchmark_close(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")).dropna()
    except Exception:
        return None
    return float(closes.iloc[-1]) if not closes.empty else None


def _close_series(frame: pd.DataFrame | None, name: str) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64", name=name)
    normalized = _normalize_ohlcv(frame)
    if "Close" not in normalized.columns:
        raise VendorUnavailableError("pykrx OHLCV data does not include a close column")
    close = pd.to_numeric(normalized["Close"], errors="coerce")
    close.name = name
    return close


def _yfinance_benchmark_close(symbol: str, start_date: str, end_date: str) -> pd.Series:
    """Benchmark closes from Yahoo Finance (^KS11 / ^KQ11); empty series on failure."""

    try:
        import yfinance as yf

        end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        frame = yf.download(symbol, start=start_date, end=end_exclusive, progress=False, auto_adjust=False, multi_level_index=False)
    except Exception:
        return pd.Series(dtype="float64", name="benchmark")
    if frame is None or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype="float64", name="benchmark")
    close = pd.to_numeric(frame["Close"], errors="coerce")
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close.name = "benchmark"
    return close.dropna()


def _get_pykrx_stock_module():
    from .http_trust import apply_system_truststore_if_available

    apply_system_truststore_if_available()
    try:
        from pykrx import stock
    except Exception as exc:
        raise VendorUnavailableError("pykrx is not installed") from exc
    return stock

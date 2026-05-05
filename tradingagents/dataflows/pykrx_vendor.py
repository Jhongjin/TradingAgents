"""pykrx-backed Korean stock price and indicator data vendor."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

import pandas as pd

from .errors import VendorUnavailableError
from .kr_tickers import is_kr_ticker, resolve_kr_ticker


_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50-day simple moving average for medium-term trend confirmation.",
    "close_200_sma": "200-day simple moving average for long-term trend confirmation.",
    "close_10_ema": "10-day exponential moving average for short-term momentum.",
    "macd": "MACD momentum indicator.",
    "macds": "MACD signal line.",
    "macdh": "MACD histogram.",
    "rsi": "Relative Strength Index momentum oscillator.",
    "boll": "Bollinger Band middle line.",
    "boll_ub": "Bollinger Band upper band.",
    "boll_lb": "Bollinger Band lower band.",
    "atr": "Average True Range volatility indicator.",
    "vwma": "Volume Weighted Moving Average.",
    "mfi": "Money Flow Index.",
}


def get_stock(
    symbol: Annotated[str, "Korean 6-digit ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Retrieve KRX OHLCV data through pykrx."""

    resolved = _require_supported(symbol)
    start = _compact_date(start_date)
    end = _compact_date(end_date)
    stock = _get_pykrx_stock_module()
    data = stock.get_market_ohlcv_by_date(start, end, resolved.code)
    if data is None or data.empty:
        return f"No Korean market OHLCV data found for {resolved.code} between {start_date} and {end_date}"

    normalized = _normalize_ohlcv(data)
    snapshot_lines = _latest_snapshot_lines(stock, resolved.code, start, end)
    header = (
        f"# KRX OHLCV data for {resolved.name} ({resolved.code}, {resolved.market})\n"
        f"# Currency: KRW\n"
        f"# Date range: {start_date} to {end_date}\n"
        f"# Data vendor: pykrx\n"
    )
    if snapshot_lines:
        header += "# Latest pykrx snapshot\n" + "\n".join(f"# - {line}" for line in snapshot_lines) + "\n"
    header += "\n"
    return header + normalized.to_csv()


def get_indicator(
    symbol: Annotated[str, "Korean 6-digit ticker symbol"],
    indicator: Annotated[str, "Technical indicator name"],
    curr_date: Annotated[str, "Current trading date in YYYY-mm-dd format"],
    look_back_days: Annotated[int, "How many days to show"] = 30,
) -> str:
    """Calculate a stockstats indicator from pykrx OHLCV data."""

    from stockstats import wrap

    resolved = _require_supported(symbol)
    indicators = [part.strip().lower() for part in indicator.split(",") if part.strip()]
    if not indicators:
        raise ValueError("indicator cannot be empty")

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=max(look_back_days + 260, 260))
    raw = _ohlcv_frame(resolved.code, start_dt.strftime("%Y-%m-%d"), curr_date)
    if raw.empty:
        return f"No Korean market OHLCV data found for {resolved.code} before {curr_date}"

    stockstats_df = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    stockstats_df.index.name = "date"
    stats = wrap(stockstats_df)
    display_start = end_dt - timedelta(days=look_back_days)

    parts = []
    for ind in indicators:
        if ind not in _INDICATOR_DESCRIPTIONS:
            parts.append(f"Indicator {ind} is not supported for pykrx. Choose from: {sorted(_INDICATOR_DESCRIPTIONS)}")
            continue
        try:
            series = stats[ind]
            values = pd.DataFrame({"date": stats.index, ind: series.to_numpy()})
            values["date"] = pd.to_datetime(values["date"])
            values = values[values["date"] >= display_start]
            values["date"] = values["date"].dt.strftime("%Y-%m-%d")
        except Exception as exc:
            parts.append(f"Could not calculate {ind} for {resolved.code}: {exc}")
            continue
        lines = [f"## {ind} values for {resolved.name} ({resolved.code})"]
        for _, row in values.tail(look_back_days + 1).iterrows():
            value = row[ind]
            if pd.isna(value):
                value = "N/A"
            lines.append(f"{row['date']}: {value}")
        lines.append("")
        lines.append(_INDICATOR_DESCRIPTIONS[ind])
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _ohlcv_frame(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    stock = _get_pykrx_stock_module()
    raw = stock.get_market_ohlcv_by_date(_compact_date(start_date), _compact_date(end_date), code)
    if raw is None or raw.empty:
        return pd.DataFrame()
    return _normalize_ohlcv(raw)


def _require_supported(symbol: str):
    if not is_kr_ticker(symbol):
        raise VendorUnavailableError(f"pykrx only supports Korean 6-digit tickers: {symbol!r}")
    return resolve_kr_ticker(symbol)


def _get_pykrx_stock_module():
    try:
        from pykrx import stock
    except Exception as exc:
        raise VendorUnavailableError("pykrx is not installed") from exc
    return stock


def _compact_date(value: str) -> str:
    datetime.strptime(value, "%Y-%m-%d")
    return value.replace("-", "")


def _normalize_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.copy()
    frame.index = pd.to_datetime(frame.index)
    frame.index.name = "Date"
    frame = frame.rename(
        columns={
            "시가": "Open",
            "고가": "High",
            "저가": "Low",
            "종가": "Close",
            "거래량": "Volume",
            "거래대금": "Value",
            "등락률": "ChangeRate",
        }
    )
    preferred = [c for c in ["Open", "High", "Low", "Close", "Volume", "Value", "ChangeRate"] if c in frame.columns]
    return frame[preferred]


def _latest_snapshot_lines(stock, code: str, start: str, end: str) -> list[str]:
    lines: list[str] = []
    cap_frame = _optional_pykrx_frame(stock, "get_market_cap_by_date", start, end, code)
    if cap_frame is not None and not cap_frame.empty:
        latest = cap_frame.sort_index().iloc[-1]
        market_cap = _get_first(latest, "MarketCap", "시가총액")
        listed_shares = _get_first(latest, "ListedShares", "상장주식수")
        trading_value = _get_first(latest, "Value", "거래대금")
        if market_cap is not None:
            lines.append(f"Market cap: {_format_number(market_cap)} KRW")
        if listed_shares is not None:
            lines.append(f"Listed shares: {_format_number(listed_shares)}")
        if trading_value is not None:
            lines.append(f"Trading value: {_format_number(trading_value)} KRW")

    fundamental_frame = _optional_pykrx_frame(stock, "get_market_fundamental_by_date", start, end, code)
    if fundamental_frame is not None and not fundamental_frame.empty:
        latest = fundamental_frame.sort_index().iloc[-1]
        metrics = []
        for name in ("PER", "PBR", "EPS", "BPS", "DIV", "DPS"):
            value = _get_first(latest, name)
            if value is not None and not pd.isna(value):
                metrics.append(f"{name}: {value}")
        if metrics:
            lines.append("Fundamentals: " + ", ".join(metrics))
    return lines


def _optional_pykrx_frame(stock, method_name: str, *args) -> pd.DataFrame | None:
    method = getattr(stock, method_name, None)
    if not callable(method):
        return None
    try:
        frame = method(*args)
    except Exception:
        return None
    if isinstance(frame, pd.DataFrame):
        return frame
    return None


def _get_first(row: pd.Series, *names: str):
    for name in names:
        if name in row.index:
            return row[name]
    return None


def _format_number(value) -> str:
    if pd.isna(value):
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"

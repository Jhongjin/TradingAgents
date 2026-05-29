"""TradingView Charting Library-compatible datafeed payloads."""

from __future__ import annotations

from datetime import datetime, time
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.chart_data import (
    INTRADAY_INTERVALS,
    get_ohlcv_chart_series,
)
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.kr_tickers import (
    KoreanTicker,
    normalize_kr_ticker,
    resolve_kr_ticker,
    search_kr_tickers,
)


KOREA_TZ = ZoneInfo("Asia/Seoul")
SUPPORTED_RESOLUTIONS = ["1", "5", "15", "30", "60", "D", "W", "M"]


def build_tradingview_config_payload() -> dict[str, Any]:
    return {
        "supports_search": True,
        "supports_group_request": False,
        "supports_marks": False,
        "supports_timescale_marks": False,
        "supports_time": True,
        "supported_resolutions": SUPPORTED_RESOLUTIONS,
        "exchanges": [
            {"value": "KRX", "name": "KRX", "desc": "Korea Exchange"},
            {"value": "KOSPI", "name": "KOSPI", "desc": "Korea Composite Stock Price Index"},
            {"value": "KOSDAQ", "name": "KOSDAQ", "desc": "Korea Securities Dealers Automated Quotations"},
            {"value": "KONEX", "name": "KONEX", "desc": "Korea New Exchange"},
        ],
        "symbols_types": [{"name": "주식", "value": "stock"}],
        "currency_codes": ["KRW"],
    }


def build_tradingview_search_payload(
    query: str,
    *,
    exchange: str = "",
    symbol_type: str = "",
    limit: int = 30,
) -> list[dict[str, Any]]:
    selected_type = symbol_type.strip().lower()
    if selected_type and selected_type != "stock":
        return []

    selected_exchange = exchange.strip().upper()
    items = search_kr_tickers(query, limit=limit)
    if selected_exchange and selected_exchange != "KRX":
        items = [item for item in items if item.market.upper() == selected_exchange]
    return [_search_item(item) for item in items[:limit]]


def build_tradingview_symbol_payload(symbol: str) -> dict[str, Any]:
    ticker = _resolve_symbol(symbol)
    return {
        "name": ticker.code,
        "ticker": ticker.code,
        "description": ticker.name,
        "type": "stock",
        "session": "0900-1530",
        "timezone": "Asia/Seoul",
        "exchange": ticker.market,
        "listed_exchange": ticker.market,
        "currency_code": "KRW",
        "format": "price",
        "pricescale": 1,
        "minmov": 1,
        "volume_precision": 0,
        "has_intraday": True,
        "has_daily": True,
        "has_weekly_and_monthly": True,
        "has_empty_bars": False,
        "intraday_multipliers": ["1", "5", "15", "30", "60"],
        "daily_multipliers": ["1"],
        "weekly_multipliers": ["1"],
        "monthly_multipliers": ["1"],
        "supported_resolutions": SUPPORTED_RESOLUTIONS,
        "data_status": "delayed_streaming",
    }


def build_tradingview_history_payload(
    symbol: str,
    *,
    resolution: str,
    from_timestamp: int,
    to_timestamp: int,
    countback: int | None = None,
    vendor: str | None = None,
) -> dict[str, Any]:
    if to_timestamp <= from_timestamp:
        return {"s": "no_data"}

    ticker = _resolve_symbol(symbol)
    interval = _resolution_to_interval(resolution)
    selected_vendor = vendor or ("yfinance" if interval in INTRADAY_INTERVALS else "pykrx")
    series = get_ohlcv_chart_series(
        ticker.code,
        _date_from_timestamp(from_timestamp),
        _date_from_timestamp(to_timestamp),
        vendor=selected_vendor,
        interval=interval,
    )
    bars = [_bar_from_point(point) for point in series.points]
    bars = [bar for bar in bars if from_timestamp <= bar["t"] <= to_timestamp]
    bars.sort(key=lambda item: item["t"])
    if countback and countback > 0:
        bars = bars[-countback:]
    if not bars:
        return {"s": "no_data"}

    return {
        "s": "ok",
        "t": [bar["t"] for bar in bars],
        "o": [bar["o"] for bar in bars],
        "h": [bar["h"] for bar in bars],
        "l": [bar["l"] for bar in bars],
        "c": [bar["c"] for bar in bars],
        "v": [bar["v"] for bar in bars],
        "meta": {
            "symbol": series.ticker_code,
            "name": series.ticker_name,
            "market": series.market,
            "currency": series.currency,
            "vendor": series.vendor,
            "interval": series.interval,
        },
    }


def build_tradingview_time_payload() -> dict[str, int]:
    return {"time": int(datetime.now(tz=KOREA_TZ).timestamp())}


def _search_item(ticker: KoreanTicker) -> dict[str, Any]:
    return {
        "symbol": ticker.code,
        "full_name": f"{ticker.market}:{ticker.code}",
        "description": ticker.name,
        "exchange": ticker.market,
        "ticker": ticker.code,
        "type": "stock",
    }


def _resolve_symbol(symbol: str) -> KoreanTicker:
    cleaned = _clean_symbol(symbol)
    try:
        code = normalize_kr_ticker(cleaned)
    except ValueError as exc:
        raise VendorUnavailableError(f"TradingView datafeed supports Korean 6-digit tickers only: {symbol!r}") from exc
    return resolve_kr_ticker(code)


def _clean_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    if ":" in cleaned:
        cleaned = cleaned.rsplit(":", 1)[1]
    if "." in cleaned and len(cleaned) >= 9:
        cleaned = cleaned[:6]
    return cleaned


def _resolution_to_interval(resolution: str) -> str:
    selected = resolution.strip().upper()
    aliases = {
        "1": "1m",
        "5": "5m",
        "15": "15m",
        "30": "30m",
        "60": "60m",
        "1H": "60m",
        "D": "1d",
        "1D": "1d",
        "W": "1wk",
        "1W": "1wk",
        "M": "1mo",
        "1M": "1mo",
    }
    if selected not in aliases:
        raise VendorUnavailableError(f"Unsupported TradingView resolution: {resolution!r}")
    return aliases[selected]


def _date_from_timestamp(value: int) -> str:
    return datetime.fromtimestamp(int(value), tz=KOREA_TZ).date().isoformat()


def _bar_from_point(point: Any) -> dict[str, Any]:
    close = _finite_number(point.close)
    if close is None:
        raise VendorUnavailableError("Chart point is missing close price")
    open_price = _finite_number(point.open) or close
    high_price = _finite_number(point.high) or close
    low_price = _finite_number(point.low) or close
    return {
        "t": _point_timestamp(point.date),
        "o": open_price,
        "h": high_price,
        "l": low_price,
        "c": close,
        "v": int(point.volume or 0),
    }


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _point_timestamp(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        raise VendorUnavailableError("Chart point is missing date")
    if "T" in text or " " in text:
        normalized = text.replace("Z", "+00:00")
        if " " in normalized and "T" not in normalized:
            normalized = normalized.replace(" ", "T", 1)
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KOREA_TZ)
        return int(parsed.timestamp())
    parsed_date = datetime.fromisoformat(text[:10]).date()
    return int(datetime.combine(parsed_date, time.min, tzinfo=KOREA_TZ).timestamp())

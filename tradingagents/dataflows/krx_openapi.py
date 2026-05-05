"""KRX Open API vendor.

The default MVP still prefers pykrx until a KRX Open API key and per-service
approvals are ready. When configured, this adapter can fetch KOSPI/KOSDAQ/KONEX
daily trade data through the pykrx-openapi wrapper behind the same tool API.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import os
from typing import Annotated

import pandas as pd

from .errors import VendorUnavailableError
from .kr_tickers import is_kr_ticker, resolve_kr_ticker


_DAILY_METHOD_BY_MARKET = {
    "KOSPI": "get_stock_daily_trade",
    "KOSDAQ": "get_kosdaq_stock_daily_trade",
    "KONEX": "get_konex_daily_trade",
    "UNKNOWN": "get_stock_daily_trade",
}
_FIELD_ALIASES = {
    "Date": ("BAS_DD", "TRD_DD", "Date"),
    "Code": ("ISU_SRT_CD", "ISU_CD", "Code"),
    "Name": ("ISU_NM", "Name"),
    "Open": ("TDD_OPNPRC", "OPNPRC", "Open"),
    "High": ("TDD_HGPRC", "HGPRC", "High"),
    "Low": ("TDD_LWPRC", "LWPRC", "Low"),
    "Close": ("TDD_CLSPRC", "CLSPRC", "Close"),
    "Volume": ("ACC_TRDVOL", "TRDVOL", "Volume"),
    "Value": ("ACC_TRDVAL", "TRDVAL", "Value"),
    "MarketCap": ("MKTCAP", "MarketCap"),
    "Shares": ("LIST_SHRS", "LIST_SHARES", "Shares"),
    "ChangeRate": ("FLUC_RT", "ChangeRate"),
}


def get_stock(
    symbol: Annotated[str, "Korean 6-digit ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    resolved = _require_supported(symbol)
    frame = _ohlcv_frame(resolved.code, resolved.market, start_date, end_date)
    if frame.empty:
        return f"No KRX Open API OHLCV data found for {resolved.code} between {start_date} and {end_date}"

    header = (
        f"# KRX Open API daily trade data for {resolved.name} ({resolved.code}, {resolved.market})\n"
        f"# Currency: KRW\n"
        f"# Date range: {start_date} to {end_date}\n"
        f"# Data vendor: KRX Open API\n\n"
    )
    return header + frame.to_csv()


def get_indicator(
    symbol: Annotated[str, "Korean 6-digit ticker symbol"],
    indicator: Annotated[str, "Technical indicator name"],
    curr_date: Annotated[str, "Current trading date in YYYY-mm-dd format"],
    look_back_days: Annotated[int, "How many days to show"] = 30,
) -> str:
    from stockstats import wrap

    resolved = _require_supported(symbol)
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=max(look_back_days + 260, 260))
    frame = _ohlcv_frame(resolved.code, resolved.market, start_dt.strftime("%Y-%m-%d"), curr_date)
    if frame.empty:
        return f"No KRX Open API OHLCV data found for {resolved.code} before {curr_date}"

    stats = wrap(
        frame.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
    )
    indicator = indicator.strip().lower()
    try:
        series = stats[indicator]
    except Exception as exc:
        return f"Could not calculate {indicator} for {resolved.code} from KRX Open API data: {exc}"

    display_start = end_dt - timedelta(days=look_back_days)
    values = pd.DataFrame({"date": stats.index, indicator: series.to_numpy()})
    values["date"] = pd.to_datetime(values["date"])
    values = values[values["date"] >= display_start]
    values["date"] = values["date"].dt.strftime("%Y-%m-%d")
    lines = [f"## {indicator} values for {resolved.name} ({resolved.code}) from KRX Open API"]
    for _, row in values.tail(look_back_days + 1).iterrows():
        value = row[indicator]
        lines.append(f"{row['date']}: {'N/A' if pd.isna(value) else value}")
    return "\n".join(lines)


def _ohlcv_frame(code: str, market: str, start_date: str, end_date: str) -> pd.DataFrame:
    client = _get_krx_client()
    method_name = _DAILY_METHOD_BY_MARKET.get(market, "get_stock_daily_trade")
    rows: list[dict] = []
    for bas_dd in _date_range(start_date, end_date):
        try:
            payload = getattr(client, method_name)(bas_dd)
        except Exception as exc:
            raise VendorUnavailableError(f"KRX Open API request failed for {bas_dd}: {exc}") from exc
        rows.extend(_matching_rows(payload.get("OutBlock_1", []), code))

    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame([_normalize_row(row) for row in rows])
    frame["Date"] = pd.to_datetime(frame["Date"])
    frame = frame.set_index("Date").sort_index()
    preferred = [
        c
        for c in ["Open", "High", "Low", "Close", "Volume", "Value", "MarketCap", "Shares", "ChangeRate"]
        if c in frame.columns
    ]
    return frame[preferred]


def _matching_rows(rows: list[dict], code: str) -> list[dict]:
    selected = []
    for row in rows:
        row_code = _first_value(row, *_FIELD_ALIASES["Code"])
        if row_code is not None and str(row_code).zfill(6) == code:
            selected.append(row)
    return selected


def _normalize_row(row: dict) -> dict:
    normalized = {}
    for target, aliases in _FIELD_ALIASES.items():
        value = _first_value(row, *aliases)
        if value is not None:
            normalized[target] = value
    return normalized


def _first_value(row: dict, *aliases: str):
    for alias in aliases:
        if alias in row and row[alias] not in {"", None, "-"}:
            return row[alias]
    return None


def _date_range(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    days = (end - start).days
    if days > int(os.getenv("KRX_OPENAPI_MAX_DAYS", "370")):
        raise ValueError("KRX Open API date range is too large")
    return [
        (start + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    ]


def _get_krx_client():
    api_key = _require_ready()
    try:
        from pykrx_openapi import KRXOpenAPI
    except Exception as exc:
        raise VendorUnavailableError("pykrx-openapi is not installed") from exc
    timeout = int(os.getenv("KRX_OPENAPI_TIMEOUT", "30"))
    return KRXOpenAPI(api_key=api_key, timeout=timeout)


def _require_ready() -> str:
    api_key = os.getenv("KRX_API_KEY") or os.getenv("KRX_OPENAPI_KEY")
    if not api_key:
        raise VendorUnavailableError("KRX_API_KEY is not configured")
    return api_key


def _require_supported(symbol: str):
    if not is_kr_ticker(symbol):
        raise VendorUnavailableError(f"KRX Open API only supports Korean 6-digit tickers: {symbol!r}")
    return resolve_kr_ticker(symbol)

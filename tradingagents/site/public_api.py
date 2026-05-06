"""Framework-neutral payload builders for public Korean stock pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
import os
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.chart_data import get_ohlcv_chart_series
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker
from tradingagents.storage import StorageRepository
from .strategy_lenses import build_korean_strategy_lenses


SEO_DISCLAIMER = (
    "AI analysis is for informational purposes only and is not investment, legal, "
    "tax, or live trading advice."
)
TRADING_BOUNDARY = "Live trading and broker order placement are intentionally not supported."


def build_public_stock_payload(
    ticker: str,
    *,
    repo: StorageRepository | None = None,
    chart_start: str | None = None,
    chart_end: str | None = None,
    as_of_date: str | None = None,
    max_analysis_age_days: int = 1,
    chart_vendor: str | None = None,
    include_chart: bool = True,
    include_analysis: bool = True,
) -> dict[str, Any]:
    """Build a JSON-ready payload for a public Korean stock page.

    The payload is intentionally independent from FastAPI, Next.js, or any
    other serving layer. It combines deterministic ticker metadata, optional
    persisted AI analysis, and optional read-only OHLCV chart data.
    """

    if not is_kr_ticker(ticker):
        raise VendorUnavailableError(f"public stock pages currently support Korean 6-digit tickers only: {ticker!r}")

    resolved = resolve_kr_ticker(ticker, lookup_pykrx=False)
    end = _parse_or_default_end(chart_end)
    start = _parse_or_default_start(chart_start, end)
    as_of = _parse_or_default_end(as_of_date)
    if max_analysis_age_days < 0:
        raise ValueError("max_analysis_age_days must be non-negative")
    analysis = _analysis_payload(repo, resolved.code) if include_analysis else {"status": "skipped"}
    analysis_refresh = _analysis_refresh_payload(analysis, as_of, max_analysis_age_days)
    selected_chart_vendor = chart_vendor or os.getenv("TRADINGAGENTS_CHART_DATA_VENDOR", "pykrx")
    chart = _chart_payload(resolved.code, start, end, selected_chart_vendor) if include_chart else {"status": "skipped"}

    payload = {
        "ticker": {
            "code": resolved.code,
            "name": resolved.name,
            "market": resolved.market,
            "currency": "KRW",
            "benchmark_symbol": resolved.benchmark_symbol,
        },
        "analysis": analysis,
        "analysis_refresh": analysis_refresh,
        "chart": chart,
        "strategy_lenses": build_korean_strategy_lenses(
            chart=chart,
            analysis=analysis,
            analysis_refresh=analysis_refresh,
            market=resolved.market,
        ),
        "notices": [SEO_DISCLAIMER, TRADING_BOUNDARY],
        "generated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
    }
    return _json_ready(payload)


def _analysis_payload(repo: StorageRepository | None, ticker_code: str) -> dict[str, Any]:
    if repo is None:
        return {"status": "not_configured"}

    try:
        bundle = repo.latest_public_analysis_bundle(ticker_code)
    except Exception as exc:
        return {"status": "unavailable", "error": _public_error(exc)}
    if bundle is None:
        return {"status": "missing"}

    return {
        "status": "available",
        "run": bundle["run"],
        "reports": bundle["reports"],
        "decision": bundle["decision"],
        "outcomes": bundle.get("outcomes", []),
    }


def _analysis_refresh_payload(
    analysis: dict[str, Any],
    as_of: date,
    max_age_days: int,
) -> dict[str, Any]:
    status = analysis.get("status")
    if status == "skipped":
        return {"recommended": False, "reason": "analysis_skipped", "as_of": as_of}
    if status == "not_configured":
        return {"recommended": False, "reason": "storage_not_configured", "as_of": as_of}
    if status == "missing":
        return {"recommended": True, "reason": "no_completed_public_analysis", "as_of": as_of}
    if status != "available":
        return {"recommended": True, "reason": "analysis_unavailable", "as_of": as_of}

    try:
        trade_date = _coerce_date(analysis.get("run", {}).get("trade_date"))
    except (TypeError, ValueError):
        return {"recommended": True, "reason": "invalid_analysis_trade_date", "as_of": as_of}
    age_days = (as_of - trade_date).days
    if age_days > max_age_days:
        return {
            "recommended": True,
            "reason": "stale",
            "as_of": as_of,
            "latest_trade_date": trade_date,
            "age_days": age_days,
            "max_age_days": max_age_days,
        }
    return {
        "recommended": False,
        "reason": "fresh",
        "as_of": as_of,
        "latest_trade_date": trade_date,
        "age_days": max(age_days, 0),
        "max_age_days": max_age_days,
    }


def _chart_payload(ticker_code: str, start: date, end: date, vendor: str) -> dict[str, Any]:
    try:
        series = get_ohlcv_chart_series(
            ticker_code,
            start.isoformat(),
            end.isoformat(),
            vendor=vendor,
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "vendor": vendor,
            "error": _public_error(exc),
        }

    return {
        "status": "available",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        **series.as_dict(),
    }


def _parse_or_default_end(value: str | None) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _parse_or_default_start(value: str | None, end: date) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return end - timedelta(days=180)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _public_error(exc: Exception) -> str:
    if isinstance(exc, VendorUnavailableError):
        return str(exc)
    return exc.__class__.__name__

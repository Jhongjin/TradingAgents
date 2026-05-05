"""Framework-neutral payload builders for public Korean stock pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.chart_data import get_ohlcv_chart_series
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker
from tradingagents.storage import StorageRepository


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
    chart_vendor: str = "pykrx",
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

    payload = {
        "ticker": {
            "code": resolved.code,
            "name": resolved.name,
            "market": resolved.market,
            "currency": "KRW",
            "benchmark_symbol": resolved.benchmark_symbol,
        },
        "analysis": _analysis_payload(repo, resolved.code) if include_analysis else {"status": "skipped"},
        "chart": _chart_payload(resolved.code, start, end, chart_vendor) if include_chart else {"status": "skipped"},
        "notices": [SEO_DISCLAIMER, TRADING_BOUNDARY],
        "generated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
    }
    return _json_ready(payload)


def _analysis_payload(repo: StorageRepository | None, ticker_code: str) -> dict[str, Any]:
    if repo is None:
        return {"status": "not_configured"}

    bundle = repo.latest_public_analysis_bundle(ticker_code)
    if bundle is None:
        return {"status": "missing"}

    return {
        "status": "available",
        "run": bundle["run"],
        "reports": bundle["reports"],
        "decision": bundle["decision"],
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

"""Framework-neutral payload builders for public Korean stock pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
import os
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.chart_data import (
    INTRADAY_INTERVALS,
    get_krx_chart_max_days,
    get_ohlcv_chart_series,
    normalize_chart_interval,
)
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker
from tradingagents.report_quality import enrich_reports_with_quality
from tradingagents.storage import StorageRepository
from .strategy_lenses import build_korean_strategy_lenses


SEO_DISCLAIMER = "AI 분석은 정보 제공용이며 투자 조언, 세무·법률 자문, 실거래 안내가 아닙니다."
TRADING_BOUNDARY = "TradingAgents Korea는 실거래 주문이나 브로커 주문 실행 기능을 제공하지 않습니다."


def build_public_stock_payload(
    ticker: str,
    *,
    repo: StorageRepository | None = None,
    chart_start: str | None = None,
    chart_end: str | None = None,
    as_of_date: str | None = None,
    max_analysis_age_days: int = 1,
    chart_vendor: str | None = None,
    chart_interval: str | None = None,
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

    resolved = resolve_kr_ticker(ticker)
    selected_chart_vendor = chart_vendor or os.getenv("TRADINGAGENTS_CHART_DATA_VENDOR", "pykrx")
    selected_chart_interval = normalize_chart_interval(chart_interval)
    end = _parse_or_default_end(chart_end)
    start = _parse_or_default_start(chart_start, end, selected_chart_vendor, selected_chart_interval)
    as_of = _parse_or_default_end(as_of_date)
    if max_analysis_age_days < 0:
        raise ValueError("max_analysis_age_days must be non-negative")
    analysis = _analysis_payload(repo, resolved.code) if include_analysis else {"status": "skipped"}
    analysis_refresh = _analysis_refresh_payload(analysis, as_of, max_analysis_age_days)
    chart = (
        _chart_payload(resolved.code, start, end, selected_chart_vendor, selected_chart_interval)
        if include_chart
        else {"status": "skipped", "interval": selected_chart_interval}
    )

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

    run = bundle["run"]
    return {
        "status": "available",
        "run": run,
        "reports": enrich_reports_with_quality(bundle["reports"], run),
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
        return _analysis_refresh_result(False, "analysis_skipped", as_of=as_of)
    if status == "not_configured":
        return _analysis_refresh_result(False, "storage_not_configured", as_of=as_of)
    if status == "missing":
        return _analysis_refresh_result(True, "no_completed_public_analysis", as_of=as_of)
    if status != "available":
        return _analysis_refresh_result(True, "analysis_unavailable", as_of=as_of)

    try:
        trade_date = _coerce_date(analysis.get("run", {}).get("trade_date"))
    except (TypeError, ValueError):
        return _analysis_refresh_result(True, "invalid_analysis_trade_date", as_of=as_of)
    age_days = (as_of - trade_date).days
    if age_days > max_age_days:
        return _analysis_refresh_result(
            True,
            "stale",
            as_of=as_of,
            latest_trade_date=trade_date,
            age_days=age_days,
            max_age_days=max_age_days,
        )
    return _analysis_refresh_result(
        False,
        "fresh",
        as_of=as_of,
        latest_trade_date=trade_date,
        age_days=max(age_days, 0),
        max_age_days=max_age_days,
    )


def _analysis_refresh_result(recommended: bool, reason: str, *, as_of: date, **extra: Any) -> dict[str, Any]:
    return {
        "recommended": recommended,
        "reason": reason,
        "reason_label": _analysis_refresh_reason_label(reason),
        "status_label": _analysis_refresh_status_label(recommended, reason),
        "as_of": as_of,
        **extra,
    }


def _analysis_refresh_reason_label(reason: str) -> str:
    return {
        "fresh": "최근 리포트",
        "stale": "업데이트 필요",
        "analysis_skipped": "분석 생략",
        "storage_not_configured": "저장소 확인 대기",
        "no_completed_public_analysis": "완료된 공개 리포트 없음",
        "analysis_unavailable": "공개 분석 응답 확인 실패",
        "invalid_analysis_trade_date": "분석 기준일 확인 필요",
    }.get(str(reason or ""), str(reason or "확인 정보 없음"))


def _analysis_refresh_status_label(recommended: bool, reason: str) -> str:
    if reason in {"storage_not_configured", "analysis_skipped"}:
        return "확인 대기"
    return "업데이트 권장" if recommended else "최신"


def _chart_payload(ticker_code: str, start: date, end: date, vendor: str, interval: str) -> dict[str, Any]:
    requested_vendor = _normalize_chart_vendor(vendor)
    requested_interval = normalize_chart_interval(interval)
    try:
        series = get_ohlcv_chart_series(
            ticker_code,
            start.isoformat(),
            end.isoformat(),
            vendor=vendor,
            interval=requested_interval,
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "interval": requested_interval,
            "vendor": vendor,
            **_chart_source_metadata(requested_vendor=requested_vendor, resolved_vendor=None, point_count=0),
            "error": _public_error(exc),
        }

    point_count = len(series.points)
    return {
        "status": "available",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "interval": series.interval,
        **_chart_source_metadata(
            requested_vendor=requested_vendor,
            resolved_vendor=series.vendor,
            point_count=point_count,
        ),
        **series.as_dict(),
    }


def _chart_source_metadata(
    *,
    requested_vendor: str,
    resolved_vendor: str | None,
    point_count: int,
) -> dict[str, Any]:
    fallback_used = requested_vendor == "auto" and resolved_vendor is not None and resolved_vendor != "krx"
    return {
        "requested_vendor": requested_vendor,
        "resolved_vendor": resolved_vendor,
        "point_count": point_count,
        "data_source_label": _chart_data_source_label(resolved_vendor or requested_vendor),
        "fallback_used": fallback_used,
    }


def _chart_data_source_label(vendor: str | None) -> str:
    selected = _normalize_chart_vendor(vendor)
    return {
        "krx": "KRX Open API",
        "pykrx": "pykrx",
        "yfinance": "Yahoo Finance",
        "auto": "auto vendor selection",
    }.get(selected, "unknown chart vendor")


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


def _parse_or_default_start(
    value: str | None,
    end: date,
    chart_vendor: str = "pykrx",
    chart_interval: str = "1d",
) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    interval = normalize_chart_interval(chart_interval)
    if interval in INTRADAY_INTERVALS:
        return end - timedelta(days=_default_intraday_days(interval))
    if _normalize_chart_vendor(chart_vendor) == "krx":
        return end - timedelta(days=get_krx_chart_max_days())
    return end - timedelta(days=180)


def _default_intraday_days(interval: str) -> int:
    return {
        "1m": 1,
        "5m": 1,
        "15m": 5,
        "30m": 5,
        "60m": 30,
    }.get(interval, 1)


def _normalize_chart_vendor(vendor: str | None) -> str:
    selected = (vendor or "pykrx").strip().lower().replace("_", "-")
    if selected in {"krx-openapi", "krx-open-api"}:
        return "krx"
    return selected


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

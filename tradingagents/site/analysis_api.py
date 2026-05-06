"""Payload builders for analysis refresh requests."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker
from tradingagents.storage import AnalysisRequestInput, StorageRepository

from .public_api import _json_ready


def queue_analysis_refresh_request(
    repo: StorageRepository,
    *,
    ticker: str,
    user_id: str,
    requested_trade_date: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Queue a member-requested analysis refresh without running LLM work inline."""

    if not is_kr_ticker(ticker):
        raise ValueError("analysis refresh currently supports Korean 6-digit tickers only")
    resolved = resolve_kr_ticker(ticker, lookup_pykrx=False)
    trade_date = _trade_date(requested_trade_date)
    existing = repo.find_active_analysis_request(
        user_id=user_id,
        ticker_code=resolved.code,
        requested_trade_date=trade_date,
    )
    if existing is not None:
        return _json_ready(
            {
                "status": "already_queued",
                "request_id": existing["id"],
                "ticker": {
                    "code": resolved.code,
                    "name": resolved.name,
                    "market": resolved.market,
                },
                "requested_trade_date": trade_date,
                "reason": existing.get("reason") or reason,
            }
        )

    request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=user_id,
            ticker_code=resolved.code,
            ticker_name=resolved.name,
            market=resolved.market,
            requested_trade_date=trade_date,
            reason=reason,
            metadata={"source": "site_api"},
        )
    )
    return _json_ready(
        {
            "status": "queued",
            "request_id": request_id,
            "ticker": {
                "code": resolved.code,
                "name": resolved.name,
                "market": resolved.market,
            },
            "requested_trade_date": trade_date,
            "reason": reason,
        }
    )


def build_member_analysis_requests_payload(
    repo: StorageRepository,
    *,
    user_id: str,
    status: str | None = None,
    limit: int = 20,
    max_limit: int = 50,
) -> dict[str, Any]:
    """Build a member-owned analysis request list payload."""

    if max_limit <= 0:
        raise ValueError("max_limit must be positive")
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > max_limit:
        raise ValueError(f"limit cannot exceed {max_limit}")
    rows = repo.list_analysis_requests(status=status, user_id=user_id, limit=limit)
    return _json_ready(
        {
            "status": "available",
            "filter_status": status,
            "limit": limit,
            "items": rows,
            "item_count": len(rows),
        }
    )


def build_member_analysis_request_payload(
    repo: StorageRepository,
    *,
    request_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    """Build a member-owned single analysis request payload."""

    row = repo.get_analysis_request(request_id)
    if row is None:
        return None
    if str(row.get("user_id")) != user_id:
        raise PermissionError("analysis request does not belong to the authenticated user")
    return _json_ready({"status": "available", "item": row})


def build_public_analysis_feed_payload(
    repo: StorageRepository,
    *,
    ticker: str | None = None,
    limit: int = 20,
    max_limit: int = 50,
) -> dict[str, Any]:
    """Build a public completed-analysis feed payload."""

    if max_limit <= 0:
        raise ValueError("max_limit must be positive")
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > max_limit:
        raise ValueError(f"limit cannot exceed {max_limit}")
    ticker_code = None
    if ticker:
        if not is_kr_ticker(ticker):
            raise ValueError("analysis feed currently supports Korean 6-digit tickers only")
        ticker_code = resolve_kr_ticker(ticker, lookup_pykrx=False).code

    try:
        rows = repo.list_public_analysis_runs(ticker_code=ticker_code, limit=limit)
    except Exception as exc:
        return _json_ready(
            {
                "status": "unavailable",
                "ticker_code": ticker_code,
                "limit": limit,
                "items": [],
                "item_count": 0,
                "error": exc.__class__.__name__,
                "summary": _analysis_feed_summary([]),
            }
        )
    return _json_ready(
        {
            "status": "available",
            "ticker_code": ticker_code,
            "limit": limit,
            "items": rows,
            "item_count": len(rows),
            "summary": _analysis_feed_summary(rows),
        }
    )


def build_public_analysis_outcomes_payload(
    repo: StorageRepository,
    *,
    ticker: str | None = None,
    status: str | None = None,
    limit: int = 20,
    max_limit: int = 50,
) -> dict[str, Any]:
    """Build a public payload of evaluated analysis outcomes."""

    if max_limit <= 0:
        raise ValueError("max_limit must be positive")
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > max_limit:
        raise ValueError(f"limit cannot exceed {max_limit}")
    ticker_code = None
    if ticker:
        if not is_kr_ticker(ticker):
            raise ValueError("analysis outcomes currently support Korean 6-digit tickers only")
        ticker_code = resolve_kr_ticker(ticker, lookup_pykrx=False).code

    try:
        rows = repo.list_analysis_outcomes(ticker_code=ticker_code, status=status, limit=limit, public_only=True)
    except Exception as exc:
        return _json_ready(
            {
                "status": "unavailable",
                "ticker_code": ticker_code,
                "filter_status": status,
                "limit": limit,
                "items": [],
                "item_count": 0,
                "error": exc.__class__.__name__,
                "summary": _analysis_outcome_summary([]),
            }
        )
    return _json_ready(
        {
            "status": "available",
            "ticker_code": ticker_code,
            "filter_status": status,
            "limit": limit,
            "items": rows,
            "item_count": len(rows),
            "summary": _analysis_outcome_summary(rows),
        }
    )


def _analysis_feed_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    market_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    ticker_codes = set()
    latest_trade_date = None
    for row in rows:
        ticker = row.get("ticker_code")
        if ticker:
            ticker_codes.add(str(ticker))
        market = str(row.get("market") or "KR")
        market_counts[market] = market_counts.get(market, 0) + 1
        provider = str(row.get("model_provider") or "unknown")
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        trade_date = row.get("trade_date")
        if trade_date is not None and (latest_trade_date is None or str(trade_date) > str(latest_trade_date)):
            latest_trade_date = trade_date
    return {
        "completed_count": len(rows),
        "unique_ticker_count": len(ticker_codes),
        "latest_trade_date": latest_trade_date,
        "market_counts": market_counts,
        "model_provider_counts": provider_counts,
    }


def _analysis_outcome_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    alpha_values = [float(row["alpha_return"]) for row in completed if row.get("alpha_return") is not None]
    raw_values = [float(row["raw_return"]) for row in completed if row.get("raw_return") is not None]
    positive_alpha_count = sum(1 for value in alpha_values if value > 0)
    return {
        "completed_count": len(completed),
        "pending_count": sum(1 for row in rows if row.get("status") == "pending"),
        "unavailable_count": sum(1 for row in rows if row.get("status") == "unavailable"),
        "positive_alpha_count": positive_alpha_count,
        "positive_alpha_rate": (positive_alpha_count / len(alpha_values)) if alpha_values else None,
        "average_alpha_return": (sum(alpha_values) / len(alpha_values)) if alpha_values else None,
        "average_raw_return": (sum(raw_values) / len(raw_values)) if raw_values else None,
    }


def _trade_date(value: str | None) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.now(ZoneInfo("Asia/Seoul")).date()

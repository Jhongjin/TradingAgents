"""Payload builders for analysis refresh requests."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker
from tradingagents.storage import AnalysisRequestInput, StorageRepository

from .public_api import _json_ready


ANALYSIS_REQUEST_ACTIVE_LIMIT_ENV = "TRADINGAGENTS_ANALYSIS_REQUEST_ACTIVE_LIMIT"
ANALYSIS_REQUEST_DAILY_LIMIT_ENV = "TRADINGAGENTS_ANALYSIS_REQUEST_DAILY_LIMIT"
DEFAULT_ANALYSIS_REQUEST_ACTIVE_LIMIT = 5
DEFAULT_ANALYSIS_REQUEST_DAILY_LIMIT = 20
ANALYSIS_REQUEST_WINDOW_HOURS = 24
ACTIVE_ANALYSIS_REQUEST_STATUSES = ("queued", "running")


class AnalysisRequestQuotaExceeded(ValueError):
    """Raised when a member analysis request would exceed queue limits."""

    def __init__(self, *, kind: str, limit: int, used: int, window_hours: int | None = None) -> None:
        self.kind = kind
        self.limit = limit
        self.used = used
        self.window_hours = window_hours
        if kind == "active":
            message = f"동시에 대기/처리 중인 분석 요청은 사용자당 {limit}개까지 가능합니다."
        else:
            message = f"분석 요청은 사용자당 최근 {window_hours or ANALYSIS_REQUEST_WINDOW_HOURS}시간에 {limit}개까지 가능합니다."
        super().__init__(message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "quota_exceeded",
            "kind": self.kind,
            "limit": self.limit,
            "used": self.used,
            "message": str(self),
        }
        if self.window_hours is not None:
            payload["window_hours"] = self.window_hours
        return payload


def queue_analysis_refresh_request(
    repo: StorageRepository,
    *,
    ticker: str,
    user_id: str,
    requested_trade_date: str | None = None,
    reason: str | None = None,
    active_limit: int | None = None,
    daily_limit: int | None = None,
    now: datetime | None = None,
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
                "duplicate": True,
                "ticker": {
                    "code": resolved.code,
                    "name": resolved.name,
                    "market": resolved.market,
                },
                "requested_trade_date": trade_date,
                "reason": existing.get("reason") or reason,
                "public_stock_path": f"/stocks/{resolved.code}",
                "status_label": _analysis_request_status_label(existing.get("status")),
            }
        )

    limits = _analysis_request_limits(active_limit=active_limit, daily_limit=daily_limit)
    active_count = repo.count_analysis_requests(user_id=user_id, statuses=ACTIVE_ANALYSIS_REQUEST_STATUSES)
    if active_count >= limits["active_limit"]:
        raise AnalysisRequestQuotaExceeded(kind="active", limit=limits["active_limit"], used=active_count)

    window_start = _analysis_request_window_start(now)
    daily_count = repo.count_analysis_requests(user_id=user_id, created_at_from=window_start)
    if daily_count >= limits["daily_limit"]:
        raise AnalysisRequestQuotaExceeded(
            kind="daily",
            limit=limits["daily_limit"],
            used=daily_count,
            window_hours=ANALYSIS_REQUEST_WINDOW_HOURS,
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
            "duplicate": False,
            "ticker": {
                "code": resolved.code,
                "name": resolved.name,
                "market": resolved.market,
            },
            "requested_trade_date": trade_date,
            "reason": reason,
            "public_stock_path": f"/stocks/{resolved.code}",
            "status_label": _analysis_request_status_label("queued"),
            "quota": {
                "active_limit": limits["active_limit"],
                "active_used": active_count + 1,
                "daily_limit": limits["daily_limit"],
                "daily_used": daily_count + 1,
                "window_hours": ANALYSIS_REQUEST_WINDOW_HOURS,
            },
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
    rows = [_analysis_request_item(row) for row in repo.list_analysis_requests(status=status, user_id=user_id, limit=limit)]
    return _json_ready(
        {
            "status": "available",
            "filter_status": status,
            "limit": limit,
            "items": rows,
            "item_count": len(rows),
            "summary": _analysis_request_summary(rows),
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
    return _json_ready({"status": "available", "item": _analysis_request_item(row)})


def build_public_analysis_bundle_payload(repo: StorageRepository, *, analysis_run_id: str) -> dict[str, Any] | None:
    """Build an addressable public analysis bundle by run id."""

    bundle = repo.get_analysis_bundle(analysis_run_id)
    if bundle is None:
        return None
    run = bundle.get("run") or {}
    if run.get("visibility") != "public" or run.get("status") != "completed":
        return None
    reports = bundle.get("reports") or []
    decision = bundle.get("decision")
    outcomes = bundle.get("outcomes") or []
    return _json_ready(
        {
            "status": "available",
            "run": run,
            "reports": reports,
            "decision": decision,
            "outcomes": outcomes,
            "summary": _analysis_bundle_summary(reports=reports, decision=decision, outcomes=outcomes),
        }
    )


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
        items = [_enrich_public_analysis_item(repo, row) for row in rows]
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
            "items": items,
            "item_count": len(items),
            "summary": _analysis_feed_summary(items),
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
    rating_counts: dict[str, int] = {}
    ticker_codes = set()
    latest_trade_date = None
    alpha_values = []
    for row in rows:
        ticker = row.get("ticker_code")
        if ticker:
            ticker_codes.add(str(ticker))
        market = str(row.get("market") or "KR")
        market_counts[market] = market_counts.get(market, 0) + 1
        provider = str(row.get("model_provider") or "unknown")
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        rating = row.get("decision_rating")
        if rating:
            key = str(rating)
            rating_counts[key] = rating_counts.get(key, 0) + 1
        if row.get("alpha_return") is not None:
            alpha_values.append(float(row["alpha_return"]))
        trade_date = row.get("trade_date")
        if trade_date is not None and (latest_trade_date is None or str(trade_date) > str(latest_trade_date)):
            latest_trade_date = trade_date
    return {
        "completed_count": len(rows),
        "unique_ticker_count": len(ticker_codes),
        "latest_trade_date": latest_trade_date,
        "market_counts": market_counts,
        "model_provider_counts": provider_counts,
        "decision_rating_counts": rating_counts,
        "completed_outcome_count": sum(int(row.get("completed_outcome_count") or 0) for row in rows),
        "average_alpha_return": (sum(alpha_values) / len(alpha_values)) if alpha_values else None,
    }


def _analysis_request_item(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    ticker_code = str(item.get("ticker_code") or "")
    item["public_stock_path"] = f"/stocks/{ticker_code}" if ticker_code else None
    item["status_label"] = _analysis_request_status_label(item.get("status"))
    item["is_active"] = str(item.get("status") or "") in {"queued", "running"}
    return item


def _analysis_request_status_label(status: Any) -> str:
    return {
        "queued": "대기",
        "running": "처리 중",
        "completed": "완료",
        "failed": "실패",
        "skipped": "건너뜀",
    }.get(str(status), "미확인")


def _enrich_public_analysis_item(repo: StorageRepository, row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    run_id = item.get("id")
    if not run_id:
        return item
    item["report_path"] = f"/analyses/{run_id}"
    item["api_path"] = f"/api/analyses/{run_id}"
    try:
        bundle = repo.get_analysis_bundle(str(run_id))
    except Exception:
        return item
    if not bundle:
        return item
    reports = bundle.get("reports") or []
    decision = bundle.get("decision")
    outcomes = bundle.get("outcomes") or []
    item["report_count"] = len(reports)
    if decision:
        item["decision_rating"] = decision.get("rating")
        item["decision_action"] = decision.get("action")
    completed_outcomes = [outcome for outcome in outcomes if outcome.get("status") == "completed"]
    item["completed_outcome_count"] = len(completed_outcomes)
    if completed_outcomes:
        preferred = sorted(completed_outcomes, key=lambda outcome: int(outcome.get("horizon_days") or 0))[0]
        item["outcome_horizon_days"] = preferred.get("horizon_days")
        item["raw_return"] = preferred.get("raw_return")
        item["benchmark_return"] = preferred.get("benchmark_return")
        item["alpha_return"] = preferred.get("alpha_return")
    return item


def _analysis_bundle_summary(
    *,
    reports: list[dict[str, Any]],
    decision: dict[str, Any] | None,
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    completed_outcomes = [outcome for outcome in outcomes if outcome.get("status") == "completed"]
    alpha_values = [float(outcome["alpha_return"]) for outcome in completed_outcomes if outcome.get("alpha_return") is not None]
    return {
        "report_count": len(reports),
        "report_roles": [str(report.get("role") or "agent") for report in reports],
        "has_decision": decision is not None,
        "decision_rating": decision.get("rating") if decision else None,
        "decision_action": decision.get("action") if decision else None,
        "outcome_count": len(outcomes),
        "completed_outcome_count": len(completed_outcomes),
        "average_alpha_return": (sum(alpha_values) / len(alpha_values)) if alpha_values else None,
    }


def _analysis_request_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    ticker_codes = set()
    latest_updated_at = None
    for row in rows:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        ticker = row.get("ticker_code")
        if ticker:
            ticker_codes.add(str(ticker))
        updated_at = row.get("updated_at") or row.get("created_at")
        if updated_at is not None and (latest_updated_at is None or str(updated_at) > str(latest_updated_at)):
            latest_updated_at = updated_at
    return {
        "status_counts": status_counts,
        "active_count": status_counts.get("queued", 0) + status_counts.get("running", 0),
        "failed_count": status_counts.get("failed", 0),
        "completed_count": status_counts.get("completed", 0),
        "unique_ticker_count": len(ticker_codes),
        "latest_updated_at": latest_updated_at,
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


def _analysis_request_limits(*, active_limit: int | None, daily_limit: int | None) -> dict[str, int]:
    active = active_limit if active_limit is not None else _positive_int_env(
        ANALYSIS_REQUEST_ACTIVE_LIMIT_ENV,
        DEFAULT_ANALYSIS_REQUEST_ACTIVE_LIMIT,
    )
    daily = daily_limit if daily_limit is not None else _positive_int_env(
        ANALYSIS_REQUEST_DAILY_LIMIT_ENV,
        DEFAULT_ANALYSIS_REQUEST_DAILY_LIMIT,
    )
    if active <= 0:
        raise ValueError("active_limit must be positive")
    if daily <= 0:
        raise ValueError("daily_limit must be positive")
    return {"active_limit": active, "daily_limit": daily}


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _analysis_request_window_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) - timedelta(hours=ANALYSIS_REQUEST_WINDOW_HOURS)

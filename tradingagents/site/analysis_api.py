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


def _trade_date(value: str | None) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.now(ZoneInfo("Asia/Seoul")).date()

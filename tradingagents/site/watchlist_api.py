"""Payload builders for member watchlists."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from tradingagents.storage import StorageRepository

from .portfolio_api import _normalize_price_map
from .public_api import _json_ready


WATCHLIST_NOTICE = "Watchlists are user-entered lists and do not imply a TradingAgents recommendation."


def build_watchlist_payload(
    repo: StorageRepository,
    watchlist_id: str,
    *,
    current_prices: Mapping[str, Decimal | float | int | str] | None = None,
) -> dict[str, Any]:
    """Build a JSON-ready watchlist payload."""

    watchlist = repo.get_watchlist(watchlist_id)
    if watchlist is None:
        raise ValueError("watchlist not found")

    prices = _normalize_price_map(current_prices or {})
    items = []
    for item in repo.watchlist_items(watchlist_id):
        ticker_code = str(item["ticker_code"]).upper()
        current_price = prices.get(ticker_code)
        items.append(
            {
                "ticker_code": ticker_code,
                "ticker_name": item["ticker_name"],
                "market": item["market"],
                "memo": item["memo"],
                "has_memo": bool(item["memo"]),
                "current_price": current_price,
                "public_stock_path": f"/stocks/{ticker_code}",
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
        )

    priced_count = sum(1 for item in items if item["current_price"] is not None)
    return _json_ready(
        {
            "watchlist": watchlist,
            "items": items,
            "item_count": len(items),
            "priced_item_count": priced_count,
            "pricing_status": _pricing_status(len(items), priced_count),
            "summary": {
                "memo_item_count": sum(1 for item in items if item["has_memo"]),
                "unpriced_item_count": len(items) - priced_count,
            },
            "notices": [WATCHLIST_NOTICE],
        }
    )


def build_watchlist_list_payload(
    repo: StorageRepository,
    *,
    user_id: str,
    limit: int = 20,
    max_limit: int = 50,
) -> dict[str, Any]:
    """Build a member-owned watchlist list payload."""

    if max_limit <= 0:
        raise ValueError("max_limit must be positive")
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > max_limit:
        raise ValueError(f"limit cannot exceed {max_limit}")
    rows = repo.list_watchlists(user_id=user_id, limit=limit)
    return _json_ready(
        {
            "status": "available",
            "limit": limit,
            "items": rows,
            "item_count": len(rows),
            "notices": [WATCHLIST_NOTICE],
        }
    )


def _pricing_status(item_count: int, priced_count: int) -> str:
    if item_count == 0:
        return "empty"
    if priced_count == 0:
        return "missing"
    if priced_count == item_count:
        return "complete"
    return "partial"

"""Ticker search payload builders for public/member UI surfaces."""

from __future__ import annotations

from typing import Any

from tradingagents.dataflows.kr_tickers import search_kr_tickers


def build_ticker_search_payload(
    query: str,
    *,
    limit: int = 10,
    lookup_pykrx: bool = True,
) -> dict[str, Any]:
    """Return API-ready Korean ticker search results."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > 50:
        raise ValueError("limit cannot exceed 50")

    results = search_kr_tickers(query, limit=limit, lookup_pykrx=lookup_pykrx)
    return {
        "status": "available",
        "query": query.strip(),
        "limit": limit,
        "item_count": len(results),
        "items": [
            {
                "code": item.code,
                "name": item.name,
                "market": item.market,
                "currency": "KRW",
                "yfinance_symbol": item.yfinance_symbol,
                "benchmark_symbol": item.benchmark_symbol,
            }
            for item in results
        ],
    }

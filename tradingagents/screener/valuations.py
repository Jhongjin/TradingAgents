"""PER, PBR and dividend yield, which the market-cap ranking does not carry.

The ranking that builds the universe gives price, volume and market cap but no
valuation ratios, so the screener's PER and PBR limits had nothing to compare
against and quietly passed everything. Naver publishes the ratios per stock,
one cheap request each, so they are collected for the whole universe on a
schedule and handed to the screener as a lookup.

Nothing here decides anything. It fetches numbers and says which ones it got.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Mapping

from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

STOCK_INTEGRATION_URL = "https://m.stock.naver.com/api/stock/{code}/integration"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TradingAgents screener)", "Accept": "application/json"}
_WANTED = {"per": "per", "pbr": "pbr", "dividendYieldRatio": "dividend_yield"}

Fetcher = Callable[[str], Mapping[str, Any]]


def _number(value: Any) -> float | None:
    """'11.25배' and '0.67%' and '-' all arrive as strings."""

    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def parse_valuation(body: Mapping[str, Any]) -> dict[str, float]:
    """Pull the ratios out of one stock's integration payload."""

    found: dict[str, float] = {}
    for row in (body or {}).get("totalInfos") or []:
        code = str((row or {}).get("code") or "")
        field = _WANTED.get(code)
        if not field:
            continue
        number = _number((row or {}).get("value"))
        if number is not None:
            found[field] = number
    return found


def _fetch_one(code: str) -> Mapping[str, Any]:
    import requests

    apply_system_truststore_if_available()
    response = requests.get(STOCK_INTEGRATION_URL.format(code=code), headers=_HEADERS, timeout=12)
    response.raise_for_status()
    return response.json()


def fetch_valuations(
    codes: list[str] | tuple[str, ...],
    *,
    fetcher: Fetcher | None = None,
    max_workers: int = 8,
) -> dict[str, dict[str, float]]:
    """Ratios for each code that answered. A code that fails is simply absent.

    An absent code is not an error: the screener treats a missing ratio as
    "this filter has nothing to say about this row", which is what it already
    does and is honest about.
    """

    wanted = [str(code).strip() for code in codes if str(code).strip()]
    if not wanted:
        return {}
    fetch = fetcher or _fetch_one

    def one(code: str) -> tuple[str, dict[str, float]]:
        try:
            return code, parse_valuation(fetch(code))
        except Exception:                               # noqa: BLE001 - a miss is a miss
            return code, {}

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(wanted)))) as pool:
        results = list(pool.map(one, wanted))
    return {code: ratios for code, ratios in results if ratios}


__all__ = ["CACHE_KEY", "fetch_valuations", "parse_valuation"]

CACHE_KEY = "valuations"

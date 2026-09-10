"""Filter the daily picks down to what a member actually wants to see.

Everyone gets the same selection run; not everyone wants the same rows out of
it. A member who only trades KOSPI large caps, or who cannot put 1,850,000원
into one share, is reading past most of the list. This stores a handful of
display preferences and applies them to the picks the member is allowed to see.

It filters. It never adds a pick, never reorders by anything but the run's own
rank, and never changes what the harness decided.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

DEFAULTS: dict[str, Any] = {
    "markets": ["KOSPI", "KOSDAQ"],
    "exclude_etf": True,
    "min_rating": "any",
    "max_price": None,
    "excluded_tickers": [],
    "excluded_sectors": [],
}

RATING_ORDER = {"strong sell": 0, "sell": 1, "underweight": 2, "reduce": 2, "hold": 3, "neutral": 3, "accumulate": 4, "overweight": 4, "buy": 5, "strong buy": 6}
MIN_RATING_CHOICES = {"any": None, "overweight": 4, "buy": 5}
ETF_HINTS = ("ETF", "ETN", "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "SOL ", "PLUS ", "ACE ", "RISE ")


def normalize(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Coerce whatever was sent or stored into a safe preference set."""

    source = dict(payload or {})
    markets = [str(item).strip().upper() for item in (source.get("markets") or DEFAULTS["markets"]) if str(item).strip()]
    markets = [item for item in markets if item in {"KOSPI", "KOSDAQ"}] or list(DEFAULTS["markets"])

    min_rating = str(source.get("min_rating") or "any").strip().lower()
    if min_rating not in MIN_RATING_CHOICES:
        min_rating = "any"

    max_price = source.get("max_price")
    try:
        max_price = float(max_price) if max_price not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        max_price = None
    if max_price is not None and max_price <= 0:
        max_price = None

    excluded = []
    for item in source.get("excluded_tickers") or []:
        code = "".join(character for character in str(item) if character.isdigit())
        if len(code) == 6 and code not in excluded:
            excluded.append(code)

    sectors = []
    for item in source.get("excluded_sectors") or []:
        text = " ".join(str(item).split())
        if text and text not in sectors:
            sectors.append(text)

    return {
        "markets": markets,
        "exclude_etf": bool(source.get("exclude_etf", DEFAULTS["exclude_etf"])),
        "min_rating": min_rating,
        "max_price": max_price,
        "excluded_tickers": excluded[:50],
        "excluded_sectors": sectors[:20],
    }


def _sector_of(code: str) -> str:
    try:
        from tradingagents.dataflows.kr_ticker_directory import sector_of

        return sector_of(code)
    except Exception:
        return ""


def _looks_like_etf(name: str) -> bool:
    upper = str(name or "").upper()
    return any(hint in upper for hint in ETF_HINTS)


def _price_of(pick: Mapping[str, Any]) -> float | None:
    for key in ("entry_price", "current_price"):
        value = pick.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value if not isinstance(value, Decimal) else value)
        except (TypeError, ValueError):
            continue
    return None


def filter_picks(picks: list[Mapping[str, Any]] | None, preferences: Mapping[str, Any] | None) -> dict[str, Any]:
    """Split the picks into what the member wants and why the rest were dropped."""

    prefs = normalize(preferences)
    kept: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}
    floor = MIN_RATING_CHOICES.get(prefs["min_rating"])

    for pick in picks or []:
        row = dict(pick)
        code = str(row.get("ticker_code") or "")
        name = str(row.get("ticker_name") or "")
        market = str(row.get("market") or "").upper()
        reason = None

        sector = str(row.get("sector") or "") or _sector_of(code)
        if sector:
            row.setdefault("sector", sector)
        if code and code in prefs["excluded_tickers"]:
            reason = "excluded"
        elif sector and sector in prefs["excluded_sectors"]:
            reason = "sector"
        elif market in {"KOSPI", "KOSDAQ"} and market not in prefs["markets"]:
            reason = "market"
        elif prefs["exclude_etf"] and _looks_like_etf(name):
            reason = "etf"
        elif floor is not None:
            rank = RATING_ORDER.get(str(row.get("confirmation_rating") or "").strip().lower())
            if rank is None or rank < floor:
                reason = "rating"
        if reason is None and prefs["max_price"] is not None:
            price = _price_of(row)
            if price is not None and price > prefs["max_price"]:
                reason = "price"

        if reason is None:
            kept.append(row)
        else:
            dropped[reason] = dropped.get(reason, 0) + 1

    labels = {
        "excluded": "제외 종목",
        "sector": "제외 업종",
        "market": "시장 조건",
        "etf": "ETF 제외",
        "rating": "등급 기준",
        "price": "가격 상한",
    }
    return {
        "preferences": prefs,
        "items": kept,
        "kept_count": len(kept),
        "total_count": len(picks or []),
        "dropped": [{"reason": key, "label": labels.get(key, key), "count": value} for key, value in sorted(dropped.items())],
        "dropped_count": sum(dropped.values()),
    }

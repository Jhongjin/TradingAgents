"""Korean market ticker normalization and resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .errors import VendorUnavailableError

_KR_CODE_RE = re.compile(r"^\d{6}$")
_KR_YFINANCE_RE = re.compile(r"^(?P<code>\d{6})\.(?P<suffix>KS|KQ)$", re.IGNORECASE)

_SUFFIX_TO_MARKET = {
    "KS": "KOSPI",
    "KQ": "KOSDAQ",
}

_MARKET_TO_SUFFIX = {
    "KOSPI": "KS",
    "KOSDAQ": "KQ",
}

_BENCHMARK_BY_MARKET = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "KONEX": "^KS11",
    "UNKNOWN": "^KS11",
}

# A tiny built-in seed keeps prompts and smoke tests useful without a network
# lookup. The resolver still tries pykrx for arbitrary Korean tickers.
_COMMON_TICKERS = {
    "005930": ("삼성전자", "KOSPI"),
    "000660": ("SK하이닉스", "KOSPI"),
    "035420": ("NAVER", "KOSPI"),
    "373220": ("LG에너지솔루션", "KOSPI"),
    "086520": ("에코프로", "KOSDAQ"),
}


@dataclass(frozen=True)
class KoreanTicker:
    code: str
    name: str
    market: str

    @property
    def yfinance_symbol(self) -> str:
        suffix = _MARKET_TO_SUFFIX.get(self.market, "KS")
        return f"{self.code}.{suffix}"

    @property
    def benchmark_symbol(self) -> str:
        return _BENCHMARK_BY_MARKET.get(self.market, "^KS11")


def normalize_kr_ticker(value: str) -> str:
    """Return a 6-digit Korean stock code from local or yfinance-style input."""

    raw = value.strip().upper()
    matched = _KR_YFINANCE_RE.fullmatch(raw)
    if matched:
        return matched.group("code")
    if _KR_CODE_RE.fullmatch(raw):
        return raw
    raise ValueError(f"Not a Korean stock ticker: {value!r}")


def is_kr_ticker(value: str) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.strip().upper()
    return bool(_KR_CODE_RE.fullmatch(raw) or _KR_YFINANCE_RE.fullmatch(raw))


def infer_market_from_suffix(value: str) -> Optional[str]:
    matched = _KR_YFINANCE_RE.fullmatch(value.strip().upper())
    if not matched:
        return None
    return _SUFFIX_TO_MARKET[matched.group("suffix").upper()]


def resolve_kr_ticker(
    value: str,
    *,
    market: str | None = None,
    lookup_pykrx: bool = True,
) -> KoreanTicker:
    """Resolve a Korean stock code to name and market.

    The function is deterministic for common tickers and resilient elsewhere:
    when pykrx is unavailable it still returns the code with an UNKNOWN market
    unless the input is not a Korean ticker at all.
    """

    code = normalize_kr_ticker(value)
    market = (market or infer_market_from_suffix(value) or "").upper() or None

    if code in _COMMON_TICKERS:
        name, common_market = _COMMON_TICKERS[code]
        return KoreanTicker(code=code, name=name, market=market or common_market)

    if lookup_pykrx:
        resolved = _resolve_with_pykrx(code, market)
        if resolved:
            return resolved

    return KoreanTicker(code=code, name=code, market=market or "UNKNOWN")


def to_yfinance_symbol(value: str) -> str:
    resolved = resolve_kr_ticker(value, lookup_pykrx=False)
    return resolved.yfinance_symbol


def benchmark_for_kr_ticker(value: str) -> str:
    resolved = resolve_kr_ticker(value, lookup_pykrx=False)
    return resolved.benchmark_symbol


def common_kr_tickers() -> tuple[KoreanTicker, ...]:
    """Return built-in Korean ticker seeds used for offline lookup/search."""

    return tuple(
        KoreanTicker(code=code, name=name, market=market)
        for code, (name, market) in sorted(_COMMON_TICKERS.items())
    )


def search_kr_tickers(
    query: str,
    *,
    limit: int = 10,
    lookup_pykrx: bool = True,
) -> list[KoreanTicker]:
    """Search Korean tickers by 6-digit code prefix or company name substring."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    normalized_query = query.strip()
    if not normalized_query:
        return []

    query_upper = normalized_query.upper()
    matches: list[KoreanTicker] = []
    seen: set[str] = set()

    def add(candidate: KoreanTicker) -> None:
        if candidate.code in seen or len(matches) >= limit:
            return
        seen.add(candidate.code)
        matches.append(candidate)

    for candidate in common_kr_tickers():
        if candidate.code.startswith(query_upper) or normalized_query.casefold() in candidate.name.casefold():
            add(candidate)

    if lookup_pykrx and len(matches) < limit:
        for candidate in _search_with_pykrx(normalized_query, limit - len(matches)):
            add(candidate)

    return matches


def require_kr_ticker(value: str) -> KoreanTicker:
    if not is_kr_ticker(value):
        raise VendorUnavailableError(f"{value!r} is not a Korean stock ticker")
    return resolve_kr_ticker(value)


def _resolve_with_pykrx(code: str, preferred_market: str | None) -> KoreanTicker | None:
    try:
        from pykrx import stock
    except Exception:
        return None


def _search_with_pykrx(query: str, remaining: int) -> list[KoreanTicker]:
    try:
        from pykrx import stock
    except Exception:
        return []

    matches: list[KoreanTicker] = []
    query_upper = query.upper()
    for market in ("KOSPI", "KOSDAQ", "KONEX"):
        try:
            codes = stock.get_market_ticker_list(market=market)
        except Exception:
            continue
        for code in codes:
            if len(matches) >= remaining:
                return matches
            try:
                name = stock.get_market_ticker_name(code) or code
            except Exception:
                name = code
            if code.startswith(query_upper) or query.casefold() in name.casefold():
                matches.append(KoreanTicker(code=code, name=name, market=market))
    return matches

    try:
        name = stock.get_market_ticker_name(code) or code
        if preferred_market:
            return KoreanTicker(code=code, name=name, market=preferred_market)
        for market in ("KOSPI", "KOSDAQ", "KONEX"):
            try:
                if code in set(stock.get_market_ticker_list(market=market)):
                    return KoreanTicker(code=code, name=name, market=market)
            except Exception:
                continue
        return KoreanTicker(code=code, name=name, market="UNKNOWN")
    except Exception:
        return None

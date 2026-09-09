"""Whole-market snapshot loaders for the Korean screener.

pykrx exposes per-date, whole-market frames (``get_market_ohlcv_by_ticker``,
``get_market_cap_by_ticker``, ``get_market_fundamental_by_ticker``). Loading a
handful of those is far cheaper than fetching a long history for every ticker,
so the screener first builds a snapshot universe, then fetches history only
for the names that pass the liquidity and valuation pre-filters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
import os
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.http_trust import apply_system_truststore_if_available


SUPPORTED_MARKETS = ("KOSPI", "KOSDAQ")


@dataclass(frozen=True)
class MarketSnapshotRow:
    code: str
    name: str
    market: str
    close: float
    volume: float
    trading_value: float | None
    market_cap: float | None
    change_rate: float | None
    per: float | None = None
    pbr: float | None = None
    dividend_yield: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketSnapshot:
    as_of_date: str
    markets: tuple[str, ...]
    rows: list[MarketSnapshotRow] = field(default_factory=list)
    vendor: str = "pykrx"

    def by_code(self) -> dict[str, MarketSnapshotRow]:
        return {row.code: row for row in self.rows}


SnapshotFetcher = Callable[[str, str], pd.DataFrame]


def load_market_snapshot(
    as_of_date: str | date | None = None,
    *,
    markets: tuple[str, ...] | list[str] = SUPPORTED_MARKETS,
    ohlcv_fetcher: SnapshotFetcher | None = None,
    cap_fetcher: SnapshotFetcher | None = None,
    fundamental_fetcher: SnapshotFetcher | None = None,
    name_lookup: Callable[[str], str] | None = None,
    lookback_business_days: int = 7,
) -> MarketSnapshot:
    """Load a one-day whole-market snapshot for the requested markets.

    Fetchers are injectable so tests and offline runs can supply frames without
    pykrx. When the requested date has no rows (holiday), the loader walks back
    up to ``lookback_business_days`` calendar days.
    """

    selected = tuple(_normalize_market(market) for market in markets)
    target = _coerce_date(as_of_date)
    ohlcv_fetcher = ohlcv_fetcher or _pykrx_ohlcv_by_ticker
    cap_fetcher = cap_fetcher or _pykrx_cap_by_ticker
    fundamental_fetcher = fundamental_fetcher or _pykrx_fundamental_by_ticker
    name_lookup = name_lookup or _pykrx_ticker_name

    rows: list[MarketSnapshotRow] = []
    resolved_date: str | None = None
    errors: list[str] = []
    for offset in range(lookback_business_days + 1):
        probe = target - timedelta(days=offset)
        compact = probe.strftime("%Y%m%d")
        collected: list[MarketSnapshotRow] = []
        for market in selected:
            ohlcv = _safe_frame(ohlcv_fetcher, compact, market, errors)
            if ohlcv is None or ohlcv.empty:
                continue
            caps = _safe_frame(cap_fetcher, compact, market, errors)
            fundamentals = _safe_frame(fundamental_fetcher, compact, market, errors)
            collected.extend(_rows_from_frames(ohlcv, caps, fundamentals, market=market, name_lookup=name_lookup))
        if collected:
            rows = collected
            resolved_date = probe.isoformat()
            break

    if resolved_date is None:
        detail = f" Last vendor error: {errors[-1]}" if errors else ""
        raise VendorUnavailableError(
            f"No Korean market snapshot rows found for {target.isoformat()} within {lookback_business_days} days.{detail}"
        )
    return MarketSnapshot(as_of_date=resolved_date, markets=selected, rows=rows)


def fallback_universe_codes() -> tuple[str, ...]:
    """Bounded ticker universe used when whole-market pykrx frames are blocked.

    Order of precedence: ``TRADINGAGENTS_SCREENER_UNIVERSE`` (CSV of 6-digit
    codes), then ``TRADINGAGENTS_SITEMAP_TICKERS``, then the built-in seed
    tickers. Per-ticker daily history (Naver-backed in pykrx) keeps working on
    networks where ``data.krx.co.kr`` whole-market queries fail.
    """

    from tradingagents.dataflows.kr_tickers import common_kr_tickers, is_kr_ticker, normalize_kr_ticker

    for env_name in ("TRADINGAGENTS_SCREENER_UNIVERSE", "TRADINGAGENTS_SITEMAP_TICKERS"):
        raw = os.getenv(env_name, "")
        codes = [normalize_kr_ticker(part.strip()) for part in raw.split(",") if part.strip() and is_kr_ticker(part.strip())]
        if codes:
            return tuple(dict.fromkeys(codes))
    return tuple(ticker.code for ticker in common_kr_tickers())


def build_snapshot_from_history(
    codes: Sequence[str],
    as_of_date: str | date | None,
    history_fetcher: Callable[[str, str, str], Sequence[Mapping[str, Any]]],
    *,
    markets: tuple[str, ...] | list[str] = SUPPORTED_MARKETS,
    lookback_days: int = 30,
) -> MarketSnapshot:
    """Build a snapshot from the latest per-ticker history point (no market cap/PER)."""

    from tradingagents.dataflows.kr_tickers import resolve_kr_ticker

    selected = tuple(_normalize_market(market) for market in markets)
    end = _coerce_date(as_of_date)
    start = end - timedelta(days=lookback_days)
    rows: list[MarketSnapshotRow] = []
    latest_date: str | None = None
    for code in codes:
        try:
            points = list(history_fetcher(code, start.isoformat(), end.isoformat()))
        except Exception:
            continue
        points = [point for point in points if point.get("close") is not None and float(point["close"]) > 0]
        if not points:
            continue
        last = points[-1]
        resolved = resolve_kr_ticker(code, lookup_pykrx=False)
        market = resolved.market if resolved.market in selected else ("UNKNOWN" if resolved.market == "UNKNOWN" else None)
        if market is None:
            continue
        close = float(last["close"])
        volume = float(last.get("volume") or 0.0)
        value = last.get("value")
        rows.append(
            MarketSnapshotRow(
                code=resolved.code,
                name=resolved.name,
                market=market if market != "UNKNOWN" else selected[0],
                close=close,
                volume=volume,
                trading_value=float(value) if value is not None else (close * volume if volume else None),
                market_cap=None,
                change_rate=_float(last.get("change_rate")),
            )
        )
        point_date = str(last.get("date") or "")[:10]
        if point_date and (latest_date is None or point_date > latest_date):
            latest_date = point_date
    if not rows:
        raise VendorUnavailableError("fallback universe produced no rows; check TRADINGAGENTS_SCREENER_UNIVERSE")
    return MarketSnapshot(as_of_date=latest_date or end.isoformat(), markets=selected, rows=rows, vendor="history_fallback")


def _rows_from_frames(
    ohlcv: pd.DataFrame,
    caps: pd.DataFrame | None,
    fundamentals: pd.DataFrame | None,
    *,
    market: str,
    name_lookup: Callable[[str], str],
) -> list[MarketSnapshotRow]:
    ohlcv = _rename(ohlcv)
    caps = _rename(caps) if caps is not None else None
    fundamentals = _rename(fundamentals) if fundamentals is not None else None
    rows: list[MarketSnapshotRow] = []
    for code, row in ohlcv.iterrows():
        code = str(code).zfill(6)
        close = _float(row.get("Close"))
        if close is None or close <= 0:
            continue
        cap_row = caps.loc[code] if caps is not None and code in caps.index else None
        fund_row = fundamentals.loc[code] if fundamentals is not None and code in fundamentals.index else None
        name = str(row.get("Name") or "").strip()
        if not name:
            name = name_lookup(code) or code
        rows.append(
            MarketSnapshotRow(
                code=code,
                name=name,
                market=market,
                close=close,
                volume=_float(row.get("Volume")) or 0.0,
                trading_value=_float(row.get("Value")),
                market_cap=_float(cap_row.get("MarketCap")) if cap_row is not None else None,
                change_rate=_float(row.get("ChangeRate")),
                per=_float(fund_row.get("PER")) if fund_row is not None else None,
                pbr=_float(fund_row.get("PBR")) if fund_row is not None else None,
                dividend_yield=_float(fund_row.get("DIV")) if fund_row is not None else None,
            )
        )
    return rows


_COLUMN_ALIASES: Mapping[str, str] = {
    "시가": "Open",
    "고가": "High",
    "저가": "Low",
    "종가": "Close",
    "거래량": "Volume",
    "거래대금": "Value",
    "등락률": "ChangeRate",
    "시가총액": "MarketCap",
    "상장주식수": "ListedShares",
    "종목명": "Name",
}


def _rename(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = frame.rename(columns={key: value for key, value in _COLUMN_ALIASES.items() if key in frame.columns})
    renamed.index = [str(index).zfill(6) for index in renamed.index]
    return renamed


def _safe_frame(
    fetcher: SnapshotFetcher,
    compact_date: str,
    market: str,
    errors: list[str] | None = None,
) -> pd.DataFrame | None:
    try:
        frame = fetcher(compact_date, market)
    except Exception as exc:
        if errors is not None:
            errors.append(f"{exc.__class__.__name__}: {str(exc)[:200]}")
        return None
    if not isinstance(frame, pd.DataFrame):
        return None
    return frame


def _pykrx_ohlcv_by_ticker(compact_date: str, market: str) -> pd.DataFrame:
    stock = _pykrx_stock()
    return stock.get_market_ohlcv_by_ticker(compact_date, market=market)


def _pykrx_cap_by_ticker(compact_date: str, market: str) -> pd.DataFrame:
    stock = _pykrx_stock()
    return stock.get_market_cap_by_ticker(compact_date, market=market)


def _pykrx_fundamental_by_ticker(compact_date: str, market: str) -> pd.DataFrame:
    stock = _pykrx_stock()
    return stock.get_market_fundamental_by_ticker(compact_date, market=market)


def _pykrx_ticker_name(code: str) -> str:
    try:
        stock = _pykrx_stock()
        return str(stock.get_market_ticker_name(code) or code)
    except Exception:
        return code


def _pykrx_stock():
    # Whole-market frames hit data.krx.co.kr directly; on corporate Windows
    # networks that host is often behind TLS interception, so honour the same
    # OS-truststore opt-in the KRX Open API vendor uses.
    apply_system_truststore_if_available()
    try:
        from pykrx import stock
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise VendorUnavailableError("pykrx is not installed") from exc
    return stock


def _normalize_market(market: str) -> str:
    normalized = market.strip().upper()
    if normalized not in SUPPORTED_MARKETS:
        raise ValueError(f"Unsupported screener market: {market!r}. Choose from {SUPPORTED_MARKETS}")
    return normalized


def _coerce_date(value: str | date | None) -> date:
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    return parsed


# --------------------------------------------------------------------------
# Naver Finance market-cap ranking (시가총액 상위) as a snapshot vendor.
#
# ``https://finance.naver.com/sise/sise_market_sum.naver?sosok={0|1}&page=N``
# lists 50 names per page sorted by market cap with 현재가, 등락률, 시가총액
# (억원), 거래량, PER. Three pages per market therefore approximate the
# KOSPI200/KOSDAQ150 universe with six cheap HTTP requests, and it works from
# serverless hosts and corporate networks where data.krx.co.kr is blocked.
# --------------------------------------------------------------------------

NAVER_MARKET_SUM_URL = "https://finance.naver.com/sise/sise_market_sum.naver"
_NAVER_SOSOK = {"KOSPI": 0, "KOSDAQ": 1}
_NAVER_PAGE_SIZE = 50
_NAVER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TradingAgents screener)"}

PageFetcher = Callable[[str, int], str]


def load_naver_market_snapshot(
    as_of_date: str | date | None = None,
    *,
    markets: tuple[str, ...] | list[str] = SUPPORTED_MARKETS,
    max_rows_per_market: int = 150,
    page_fetcher: PageFetcher | None = None,
) -> MarketSnapshot:
    """Snapshot of the top-``max_rows_per_market`` names per market by market cap.

    ``page_fetcher(market, page) -> html`` is injectable for tests. The
    snapshot date is the requested date (or today, KST); Naver shows live or
    last-close prices, so the screener's daily history is what anchors dates.
    """

    if max_rows_per_market <= 0:
        raise ValueError("max_rows_per_market must be positive")
    selected = tuple(_normalize_market(market) for market in markets)
    fetch = page_fetcher or _fetch_naver_market_sum_page
    rows: list[MarketSnapshotRow] = []
    errors: list[str] = []
    pages = (max_rows_per_market + _NAVER_PAGE_SIZE - 1) // _NAVER_PAGE_SIZE
    for market in selected:
        collected = 0
        for page in range(1, pages + 1):
            try:
                html = fetch(market, page)
            except Exception as exc:
                errors.append(f"{market} page {page}: {exc.__class__.__name__}: {exc}")
                break
            parsed = parse_naver_market_sum(html, market)
            listed = _page_code_count(html)
            if not listed:
                break
            for row in parsed:
                if collected >= max_rows_per_market:
                    break
                rows.append(row)
                collected += 1
            # Stop at the end of the listing (a clearly short page); Naver pages
            # occasionally list 49 rows, so only a half-empty page ends the walk.
            if listed < _NAVER_PAGE_SIZE // 2 or collected >= max_rows_per_market:
                break
    if not rows:
        raise VendorUnavailableError("Naver market-cap ranking returned no rows" + (f" ({'; '.join(errors)[:200]})" if errors else ""))
    resolved = _coerce_date(as_of_date).isoformat()
    return MarketSnapshot(as_of_date=resolved, markets=selected, rows=rows, vendor="naver")


def parse_naver_market_sum(html: str, market: str) -> list[MarketSnapshotRow]:
    """Parse one 시가총액 ranking page into snapshot rows (no external parser needed)."""

    import re

    start = html.find('class="type_2"')
    if start < 0:
        return []
    end = html.find("</table>", start)
    table = html[start : end if end > 0 else None]
    headers = [_strip_tags(cell) for cell in re.findall(r"<th[^>]*>([\s\S]*?)</th>", table)]
    index = {name: position for position, name in enumerate(headers)}
    rows: list[MarketSnapshotRow] = []
    for raw_row in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", table):
        code_match = re.search(r"/item/main\.naver\?code=(\d{6})", raw_row)
        if not code_match:
            continue
        cells = [_strip_tags(cell) for cell in re.findall(r"<td[^>]*>([\s\S]*?)</td>", raw_row)]
        if len(cells) < len(headers) - 1:
            continue

        def cell(name: str) -> str | None:
            position = index.get(name)
            return cells[position] if position is not None and position < len(cells) else None

        close = _naver_number(cell("현재가"))
        if close is None or close <= 0:
            continue
        name = cell("종목명") or code_match.group(1)
        if _is_non_equity_name(name, par_value=_naver_number(cell("액면가"))):
            continue
        volume = _naver_number(cell("거래량")) or 0.0
        market_cap_100m = _naver_number(cell("시가총액"))
        rows.append(
            MarketSnapshotRow(
                code=code_match.group(1),
                name=name,
                market=_normalize_market(market),
                close=close,
                volume=volume,
                trading_value=close * volume if volume else None,
                market_cap=market_cap_100m * 100_000_000 if market_cap_100m is not None else None,
                change_rate=_naver_percent(cell("등락률")),
                per=_naver_number(cell("PER")),
                pbr=_naver_number(cell("PBR")),
                dividend_yield=_naver_number(cell("배당수익률")),
            )
        )
    return rows


_ETF_BRAND_PREFIXES = (
    "KODEX", "TIGER", "ACE ", "KBSTAR", "RISE ", "SOL ", "HANARO", "ARIRANG", "PLUS ", "KOSEF", "TIMEFOLIO",
    "WON ", "1Q ", "BNK ", "DAISHIN", "KIWOOM", "히어로즈", "UNICORN", "마이티", "파워 ", "KINDEX", "TREX", "SMART ",
    "KCTOP", "FOCUS ", "에셋플러스", "VITA ", "ITF ", "TRUE ", "QV ", "신한 ", "삼성 ", "대신 ", "메리츠 ", "미래에셋 ",
    "한투 ", "KB ", "NH ", "하나 ", "키움 ", "유안타 ", "DB ", "현대 ", "SK ",
)


def _is_non_equity_name(name: str, *, par_value: float | None) -> bool:
    """Drop ETFs, ETNs, SPACs, and REIT-style listings from the equity universe.

    ETF/ETN rows on the Naver ranking carry a zero/blank 액면가 and a brand
    prefix; SPACs (기업인수목적) are named ``...스팩``.
    """

    upper = name.upper()
    if "스팩" in name or "인수목적" in name:
        return True
    if any(upper.startswith(prefix.strip().upper() + " ") or upper.startswith(prefix.upper()) for prefix in _ETF_BRAND_PREFIXES if prefix.endswith(" ")) and (par_value is None or par_value <= 0):
        return True
    if any(upper.startswith(prefix.upper()) for prefix in _ETF_BRAND_PREFIXES if not prefix.endswith(" ")):
        return True
    if (par_value is None or par_value <= 0) and any(token in upper for token in ("ETF", "ETN", " 선물", " 레버리지", " 인버스", " 액티브", " 채권", "TOP10", "TOP 10")):
        return True
    return False


def _fetch_naver_market_sum_page(market: str, page: int) -> str:
    import requests

    apply_system_truststore_if_available()
    sosok = _NAVER_SOSOK[_normalize_market(market)]
    response = requests.get(NAVER_MARKET_SUM_URL, params={"sosok": sosok, "page": page}, headers=_NAVER_HEADERS, timeout=15)
    response.raise_for_status()
    response.encoding = "euc-kr"
    return response.text


def _page_code_count(html: str) -> int:
    """Number of distinct stock links on a Naver listing page (before any filtering)."""

    import re

    return len(set(re.findall(r"/item/main\.naver\?code=(\d{6})", html)))


def _strip_tags(value: str) -> str:
    import html as html_module
    import re

    text = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", html_module.unescape(text)).strip()


def _naver_number(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace("%", "").strip()
    if cleaned in {"", "N/A", "-"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _naver_percent(value: str | None) -> float | None:
    number = _naver_number(value)
    return number / 100 if number is not None else None


# --------------------------------------------------------------------------
# Index universes: KOSPI200 (real constituents from Naver) and KOSDAQ150
# (KRX constituents when KRX_ID/KRX_PW are configured for pykrx, otherwise the
# top-150 KOSDAQ names by market cap as a documented proxy).
# --------------------------------------------------------------------------

NAVER_KOSPI200_URL = "https://finance.naver.com/sise/entryJongmok.naver"
_KOSPI200_MAX_PAGES = 25
_KOSDAQ150_PYKRX_INDEX = "2203"
KOSDAQ150_PROXY_SIZE = 150

ConstituentPageFetcher = Callable[[int], str]


def load_index_snapshot(
    as_of_date: str | date | None = None,
    *,
    markets: tuple[str, ...] | list[str] = SUPPORTED_MARKETS,
    kospi200_page_fetcher: ConstituentPageFetcher | None = None,
    market_sum_page_fetcher: PageFetcher | None = None,
    kosdaq150_codes: Sequence[str] | None = None,
    kosdaq_scan_pages: int = 6,
) -> MarketSnapshot:
    """Snapshot over the KOSPI200 + KOSDAQ150 universe.

    * KOSPI200 rows come straight from Naver's constituent pages (price,
      volume, trading value, market cap).
    * KOSDAQ150 codes come from ``kosdaq150_codes`` or pykrx (needs a KRX
      account); the rows themselves come from the Naver market-cap ranking.
      Without a constituent list the top ``KOSDAQ150_PROXY_SIZE`` KOSDAQ names by
      market cap stand in, and the snapshot notes say so.
    """

    selected = tuple(_normalize_market(market) for market in markets)
    rows: list[MarketSnapshotRow] = []
    notes: list[str] = []
    if "KOSPI" in selected:
        kospi_rows = load_kospi200_rows(page_fetcher=kospi200_page_fetcher)
        rows.extend(kospi_rows)
        notes.append(f"KOSPI200 constituents: {len(kospi_rows)}")
    if "KOSDAQ" in selected:
        codes = list(kosdaq150_codes) if kosdaq150_codes is not None else _kosdaq150_codes_from_pykrx()
        ranking = load_naver_market_snapshot(as_of_date, markets=("KOSDAQ",), max_rows_per_market=kosdaq_scan_pages * _NAVER_PAGE_SIZE, page_fetcher=market_sum_page_fetcher).rows
        if codes:
            wanted = set(codes)
            kosdaq_rows = [row for row in ranking if row.code in wanted]
            notes.append(f"KOSDAQ150 constituents: {len(kosdaq_rows)} of {len(wanted)} matched in market-cap ranking")
        else:
            kosdaq_rows = ranking[:KOSDAQ150_PROXY_SIZE]
            notes.append(f"KOSDAQ150 proxy: top {len(kosdaq_rows)} KOSDAQ names by market cap (set KRX_ID/KRX_PW or TRADINGAGENTS_KOSDAQ150_CODES for real constituents)")
        rows.extend(kosdaq_rows)
    if not rows:
        raise VendorUnavailableError("index universe produced no rows")
    return MarketSnapshot(as_of_date=_coerce_date(as_of_date).isoformat(), markets=selected, rows=rows, vendor="index:" + ", ".join(notes))


def load_kospi200_rows(*, page_fetcher: ConstituentPageFetcher | None = None) -> list[MarketSnapshotRow]:
    fetch = page_fetcher or _fetch_naver_kospi200_page
    rows: list[MarketSnapshotRow] = []
    seen: set[str] = set()
    for page in range(1, _KOSPI200_MAX_PAGES + 1):
        try:
            html = fetch(page)
        except Exception as exc:
            if rows:
                break
            raise VendorUnavailableError(f"KOSPI200 constituents unavailable: {exc.__class__.__name__}: {exc}") from exc
        parsed = parse_naver_kospi200_page(html)
        listed = _page_code_count(html)
        new_rows = [row for row in parsed if row.code not in seen]
        if not listed or not new_rows:
            break
        for row in new_rows:
            seen.add(row.code)
            rows.append(row)
        if listed < 5:  # pages carry 10 names; a near-empty page is the tail
            break
    if not rows:
        raise VendorUnavailableError("KOSPI200 constituent pages returned no rows")
    return rows


def parse_naver_kospi200_page(html: str) -> list[MarketSnapshotRow]:
    """Parse one 코스피200 구성종목 page (종목별·현재가·전일비·등락률·거래량·거래대금(백만)·시가총액(억))."""

    import re

    start = html.find('class="type_1"')
    if start < 0:
        return []
    end = html.find("</table>", start)
    table = html[start : end if end > 0 else None]
    headers = [_strip_tags(cell) for cell in re.findall(r"<th[^>]*>([\s\S]*?)</th>", table)]
    index = {name: position for position, name in enumerate(headers)}
    rows: list[MarketSnapshotRow] = []
    for raw_row in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", table):
        code_match = re.search(r"/item/main\.naver\?code=(\d{6})", raw_row)
        if not code_match:
            continue
        cells = [_strip_tags(cell) for cell in re.findall(r"<td[^>]*>([\s\S]*?)</td>", raw_row)]

        def cell(name: str) -> str | None:
            position = index.get(name)
            return cells[position] if position is not None and position < len(cells) else None

        close = _naver_number(cell("현재가"))
        if close is None or close <= 0:
            continue
        volume = _naver_number(cell("거래량")) or 0.0
        value_million = _naver_number(cell("거래대금(백만)"))
        cap_100m = _naver_number(cell("시가총액(억)"))
        rows.append(
            MarketSnapshotRow(
                code=code_match.group(1),
                name=cell("종목별") or code_match.group(1),
                market="KOSPI",
                close=close,
                volume=volume,
                trading_value=value_million * 1_000_000 if value_million is not None else (close * volume if volume else None),
                market_cap=cap_100m * 100_000_000 if cap_100m is not None else None,
                change_rate=_naver_percent(cell("등락률")),
            )
        )
    return rows


def _fetch_naver_kospi200_page(page: int) -> str:
    import requests

    apply_system_truststore_if_available()
    response = requests.get(NAVER_KOSPI200_URL, params={"page": page}, headers=_NAVER_HEADERS, timeout=15)
    response.raise_for_status()
    response.encoding = "euc-kr"
    return response.text


def _kosdaq150_codes_from_pykrx() -> list[str]:
    """KOSDAQ150 constituents via pykrx (KRX data portal; needs KRX_ID/KRX_PW), else env CSV, else empty."""

    from tradingagents.dataflows.kr_tickers import is_kr_ticker, normalize_kr_ticker

    raw = os.getenv("TRADINGAGENTS_KOSDAQ150_CODES", "")
    codes = [normalize_kr_ticker(part.strip()) for part in raw.split(",") if part.strip() and is_kr_ticker(part.strip())]
    if codes:
        return list(dict.fromkeys(codes))
    if not (os.getenv("KRX_ID") and os.getenv("KRX_PW")):
        return []
    try:
        apply_system_truststore_if_available()
        from pykrx import stock

        frame = stock.get_index_portfolio_deposit_file(_KOSDAQ150_PYKRX_INDEX)
        return [str(code).zfill(6) for code in list(frame)]
    except Exception:
        return []

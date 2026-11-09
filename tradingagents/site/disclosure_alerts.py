"""Tell members when a company they follow files a disclosure.

전자공시 is the first place a Korean listing says anything that matters, and it
lands long before the news writes it up. Members already told us which names
they care about, through their journals and watchlists, and the accounts hold
their own. This checks those names for new filings and sends what it finds.

It reports filings. It never trades on them and never changes a position.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from tradingagents.storage import StorageRepository

from .notifications import TelegramClient, TelegramError

KST = ZoneInfo("Asia/Seoul")
ALERT_KEY = "disclosure_alerts"
MAX_TICKERS_PER_MEMBER = 30
MAX_LINES = 8
MAX_KEY_FIGURES = 3

DisclosureFetcher = Callable[[str, int], list[dict[str, Any]]]
BodyFetcher = Callable[[str], str]

# Filings that move a price. Everything else is filed constantly and would turn
# the alert into noise nobody reads.
NOTABLE = (
    "유상증자", "무상증자", "전환사채", "신주인수권", "교환사채", "자기주식",
    "합병", "분할", "영업양수", "영업양도", "주식교환",
    "감사보고서", "의견거절", "한정", "정정",
    "매출액또는손익구조", "실적", "잠정",
    "공급계약", "수주", "특허", "임상",
    "최대주주", "경영권", "상장폐지", "관리종목", "거래정지", "소송", "제재", "횡령", "배임",
    "현금·현물배당", "배당",
)


def _default_fetcher(ticker: str, days: int) -> list[dict[str, Any]]:
    from tradingagents.dataflows.dart import list_recent_disclosures

    return list_recent_disclosures(ticker, days=days)


def _default_body_fetcher(receipt_no: str) -> str:
    from tradingagents.dataflows.dart import get_disclosure_body

    return get_disclosure_body(receipt_no)


def is_notable(report_name: str) -> bool:
    text = str(report_name or "").replace(" ", "")
    return any(keyword in text for keyword in NOTABLE)


def _is_body_worthy(report_name: str) -> bool:
    from tradingagents.dataflows.dart import _is_body_worthy as dart_is_body_worthy

    return dart_is_body_worthy(str(report_name or ""))


# For each body-worthy filing type (tradingagents.dataflows.dart's own
# _BODY_WORTHY_REPORT_KEYWORDS), the row-label keywords that hold the number a
# member actually needs, in priority order. Matched the same way DART's own
# body rows look once flattened by get_disclosure_body: "label | value...".
# Earnings filings (영업(잠정)실적) are handled separately in _earnings_figures
# because the number that matters sits at a fixed column position, not behind
# a distinct label.
_FIGURE_RULES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "전환사채권발행결정": (
        ("권면총액", ("권면",)),
        ("전환가액", ("전환가액",)),
    ),
    "신주인수권부사채권발행결정": (
        ("권면총액", ("권면",)),
        ("행사가액", ("행사가액",)),
    ),
    "교환사채권발행결정": (
        ("권면총액", ("권면",)),
        ("교환가액", ("교환가액",)),
    ),
    "유상증자결정": (
        ("발행주식수", ("신주의 종류와 수", "신주의종류와수")),
        ("발행가액", ("신주 발행가액", "발행가액")),
        ("조달금액", ("운영자금", "시설자금", "영업양수자금", "채무상환자금", "타법인", "기타자금")),
    ),
    "무상증자결정": (
        ("발행주식수", ("신주의 종류와 수", "신주의종류와수")),
    ),
    "자기주식취득결정": (
        ("취득예정주식", ("취득예정주식",)),
        ("취득예정금액", ("취득예정금액",)),
    ),
    "자기주식처분결정": (
        ("처분예정주식", ("처분예정주식",)),
        ("처분예정금액", ("처분예정금액",)),
    ),
}


def _rule_set_for(report_name: str) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
    for keyword, rules in _FIGURE_RULES.items():
        if keyword in report_name:
            return rules
    return None


def _row_value(lines: list[str], keywords: tuple[str, ...]) -> str | None:
    """First "label | value" row whose label carries one of ``keywords`` and
    whose value looks like a short figure rather than a prose paragraph."""

    for keyword in keywords:
        for line in lines:
            if " | " not in line:
                continue
            label, _, rest = line.partition(" | ")
            if keyword not in label:
                continue
            parts = [p.strip() for p in rest.split(" | ") if p.strip()]
            if not parts:
                continue
            value = parts[-1]
            if not value or value == "-" or len(value) > 40:
                continue
            if not any(ch.isdigit() for ch in value):
                continue
            return value
    return None


def _earnings_figures(body: str) -> list[str]:
    """매출액/영업이익, 당기 vs 전년동기, from the standard 영업(잠정)실적 row shape:
    ``label | 당해실적 | 당기 | 전기 | 전기대비% | 흑자전환 | 전년동기 | 전년동기대비% | 흑자전환``.
    """

    figures: list[str] = []
    for label in ("매출액", "영업이익"):
        if len(figures) >= MAX_KEY_FIGURES:
            break
        for line in body.splitlines():
            cells = [c.strip() for c in line.split(" | ")]
            if not cells or cells[0] != label or len(cells) < 7:
                continue
            current = cells[2]
            if not current or current == "-" or not any(ch.isdigit() for ch in current):
                break
            prior_year = cells[6]
            if prior_year and prior_year != "-" and any(ch.isdigit() for ch in prior_year):
                figures.append(f"{label} {current}(전년동기 {prior_year})")
            else:
                figures.append(f"{label} {current}")
            break
    return figures[:MAX_KEY_FIGURES]


def _extract_key_figures(report_name: str, body: str) -> list[str]:
    """Up to ``MAX_KEY_FIGURES`` short "label value" strings pulled from a
    filing body, or an empty list if nothing matches or anything goes wrong.

    Never raises: a body in an unexpected shape should cost the figures, not
    the alert line they were going to decorate.
    """

    try:
        if "영업" in report_name and "실적" in report_name:
            return _earnings_figures(body)
        rules = _rule_set_for(report_name)
        if not rules:
            return []
        lines = body.splitlines()
        figures: list[str] = []
        for display, keywords in rules:
            if len(figures) >= MAX_KEY_FIGURES:
                break
            value = _row_value(lines, keywords)
            if value:
                figures.append(f"{display} {value}")
        return figures[:MAX_KEY_FIGURES]
    except Exception:
        return []


def _key_figures_for_filing(report_name: str, receipt_no: str, body_fetch: BodyFetcher) -> list[str]:
    """At most one body fetch (``body_fetch`` is cached by receipt_no on the
    DART side), and never raises: any failure here must leave today's alert
    text exactly as it already was."""

    try:
        if not _is_body_worthy(report_name):
            return []
        body = body_fetch(receipt_no)
        return _extract_key_figures(report_name, body)
    except Exception:
        return []


def member_tickers(repo: StorageRepository, user_id: str) -> dict[str, str]:
    """Every ticker this member follows, mapped to a display name."""

    names: dict[str, str] = {}
    try:
        for portfolio in repo.list_manual_portfolios(user_id=user_id, limit=20):
            for trade in repo.manual_trades_for_portfolio(str(portfolio["id"])):
                code = str(trade.get("ticker_code") or "").strip()
                if code:
                    names.setdefault(code, str(trade.get("ticker_name") or code))
    except Exception:
        pass
    try:
        for watchlist in repo.list_watchlists(user_id=user_id, limit=20):
            for item in repo.watchlist_items(str(watchlist["id"])):
                code = str(item.get("ticker_code") or "").strip()
                if code:
                    names.setdefault(code, str(item.get("ticker_name") or code))
    except Exception:
        pass
    return dict(list(names.items())[:MAX_TICKERS_PER_MEMBER])


def notify_disclosure_alerts(
    repo: StorageRepository,
    client: TelegramClient,
    *,
    site_base_url: str | None = None,
    now: datetime | None = None,
    days: int = 2,
    fetcher: DisclosureFetcher | None = None,
    body_fetcher: BodyFetcher | None = None,
) -> dict[str, Any]:
    """Send each member the new filings on the names they follow."""

    now = now or datetime.now(timezone.utc)
    base = (site_base_url or "").rstrip("/")
    fetch = fetcher or _default_fetcher
    fetch_body = body_fetcher or _default_body_fetcher
    recipients = repo.list_notification_recipients("telegram")
    if not recipients:
        return {"status": "no_recipients", "sent": 0}

    cache: dict[str, list[dict[str, Any]]] = {}
    sent = failed = announced = 0
    for recipient in recipients:
        user_id = str(recipient.get("user_id") or "")
        names = member_tickers(repo, user_id)
        if not names:
            continue
        metadata = dict(recipient.get("metadata_json") or {})
        seen = dict(metadata.get(ALERT_KEY) or {})

        lines: list[str] = []
        fresh: dict[str, str] = {}
        for code, name in names.items():
            if code not in cache:
                try:
                    cache[code] = list(fetch(code, days))
                except Exception:
                    cache[code] = []
            for row in cache[code]:
                receipt = str(row.get("receipt_no") or "").strip()
                title = str(row.get("report_name") or "").strip()
                if not receipt or receipt in seen or not is_notable(title):
                    continue
                fresh[receipt] = now.date().isoformat()
                if len(lines) < MAX_LINES:
                    filed = str(row.get("filed_at") or "")
                    figures = _key_figures_for_filing(title, receipt, fetch_body)
                    figure_line = f"\n  {' · '.join(figures)}" if figures else ""
                    lines.append(
                        f"• <b>{name}</b>({code}) {title}{figure_line}"
                        f"\n  {filed} · https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}"
                    )

        if not fresh:
            continue
        more = len(fresh) - len(lines)
        text = (
            "<b>전자공시 알림</b>\n"
            + "\n".join(lines)
            + (f"\n외 {more}건" if more > 0 else "")
            + f"\n\n관심 종목 관리: {base}/mypage\n공시 원문은 금융감독원 전자공시시스템에서 제공합니다. 매매 권유가 아닙니다."
        )
        try:
            client.send_message(str(recipient["external_id"]), text)
            sent += 1
        except TelegramError:
            failed += 1
            continue
        announced += len(fresh)
        seen.update(fresh)
        trimmed = dict(sorted(seen.items(), key=lambda item: item[1])[-400:])
        try:
            repo.update_notification_channel_metadata(str(recipient["id"]), {ALERT_KEY: trimmed})
        except Exception:
            pass

    if not announced and not failed:
        return {"status": "nothing_to_send", "sent": 0, "recipients": len(recipients), "tickers": len(cache)}
    return {"status": "sent", "filings": announced, "recipients": len(recipients), "sent": sent, "failed": failed, "tickers": len(cache)}

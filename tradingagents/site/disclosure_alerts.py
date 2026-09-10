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

DisclosureFetcher = Callable[[str, int], list[dict[str, Any]]]

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


def is_notable(report_name: str) -> bool:
    text = str(report_name or "").replace(" ", "")
    return any(keyword in text for keyword in NOTABLE)


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
) -> dict[str, Any]:
    """Send each member the new filings on the names they follow."""

    now = now or datetime.now(timezone.utc)
    base = (site_base_url or "").rstrip("/")
    fetch = fetcher or _default_fetcher
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
                    lines.append(f"• <b>{name}</b>({code}) {title}\n  {filed} · https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}")

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

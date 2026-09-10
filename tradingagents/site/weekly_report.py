"""A Friday summary of what the accounts did this week.

The daily message says what was picked; nobody reads five of those and keeps a
running total in their head. This closes the week: what each book returned, how
that compares with KOSPI, which positions were closed and why.

Everything here is read from what the accounts already recorded.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from tradingagents.harness.paper_state import ACCOUNTS, build_combined_account_payload
from tradingagents.storage import StorageRepository

from .notifications import TelegramClient, TelegramError

KST = ZoneInfo("Asia/Seoul")
REPORT_KEY = "weekly_report"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.2f}%"
    except (TypeError, ValueError):
        return "-"


def _won(value: Any) -> str:
    try:
        return f"{float(value):,.0f}원"
    except (TypeError, ValueError):
        return "-"


def week_key(when: date) -> str:
    year, week, _day = when.isocalendar()
    return f"{year}-W{week:02d}"


def build_weekly_report(
    repo: StorageRepository | None,
    *,
    now: datetime | None = None,
    site_base_url: str | None = None,
    days: int = 7,
) -> dict[str, Any]:
    """The week's numbers per book, plus the trades that closed."""

    if repo is None:
        return {"status": "not_configured"}
    moment = (now or datetime.now(KST)).astimezone(KST)
    today = moment.date()
    since = today - timedelta(days=max(days, 1))

    books: list[dict[str, Any]] = []
    for key, label in ACCOUNTS:
        try:
            from .paper_snapshot_worker import build_paper_curve_payload

            curve = build_paper_curve_payload(repo, account_key=key)
        except Exception:
            curve = {"points": []}
        points = [point for point in (curve.get("points") or []) if str(point.get("date") or "") >= since.isoformat()]
        if len(points) >= 2:
            start_value = float(points[0].get("equity") or 0.0)
            end_value = float(points[-1].get("equity") or 0.0)
            week_return = (end_value / start_value) - 1 if start_value else None
        else:
            week_return = None
        summary = (curve.get("summary") or {})
        books.append(
            {
                "key": key,
                "label": label,
                "week_return": round(week_return, 6) if week_return is not None else None,
                "total_return": summary.get("account_return"),
                "benchmark_return": summary.get("benchmark_return"),
                "day_count": summary.get("day_count"),
            }
        )

    combined = build_combined_account_payload(repo)
    closed = [row for row in (combined.get("closed") or []) if str(row.get("exit_date") or "") >= since.isoformat()]
    return {
        "status": "available",
        "week": week_key(today),
        "from": since.isoformat(),
        "to": today.isoformat(),
        "books": books,
        "closed": closed,
        "open_count": (combined.get("summary") or {}).get("open_count"),
        "site_base_url": (site_base_url or "").rstrip("/"),
    }


def compose_weekly_message(report: Mapping[str, Any]) -> str:
    base = str(report.get("site_base_url") or "")
    lines = [f"<b>주간 결산 · {report.get('from')} ~ {report.get('to')}</b>"]
    for book in report.get("books") or []:
        week = _pct(book.get("week_return")) if book.get("week_return") is not None else "기록 부족"
        total = _pct(book.get("total_return")) if book.get("total_return") is not None else "-"
        lines.append(f"• {book['label']} 주간 {week} · 누적 {total}")
    benchmark = next((book.get("benchmark_return") for book in report.get("books") or [] if book.get("benchmark_return") is not None), None)
    if benchmark is not None:
        lines.append(f"• KOSPI 누적 {_pct(benchmark)}")

    closed = list(report.get("closed") or [])
    if closed:
        lines.append("")
        lines.append(f"<b>이번 주 정리한 종목 {len(closed)}건</b>")
        for row in closed[:6]:
            from .plain_korean import exit_reason_label

            lines.append(
                f"• {row.get('ticker_name') or row.get('ticker_code')} {exit_reason_label(row.get('exit_reason'))} "
                f"{_pct(row.get('realized_return'))} ({_won(row.get('realized_pnl'))})"
            )
        if len(closed) > 6:
            lines.append(f"외 {len(closed) - 6}건")
    else:
        lines.append("")
        lines.append("이번 주에 규칙으로 정리된 종목은 없습니다.")

    lines.append("")
    lines.append(f"보유 {report.get('open_count') or 0}종목 · 계좌 보기: {base}/paper")
    lines.append("모의투자 기록이며 매매 권유가 아닙니다.")
    return "\n".join(lines)


def notify_weekly_report(
    repo: StorageRepository,
    client: TelegramClient,
    *,
    site_base_url: str | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Send the week's summary to every linked member, once per week."""

    moment = (now or datetime.now(timezone.utc)).astimezone(KST)
    report = build_weekly_report(repo, now=moment, site_base_url=site_base_url)
    if report.get("status") != "available":
        return {"status": report.get("status") or "unavailable", "sent": 0}
    text = compose_weekly_message(report)
    stamp = report["week"]

    recipients = repo.list_notification_recipients("telegram")
    sent = failed = skipped = 0
    for recipient in recipients:
        metadata = dict(recipient.get("metadata_json") or {})
        if not force and metadata.get(REPORT_KEY) == stamp:
            skipped += 1
            continue
        try:
            client.send_message(str(recipient["external_id"]), text)
            sent += 1
        except TelegramError:
            failed += 1
            continue
        try:
            repo.update_notification_channel_metadata(str(recipient["id"]), {REPORT_KEY: stamp})
        except Exception:
            pass
    if not sent and not failed:
        return {"status": "already_sent" if skipped else "no_recipients", "week": stamp, "sent": 0, "skipped": skipped}
    return {"status": "sent", "week": stamp, "recipients": len(recipients), "sent": sent, "failed": failed, "skipped": skipped}

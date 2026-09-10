"""Member journal alerts: target/stop hits on manually recorded positions.

For every member with a linked Telegram channel, load their journals with
current prices and find positions whose price crossed the member's own target
or stop level. Each hit is announced once per (journal, ticker, kind, level);
the "already told" keys live in the channel's ``metadata_json`` so no new table
is needed. The message links to the journal tab and to a prefilled AI check
request that frames the answer as an analysis (청산 근거 비중, 50% 기준), not
an instruction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from urllib.parse import quote

from tradingagents.storage import StorageRepository

from .notifications import TelegramClient, TelegramError
from .portfolio_api import build_manual_portfolio_payload

PriceLoader = Callable[[str], tuple[dict[str, Decimal], dict | None]]

ALERT_KEY = "journal_alerts"
KIND_LABELS = {"target": "목표가 도달", "stop": "손절선 도달"}


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.0f}원"
    except (TypeError, ValueError):
        return "-"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.1f}%"
    except (TypeError, ValueError):
        return "-"


def _level_key(value: Any) -> str:
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except Exception:
        return str(value)


def check_reason(kind: str, position: dict[str, Any]) -> str:
    """Prefilled reason for the AI check request (drives the 50%-based framing)."""

    name = position.get("ticker_name") or position.get("ticker_code")
    level = position.get("target_price") if kind == "target" else position.get("stop_price")
    head = "[목표 점검]" if kind == "target" else "[손절 점검]"
    goal = "수익 실현" if kind == "target" else "손절"
    return (
        f"{head} {name} 현재가 {_money(position.get('current_price'))}, {'목표' if kind == 'target' else '손절'} {_money(level)}, "
        f"평단 {_money(position.get('average_cost'))}, 수익률 {_pct(position.get('unrealized_pnl_rate'))}. "
        f"{goal} 여부를 지시가 아닌 분석 관점으로 점검: 청산 근거 비중을 50% 기준으로 제시"
    )


def check_request_path(kind: str, position: dict[str, Any]) -> str:
    return f"/mypage?tab=analysis&ticker={quote(str(position.get('ticker_code') or ''))}&reason={quote(check_reason(kind, position))}"


def scan_journal_hits(repo: StorageRepository, *, user_id: str, price_loader: PriceLoader) -> list[dict[str, Any]]:
    """Positions in the member's journals whose price crossed their target or stop."""

    hits: list[dict[str, Any]] = []
    for portfolio in repo.list_manual_portfolios(user_id=user_id, limit=50):
        portfolio_id = str(portfolio.get("id") or "")
        if not portfolio_id:
            continue
        try:
            prices, _source = price_loader(portfolio_id)
            payload = build_manual_portfolio_payload(repo, portfolio_id, current_prices=prices)
        except Exception:  # one broken journal must not stop the others
            continue
        for position in payload.get("positions") or []:
            for kind, flag in (("target", "target_hit"), ("stop", "stop_hit")):
                if not position.get(flag):
                    continue
                level = position.get("target_price") if kind == "target" else position.get("stop_price")
                hits.append(
                    {
                        "user_id": user_id,
                        "portfolio_id": portfolio_id,
                        "portfolio_name": portfolio.get("name"),
                        "kind": kind,
                        "key": f"{portfolio_id}:{position.get('ticker_code')}:{kind}:{_level_key(level)}",
                        "position": position,
                    }
                )
    return hits


def notify_journal_alerts(
    repo: StorageRepository,
    client: TelegramClient,
    *,
    site_base_url: str | None = None,
    now: datetime | None = None,
    price_loader: PriceLoader | None = None,
) -> dict[str, Any]:
    """Send each linked member their new target/stop hits (once per level)."""

    now = now or datetime.now(timezone.utc)
    if price_loader is None:
        return {"status": "skipped", "reason": "price loader required", "sent": 0}
    base = (site_base_url or "").rstrip("/")
    recipients = repo.list_notification_recipients("telegram")
    sent = failed = announced = 0
    for recipient in recipients:
        user_id = str(recipient.get("user_id") or "")
        metadata = dict(recipient.get("metadata_json") or {})
        seen = dict(metadata.get(ALERT_KEY) or {})
        hits = [hit for hit in scan_journal_hits(repo, user_id=user_id, price_loader=price_loader) if hit["key"] not in seen]
        if not hits:
            continue
        lines = []
        for hit in hits:
            position = hit["position"]
            label = KIND_LABELS[hit["kind"]]
            level = position.get("target_price") if hit["kind"] == "target" else position.get("stop_price")
            lines.append(
                f"• <b>{position.get('ticker_name') or position.get('ticker_code')}</b>({position.get('ticker_code')}) {label}\n"
                f"  현재가 {_money(position.get('current_price'))} · 기준 {_money(level)} · 평단 {_money(position.get('average_cost'))} · 수익률 {_pct(position.get('unrealized_pnl_rate'))} · {hit['portfolio_name']}\n"
                f"  AI 점검 요청: {base}{check_request_path(hit['kind'], position)}"
            )
        text = "<b>매매 일지 알림</b>\n" + "\n".join(lines) + f"\n\n일지 보기: {base}/mypage?tab=portfolio\n직접 정한 목표·손절 기준에 도달했다는 안내이며 매매 지시가 아닙니다."
        try:
            client.send_message(str(recipient["external_id"]), text)
            sent += 1
        except TelegramError:
            failed += 1
            continue
        announced += len(hits)
        for hit in hits:
            seen[hit["key"]] = now.date().isoformat()
        # keep the memory small: newest 200 keys
        trimmed = dict(sorted(seen.items(), key=lambda item: item[1])[-200:])
        repo.update_notification_channel_metadata(str(recipient["id"]), {ALERT_KEY: trimmed})
    if not announced and not failed:
        return {"status": "nothing_to_send", "sent": 0, "recipients": len(recipients)}
    return {"status": "sent", "hits": announced, "recipients": len(recipients), "sent": sent, "failed": failed}

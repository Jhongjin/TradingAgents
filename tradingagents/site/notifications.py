"""Telegram notifications: member linking, bot webhook, and the daily issue push.

Linking flow: the member asks for a code (``POST /api/notifications/telegram/link``),
opens ``https://t.me/<bot>?start=<code>`` and presses Start. Telegram delivers
``/start <code>`` to our webhook; we bind the chat id to the member. Every
outbound message goes through ``TelegramClient`` whose transport is injectable
so the flow is unit-tested offline (the operator's network blocks Telegram).

Issue push: after a harness run is stored, ``notify_harness_issue`` sends the
issue headline. Paid members receive the picks; free members receive a teaser
that names the counts only, matching the plan gate on the site.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from tradingagents.storage import NotificationChannelInput, StorageRepository

from .billing import PlanAccess, resolve_plan_access
from .harness_api import build_harness_run_payload, build_harness_runs_payload

KST = ZoneInfo("Asia/Seoul")
TELEGRAM_API = "https://api.telegram.org"
LINK_CODE_TTL_MINUTES = 30
Transport = Callable[[str, str, Mapping[str, Any] | None], tuple[int, Mapping[str, Any]]]


@dataclass
class TelegramConfig:
    bot_token: str | None
    bot_username: str | None
    webhook_secret: str | None

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        return cls(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            bot_username=(os.getenv("TELEGRAM_BOT_USERNAME") or "").lstrip("@") or None,
            webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET") or None,
        )

    def is_configured(self) -> bool:
        return bool(self.bot_token)

    def __repr__(self) -> str:
        return f"TelegramConfig(bot_username={self.bot_username!r}, bot_token={'***' if self.bot_token else None!r}, webhook_secret={'***' if self.webhook_secret else None!r})"


class TelegramError(RuntimeError):
    pass


@dataclass
class TelegramClient:
    config: TelegramConfig
    transport: Transport | None = None
    timeout: float = 10.0

    def send_message(self, chat_id: str, text: str, *, disable_preview: bool = True) -> Mapping[str, Any]:
        return self._call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": disable_preview})

    def set_webhook(self, url: str, *, secret_token: str | None) -> Mapping[str, Any]:
        body: dict[str, Any] = {"url": url, "allowed_updates": ["message"]}
        if secret_token:
            body["secret_token"] = secret_token
        return self._call("setWebhook", body)

    def get_me(self) -> Mapping[str, Any]:
        return self._call("getMe", None)

    def get_webhook_info(self) -> Mapping[str, Any]:
        """Delivery diagnostics: pending updates, last error, registered URL."""

        return self._call("getWebhookInfo", None)

    def _call(self, method: str, body: Mapping[str, Any] | None) -> Mapping[str, Any]:
        if not self.config.bot_token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not configured")
        url = f"{TELEGRAM_API}/bot{self.config.bot_token}/{method}"
        transport = self.transport or self._requests_transport
        status, payload = transport("POST", url, body)
        if status >= 400 or not payload.get("ok", False):
            raise TelegramError(f"Telegram {method} failed ({status}): {str(payload.get('description') or payload)[:200]}")
        return payload.get("result") or {}

    def _requests_transport(self, method: str, url: str, body: Mapping[str, Any] | None) -> tuple[int, Mapping[str, Any]]:
        import requests

        from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

        apply_system_truststore_if_available()
        response = requests.request(method, url, json=body, timeout=self.timeout)
        try:
            payload = response.json()
        except ValueError:
            payload = {"ok": False, "description": response.text[:200]}
        return response.status_code, payload


# ---------------------------------------------------------------- linking
def create_link_code(repo: StorageRepository, user_id: str, config: TelegramConfig, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    existing = repo.get_notification_channel(user_id, "telegram") or {}
    code = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")[:12]
    repo.upsert_notification_channel(
        NotificationChannelInput(
            user_id=user_id,
            channel="telegram",
            external_id=existing.get("external_id"),
            display_name=existing.get("display_name"),
            link_code=code,
            link_code_expires_at=now + timedelta(minutes=LINK_CODE_TTL_MINUTES),
            linked_at=existing.get("linked_at"),
            enabled=bool(existing.get("enabled", True)),
            metadata=dict(existing.get("metadata_json") or {}),
        )
    )
    bot = config.bot_username
    return {
        "channel": "telegram",
        "code": code,
        "expires_at": (now + timedelta(minutes=LINK_CODE_TTL_MINUTES)).isoformat(),
        "bot_username": bot,
        "link_url": f"https://t.me/{bot}?start={code}" if bot else None,
        "instructions": f"텔레그램에서 @{bot} 봇을 열고 시작 버튼을 누르거나 '/start {code}'를 보내세요." if bot else "봇 사용자명이 설정되면 연결 링크가 표시됩니다.",
        "linked": bool(existing.get("external_id")),
    }


def unlink_channel(repo: StorageRepository, user_id: str) -> dict[str, Any]:
    existing = repo.get_notification_channel(user_id, "telegram")
    if not existing:
        return {"channel": "telegram", "linked": False}
    repo.upsert_notification_channel(NotificationChannelInput(user_id=user_id, channel="telegram", enabled=False, metadata={"unlinked_at": datetime.now(timezone.utc).isoformat()}))
    return {"channel": "telegram", "linked": False}


def channel_status(repo: StorageRepository, user_id: str) -> dict[str, Any]:
    row = repo.get_notification_channel(user_id, "telegram")
    if not row or not row.get("external_id") or not row.get("enabled"):
        return {"channel": "telegram", "linked": False}
    return {"channel": "telegram", "linked": True, "display_name": row.get("display_name"), "linked_at": _iso(row.get("linked_at"))}


def handle_telegram_update(repo: StorageRepository, update: Mapping[str, Any], client: TelegramClient | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    """Process one Telegram update: ``/start <code>`` links, ``/stop`` unlinks."""

    now = now or datetime.now(timezone.utc)
    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    text = str(message.get("text") or "").strip()
    if not chat_id or not text:
        return {"handled": False, "reason": "no message"}
    parts = text.split()
    command = parts[0].split("@", 1)[0].lower()
    reply: str | None = None
    result: dict[str, Any] = {"handled": True, "command": command}
    if command == "/start":
        code = parts[1] if len(parts) > 1 else ""
        row = repo.find_notification_channel_by_code(code) if code else None
        expires = _aware(row.get("link_code_expires_at")) if row else None
        if not row or (expires and expires < now):
            reply = "연결 코드가 없거나 만료되었습니다. 마이페이지의 알림 설정에서 새 코드를 받아 주세요."
            result["linked"] = False
        else:
            display = " ".join(part for part in (chat.get("first_name"), chat.get("last_name")) if part) or chat.get("username") or None
            repo.upsert_notification_channel(
                NotificationChannelInput(
                    user_id=str(row["user_id"]),
                    channel="telegram",
                    external_id=chat_id,
                    display_name=display,
                    link_code=None,
                    link_code_expires_at=None,
                    linked_at=now,
                    enabled=True,
                    metadata={**dict(row.get("metadata_json") or {}), "telegram_username": chat.get("username")},
                )
            )
            reply = "연결되었습니다. 평일 아침 하네스 호가 발행되면 이 대화로 알려드립니다. 중단하려면 /stop 을 보내세요."
            result["linked"] = True
    elif command == "/stop":
        row = repo.find_notification_channel_by_external_id(chat_id)
        if row:
            repo.upsert_notification_channel(NotificationChannelInput(user_id=str(row["user_id"]), channel="telegram", external_id=chat_id, display_name=row.get("display_name"), linked_at=_aware(row.get("linked_at")), enabled=False, metadata=dict(row.get("metadata_json") or {})))
        reply = "알림을 중단했습니다. 다시 받으려면 마이페이지에서 새 코드로 /start 하세요."
        result["linked"] = False
    else:
        reply = "이 봇은 TradingAgents Korea 하네스 알림 전용입니다. 마이페이지의 연결 코드로 /start 하세요."
        result["handled"] = False
    if client is not None and reply:
        try:
            client.send_message(chat_id, reply)
        except TelegramError as exc:
            result["reply_error"] = str(exc)[:200]
    return result


# ------------------------------------------------------------ issue push
def compose_issue_messages(run_payload: Mapping[str, Any], *, issue_number: int, site_base_url: str | None) -> dict[str, str]:
    run = run_payload.get("run") or {}
    decisions = run_payload.get("decisions") or []
    ordered = [item for item in decisions if item.get("stage") in {"ordered", "exit"}]
    total = len(decisions)
    date_text = str(run.get("as_of_date") or "")
    base = (site_base_url or "").rstrip("/")
    link = f"{base}/harness/{run.get('id')}" if base else f"/harness/{run.get('id')}"
    if ordered:
        names = ", ".join(f"{item.get('ticker_name') or item.get('ticker_code')}({item.get('ticker_code')})" for item in ordered[:5])
        head = f"<b>제 {issue_number}호 · {date_text}</b>\n{total}개 후보 중 {len(ordered)}개 통과: {names}"
    else:
        head = f"<b>제 {issue_number}호 · {date_text}</b>\n{total}개 후보를 살폈지만 통과한 종목이 없습니다."
    lines = []
    for item in ordered[:5]:
        rating = item.get("confirmation_rating") or "-"
        conf = item.get("confirmation_confidence")
        conf_text = f" {float(conf):.2f}" if conf is not None else ""
        qty = item.get("quantity")
        lines.append(f"• {item.get('ticker_name') or item.get('ticker_code')} — {rating}{conf_text}{f' · 가상 {qty}주' if qty else ''}")
    paid = head + ("\n" + "\n".join(lines) if lines else "") + f"\n토론 전문: {link}\n\nAI 분석 자료이며 매매 권유가 아닙니다."
    free = (
        f"<b>제 {issue_number}호 · {date_text}</b>\n{total}개 후보 중 {len(ordered)}개가 통과했습니다. "
        f"종목과 토론 전문은 데일리 패스에서 실행 즉시 열리고, 무료 플랜은 다음 거래일에 공개됩니다.\n{base or ''}/pricing"
    )
    return {"paid": paid, "free": free}


def notify_harness_issue(
    repo: StorageRepository,
    client: TelegramClient,
    *,
    site_base_url: str | None = None,
    now: datetime | None = None,
    harness_run_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Send the newest un-notified public run to every linked member."""

    now = now or datetime.now(timezone.utc)
    runs = build_harness_runs_payload(repo, limit=50)
    items = runs.get("items") or []
    if harness_run_id:
        target = next((item for item in items if item.get("id") == harness_run_id), None)
    else:
        target = items[0] if items else None
    if not target:
        return {"status": "no_run", "sent": 0}
    if (target.get("metadata") or {}).get("notified_at") and not force:
        return {"status": "already_notified", "run_id": target["id"], "sent": 0}
    payload = build_harness_run_payload(repo, harness_run_id=str(target["id"]))
    if not payload:
        return {"status": "no_run", "sent": 0}
    messages = compose_issue_messages(payload, issue_number=int(runs.get("item_count") or len(items)), site_base_url=site_base_url)
    recipients = repo.list_notification_recipients("telegram")
    sent = 0
    failed = 0
    details = []
    for recipient in recipients:
        access = resolve_plan_access(repo, str(recipient["user_id"]), now=now)
        text = messages["paid"] if access.is_paid else messages["free"]
        try:
            client.send_message(str(recipient["external_id"]), text)
            sent += 1
        except TelegramError as exc:
            failed += 1
            details.append({"user_id": str(recipient["user_id"]), "error": str(exc)[:120]})
    repo.update_harness_run_metadata(str(target["id"]), {"notified_at": now.isoformat(), "notified_count": sent})
    return {"status": "sent", "run_id": str(target["id"]), "recipients": len(recipients), "sent": sent, "failed": failed, "details": details}


def _aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _iso(value: Any) -> str | None:
    parsed = _aware(value)
    return parsed.isoformat() if parsed else None

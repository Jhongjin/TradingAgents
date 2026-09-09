from datetime import date, datetime, timedelta, timezone

import pytest

from tradingagents.site.notifications import (
    TelegramClient,
    TelegramConfig,
    TelegramError,
    channel_status,
    compose_issue_messages,
    create_link_code,
    handle_telegram_update,
    notify_harness_issue,
    unlink_channel,
)
from tradingagents.storage import HarnessDecisionInput, HarnessRunInput, StorageRepository, SubscriptionInput, create_storage_engine

USER = "11111111-1111-4111-8111-111111111111"
PAID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc)
CONFIG = TelegramConfig(bot_token="123:abc", bot_username="TradingAgentsKRBot", webhook_secret="s3")


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _client(sent: list, *, fail_for: set | None = None) -> TelegramClient:
    def transport(method, url, body):
        assert url.startswith("https://api.telegram.org/bot123:abc/")
        method_name = url.rsplit("/", 1)[1]
        if method_name == "sendMessage":
            if fail_for and body["chat_id"] in fail_for:
                return 403, {"ok": False, "description": "bot was blocked by the user"}
            sent.append(body)
            return 200, {"ok": True, "result": {"message_id": len(sent)}}
        if method_name == "getMe":
            return 200, {"ok": True, "result": {"username": "TradingAgentsKRBot", "id": 123}}
        if method_name == "setWebhook":
            return 200, {"ok": True, "result": True}
        if method_name == "getWebhookInfo":
            return 200, {"ok": True, "result": {"url": "https://example.com/hook", "pending_update_count": 0}}
        raise AssertionError(method_name)

    return TelegramClient(CONFIG, transport=transport)


def test_link_code_then_start_command_links_chat_and_replies():
    repo = _repo()
    sent: list = []
    client = _client(sent)
    link = create_link_code(repo, USER, CONFIG, now=NOW)
    assert link["link_url"] == f"https://t.me/TradingAgentsKRBot?start={link['code']}"
    assert channel_status(repo, USER)["linked"] is False

    bad = handle_telegram_update(repo, {"message": {"chat": {"id": 555}, "text": "/start nope"}}, client, now=NOW)
    assert bad["linked"] is False and "만료" in sent[-1]["text"]

    good = handle_telegram_update(repo, {"message": {"chat": {"id": 555, "first_name": "홍진", "username": "hj"}, "text": f"/start {link['code']}"}}, client, now=NOW)
    assert good["linked"] is True
    status = channel_status(repo, USER)
    assert status["linked"] is True and status["display_name"] == "홍진"
    assert sent[-1]["chat_id"] == "555" and "연결되었습니다" in sent[-1]["text"]

    expired = create_link_code(repo, USER, CONFIG, now=NOW)
    late = handle_telegram_update(repo, {"message": {"chat": {"id": 556}, "text": f"/start {expired['code']}"}}, client, now=NOW + timedelta(hours=2))
    assert late["linked"] is False

    stop = handle_telegram_update(repo, {"message": {"chat": {"id": 555}, "text": "/stop"}}, client, now=NOW)
    assert stop["linked"] is False and channel_status(repo, USER)["linked"] is False
    assert handle_telegram_update(repo, {"message": {"chat": {"id": 555}, "text": "hello"}}, client)["handled"] is False
    assert handle_telegram_update(repo, {}, client)["handled"] is False
    assert unlink_channel(repo, USER)["linked"] is False
    assert "123:abc" not in repr(CONFIG)


def _seed_run(repo: StorageRepository, as_of: date) -> str:
    run_id = repo.create_harness_run(HarnessRunInput(as_of_date=as_of, confirmer="debate", candidate_count=3, order_count=1))
    repo.add_harness_decision(HarnessDecisionInput(harness_run_id=run_id, as_of_date=as_of, ticker_code="000660", stage="ordered", ticker_name="SK하이닉스", market="KOSPI", quantity=3, confirmation_rating="Overweight", confirmation_confidence=0.78))
    repo.add_harness_decision(HarnessDecisionInput(harness_run_id=run_id, as_of_date=as_of, ticker_code="005930", stage="forecast_rejected", ticker_name="삼성전자", market="KOSPI"))
    return run_id


def test_compose_messages_separate_paid_and_free():
    repo = _repo()
    _seed_run(repo, date(2026, 9, 9))
    from tradingagents.site.harness_api import build_harness_run_payload

    messages = compose_issue_messages(build_harness_run_payload(repo), issue_number=7, site_base_url="https://example.com")
    assert "SK하이닉스(000660)" in messages["paid"] and "Overweight 0.78" in messages["paid"] and "모의 3주" in messages["paid"]
    assert "https://example.com/harness/" in messages["paid"] and "매매 권유가 아닙니다" in messages["paid"]
    assert "SK하이닉스" not in messages["free"] and "데일리 패스" in messages["free"]


def test_notify_harness_issue_sends_by_plan_and_marks_run():
    repo = _repo()
    run_id = _seed_run(repo, date(2026, 9, 9))
    for user, chat in ((USER, "100"), (PAID, "200")):
        create_link_code(repo, user, CONFIG, now=NOW)
        code = repo.get_notification_channel(user)["link_code"]
        handle_telegram_update(repo, {"message": {"chat": {"id": int(chat)}, "text": f"/start {code}"}}, None, now=NOW)
    repo.upsert_subscription(SubscriptionInput(user_id=PAID, plan="daily", status="active", current_period_end=NOW + timedelta(days=20)))
    sent: list = []
    client = _client(sent, fail_for={"999"})

    result = notify_harness_issue(repo, client, site_base_url="https://example.com", now=NOW)
    assert result["status"] == "sent" and result["sent"] == 2 and result["failed"] == 0
    by_chat = {item["chat_id"]: item["text"] for item in sent}
    assert "SK하이닉스" in by_chat["200"] and "SK하이닉스" not in by_chat["100"]
    assert repo.get_harness_run(run_id)["metadata_json"]["notified_at"]

    again = notify_harness_issue(repo, client, now=NOW)
    assert again["status"] == "already_notified"
    forced = notify_harness_issue(repo, client, now=NOW, force=True)
    assert forced["sent"] == 2
    assert notify_harness_issue(_repo(), client, now=NOW)["status"] == "no_run"


def test_telegram_client_errors_surface():
    client = TelegramClient(TelegramConfig(bot_token=None, bot_username=None, webhook_secret=None))
    with pytest.raises(TelegramError, match="not configured"):
        client.send_message("1", "x")
    failing = _client([], fail_for={"7"})
    with pytest.raises(TelegramError, match="blocked"):
        failing.send_message("7", "x")
    assert failing.get_me()["username"] == "TradingAgentsKRBot"
    assert failing.set_webhook("https://example.com/hook", secret_token="s") is True
    assert failing.get_webhook_info()["pending_update_count"] == 0

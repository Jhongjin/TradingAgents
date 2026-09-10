"""The Friday summary: what each book returned, and what it closed."""

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site.notifications import TelegramClient, TelegramConfig
from tradingagents.site.weekly_report import (
    REPORT_KEY,
    build_weekly_report,
    compose_weekly_message,
    notify_weekly_report,
    week_key,
)
from tradingagents.storage import NotificationChannelInput, StorageRepository, create_storage_engine

from tests.test_paper_account import _fill, _repo, _run


class FakeTelegram(TelegramClient):
    def __init__(self):
        super().__init__(TelegramConfig(bot_token="t", bot_username=None, webhook_secret="s"), transport=lambda *a, **k: {"ok": True})
        self.messages = []

    def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))
        return {"ok": True}


USER = "11111111-1111-4111-8111-111111111111"


def _seed_week(repo: StorageRepository) -> None:
    today = datetime.now(timezone.utc).date()
    bought = today - timedelta(days=20)
    sold = today - timedelta(days=2)
    run_in = _run(repo, when=bought, dry_run=False)
    _fill(repo, run_in, when=bought, code="096770", stage="ordered", price=153500, quantity=13, name="SK이노베이션")
    run_out = _run(repo, when=sold, dry_run=False)
    _fill(repo, run_out, when=sold, code="096770", stage="exit", price=170000, quantity=13, reasons=("take_profit", "paper fill"))
    repo.upsert_notification_channel(
        NotificationChannelInput(user_id=USER, channel="telegram", external_id="777", enabled=True, linked_at=datetime.now(timezone.utc))
    )


def test_the_report_covers_the_week_just_closed():
    repo = _repo()
    _seed_week(repo)
    report = build_weekly_report(repo, site_base_url="https://agenttrust.kr")
    assert report["status"] == "available"
    assert {book["key"] for book in report["books"]} == {"paper", "rules", "kis"}
    assert [row["ticker_code"] for row in report["closed"]] == ["096770"]

    text = compose_weekly_message(report)
    assert "주간 결산" in text and "AI 확인" in text and "규칙 전용" in text
    assert "SK이노베이션 목표가 도달" in text
    assert "https://agenttrust.kr/paper" in text and "매매 권유가 아닙니다" in text


def test_older_trades_are_not_in_this_week():
    repo = _repo()
    today = datetime.now(timezone.utc).date()
    bought = today - timedelta(days=60)
    sold = today - timedelta(days=30)
    run_in = _run(repo, when=bought, dry_run=False)
    _fill(repo, run_in, when=bought, code="005930", stage="ordered", price=70000, quantity=10, name="삼성전자")
    run_out = _run(repo, when=sold, dry_run=False)
    _fill(repo, run_out, when=sold, code="005930", stage="exit", price=75000, quantity=10, reasons=("take_profit",))

    report = build_weekly_report(repo)
    assert report["closed"] == []
    assert "규칙으로 정리된 종목은 없습니다" in compose_weekly_message(report)


def test_one_report_a_week_per_member():
    repo = _repo()
    _seed_week(repo)
    client = FakeTelegram()

    first = notify_weekly_report(repo, client, site_base_url="https://agenttrust.kr")
    assert first["status"] == "sent" and first["sent"] == 1

    again = notify_weekly_report(repo, client, site_base_url="https://agenttrust.kr")
    assert again["status"] == "already_sent" and len(client.messages) == 1

    channel = repo.get_notification_channel(USER, "telegram")
    assert (channel["metadata_json"] or {})[REPORT_KEY] == week_key(date.today())

    forced = notify_weekly_report(repo, client, site_base_url="https://agenttrust.kr", force=True)
    assert forced["sent"] == 1 and len(client.messages) == 2


def test_the_cron_route_needs_the_worker_token(monkeypatch):
    repo = _repo()
    _seed_week(repo)
    monkeypatch.setenv("OPERATOR_ACCESS_CODE", "op-token")
    app = create_app(repo=repo, load_repo_from_env=False)
    app.state.telegram_client = FakeTelegram()
    client = TestClient(app)
    assert client.get("/api/cron/notify-weekly-report").status_code == 401
    body = client.get("/api/cron/notify-weekly-report", headers={"X-TradingAgents-Worker-Token": "op-token"}).json()
    assert body["status"] == "sent" and body["sent"] == 1

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site.journal_alerts import check_reason, check_request_path, notify_journal_alerts, scan_journal_hits
from tradingagents.site.notifications import TelegramClient, TelegramConfig
from tradingagents.storage import ManualTradeInput, NotificationChannelInput, StorageRepository, create_storage_engine

USER = "11111111-1111-4111-8111-111111111111"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _seed(repo: StorageRepository) -> str:
    pid = repo.create_manual_portfolio(user_id=USER, name="장기")
    repo.add_manual_trade(ManualTradeInput(portfolio_id=pid, ticker_code="034020", ticker_name="두산에너빌리티", side="buy", trade_date=date(2026, 9, 7), price=Decimal("89000"), quantity=20))
    repo.set_price_target(portfolio_id=pid, ticker_code="034020", target_price=Decimal("90000"), stop_price=Decimal("85000"))
    repo.upsert_notification_channel(NotificationChannelInput(user_id=USER, channel="telegram", external_id="777", enabled=True, linked_at=datetime.now(timezone.utc)))
    return pid


class FakeTelegram(TelegramClient):
    def __init__(self):
        super().__init__(TelegramConfig(bot_token="t", bot_username=None, webhook_secret="s"), transport=lambda *args, **kwargs: {"ok": True})
        self.messages = []

    def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))
        return {"ok": True}


def test_scan_detects_target_and_stop_hits():
    repo = _repo()
    pid = _seed(repo)
    hits = scan_journal_hits(repo, user_id=USER, price_loader=lambda _pid: ({"034020": Decimal("91000")}, None))
    assert [h["kind"] for h in hits] == ["target"] and hits[0]["portfolio_id"] == pid
    assert "목표 점검" in check_reason("target", hits[0]["position"]) and "50% 기준" in check_reason("target", hits[0]["position"])
    assert check_request_path("target", hits[0]["position"]).startswith("/mypage?tab=analysis&ticker=034020&reason=")
    stop_hits = scan_journal_hits(repo, user_id=USER, price_loader=lambda _pid: ({"034020": Decimal("84000")}, None))
    assert [h["kind"] for h in stop_hits] == ["stop"]
    assert scan_journal_hits(repo, user_id=USER, price_loader=lambda _pid: ({"034020": Decimal("89500")}, None)) == []


def test_notify_sends_once_per_level_and_remembers_in_channel_metadata():
    repo = _repo()
    _seed(repo)
    client = FakeTelegram()
    loader = lambda _pid: ({"034020": Decimal("91000")}, None)
    first = notify_journal_alerts(repo, client, site_base_url="https://agenttrust.kr", price_loader=loader)
    assert first["status"] == "sent" and first["hits"] == 1 and len(client.messages) == 1
    text = client.messages[0][1]
    assert "목표가 도달" in text and "https://agenttrust.kr/mypage?tab=analysis&ticker=034020" in text and "매매 지시가 아닙니다" in text
    again = notify_journal_alerts(repo, client, site_base_url="https://agenttrust.kr", price_loader=loader)
    assert again["status"] == "nothing_to_send" and len(client.messages) == 1
    channel = repo.get_notification_channel(USER, "telegram")
    assert list((channel["metadata_json"] or {})["journal_alerts"].keys())[0].endswith(":target:90000")
    # a new level (stop) still alerts
    third = notify_journal_alerts(repo, client, site_base_url="https://agenttrust.kr", price_loader=lambda _pid: ({"034020": Decimal("84000")}, None))
    assert third["hits"] == 1 and "손절선 도달" in client.messages[-1][1]


def test_cron_route_requires_token_and_runs(monkeypatch):
    repo = _repo()
    _seed(repo)
    monkeypatch.setenv("OPERATOR_ACCESS_CODE", "op-token")
    monkeypatch.setattr("tradingagents.site.api_app._latest_current_prices", lambda tickers, max_tickers: ({"034020": Decimal("91000")}, {"vendor": "test"}))
    app = create_app(repo=repo, load_repo_from_env=False)
    app.state.telegram_client = FakeTelegram()
    client = TestClient(app)
    assert client.get("/api/cron/notify-journal-targets").status_code == 401
    result = client.get("/api/cron/notify-journal-targets", headers={"X-TradingAgents-Worker-Token": "op-token"}).json()
    assert result["status"] == "sent" and result["hits"] == 1
    assert len(app.state.telegram_client.messages) == 1


def test_member_page_marks_hits_and_prefills_check_request():
    from tradingagents.site.web_pages import render_member_dashboard_page

    html = render_member_dashboard_page()
    for needle in ("is-target-hit", "AI 점검 요청", "checkReasonFor", "applyRequestedAnalysisPrefill", "청산 근거 비중", "EXIT_BASIS_BY_RATING"):
        assert needle in html, needle


def test_member_page_offers_telegram_connect_and_admin_entry():
    from tradingagents.site.web_pages import render_member_dashboard_page

    html = render_member_dashboard_page()
    for needle in (
        "memberTelegramCard",
        "연결 코드 받기",
        "/api/notifications/telegram/link",
        "/api/notifications/telegram/status",
        "refreshTelegramStatus",
        'href="/admin/members" data-admin-only hidden',
        "admin-members-link",
        "member-signed-in-tags",
        "refreshAccountBadges",
    ):
        assert needle in html, needle


def test_header_plan_badge_marks_admins():
    from tradingagents.site.design_system import render_shell

    html = render_shell(title="t", body="<p>body</p>")
    assert "d.is_admin ? '관리자' : planLabel" in html
    assert "badge.href = '/admin/members'" in html

from datetime import date, datetime, timedelta, timezone

import pytest

from tradingagents.site.billing import PLANS, PortOneClient, PortOneConfig, compute_refund_amount, request_refund
from tradingagents.site.billing_page import render_billing_page
from tradingagents.site.notifications import TelegramClient, TelegramConfig, create_link_code, handle_telegram_update, notify_exit_alerts, notify_outcome_results
from tradingagents.site.web_pages import render_member_dashboard_page
from tradingagents.storage import HarnessDecisionInput, HarnessOutcomeInput, HarnessRunInput, StorageRepository, SubscriptionInput, create_storage_engine

USER = "11111111-1111-4111-8111-111111111111"
FREE = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 9, 9, 3, 0, tzinfo=timezone.utc)
CONFIG = TelegramConfig(bot_token="123:abc", bot_username="TradingAgentsKRBot", webhook_secret="s3")


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


# ------------------------------------------------------------------ refund
def test_refund_policy_full_then_prorated():
    paid = NOW - timedelta(days=3)
    assert compute_refund_amount(price_krw=10_000, paid_at=paid, period_end=paid + timedelta(days=30), now=NOW) == (10_000, "full_within_7_days")
    paid = NOW - timedelta(days=15)
    amount, basis = compute_refund_amount(price_krw=10_000, paid_at=paid, period_end=paid + timedelta(days=30), now=NOW)
    assert basis == "prorated" and amount == 5_000
    assert compute_refund_amount(price_krw=10_000, paid_at=NOW - timedelta(days=40), period_end=NOW - timedelta(days=1), now=NOW) == (0, "period_elapsed")


def test_request_refund_cancels_payment_and_ends_plan():
    repo = _repo()
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url, body))
        return 200, {"cancellation": {"status": "SUCCEEDED"}}

    client = PortOneClient(PortOneConfig(api_secret="s", store_id="st", channel_key="ch", webhook_secret=None), transport=transport)
    with pytest.raises(ValueError):
        request_refund(repo, USER, client, now=NOW)
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="daily", status="active", billing_key="bk", last_payment_id="pay-1", last_payment_at=NOW - timedelta(days=2), current_period_start=NOW - timedelta(days=2), current_period_end=NOW + timedelta(days=28)))
    result = request_refund(repo, USER, client, now=NOW)
    assert result == {"refunded_amount": 10_000, "basis": "full_within_7_days", "status": "canceled", "payment_id": "pay-1"}
    assert calls[0][1].endswith("/payments/pay-1/cancel") and "amount" not in calls[0][2]  # full cancel
    row = repo.get_subscription(USER)
    assert row["status"] == "canceled"
    with pytest.raises(ValueError, match="이미 환불"):
        repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="daily", status="active", billing_key="bk", last_payment_id="pay-1", last_payment_at=NOW - timedelta(days=2), current_period_end=NOW + timedelta(days=28)))
        request_refund(repo, USER, client, now=NOW)
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="pro", status="active", billing_key="bk", last_payment_id="pay-2", last_payment_at=NOW - timedelta(days=15), current_period_end=NOW + timedelta(days=15)))
    partial = request_refund(repo, USER, client, now=NOW)
    assert partial["basis"] == "prorated" and partial["refunded_amount"] == 15_000
    assert calls[-1][2]["amount"] == 15_000


# --------------------------------------------------------- exit / outcomes
def _client(sent: list) -> TelegramClient:
    def transport(method, url, body):
        sent.append(body)
        return 200, {"ok": True, "result": {}}

    return TelegramClient(CONFIG, transport=transport)


def _link(repo: StorageRepository, user: str, chat: str) -> None:
    create_link_code(repo, user, CONFIG, now=NOW)
    code = repo.get_notification_channel(user)["link_code"]
    handle_telegram_update(repo, {"message": {"chat": {"id": int(chat)}, "text": f"/start {code}"}}, None, now=NOW)


def test_exit_alerts_go_to_paid_members_once():
    repo = _repo()
    run_id = repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 9, 9), broker="kis", dry_run=False, confirmer="debate"))
    repo.add_harness_decision(HarnessDecisionInput(harness_run_id=run_id, as_of_date=date(2026, 9, 9), ticker_code="000660", stage="exit", ticker_name="SK하이닉스", market="KOSPI", quantity=3, reasons=["stop_loss", "accepted"]))
    _link(repo, USER, "100")
    _link(repo, FREE, "200")
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="daily", status="active", current_period_end=NOW + timedelta(days=10)))
    sent: list = []
    result = notify_exit_alerts(repo, _client(sent), site_base_url="https://example.com", now=NOW)
    assert result["status"] == "sent" and result["sent"] == 1 and result["recipients"] == 1
    assert sent[0]["chat_id"] == "100" and "손절" in sent[0]["text"] and "SK하이닉스" in sent[0]["text"]
    assert notify_exit_alerts(repo, _client(sent), now=NOW)["status"] == "nothing_to_send"


def test_outcome_results_go_to_everyone_once():
    repo = _repo()
    run_id = repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 9, 1), confirmer="debate"))
    decision_id = repo.add_harness_decision(HarnessDecisionInput(harness_run_id=run_id, as_of_date=date(2026, 9, 1), ticker_code="005930", stage="ordered", ticker_name="삼성전자", market="KOSPI"))
    repo.upsert_harness_outcome(HarnessOutcomeInput(harness_decision_id=decision_id, harness_run_id=run_id, ticker_code="005930", ticker_name="삼성전자", entry_date=date(2026, 9, 1), evaluated_at=date(2026, 9, 9), horizon_days=5, actual_holding_days=5, raw_return=0.021, benchmark_return=0.011, alpha_return=0.01, status="completed"))
    repo.upsert_harness_outcome(HarnessOutcomeInput(harness_decision_id=decision_id, harness_run_id=run_id, ticker_code="005930", ticker_name="삼성전자", entry_date=date(2026, 9, 1), evaluated_at=date(2026, 9, 9), horizon_days=20, status="pending"))
    _link(repo, USER, "100")
    _link(repo, FREE, "200")
    sent: list = []
    result = notify_outcome_results(repo, _client(sent), site_base_url="https://example.com", now=NOW)
    assert result["status"] == "sent" and result["sent"] == 2 and result["outcomes"] == 1
    assert "삼성전자 5D +2.1% α +1.0%" in sent[0]["text"]
    assert notify_outcome_results(repo, _client(sent), now=NOW)["status"] == "nothing_to_send"


# ------------------------------------------------------------------ pages
def test_billing_page_has_password_form_and_config(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    html = render_billing_page()
    assert 'id="password-form"' in html and "/auth/v1/user" in html
    assert 'id="billing-config"' in html and "https://example.supabase.co" in html
    assert 'data-action="refund"' in html


def test_member_page_links_to_billing_with_plan_badge():
    html = render_member_dashboard_page()
    assert 'href="/billing"' in html and 'id="memberPlanBadge"' in html and "/api/billing/me" in html

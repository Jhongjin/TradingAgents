"""The site with the paid plans switched off: everything open, nothing for sale.

This is how production runs. The rest of the suite keeps the plans on so the
dormant billing code stays tested; here they are off, and every gate, page and
notifier is asked to behave as it does for a visitor today.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site.billing import (
    OPEN_PLAN,
    PLANS,
    gate_harness_payload,
    gate_paper_account_payload,
    latest_visible_run_id,
    paid_plans_enabled,
    resolve_plan_access,
)
from tradingagents.storage import StorageRepository, SubscriptionInput, create_storage_engine

NOW = datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc)   # 10:00 KST, a trading morning
USER = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def _plans_off(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_PAID_PLANS_ENABLED", raising=False)


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _run_payload(as_of: date) -> dict:
    return {
        "status": "ok",
        "run": {"id": "run-1", "as_of_date": as_of.isoformat()},
        "decisions": [
            {
                "ticker_code": "005930",
                "ticker_name": "삼성전자",
                "quantity": 3,
                "entry_price": 70000,
                "stop_price": 66500,
                "take_profit_price": 77000,
                "confirmation_rating": "overweight",
                "confirmation_confidence": 0.7,
                "detail": {"confirmation": {"raw": {"debate": {"turns": {"bull": {"data": {"thesis": "수요 회복"}}}}}}},
            }
        ],
    }


def test_the_switch_is_off_by_default_and_everyone_gets_the_open_plan(monkeypatch):
    assert not paid_plans_enabled()
    anonymous = resolve_plan_access(None, None)
    assert anonymous.plan is OPEN_PLAN and anonymous.status == "anonymous"
    assert anonymous.full_access and not anonymous.is_paid          # open, but not a subscriber: ads stay on

    repo = _repo()
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="pro", status="active", current_period_end=NOW + timedelta(days=20)))
    member = resolve_plan_access(repo, USER, now=NOW)
    assert member.plan is OPEN_PLAN and member.status == "free" and member.full_access

    monkeypatch.setenv("TRADINGAGENTS_PAID_PLANS_ENABLED", "1")
    assert paid_plans_enabled()
    assert resolve_plan_access(repo, USER, now=NOW).plan.id == "pro"   # the dormant rules still work when asked
    assert resolve_plan_access(None, None).plan is PLANS["free"]


def test_todays_run_and_todays_trades_are_open_to_a_visitor():
    access = resolve_plan_access(None, None)
    today = NOW.astimezone(gate_harness_payload.__globals__["KST"]).date()

    run = gate_harness_payload(_run_payload(today), access, now=NOW)
    decision = run["decisions"][0]
    assert run["plan_gate"] == {"plan": "free", "status": "anonymous", "locked": False}
    assert decision["ticker_name"] == "삼성전자" and decision["take_profit_price"] == 77000
    assert "raw" in decision["detail"]["confirmation"]              # the transcript is not stripped

    account = {"positions": [{"entry_date": today.isoformat(), "ticker_code": "005930"}], "closed": [{"exit_date": today.isoformat()}]}
    visible = gate_paper_account_payload(account, access, now=NOW)
    assert visible["positions"] and visible["closed"] and visible["plan_gate"]["locked"] is False


def test_the_newest_run_is_the_visible_one():
    repo = _repo()
    from tests.test_notifications import _seed_run  # the notification suite's seeded runs

    old = _seed_run(repo, date(2026, 9, 9))
    new = _seed_run(repo, date(2026, 9, 12))
    assert latest_visible_run_id(repo, resolve_plan_access(None, None), now=NOW) == new
    assert old != new


def test_checkout_and_trials_refuse_and_the_plan_list_says_why(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "true")
    app = create_app(repo=_repo(), load_repo_from_env=False, trust_member_user_header=True)
    client = TestClient(app)

    plans = client.get("/api/billing/plans").json()
    assert plans["mode"] == "free_for_all" and plans["paid_plans_enabled"] is False
    assert [plan["id"] for plan in plans["plans"]] == ["free"] and plans["plans"][0]["same_day_harness"] is True

    headers = {"X-TradingAgents-User-Id": USER}
    assert client.post("/api/billing/trial", headers=headers).status_code == 409
    assert client.post("/api/billing/checkout", json={"plan": "daily"}, headers=headers).status_code == 409
    me = client.get("/api/billing/me", headers=headers).json()
    assert me["access"]["plan"]["id"] == "free" and me["access"]["is_paid"] is False


def test_the_pages_speak_of_free_not_of_prices():
    app = create_app(repo=_repo(), load_repo_from_env=False, trust_member_user_header=False)
    client = TestClient(app)

    pricing = client.get("/pricing").text
    assert "전부 무료" in pricing and "광고로 운영" in pricing
    assert "월 10,000원" not in pricing and "무료 체험" not in pricing
    assert '"@type": "Product"' not in pricing                         # no offers when nothing is sold

    home = client.get("/").text
    assert ">무료 안내<" in home and ">요금제<" not in home             # the nav and footer
    assert "전문은 데일리 패스" not in home
    assert 'data-plan-badge data-paid-plans="0"' in home and " hidden>플랜 확인 중" in home

    billing = client.get("/billing").text
    assert "모든 기능이 무료입니다" in billing and "구독 · 월" not in billing
    assert "종목과 등급까지 바로 받습니다" in billing

    harness = client.get("/harness").text
    assert "데일리 패스 회원에게 열립니다" not in harness
    paper = client.get("/paper").text
    assert "데일리 패스에서 열립니다" not in paper and "목표가와 손절가까지 모두 공개" in paper

    llms = client.get("/llms.txt").text
    assert "무료 안내" in llms and "월 10,000원" not in llms


def test_every_telegram_reader_gets_the_full_message():
    from tests.test_notifications import CONFIG, PAID, USER as FREE_USER, _client, _seed_run
    from tradingagents.site.notifications import create_link_code, handle_telegram_update, notify_harness_issue

    repo = _repo()
    _seed_run(repo, date(2026, 9, 9))
    for user, chat in ((FREE_USER, "100"), (PAID, "200")):
        create_link_code(repo, user, CONFIG, now=NOW)
        code = repo.get_notification_channel(user)["link_code"]
        handle_telegram_update(repo, {"message": {"chat": {"id": int(chat)}, "text": f"/start {code}"}}, None, now=NOW)
    sent: list = []
    result = notify_harness_issue(repo, _client(sent, fail_for=set()), site_base_url="https://example.com", now=NOW)
    assert result["sent"] == 2
    assert all("SK하이닉스" in item["text"] for item in sent)        # nobody gets the teaser version


def test_an_ad_unit_renders_only_with_a_publisher_and_a_slot(monkeypatch):
    from tradingagents.site.seo import ad_unit

    monkeypatch.delenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_ADSENSE_SLOT_INFEED", raising=False)
    assert ad_unit() == ""
    monkeypatch.setenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID", "pub-1234567890123456")
    assert ad_unit() == ""                                            # a publisher alone is not a placement
    monkeypatch.setenv("TRADINGAGENTS_ADSENSE_SLOT_INFEED", "9876543210")
    html = ad_unit()
    assert 'data-ad-client="ca-pub-1234567890123456"' in html and 'data-ad-slot="9876543210"' in html
    monkeypatch.setenv("TRADINGAGENTS_ADSENSE_SLOT_INFEED", "not-a-slot")
    assert ad_unit() == ""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tradingagents.site.billing import (
    PLANS,
    PortOneClient,
    PortOneConfig,
    PortOneError,
    build_checkout_payload,
    cancel_at_period_end,
    charge_subscription,
    gate_harness_payload,
    handle_portone_webhook,
    latest_visible_run_id,
    process_subscription_renewals,
    resolve_plan_access,
    sign_webhook,
    start_trial,
    verify_webhook_signature,
)
from tradingagents.storage import HarnessDecisionInput, HarnessRunInput, StorageRepository, SubscriptionInput, create_storage_engine

USER = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 9, 9, 3, 0, tzinfo=timezone.utc)  # 12:00 KST
SECRET = "whsec_" + "c2VjcmV0LXNlY3JldC1zZWNyZXQ="


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _fake_client(payments: dict, log: list | None = None) -> PortOneClient:
    log = log if log is not None else []

    def transport(method, url, headers, body):
        log.append((method, url, body))
        assert headers["Authorization"] == "PortOne secret"
        if method == "GET":
            payment_id = url.rsplit("/", 1)[1]
            return (200, payments[payment_id]) if payment_id in payments else (404, {"message": "not found"})
        if url.endswith("/billing-key"):
            payment_id = url.split("/payments/")[1].split("/")[0]
            if body["billingKey"] == "bk-bad":
                return 400, {"message": "card declined"}
            payments[payment_id] = {"status": "PAID", "amount": {"total": body["amount"]["total"]}, "customer": body["customer"], "customData": body.get("customData")}
            return 200, {"payment": {"paidAt": "2026-09-09T03:00:00Z"}}
        raise AssertionError(url)

    return PortOneClient(PortOneConfig(api_secret="secret", store_id="store", channel_key="channel", webhook_secret=SECRET), transport=transport)


# ------------------------------------------------------------- plan access
def test_plan_access_defaults_and_trial_lifecycle():
    repo = _repo()
    assert resolve_plan_access(repo, None).status == "anonymous"
    assert resolve_plan_access(repo, USER, now=NOW).plan.id == "free"

    trial = start_trial(repo, USER, now=NOW)
    assert trial["status"] == "trialing"
    access = resolve_plan_access(repo, USER, now=NOW + timedelta(days=3))
    assert access.plan.id == "daily" and access.status == "trialing" and access.is_paid
    expired = resolve_plan_access(repo, USER, now=NOW + timedelta(days=15))
    assert expired.plan.id == "free" and expired.status == "free"
    with pytest.raises(ValueError):
        start_trial(repo, USER, now=NOW + timedelta(days=20))


def test_plan_access_active_grace_and_past_due():
    repo = _repo()
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="pro", status="active", current_period_end=NOW + timedelta(days=10)))
    assert resolve_plan_access(repo, USER, now=NOW).plan.id == "pro"
    assert resolve_plan_access(repo, USER, now=NOW + timedelta(days=11)).status == "active"  # grace
    lapsed = resolve_plan_access(repo, USER, now=NOW + timedelta(days=13))
    assert lapsed.status == "past_due" and lapsed.plan.id == "free"
    with pytest.raises(ValueError):
        repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="gold"))


# -------------------------------------------------------------- gating
def _payload(as_of: date):
    return {
        "run": {"id": "r1", "as_of_date": as_of.isoformat()},
        "decisions": [
            {"ticker_code": "000660", "ticker_name": "SK하이닉스", "stage": "ordered", "quantity": 3, "reasons": ["ok"], "stock_path": "/stocks/000660", "detail": {"confirmation": {"rationale": "x", "raw": {"debate": {"turns": {}}}}}}
        ],
    }


def test_gate_hides_debate_for_free_and_locks_same_day():
    free = resolve_plan_access(None, None)
    yesterday = gate_harness_payload(_payload(date(2026, 9, 8)), free, now=NOW)
    assert yesterday["plan_gate"]["locked"] is False
    assert yesterday["decisions"][0]["ticker_code"] == "000660"
    assert "raw" not in yesterday["decisions"][0]["detail"]["confirmation"]

    today = gate_harness_payload(_payload(date(2026, 9, 9)), free, now=NOW)
    assert today["plan_gate"]["locked"] is True
    assert today["decisions"][0]["ticker_code"] is None
    assert today["decisions"][0]["locked"] is True

    repo = _repo()
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="daily", status="active", current_period_end=NOW + timedelta(days=20)))
    paid = gate_harness_payload(_payload(date(2026, 9, 9)), resolve_plan_access(repo, USER, now=NOW), now=NOW)
    assert paid["plan_gate"]["locked"] is False
    assert "raw" in paid["decisions"][0]["detail"]["confirmation"]
    assert gate_harness_payload(None, free) is None


def test_latest_visible_run_prefers_previous_day_for_free():
    repo = _repo()
    old = repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 9, 8), confirmer="debate"))
    new = repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 9, 9), confirmer="debate"))
    assert latest_visible_run_id(repo, resolve_plan_access(None, None), now=NOW) == old
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="daily", status="active", current_period_end=NOW + timedelta(days=20)))
    assert latest_visible_run_id(repo, resolve_plan_access(repo, USER, now=NOW), now=NOW) == new
    assert latest_visible_run_id(None, resolve_plan_access(None, None)) is None


# ------------------------------------------------------------ webhooks
def test_webhook_signature_roundtrip_and_rejections():
    body = b'{"type":"Transaction.Paid","data":{"paymentId":"p1"}}'
    headers = sign_webhook(body, SECRET, timestamp=1_700_000_000)
    verify_webhook_signature(headers, body, SECRET, now=1_700_000_100)
    with pytest.raises(PortOneError, match="tolerance"):
        verify_webhook_signature(headers, body, SECRET, now=1_700_001_000)
    with pytest.raises(PortOneError, match="mismatch"):
        verify_webhook_signature(headers, body + b" ", SECRET, now=1_700_000_100)
    with pytest.raises(PortOneError, match="missing"):
        verify_webhook_signature({}, body, SECRET, now=1_700_000_100)
    with pytest.raises(PortOneError, match="not configured"):
        verify_webhook_signature(headers, body, None, now=1_700_000_100)


def test_billing_key_issue_charges_first_month_and_paid_webhook_activates():
    repo = _repo()
    payments: dict = {}
    log: list = []
    client = _fake_client(payments, log)
    custom = json.dumps({"user_id": USER, "plan": "daily", "customer_key": f"ta-{USER}"})

    issued = handle_portone_webhook(repo, {"type": "BillingKey.Issued", "data": {"billingKey": "bk-1", "customer": {"id": f"ta-{USER}"}, "customData": custom}}, client, now=NOW)
    assert issued["handled"] and issued["charge"]["charged"]
    payment_id = issued["charge"]["payment_id"]
    assert repo.get_subscription(USER)["status"] == "inactive"  # not yet paid
    assert payments[payment_id]["amount"]["total"] == 10_000

    paid = handle_portone_webhook(repo, {"type": "Transaction.Paid", "data": {"paymentId": payment_id}}, client, now=NOW)
    assert paid["handled"] and paid["plan"] == "daily"
    row = repo.get_subscription(USER)
    assert row["status"] == "active" and row["plan"] == "daily"
    assert resolve_plan_access(repo, USER, now=NOW + timedelta(days=29)).is_paid
    assert not resolve_plan_access(repo, USER, now=NOW + timedelta(days=33)).is_paid

    duplicate = handle_portone_webhook(repo, {"type": "Transaction.Paid", "data": {"paymentId": payment_id}}, client, now=NOW)
    assert duplicate.get("duplicate") is True
    events = repo.list_billing_events(user_id=USER)
    assert {e["event_type"] for e in events} == {"Transaction.Paid", "payment.requested", "billing_key.issued"}


def test_paid_webhook_rejects_amount_mismatch_and_unknown_events():
    repo = _repo()
    payments = {"p-bad": {"status": "PAID", "amount": {"total": 1_000}, "customer": {"id": f"ta-{USER}"}, "customData": json.dumps({"user_id": USER, "plan": "daily"})}}
    client = _fake_client(payments)
    result = handle_portone_webhook(repo, {"type": "Transaction.Paid", "data": {"paymentId": "p-bad"}}, client, now=NOW)
    assert result["handled"] is False and result["reason"] == "amount mismatch"
    assert repo.get_subscription(USER) is None
    assert handle_portone_webhook(repo, {"type": "Something.Else", "data": {}}, client, now=NOW)["handled"] is False


def test_renewals_charge_due_subscriptions_and_honour_cancellation():
    repo = _repo()
    payments: dict = {}
    client = _fake_client(payments)
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="daily", status="active", billing_key="bk-1", customer_key=f"ta-{USER}", current_period_start=NOW - timedelta(days=30), current_period_end=NOW + timedelta(hours=6), last_payment_at=NOW - timedelta(days=30)))
    other = "22222222-2222-4222-8222-222222222222"
    repo.upsert_subscription(SubscriptionInput(user_id=other, plan="pro", status="active", billing_key="bk-bad", customer_key=f"ta-{other}", current_period_end=NOW + timedelta(hours=1), last_payment_at=NOW - timedelta(days=30)))

    result = process_subscription_renewals(repo, client, now=NOW)
    assert result["due_count"] == 2 and result["charged_count"] == 1
    failed = repo.get_subscription(other)
    assert failed["failure_count"] == 1 and failed["status"] == "active"

    cancel_at_period_end(repo, USER)
    assert charge_subscription(repo, USER, client, now=NOW)["reason"] == "canceled at period end"
    assert repo.get_subscription(USER)["status"] == "canceled"
    with pytest.raises(ValueError):
        cancel_at_period_end(repo, "33333333-3333-4333-8333-333333333333")


def test_checkout_payload_requires_configuration_and_paid_plan():
    config = PortOneConfig(api_secret="s3cr3tvalue", store_id="store-1", channel_key="ch-1", webhook_secret=None)
    payload = build_checkout_payload(USER, "daily", config, redirect_url="https://example.com/mypage")
    assert payload["params"]["storeId"] == "store-1"
    assert payload["params"]["customer"]["customerId"] == f"ta-{USER}"
    assert json.loads(payload["params"]["customData"])["plan"] == "daily"
    assert payload["plan"]["price_krw"] == 10_000
    with pytest.raises(ValueError):
        build_checkout_payload(USER, "free", config)
    with pytest.raises(PortOneError):
        build_checkout_payload(USER, "daily", PortOneConfig(None, None, None, None))
    assert "s3cr3tvalue" not in repr(config)


def test_plans_table_is_consistent():
    assert PLANS["free"].price_krw == 0 and PLANS["daily"].price_krw == 10_000 and PLANS["pro"].price_krw == 30_000
    assert not PLANS["free"].same_day_harness and PLANS["daily"].same_day_harness
    assert PLANS["free"].analysis_requests_per_day < PLANS["daily"].analysis_requests_per_day < PLANS["pro"].analysis_requests_per_day


def test_billing_key_issued_webhook_without_customer_looks_up_the_key():
    """PortOne's Issued webhook carries only the key; customData comes back double-encoded."""

    repo = _repo()
    payments: dict = {}
    calls: list = []
    custom = json.dumps(json.dumps({"user_id": USER, "plan": "pro", "customer_key": f"ta-{USER}"}))

    def transport(method, url, headers, body):
        calls.append(url)
        if url.endswith("/billing-keys/bk-2"):
            return 200, {"status": "ISSUED", "billingKey": "bk-2", "customer": {"id": f"ta-{USER}"}, "customData": custom}
        if url.endswith("/billing-key"):
            payment_id = url.split("/payments/")[1].split("/")[0]
            payments[payment_id] = {"status": "PAID", "amount": {"total": body["amount"]["total"]}, "customer": body["customer"], "customData": body.get("customData")}
            return 200, {"payment": {}}
        if "/payments/" in url:
            return 200, payments[url.rsplit("/", 1)[1]]
        raise AssertionError(url)

    client = PortOneClient(PortOneConfig(api_secret="secret", store_id="store", channel_key="ch", webhook_secret=SECRET), transport=transport)
    issued = handle_portone_webhook(repo, {"type": "BillingKey.Issued", "data": {"storeId": "store", "billingKey": "bk-2"}}, client, now=NOW)
    assert issued["handled"] is True and issued["charge"]["charged"] is True
    assert any(url.endswith("/billing-keys/bk-2") for url in calls)
    row = repo.get_subscription(USER)
    assert row["billing_key"] == "bk-2" and row["plan"] == "pro"
    paid = handle_portone_webhook(repo, {"type": "Transaction.Paid", "data": {"paymentId": issued["charge"]["payment_id"]}}, client, now=NOW)
    assert paid["plan"] == "pro" and repo.get_subscription(USER)["status"] == "active"
    assert handle_portone_webhook(repo, {"type": "BillingKey.Issued", "data": {}}, client, now=NOW)["handled"] is False

import json
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site.billing import PortOneClient, PortOneConfig, sign_webhook
from tradingagents.storage import HarnessDecisionInput, HarnessRunInput, StorageRepository, SubscriptionInput, create_storage_engine

USER = "11111111-1111-4111-8111-111111111111"
SECRET = "whsec_" + "c2VjcmV0LXNlY3JldC1zZWNyZXQ="


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _seed_runs(repo: StorageRepository, today: date) -> tuple[str, str]:
    old = repo.create_harness_run(HarnessRunInput(as_of_date=today - timedelta(days=1), confirmer="debate", candidate_count=1, order_count=1))
    new = repo.create_harness_run(HarnessRunInput(as_of_date=today, confirmer="debate", candidate_count=1, order_count=1))
    for run_id, when in ((old, today - timedelta(days=1)), (new, today)):
        repo.add_harness_decision(
            HarnessDecisionInput(harness_run_id=run_id, as_of_date=when, ticker_code="000660", stage="ordered", ticker_name="SK하이닉스", market="KOSPI", quantity=3, order_status="accepted", detail={"confirmation": {"rationale": "x", "raw": {"debate": {"turns": {}}}}})
        )
    return old, new


def _client(repo, monkeypatch, *, portone: PortOneClient | None = None) -> TestClient:
    monkeypatch.setenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "true")
    app = create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True)
    if portone is not None:
        app.state.portone_client = portone
    return TestClient(app)


def test_pricing_page_and_plans_endpoint(monkeypatch):
    client = _client(_repo(), monkeypatch)
    page = client.get("/pricing")
    assert page.status_code == 200
    assert "데일리 패스" in page.text and "10,000" in page.text and "투자일임" in page.text
    plans = client.get("/api/billing/plans").json()
    assert [p["id"] for p in plans["plans"]] == ["free", "daily", "pro"]
    assert plans["mode"] == "research_tool"


def test_harness_latest_is_gated_by_plan(monkeypatch):
    repo = _repo()
    today = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")).date()
    old, new = _seed_runs(repo, today)
    client = _client(repo, monkeypatch)

    anonymous = client.get("/api/harness/runs/latest").json()
    assert anonymous["run"]["id"] == old
    assert anonymous["plan_gate"]["plan"] == "free" and anonymous["plan_gate"]["locked"] is False
    assert "raw" not in anonymous["decisions"][0]["detail"]["confirmation"]

    locked = client.get(f"/api/harness/runs/{new}").json()
    assert locked["plan_gate"]["locked"] is True and locked["decisions"][0]["ticker_code"] is None

    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="daily", status="active", current_period_end=datetime.now(timezone.utc) + timedelta(days=20)))
    paid = client.get("/api/harness/runs/latest", headers={"X-TradingAgents-User-Id": USER}).json()
    assert paid["run"]["id"] == new and paid["plan_gate"]["locked"] is False
    assert "raw" in paid["decisions"][0]["detail"]["confirmation"]


def test_member_billing_endpoints(monkeypatch):
    repo = _repo()
    client = _client(repo, monkeypatch)
    headers = {"X-TradingAgents-User-Id": USER}
    assert client.get("/api/billing/me").status_code in {401, 403}  # no credentials

    me = client.get("/api/billing/me", headers=headers).json()
    assert me["access"]["plan"]["id"] == "free" and me["access"]["status"] == "free"

    trial = client.post("/api/billing/trial", headers=headers)
    assert trial.status_code == 200 and trial.json()["status"] == "trialing"
    assert client.post("/api/billing/trial", headers=headers).status_code == 409
    assert client.get("/api/billing/me", headers=headers).json()["access"]["plan"]["id"] == "daily"

    monkeypatch.delenv("PORTONE_STORE_ID", raising=False)
    assert client.post("/api/billing/checkout", json={"plan": "daily"}, headers=headers).status_code == 503
    monkeypatch.setenv("PORTONE_API_SECRET", "s")
    monkeypatch.setenv("PORTONE_STORE_ID", "store")
    monkeypatch.setenv("PORTONE_CHANNEL_KEY", "channel")
    checkout = client.post("/api/billing/checkout", json={"plan": "pro"}, headers=headers)
    assert checkout.status_code == 200 and checkout.json()["params"]["storeId"] == "store"
    assert client.post("/api/billing/checkout", json={"plan": "free"}, headers=headers).status_code == 422

    cancel = client.post("/api/billing/cancel", headers=headers)
    assert cancel.status_code == 200 and cancel.json()["cancel_at_period_end"] is True


def test_portone_webhook_requires_valid_signature_and_activates(monkeypatch):
    repo = _repo()
    payments = {"p1": {"status": "PAID", "amount": {"total": 10_000}, "customer": {"id": f"ta-{USER}"}, "customData": json.dumps({"user_id": USER, "plan": "daily"})}}

    def transport(method, url, headers, body):
        return 200, payments[url.rsplit("/", 1)[1]]

    portone = PortOneClient(PortOneConfig(api_secret="s", store_id="store", channel_key="ch", webhook_secret=SECRET), transport=transport)
    monkeypatch.setenv("PORTONE_WEBHOOK_SECRET", SECRET)
    client = _client(repo, monkeypatch, portone=portone)
    body = json.dumps({"type": "Transaction.Paid", "data": {"paymentId": "p1"}}).encode("utf-8")

    unsigned = client.post("/api/billing/portone/webhook", content=body, headers={"content-type": "application/json"})
    assert unsigned.status_code == 401
    signed = client.post("/api/billing/portone/webhook", content=body, headers={"content-type": "application/json", **sign_webhook(body, SECRET)})
    assert signed.status_code == 200 and signed.json()["plan"] == "daily"
    assert repo.get_subscription(USER)["status"] == "active"

    assert client.get("/api/cron/process-subscription-renewals").status_code in {401, 503}
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "tok")
    renew = client.post("/api/admin/subscriptions/renew", headers={"X-TradingAgents-Worker-Token": "tok"})
    assert renew.status_code == 200 and renew.json()["status"] == "completed"


def test_plan_gated_and_billing_responses_are_private(monkeypatch):
    repo = _repo()
    client = _client(repo, monkeypatch)
    assert client.get("/pricing").headers["cache-control"].startswith("public")
    assert client.get("/api/billing/plans").headers["cache-control"] == "private, no-store"
    with_member = client.get("/api/harness/runs", headers={"X-TradingAgents-User-Id": USER})
    assert with_member.headers["cache-control"] == "private, no-store"
    anonymous = client.get("/api/harness/runs")
    assert anonymous.headers["cache-control"].startswith("public")


def test_billing_page_and_telegram_member_endpoints(monkeypatch):
    from tradingagents.site.notifications import TelegramClient, TelegramConfig

    repo = _repo()
    sent = []

    def transport(method, url, body):
        sent.append(body)
        return 200, {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "TradingAgentsKRBot")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "hook-secret")
    client = _client(repo, monkeypatch)
    client.app.state.telegram_client = TelegramClient(TelegramConfig.from_env(), transport=transport)
    headers = {"X-TradingAgents-User-Id": USER}

    page = client.get("/billing")
    assert page.status_code == 200 and "텔레그램 알림" in page.text and "requestIssueBillingKey" in page.text
    assert page.headers["cache-control"] == "private, no-store" or "noindex" in page.text

    link = client.post("/api/notifications/telegram/link", headers=headers).json()
    assert link["link_url"].startswith("https://t.me/TradingAgentsKRBot?start=")
    assert client.get("/api/notifications/telegram/status", headers=headers).json()["linked"] is False

    update = {"message": {"chat": {"id": 900, "first_name": "Tester"}, "text": f"/start {link['code']}"}}
    assert client.post("/api/notifications/telegram/webhook", json=update).status_code == 401
    ok = client.post("/api/notifications/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"})
    assert ok.status_code == 200 and ok.json()["linked"] is True
    assert client.get("/api/notifications/telegram/status", headers=headers).json()["linked"] is True
    assert sent and "연결되었습니다" in sent[-1]["text"]

    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "tok")
    setup = client.post("/api/admin/notifications/telegram/setup", headers={"X-TradingAgents-Worker-Token": "tok"})
    assert setup.status_code == 502 or setup.status_code == 200  # fake transport answers getMe/setWebhook with generic payload
    notify = client.post("/api/admin/notifications/harness-issue", headers={"X-TradingAgents-Worker-Token": "tok"}).json()
    assert notify["status"] == "no_run"
    assert client.delete("/api/notifications/telegram/link", headers=headers).json()["linked"] is False


def test_analysis_request_quota_follows_plan(monkeypatch):
    repo = _repo()
    client = _client(repo, monkeypatch)
    headers = {"X-TradingAgents-User-Id": USER}
    codes = ["005930", "000660", "035420", "373220"]
    statuses = [client.post("/api/analysis-requests", json={"ticker": code}, headers=headers).status_code for code in codes[:3]]
    assert statuses == [200, 200, 429]  # free plan: 2 active requests
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="daily", status="active", current_period_end=datetime.now(timezone.utc) + timedelta(days=10)))
    assert client.post("/api/analysis-requests", json={"ticker": codes[2]}, headers=headers).status_code == 200


def test_csp_allows_payment_sdk_and_web_fonts(monkeypatch):
    client = _client(_repo(), monkeypatch)
    csp = client.get("/pricing").headers["content-security-policy"]
    assert "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.portone.io" in csp
    assert "https://fonts.googleapis.com" in csp and "https://fonts.gstatic.com" in csp
    assert "frame-src 'self' https://*.portone.io https://*.iamport.co" in csp
    assert "https://*.iamport.co" in csp.split("connect-src", 1)[1]
    assert "frame-ancestors 'none'" in csp


def test_refund_endpoint_and_alert_crons(monkeypatch):
    from tradingagents.site.notifications import TelegramClient, TelegramConfig

    repo = _repo()
    portone = PortOneClient(PortOneConfig(api_secret="s", store_id="store", channel_key="ch", webhook_secret=SECRET), transport=lambda m, u, h, b: (200, {"cancellation": {"status": "SUCCEEDED"}}))
    client = _client(repo, monkeypatch, portone=portone)
    client.app.state.telegram_client = TelegramClient(TelegramConfig(bot_token="t", bot_username="b", webhook_secret="s"), transport=lambda m, u, b: (200, {"ok": True, "result": {}}))
    headers = {"X-TradingAgents-User-Id": USER}
    assert client.post("/api/billing/refund", headers=headers).status_code == 409
    repo.upsert_subscription(SubscriptionInput(user_id=USER, plan="daily", status="active", billing_key="bk", last_payment_id="pay-9", last_payment_at=datetime.now(timezone.utc) - timedelta(days=1), current_period_end=datetime.now(timezone.utc) + timedelta(days=29)))
    refund = client.post("/api/billing/refund", headers=headers)
    assert refund.status_code == 200 and refund.json()["refunded_amount"] == 10_000
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "tok")
    for path in ("/api/cron/notify-exits", "/api/cron/notify-outcomes"):
        r = client.get(path, headers={"X-TradingAgents-Worker-Token": "tok"})
        assert r.status_code == 200 and r.json()["status"] == "nothing_to_send"

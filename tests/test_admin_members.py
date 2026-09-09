from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site.admin_members import SupabaseAdminClient, SupabaseAdminError, grant_member_plan, list_members, set_member_role
from tradingagents.storage import NotificationChannelInput, StorageRepository, SubscriptionInput, create_storage_engine

ADMIN = "11111111-1111-4111-8111-111111111111"
MEMBER = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 9, 9, 3, 0, tzinfo=timezone.utc)


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


class FakeSupabase(SupabaseAdminClient):
    def __init__(self):
        super().__init__(url="https://example.supabase.co", service_role_key="service")
        self.users = {
            ADMIN: {"id": ADMIN, "email": "owner@example.com", "created_at": "2026-09-01T00:00:00Z", "last_sign_in_at": "2026-09-09T01:00:00Z", "email_confirmed_at": "2026-09-01T00:00:00Z", "app_metadata": {"role": "admin"}},
            MEMBER: {"id": MEMBER, "email": "member@example.com", "created_at": "2026-09-05T00:00:00Z", "app_metadata": {}},
        }
        self.updates = []

    def list_users(self, *, per_page=200, max_pages=10):
        return list(self.users.values())

    def update_user(self, user_id, payload):
        self.updates.append((user_id, dict(payload)))
        self.users[user_id]["app_metadata"] = {**self.users[user_id].get("app_metadata", {}), **payload.get("app_metadata", {})}
        return self.users[user_id]


def test_list_members_merges_auth_users_with_plans_and_channels():
    repo = _repo()
    repo.upsert_subscription(SubscriptionInput(user_id=MEMBER, plan="daily", status="active", current_period_start=NOW - timedelta(days=10), current_period_end=NOW + timedelta(days=20), billing_key="bk"))
    repo.upsert_notification_channel(NotificationChannelInput(user_id=MEMBER, channel="telegram", external_id="123", enabled=True))

    payload = list_members(repo, FakeSupabase(), now=NOW)
    by_id = {item["user_id"]: item for item in payload["items"]}
    assert [item["user_id"] for item in payload["items"]] == [MEMBER, ADMIN]  # newest first
    assert by_id[ADMIN]["role"] == "admin" and by_id[ADMIN]["plan"] == "free" and by_id[ADMIN]["remaining_days"] is None
    member = by_id[MEMBER]
    assert member["plan"] == "daily" and member["status"] == "active" and member["remaining_days"] == 20
    assert member["telegram_linked"] is True and member["has_billing_key"] is True
    assert payload["summary"] == {"member_count": 2, "paid_count": 1, "trial_count": 0, "admin_count": 1, "telegram_linked_count": 1}


def test_grant_member_plan_extends_active_period_and_records_event():
    repo = _repo()
    first = grant_member_plan(repo, MEMBER, plan="pro", days=30, actor="owner@example.com", now=NOW)
    assert first["status"] == "active" and first["period_end"] == (NOW + timedelta(days=30)).isoformat()
    second = grant_member_plan(repo, MEMBER, plan="pro", days=10, now=NOW)
    assert second["period_end"] == (NOW + timedelta(days=40)).isoformat()
    row = repo.get_subscription(MEMBER)
    assert row["plan"] == "pro" and row["metadata_json"]["operator_override"] == "pro:10d"

    back = grant_member_plan(repo, MEMBER, plan="free", now=NOW)
    assert back == {"user_id": MEMBER, "plan": "free", "status": "inactive", "period_end": None}
    events = repo.list_billing_events(user_id=MEMBER, limit=10)
    assert {event["event_type"] for event in events} == {"operator.plan_granted"} and len(events) == 3
    with pytest.raises(ValueError):
        grant_member_plan(repo, MEMBER, plan="daily", days=0, now=NOW)
    with pytest.raises(ValueError):
        grant_member_plan(repo, MEMBER, plan="gold", now=NOW)


def test_set_member_role_updates_app_metadata():
    fake = FakeSupabase()
    assert set_member_role(fake, MEMBER, "admin") == {"user_id": MEMBER, "role": "admin"}
    assert fake.updates == [(MEMBER, {"app_metadata": {"role": "admin"}})]
    with pytest.raises(ValueError):
        set_member_role(fake, MEMBER, "root")


def test_supabase_admin_client_paginates_and_reports_errors():
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url))
        assert headers["apikey"] == "sr-key-9" and headers["Authorization"] == "Bearer sr-key-9"
        page = int(url.split("?page=", 1)[1].split("&")[0])
        if page == 1:
            return 200, {"users": [{"id": str(i)} for i in range(2)]}
        return 200, {"users": [{"id": "x"}]}

    client = SupabaseAdminClient(url="https://example.supabase.co", service_role_key="sr-key-9", transport=transport)
    assert [u["id"] for u in client.list_users(per_page=2)] == ["0", "1", "x"]
    assert len(calls) == 2 and "***" in repr(client) and "sr-key-9" not in repr(client)

    failing = SupabaseAdminClient(url="https://example.supabase.co", service_role_key="service", transport=lambda *a: (401, {"message": "no"}))
    with pytest.raises(SupabaseAdminError):
        failing.list_users()
    with pytest.raises(SupabaseAdminError):
        SupabaseAdminClient(url=None, service_role_key=None).list_users()


def _client(repo, monkeypatch, fake: FakeSupabase) -> TestClient:
    monkeypatch.setenv("OPERATOR_ACCESS_CODE", "op-token")
    app = create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=False)
    app.state.supabase_admin_client = fake
    return TestClient(app)


def test_admin_member_routes_accept_worker_token(monkeypatch):
    repo = _repo()
    fake = FakeSupabase()
    client = _client(repo, monkeypatch, fake)
    assert client.get("/api/admin/members").status_code == 401
    assert client.get("/api/admin/members", headers={"X-TradingAgents-Worker-Token": "wrong"}).status_code == 403

    listing = client.get("/api/admin/members", headers={"X-TradingAgents-Worker-Token": "op-token"})
    assert listing.status_code == 200 and listing.json()["summary"]["member_count"] == 2

    granted = client.post(f"/api/admin/members/{MEMBER}/plan", json={"plan": "daily", "days": 30}, headers={"X-TradingAgents-Worker-Token": "op-token"})
    assert granted.status_code == 200 and granted.json()["plan"] == "daily"
    assert client.post("/api/admin/members/not-a-uuid/plan", json={"plan": "daily"}, headers={"X-TradingAgents-Worker-Token": "op-token"}).status_code == 400
    assert client.post(f"/api/admin/members/{MEMBER}/plan", json={"plan": "gold"}, headers={"X-TradingAgents-Worker-Token": "op-token"}).status_code == 422

    role = client.post(f"/api/admin/members/{MEMBER}/role", json={"role": "admin"}, headers={"X-TradingAgents-Worker-Token": "op-token"})
    assert role.status_code == 200 and fake.users[MEMBER]["app_metadata"]["role"] == "admin"

    page = client.get("/admin/members")
    assert page.status_code == 200 and "회원 관리" in page.text and page.headers["cache-control"] == "private, no-store"


def test_admin_member_routes_accept_admin_member_bearer(monkeypatch):
    repo = _repo()
    fake = FakeSupabase()
    client = _client(repo, monkeypatch, fake)

    def fake_profile(request, trusted_header):
        token = request.headers.get("authorization", "").split(" ", 1)[-1]
        if token == "admin-jwt":
            return {"id": ADMIN, "email": "owner@example.com", "role": "admin", "is_admin": True}
        return {"id": MEMBER, "email": "member@example.com", "role": "member", "is_admin": False}

    monkeypatch.setattr("tradingagents.site.api_app.resolve_member_profile", fake_profile)
    assert client.get("/api/admin/members", headers={"Authorization": "Bearer member-jwt"}).status_code == 403
    ok = client.get("/api/admin/members", headers={"Authorization": "Bearer admin-jwt"})
    assert ok.status_code == 200

    granted = client.post(f"/api/admin/members/{MEMBER}/plan", json={"plan": "pro", "days": 7}, headers={"Authorization": "Bearer admin-jwt"})
    assert granted.status_code == 200
    event = repo.list_billing_events(user_id=MEMBER, limit=1)[0]
    assert "owner@example.com" in event["message"]

    me = client.get("/api/billing/me", headers={"Authorization": "Bearer admin-jwt"}).json()
    assert me["is_admin"] is True and me["role"] == "admin"
    me_member = client.get("/api/billing/me", headers={"Authorization": "Bearer member-jwt"}).json()
    assert me_member["is_admin"] is False and me_member["access"]["plan"]["id"] == "pro"


def test_resolve_member_profile_reads_role_and_admin_emails(monkeypatch):
    from tradingagents.site import auth

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("TRADINGAGENTS_ADMIN_EMAILS", "Owner@Example.com")

    class Resp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    payloads = {"a": {"id": ADMIN, "email": "owner@example.com", "app_metadata": {}}, "b": {"id": MEMBER, "email": "m@example.com", "app_metadata": {"role": "admin"}}, "c": {"id": MEMBER, "email": "m@example.com"}}
    monkeypatch.setattr(auth.requests, "get", lambda url, headers, timeout: Resp(payloads[headers["Authorization"].split()[-1]]))

    class Req:
        def __init__(self, token):
            self.headers = {"authorization": f"Bearer {token}"}
            self.app = type("App", (), {"state": type("S", (), {"trust_member_user_header": False})()})()

    assert auth.resolve_member_profile(Req("a"), None)["is_admin"] is True  # via TRADINGAGENTS_ADMIN_EMAILS
    assert auth.resolve_member_profile(Req("b"), None)["role"] == "admin"  # via app_metadata.role
    assert auth.resolve_member_profile(Req("c"), None) == {"id": MEMBER, "email": "m@example.com", "role": "member", "is_admin": False}

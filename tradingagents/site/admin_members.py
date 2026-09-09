"""Operator member management: list members with plan state, grant plans, set roles.

Member identities live in Supabase Auth (read through the service-role admin
API), plan state in ``subscriptions``, and Telegram links in
``notification_channels``. The Supabase client is injectable for tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from tradingagents.storage import BillingEventInput, StorageRepository, SubscriptionInput

from .billing import PAID_PLANS, PLANS, resolve_plan_access

UsersFetcher = Callable[[], list[dict[str, Any]]]


class SupabaseAdminError(RuntimeError):
    pass


@dataclass
class SupabaseAdminClient:
    """Minimal Supabase Auth admin API wrapper (service role key)."""

    url: str | None
    service_role_key: str | None
    timeout: float = 15.0
    transport: Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None], tuple[int, Any]] | None = None

    @classmethod
    def from_env(cls) -> "SupabaseAdminClient":
        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("TRADINGAGENTS_SUPABASE_URL")
        return cls(url=url.rstrip("/") if url else None, service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None)

    def is_configured(self) -> bool:
        return bool(self.url and self.service_role_key)

    def __repr__(self) -> str:
        return f"SupabaseAdminClient(url={self.url!r}, service_role_key={'***' if self.service_role_key else None!r})"

    def list_users(self, *, per_page: int = 200, max_pages: int = 10) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            status, body = self._request("GET", f"/auth/v1/admin/users?page={page}&per_page={per_page}", None)
            if status >= 400:
                raise SupabaseAdminError(f"Supabase admin users -> {status}")
            batch = list((body or {}).get("users") or [])
            users.extend(batch)
            if len(batch) < per_page:
                break
        return users

    def update_user(self, user_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        status, body = self._request("PUT", f"/auth/v1/admin/users/{user_id}", payload)
        if status >= 400:
            raise SupabaseAdminError(f"Supabase admin update -> {status}: {str(body)[:120]}")
        return body or {}

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None) -> tuple[int, Any]:
        if not self.is_configured():
            raise SupabaseAdminError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        headers = {"apikey": str(self.service_role_key), "Authorization": f"Bearer {self.service_role_key}", "Content-Type": "application/json"}
        transport = self.transport or self._requests_transport
        return transport(method, f"{self.url}{path}", headers, body)

    def _requests_transport(self, method: str, url: str, headers: Mapping[str, str], body: Mapping[str, Any] | None) -> tuple[int, Any]:
        import requests

        from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

        apply_system_truststore_if_available()
        response = requests.request(method, url, headers=dict(headers), json=body, timeout=self.timeout)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"message": response.text[:200]}


def list_members(repo: StorageRepository, supabase: SupabaseAdminClient, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    users = supabase.list_users()
    items = []
    for user in users:
        user_id = str(user.get("id") or "")
        access = resolve_plan_access(repo, user_id, now=now)
        subscription = repo.get_subscription(user_id) or {}
        channel = repo.get_notification_channel(user_id, "telegram") or {}
        role = str(((user.get("app_metadata") or {}).get("role")) or "member")
        period_end = access.period_end
        remaining_days = max(0, (period_end - now).days) if period_end else None
        items.append(
            {
                "user_id": user_id,
                "email": user.get("email"),
                "role": role,
                "created_at": user.get("created_at"),
                "last_sign_in_at": user.get("last_sign_in_at"),
                "email_confirmed": bool(user.get("email_confirmed_at")),
                "plan": access.plan.id,
                "plan_name": access.plan.name,
                "status": access.status,
                "period_end": period_end.isoformat() if period_end else None,
                "remaining_days": remaining_days,
                "trial_ends_at": access.trial_ends_at.isoformat() if access.trial_ends_at else None,
                "has_billing_key": bool(subscription.get("billing_key")),
                "last_payment_at": _iso(subscription.get("last_payment_at")),
                "failure_count": int(subscription.get("failure_count") or 0),
                "telegram_linked": bool(channel.get("external_id") and channel.get("enabled")),
            }
        )
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    summary = {
        "member_count": len(items),
        "paid_count": sum(1 for item in items if item["plan"] in PAID_PLANS and item["status"] == "active"),
        "trial_count": sum(1 for item in items if item["status"] == "trialing"),
        "admin_count": sum(1 for item in items if item["role"] == "admin"),
        "telegram_linked_count": sum(1 for item in items if item["telegram_linked"]),
    }
    return {"status": "available", "items": items, "summary": summary, "plans": [PLANS[name].as_dict() for name in ("free", "daily", "pro")]}


def grant_member_plan(repo: StorageRepository, user_id: str, *, plan: str, days: int = 30, actor: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Operator override: put a member on a plan for ``days`` (no payment), or back to free."""

    now = now or datetime.now(timezone.utc)
    if plan not in PLANS:
        raise ValueError("plan must be free, daily, or pro")
    existing = repo.get_subscription(user_id) or {}
    if plan == "free":
        subscription_id = repo.upsert_subscription(
            SubscriptionInput(user_id=user_id, plan="free", status="inactive", provider=str(existing.get("provider") or "portone"), customer_key=existing.get("customer_key"), billing_key=existing.get("billing_key"), trial_ends_at=_aware(existing.get("trial_ends_at")), current_period_start=None, current_period_end=None, metadata={**dict(existing.get("metadata_json") or {}), "operator_override": "free"})
        )
        status = "inactive"
        period_end = None
    else:
        if days <= 0 or days > 366:
            raise ValueError("days must be between 1 and 366")
        base = _aware(existing.get("current_period_end")) if existing.get("status") == "active" and _aware(existing.get("current_period_end")) and _aware(existing["current_period_end"]) > now else now
        period_end = base + timedelta(days=days)
        subscription_id = repo.upsert_subscription(
            SubscriptionInput(user_id=user_id, plan=plan, status="active", provider=str(existing.get("provider") or "portone"), customer_key=existing.get("customer_key"), billing_key=existing.get("billing_key"), trial_ends_at=_aware(existing.get("trial_ends_at")), current_period_start=now, current_period_end=period_end, last_payment_id=existing.get("last_payment_id"), last_payment_at=_aware(existing.get("last_payment_at")), failure_count=0, metadata={**dict(existing.get("metadata_json") or {}), "operator_override": f"{plan}:{days}d"})
        )
        status = "active"
    repo.record_billing_event(BillingEventInput(event_type="operator.plan_granted", user_id=user_id, subscription_id=subscription_id, status=status, message=f"{plan} {days}d by {actor or 'operator'}" if plan != "free" else f"free by {actor or 'operator'}"))
    return {"user_id": user_id, "plan": plan, "status": status, "period_end": period_end.isoformat() if period_end else None}


def set_member_role(supabase: SupabaseAdminClient, user_id: str, role: str) -> dict[str, Any]:
    if role not in {"admin", "member"}:
        raise ValueError("role must be admin or member")
    result = supabase.update_user(user_id, {"app_metadata": {"role": role}})
    return {"user_id": user_id, "role": str(((result.get("app_metadata") or {}).get("role")) or role)}


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

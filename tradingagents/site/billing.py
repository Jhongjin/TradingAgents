"""Subscription plans, plan gating, and PortOne (포트원) billing.

Positioning: the paid plans sell a *research tool* — earlier access to the
daily harness, the full debate transcripts, and per-member analysis quotas.
Nothing here recommends trades to an individual or places orders; the public
notices and terms keep that boundary, and this module keeps the gate rules in
one place so the API and pages agree.

Plan gate rules (KST):

* ``free``      – harness runs up to the previous trading day, decision
                  ledger without the debate transcript, 3 analysis requests
                  per day.
* ``trialing``  – 14 days of the ``daily`` plan after the member opts in.
* ``daily``     – today's runs as soon as they are stored, full debate detail,
                  20 analysis requests per day.
* ``pro``       – ``daily`` plus custom harness parameters and JSON API
                  access (60 analysis requests per day).

PortOne V2 flow:

1. The browser asks ``POST /api/billing/checkout`` for SDK parameters and
   calls ``PortOne.requestIssueBillingKey`` (card / 카카오페이 / 네이버페이).
2. PortOne posts ``BillingKey.Issued`` to the webhook; the server stores the
   key and charges the first month through ``POST /payments/{id}/billing-key``.
3. PortOne posts ``Transaction.Paid``; the server re-reads the payment from
   the API (never trusting the webhook body alone), then activates the plan
   for 30 days.
4. A daily worker charges billing keys whose period ends today.

The HTTP transport is injectable so every step is unit-tested without the
network; production uses ``requests`` with the corporate truststore.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from tradingagents.storage import BillingEventInput, StorageRepository, SubscriptionInput

KST = ZoneInfo("Asia/Seoul")
PORTONE_API_BASE = "https://api.portone.io"
TRIAL_DAYS = 14
PERIOD_DAYS = 30
WEBHOOK_TOLERANCE_SECONDS = 300
MAX_PAYMENT_FAILURES = 3


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_krw: int
    tagline: str
    features: tuple[str, ...]
    analysis_requests_per_day: int
    active_requests_limit: int
    same_day_harness: bool
    debate_transcript: bool
    custom_harness: bool
    api_access: bool

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["features"] = list(self.features)
        return payload


PLANS: dict[str, Plan] = {
    "free": Plan(
        id="free",
        name="무료",
        price_krw=0,
        tagline="전일 하네스와 공개 성적표",
        features=("전일 실행 하네스 원장", "공개 5·20일 성적표", "종목 분석실 기본 정보", "분석 요청 하루 3회"),
        analysis_requests_per_day=3,
        active_requests_limit=2,
        same_day_harness=False,
        debate_transcript=False,
        custom_harness=False,
        api_access=False,
    ),
    "daily": Plan(
        id="daily",
        name="데일리 패스",
        price_krw=10_000,
        tagline="아침 8시, 오늘의 호가 도착합니다",
        features=("당일 하네스 실행 즉시 열람", "강세·약세·판정관·리스크 패널 토론 전문", "분석 요청 하루 20회 · 관심종목 10개", "가상계좌 자동 추적과 세 가지 테마", "광고 없음"),
        analysis_requests_per_day=20,
        active_requests_limit=5,
        same_day_harness=True,
        debate_transcript=True,
        custom_harness=False,
        api_access=False,
    ),
    "pro": Plan(
        id="pro",
        name="프로",
        price_krw=30_000,
        tagline="내 규칙으로 하네스를 돌립니다",
        features=("데일리 패스 전부", "사용자 지정 유니버스·리스크 파라미터", "본인 KIS 모의투자 키 연동 (주문 초안은 직접 승인)", "주간 PDF 리포트와 JSON API", "분석 요청 하루 60회"),
        analysis_requests_per_day=60,
        active_requests_limit=10,
        same_day_harness=True,
        debate_transcript=True,
        custom_harness=True,
        api_access=True,
    ),
}

PAID_PLANS = ("daily", "pro")

RESEARCH_TOOL_NOTICES = [
    "TradingAgents Korea는 리서치 도구입니다. 하네스 결과와 AI 토론은 이용자가 스스로 판단하기 위한 분석 자료이며 특정 종목의 매매를 권유하지 않습니다.",
    "유료 플랜은 분석 도구의 이용 범위(열람 시점, 토론 전문, 요청 횟수)를 넓히는 것이며 수익을 보장하지 않습니다.",
    "실계좌 주문·자동매매·투자일임 기능은 어떤 플랜에도 포함되지 않습니다.",
    "결제 후 7일 이내에는 전액 환불되며, 이후에는 남은 기간을 일할 계산해 환불합니다.",
]


@dataclass(frozen=True)
class PlanAccess:
    user_id: str | None
    plan: Plan
    status: str  # anonymous | free | trialing | active | past_due | canceled
    period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    subscription_id: str | None = None

    @property
    def is_paid(self) -> bool:
        return self.plan.id in PAID_PLANS and self.status in {"trialing", "active"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "plan": self.plan.as_dict(),
            "status": self.status,
            "is_paid": self.is_paid,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "trial_ends_at": self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            "subscription_id": self.subscription_id,
        }


def resolve_plan_access(repo: StorageRepository | None, user_id: str | None, *, now: datetime | None = None) -> PlanAccess:
    """Map a member (or anonymous visitor) to the plan they may use right now."""

    now = now or datetime.now(timezone.utc)
    if user_id is None:
        return PlanAccess(user_id=None, plan=PLANS["free"], status="anonymous")
    if repo is None:
        return PlanAccess(user_id=user_id, plan=PLANS["free"], status="free")
    row = repo.get_subscription(user_id)
    if not row:
        return PlanAccess(user_id=user_id, plan=PLANS["free"], status="free")
    plan = PLANS.get(str(row.get("plan") or "free"), PLANS["free"])
    status = str(row.get("status") or "inactive")
    period_end = _aware(row.get("current_period_end"))
    trial_end = _aware(row.get("trial_ends_at"))
    if status == "trialing":
        if trial_end and trial_end > now:
            return PlanAccess(user_id, PLANS["daily"], "trialing", period_end=trial_end, trial_ends_at=trial_end, subscription_id=str(row["id"]))
        return PlanAccess(user_id, PLANS["free"], "free", trial_ends_at=trial_end, subscription_id=str(row["id"]))
    if status == "active" and plan.id in PAID_PLANS:
        if period_end is None or period_end + timedelta(days=2) > now:  # 2-day grace for renewal delays
            return PlanAccess(user_id, plan, "active", period_end=period_end, subscription_id=str(row["id"]))
        return PlanAccess(user_id, PLANS["free"], "past_due", period_end=period_end, subscription_id=str(row["id"]))
    if status == "past_due":
        return PlanAccess(user_id, PLANS["free"], "past_due", period_end=period_end, subscription_id=str(row["id"]))
    return PlanAccess(user_id, PLANS["free"], "canceled" if status == "canceled" else "free", period_end=period_end, subscription_id=str(row["id"]))


def start_trial(repo: StorageRepository, user_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Grant the 14-day daily-plan trial once per member."""

    now = now or datetime.now(timezone.utc)
    existing = repo.get_subscription(user_id)
    if existing and (existing.get("trial_ends_at") or existing.get("status") in {"active", "trialing"}):
        raise ValueError("이미 체험을 사용했거나 유료 플랜을 이용 중입니다.")
    trial_end = now + timedelta(days=TRIAL_DAYS)
    subscription_id = repo.upsert_subscription(
        SubscriptionInput(
            user_id=user_id,
            plan="daily",
            status="trialing",
            provider="portone",
            customer_key=(existing or {}).get("customer_key") or _customer_key(user_id),
            trial_ends_at=trial_end,
            current_period_start=now,
            current_period_end=trial_end,
            metadata={"source": "trial"},
        )
    )
    repo.record_billing_event(BillingEventInput(event_type="trial.started", user_id=user_id, subscription_id=subscription_id, status="trialing", message=f"{TRIAL_DAYS}일 체험 시작"))
    return {"subscription_id": subscription_id, "plan": "daily", "status": "trialing", "trial_ends_at": trial_end.isoformat()}


def cancel_at_period_end(repo: StorageRepository, user_id: str) -> dict[str, Any]:
    row = repo.get_subscription(user_id)
    if not row or row.get("status") not in {"active", "trialing"}:
        raise ValueError("해지할 유료 플랜이 없습니다.")
    repo.upsert_subscription(_input_from_row(row, cancel_at_period_end=True))
    repo.record_billing_event(BillingEventInput(event_type="subscription.cancel_requested", user_id=user_id, subscription_id=str(row["id"]), status=str(row.get("status"))))
    return {"status": str(row.get("status")), "cancel_at_period_end": True, "current_period_end": _iso(row.get("current_period_end"))}


# ------------------------------------------------------------------ gating
def gate_harness_payload(payload: Mapping[str, Any] | None, access: PlanAccess, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Apply the plan rules to a harness run payload.

    Free visitors see the run only once its ``as_of_date`` is before today
    (KST) and never see the debate transcript inside ``detail``; paid members
    see everything. The response says what was withheld and why.
    """

    if payload is None:
        return None
    if access.plan.same_day_harness:
        result = dict(payload)
        result["plan_gate"] = {"plan": access.plan.id, "status": access.status, "locked": False}
        return result
    today = (now or datetime.now(KST)).astimezone(KST).date()
    run = payload.get("run") or {}
    as_of = _coerce_date(run.get("as_of_date"))
    locked_today = bool(as_of and as_of >= today)
    decisions = []
    for item in payload.get("decisions") or []:
        trimmed = dict(item)
        detail = dict(trimmed.get("detail") or {})
        confirmation = dict(detail.get("confirmation") or {})
        raw = confirmation.pop("raw", None)
        # Keep one-line excerpts per debate role for the public page; the full
        # transcript (arguments, rebuttals, risk views) stays behind the plan.
        if raw and not locked_today:
            excerpts = debate_excerpts(raw)
            if excerpts:
                confirmation["excerpts"] = excerpts
        if confirmation:
            detail["confirmation"] = confirmation
        trimmed["detail"] = detail
        if locked_today:
            for key in ("quantity", "entry_price", "stop_price", "take_profit_price", "confirmation_rating", "confirmation_confidence"):
                trimmed[key] = None
            trimmed["ticker_code"] = None
            trimmed["ticker_name"] = "데일리 패스에서 공개"
            trimmed["stock_path"] = "/pricing"
            trimmed["reasons"] = ["당일 실행 결과는 데일리 패스 회원에게 즉시 열립니다."]
            trimmed["detail"] = {}
            trimmed["locked"] = True
        decisions.append(trimmed)
    result = dict(payload)
    result["decisions"] = decisions
    result["plan_gate"] = {
        "plan": access.plan.id,
        "status": access.status,
        "locked": locked_today,
        "debate_transcript": False,
        "reason": "당일 하네스는 데일리 패스부터 실행 즉시 열립니다. 무료 플랜은 다음 거래일부터 열람할 수 있습니다." if locked_today else "토론 전문은 데일리 패스부터 열람할 수 있습니다.",
        "upgrade_path": "/pricing",
    }
    return result


EXCERPT_ROLES = ("bull", "bear", "judge", "risk_panel")


def debate_excerpts(raw: Mapping[str, Any], *, limit: int = 160) -> dict[str, str]:
    """Short public excerpts (one line per role) from a stored debate transcript."""

    turns = ((raw or {}).get("debate") or {}).get("turns") or {}
    excerpts: dict[str, str] = {}
    for role in EXCERPT_ROLES:
        data = (turns.get(role) or {}).get("data") or {}
        if role in {"bull", "bear"}:
            text = data.get("thesis") or data.get("summary") or ""
        elif role == "judge":
            text = data.get("rationale") or data.get("summary") or ""
        else:
            parts = []
            if data.get("stop_loss_pct") is not None:
                parts.append(f"손절 {-abs(_float(data.get('stop_loss_pct'))) * 100:+.0f}%")
            if data.get("take_profit_pct") is not None:
                parts.append(f"익절 {abs(_float(data.get('take_profit_pct'))) * 100:+.0f}%")
            if data.get("risk_score") is not None:
                parts.append(f"위험 점수 {_float(data.get('risk_score')):.2f}")
            text = (" · ".join(parts) + ". " if parts else "") + str(data.get("neutral_view") or data.get("summary") or "")
        text = str(text).strip()
        if text:
            excerpts[role] = text[:limit] + ("…" if len(text) > limit else "")
    return excerpts


def latest_visible_run_id(repo: StorageRepository | None, access: PlanAccess, *, now: datetime | None = None) -> str | None:
    """For free visitors pick the newest run dated before today; paid members get the newest."""

    if repo is None:
        return None
    try:
        runs = repo.list_harness_runs(limit=20)
    except Exception:
        return None
    if not runs:
        return None
    if access.plan.same_day_harness:
        return str(runs[0]["id"])
    today = (now or datetime.now(KST)).astimezone(KST).date()
    for run in runs:
        as_of = _coerce_date(run.get("as_of_date"))
        if as_of and as_of < today:
            return str(run["id"])
    return str(runs[0]["id"])  # only today's runs exist: return it locked


# ---------------------------------------------------------------- PortOne
Transport = Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None], tuple[int, Mapping[str, Any]]]


class PortOneError(RuntimeError):
    pass


@dataclass
class PortOneConfig:
    api_secret: str | None
    store_id: str | None
    channel_key: str | None
    webhook_secret: str | None

    @classmethod
    def from_env(cls) -> "PortOneConfig":
        return cls(
            api_secret=os.getenv("PORTONE_API_SECRET") or None,
            store_id=os.getenv("PORTONE_STORE_ID") or None,
            channel_key=os.getenv("PORTONE_CHANNEL_KEY") or None,
            webhook_secret=os.getenv("PORTONE_WEBHOOK_SECRET") or None,
        )

    def is_configured(self) -> bool:
        return bool(self.api_secret and self.store_id and self.channel_key)

    def __repr__(self) -> str:
        return f"PortOneConfig(store_id={self.store_id!r}, channel_key={'***' if self.channel_key else None!r}, api_secret={'***' if self.api_secret else None!r}, webhook_secret={'***' if self.webhook_secret else None!r})"


@dataclass
class PortOneClient:
    config: PortOneConfig
    transport: Transport | None = None
    timeout: float = 15.0

    def get_payment(self, payment_id: str) -> Mapping[str, Any]:
        status, body = self._request("GET", f"/payments/{payment_id}", None)
        if status >= 400:
            raise PortOneError(f"PortOne GET /payments/{payment_id} -> {status}: {_message(body)}")
        return body

    def get_billing_key(self, billing_key: str) -> Mapping[str, Any]:
        """Billing key detail (customer id, customData) — the Issued webhook carries only the key."""

        status, body = self._request("GET", f"/billing-keys/{billing_key}", None)
        if status >= 400:
            raise PortOneError(f"PortOne GET /billing-keys/{billing_key} -> {status}: {_message(body)}")
        return body

    def pay_with_billing_key(self, *, payment_id: str, billing_key: str, amount: int, order_name: str, customer_id: str, custom_data: str | None = None) -> Mapping[str, Any]:
        body = {
            "billingKey": billing_key,
            "orderName": order_name,
            "customer": {"id": customer_id},
            "amount": {"total": int(amount)},
            "currency": "KRW",
        }
        if custom_data:
            body["customData"] = custom_data
        status, response = self._request("POST", f"/payments/{payment_id}/billing-key", body)
        if status >= 400:
            raise PortOneError(f"PortOne billing-key payment failed ({status}): {_message(response)}")
        return response

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None) -> tuple[int, Mapping[str, Any]]:
        if not self.config.api_secret:
            raise PortOneError("PORTONE_API_SECRET is not configured")
        headers = {"Authorization": f"PortOne {self.config.api_secret}", "Content-Type": "application/json"}
        transport = self.transport or self._requests_transport
        return transport(method, PORTONE_API_BASE + path, headers, body)

    def _requests_transport(self, method: str, url: str, headers: Mapping[str, str], body: Mapping[str, Any] | None) -> tuple[int, Mapping[str, Any]]:
        import requests

        from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

        apply_system_truststore_if_available()
        response = requests.request(method, url, headers=dict(headers), json=body, timeout=self.timeout)
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text[:300]}
        return response.status_code, payload


def verify_webhook_signature(headers: Mapping[str, str], body: bytes, secret: str | None, *, now: float | None = None) -> None:
    """Standard-Webhooks verification used by PortOne V2 (raises on failure)."""

    if not secret:
        raise PortOneError("PORTONE_WEBHOOK_SECRET is not configured")
    lowered = {str(key).lower(): str(value) for key, value in headers.items()}
    msg_id = lowered.get("webhook-id")
    timestamp = lowered.get("webhook-timestamp")
    signatures = lowered.get("webhook-signature")
    if not msg_id or not timestamp or not signatures:
        raise PortOneError("missing webhook signature headers")
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise PortOneError("invalid webhook timestamp") from exc
    current = int(now if now is not None else time.time())
    if abs(current - sent_at) > WEBHOOK_TOLERANCE_SECONDS:
        raise PortOneError("webhook timestamp outside tolerance")
    key = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    key_bytes = base64.b64decode(key)
    expected = base64.b64encode(hmac.new(key_bytes, f"{msg_id}.{timestamp}.".encode("utf-8") + body, hashlib.sha256).digest()).decode("ascii")
    for candidate in signatures.split():
        provided = candidate.split(",", 1)[1] if "," in candidate else candidate
        if hmac.compare_digest(provided, expected):
            return
    raise PortOneError("webhook signature mismatch")


def sign_webhook(body: bytes, secret: str, *, msg_id: str = "msg_test", timestamp: int | None = None) -> dict[str, str]:
    """Produce Standard-Webhooks headers (used by tests and local simulation)."""

    ts = int(timestamp if timestamp is not None else time.time())
    key = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    signature = base64.b64encode(hmac.new(base64.b64decode(key), f"{msg_id}.{ts}.".encode("utf-8") + body, hashlib.sha256).digest()).decode("ascii")
    return {"webhook-id": msg_id, "webhook-timestamp": str(ts), "webhook-signature": f"v1,{signature}"}


def build_checkout_payload(user_id: str, plan_id: str, config: PortOneConfig, *, redirect_url: str | None = None) -> dict[str, Any]:
    """Parameters the browser passes to the PortOne SDK to issue a billing key."""

    plan = PLANS.get(plan_id)
    if plan is None or plan.id not in PAID_PLANS:
        raise ValueError("plan must be daily or pro")
    if not config.is_configured():
        raise PortOneError("결제 설정이 아직 준비되지 않았습니다 (PORTONE_STORE_ID / PORTONE_CHANNEL_KEY).")
    return {
        "provider": "portone",
        "sdk": "https://cdn.portone.io/v2/browser-sdk.js",
        "method": "requestIssueBillingKey",
        "params": {
            "storeId": config.store_id,
            "channelKey": config.channel_key,
            "billingKeyMethod": "CARD",
            "issueId": f"bk-{user_id[:8]}-{secrets.token_hex(6)}",
            "issueName": f"TradingAgents Korea {plan.name} 정기결제",
            "customer": {"customerId": _customer_key(user_id)},
            "customData": _custom_data(user_id, plan.id),
            "redirectUrl": redirect_url,
        },
        "plan": plan.as_dict(),
        "notices": RESEARCH_TOOL_NOTICES,
    }


def handle_portone_webhook(repo: StorageRepository, event: Mapping[str, Any], client: PortOneClient, *, now: datetime | None = None) -> dict[str, Any]:
    """Apply one verified webhook event. Idempotent per (payment_id, type)."""

    now = now or datetime.now(timezone.utc)
    event_type = str(event.get("type") or "")
    data = event.get("data") or {}
    if event_type == "BillingKey.Issued":
        return _on_billing_key_issued(repo, data, client, now=now)
    if event_type in {"Transaction.Paid", "Transaction.Failed", "Transaction.Cancelled"}:
        return _on_transaction(repo, event_type, data, client, now=now)
    if event_type == "BillingKey.Deleted":
        return _on_billing_key_deleted(repo, data, now=now)
    return {"handled": False, "event_type": event_type}


def _on_billing_key_issued(repo: StorageRepository, data: Mapping[str, Any], client: PortOneClient, *, now: datetime) -> dict[str, Any]:
    billing_key = str(data.get("billingKey") or "")
    if not billing_key:
        return {"handled": False, "event_type": "BillingKey.Issued", "reason": "missing billing key"}
    custom = _parse_custom_data(data.get("customData"))
    customer_id = str(((data.get("customer") or {}).get("id")) or custom.get("customer_key") or "")
    if not customer_id and not custom.get("user_id"):
        # PortOne's webhook body carries only the key: read customer/customData from the API.
        info = client.get_billing_key(billing_key)
        custom = _parse_custom_data(info.get("customData"))
        customer_id = str(((info.get("customer") or {}).get("id")) or custom.get("customer_key") or "")
        if str(info.get("status") or "ISSUED").upper() not in {"ISSUED", "READY"}:
            return {"handled": False, "event_type": "BillingKey.Issued", "reason": f"billing key status {info.get('status')}"}
    user_id = custom.get("user_id") or _user_from_customer_key(customer_id)
    plan_id = custom.get("plan") or "daily"
    if not user_id:
        return {"handled": False, "event_type": "BillingKey.Issued", "reason": "billing key has no member"}
    existing = repo.get_subscription(user_id) or {}
    subscription_id = repo.upsert_subscription(
        _merge_input(existing, user_id=user_id, plan=plan_id, status=str(existing.get("status") or "inactive") if existing.get("status") in {"active", "trialing"} else "inactive", customer_key=customer_id or _customer_key(user_id), billing_key=billing_key)
    )
    repo.record_billing_event(BillingEventInput(event_type="billing_key.issued", user_id=user_id, subscription_id=subscription_id, status="issued", payload={"plan": plan_id}))
    charge = charge_subscription(repo, user_id, client, now=now, reason="first_payment")
    return {"handled": True, "event_type": "BillingKey.Issued", "subscription_id": subscription_id, "charge": charge}


def _on_transaction(repo: StorageRepository, event_type: str, data: Mapping[str, Any], client: PortOneClient, *, now: datetime) -> dict[str, Any]:
    payment_id = str(data.get("paymentId") or "")
    if not payment_id:
        return {"handled": False, "event_type": event_type, "reason": "missing paymentId"}
    if repo.billing_event_exists(payment_id=payment_id, event_type=event_type):
        return {"handled": True, "event_type": event_type, "duplicate": True}
    payment = client.get_payment(payment_id)
    status = str(payment.get("status") or "")
    custom = _parse_custom_data(payment.get("customData"))
    customer_id = str(((payment.get("customer") or {}).get("id")) or "")
    user_id = custom.get("user_id") or _user_from_customer_key(customer_id)
    amount = _amount(payment)
    if not user_id:
        return {"handled": False, "event_type": event_type, "reason": "payment has no member"}
    existing = repo.get_subscription(user_id) or {}
    if event_type == "Transaction.Paid" and status == "PAID":
        plan_id = custom.get("plan") or str(existing.get("plan") or "daily")
        plan = PLANS.get(plan_id, PLANS["daily"])
        if amount != plan.price_krw:
            repo.record_billing_event(BillingEventInput(event_type="payment.amount_mismatch", user_id=user_id, payment_id=payment_id, amount=Decimal(amount), status=status, message=f"expected {plan.price_krw}"))
            return {"handled": False, "event_type": event_type, "reason": "amount mismatch"}
        period_start = _aware(existing.get("current_period_end")) if existing.get("status") == "active" and _aware(existing.get("current_period_end")) and _aware(existing["current_period_end"]) > now else now
        period_end = period_start + timedelta(days=PERIOD_DAYS)
        subscription_id = repo.upsert_subscription(
            _merge_input(existing, user_id=user_id, plan=plan.id, status="active", customer_key=customer_id or _customer_key(user_id), current_period_start=period_start, current_period_end=period_end, last_payment_id=payment_id, last_payment_at=now, failure_count=0, trial_ends_at=existing.get("trial_ends_at"), cancel_at_period_end=False)
        )
        repo.record_billing_event(BillingEventInput(event_type=event_type, user_id=user_id, subscription_id=subscription_id, payment_id=payment_id, amount=Decimal(amount), status=status, message=f"{plan.name} {PERIOD_DAYS}일 활성화", payload={"period_end": period_end.isoformat()}))
        return {"handled": True, "event_type": event_type, "subscription_id": subscription_id, "plan": plan.id, "period_end": period_end.isoformat()}
    if event_type == "Transaction.Failed":
        failures = int(existing.get("failure_count") or 0) + 1
        new_status = "past_due" if failures >= MAX_PAYMENT_FAILURES or existing.get("status") == "active" else str(existing.get("status") or "inactive")
        subscription_id = repo.upsert_subscription(_merge_input(existing, user_id=user_id, status=new_status if existing else "inactive", failure_count=failures)) if existing else None
        repo.record_billing_event(BillingEventInput(event_type=event_type, user_id=user_id, subscription_id=subscription_id, payment_id=payment_id, amount=Decimal(amount) if amount else None, status=status, message=_message(payment)))
        return {"handled": True, "event_type": event_type, "failure_count": failures}
    repo.record_billing_event(BillingEventInput(event_type=event_type, user_id=user_id, subscription_id=str(existing.get("id")) if existing else None, payment_id=payment_id, amount=Decimal(amount) if amount else None, status=status))
    return {"handled": True, "event_type": event_type, "status": status}


def _on_billing_key_deleted(repo: StorageRepository, data: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    billing_key = str(data.get("billingKey") or "")
    customer_id = str(((data.get("customer") or {}).get("id")) or "")
    user_id = _user_from_customer_key(customer_id)
    if not user_id:
        return {"handled": False, "event_type": "BillingKey.Deleted"}
    existing = repo.get_subscription(user_id)
    if existing and existing.get("billing_key") == billing_key:
        repo.upsert_subscription(_merge_input(existing, user_id=user_id, billing_key=None, cancel_at_period_end=True))
        repo.record_billing_event(BillingEventInput(event_type="billing_key.deleted", user_id=user_id, subscription_id=str(existing["id"]), status="deleted"))
    return {"handled": True, "event_type": "BillingKey.Deleted"}


def charge_subscription(repo: StorageRepository, user_id: str, client: PortOneClient, *, now: datetime | None = None, reason: str = "renewal") -> dict[str, Any]:
    """Charge a member's billing key for one period. Activation happens on the Paid webhook."""

    now = now or datetime.now(timezone.utc)
    row = repo.get_subscription(user_id)
    if not row or not row.get("billing_key"):
        return {"charged": False, "reason": "no billing key"}
    plan = PLANS.get(str(row.get("plan") or ""), None)
    if plan is None or plan.id not in PAID_PLANS:
        return {"charged": False, "reason": "not a paid plan"}
    if row.get("cancel_at_period_end") and reason == "renewal":
        repo.upsert_subscription(_merge_input(row, user_id=user_id, status="canceled"))
        repo.record_billing_event(BillingEventInput(event_type="subscription.canceled", user_id=user_id, subscription_id=str(row["id"]), status="canceled", message="기간 종료로 해지"))
        return {"charged": False, "reason": "canceled at period end"}
    payment_id = f"sub-{user_id[:8]}-{now.strftime('%Y%m%d')}-{secrets.token_hex(4)}"
    try:
        response = client.pay_with_billing_key(
            payment_id=payment_id,
            billing_key=str(row["billing_key"]),
            amount=plan.price_krw,
            order_name=f"TradingAgents Korea {plan.name} ({reason})",
            customer_id=str(row.get("customer_key") or _customer_key(user_id)),
            custom_data=_custom_data(user_id, plan.id),
        )
    except PortOneError as exc:
        failures = int(row.get("failure_count") or 0) + 1
        repo.upsert_subscription(_merge_input(row, user_id=user_id, failure_count=failures, status="past_due" if failures >= MAX_PAYMENT_FAILURES else str(row.get("status"))))
        repo.record_billing_event(BillingEventInput(event_type="payment.request_failed", user_id=user_id, subscription_id=str(row["id"]), payment_id=payment_id, amount=Decimal(plan.price_krw), status="failed", message=str(exc)[:300]))
        return {"charged": False, "reason": str(exc)[:200], "failure_count": failures}
    repo.record_billing_event(BillingEventInput(event_type="payment.requested", user_id=user_id, subscription_id=str(row["id"]), payment_id=payment_id, amount=Decimal(plan.price_krw), status="requested", message=reason, payload=dict(response)))
    return {"charged": True, "payment_id": payment_id, "amount": plan.price_krw}


def process_subscription_renewals(repo: StorageRepository, client: PortOneClient, *, now: datetime | None = None, limit: int = 100) -> dict[str, Any]:
    """Charge every active paid subscription whose period ends within the next day."""

    now = now or datetime.now(timezone.utc)
    due = repo.list_subscriptions_due(before=now + timedelta(days=1), limit=limit)
    results = []
    for row in due:
        if _aware(row.get("last_payment_at")) and _aware(row["last_payment_at"]) > now - timedelta(days=PERIOD_DAYS - 2):
            results.append({"user_id": row["user_id"], "charged": False, "reason": "recently paid"})
            continue
        results.append({"user_id": row["user_id"], **charge_subscription(repo, str(row["user_id"]), client, now=now)})
    return {"due_count": len(due), "charged_count": sum(1 for item in results if item.get("charged")), "results": results}


# ----------------------------------------------------------------- helpers
def _customer_key(user_id: str) -> str:
    return f"ta-{user_id}"


def _user_from_customer_key(customer_key: str) -> str | None:
    if customer_key.startswith("ta-") and len(customer_key) > 3:
        return customer_key[3:]
    return None


def _custom_data(user_id: str, plan_id: str) -> str:
    import json

    return json.dumps({"user_id": user_id, "plan": plan_id, "customer_key": _customer_key(user_id)}, separators=(",", ":"))


def _parse_custom_data(value: Any) -> dict[str, str]:
    import json

    if not value:
        return {}
    if isinstance(value, Mapping):
        return {str(k): str(v) for k, v in value.items()}
    parsed: Any = value
    # PortOne stores customData as a string and may return it JSON-encoded twice.
    for _ in range(3):
        if isinstance(parsed, Mapping):
            break
        try:
            parsed = json.loads(str(parsed))
        except ValueError:
            return {}
    return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, Mapping) else {}


def _amount(payment: Mapping[str, Any]) -> int:
    amount = payment.get("amount") or {}
    if isinstance(amount, Mapping):
        return int(_float(amount.get("total") or amount.get("paid") or 0))
    return int(_float(amount))


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _message(body: Mapping[str, Any]) -> str:
    return str(body.get("message") or body.get("type") or body.get("status") or "")[:300]


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


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _input_from_row(row: Mapping[str, Any], **overrides: Any) -> SubscriptionInput:
    return _merge_input(row, user_id=str(row["user_id"]), **overrides)


def _merge_input(row: Mapping[str, Any], *, user_id: str, **overrides: Any) -> SubscriptionInput:
    base = {
        "plan": str(row.get("plan") or "free"),
        "status": str(row.get("status") or "inactive"),
        "provider": str(row.get("provider") or "portone"),
        "customer_key": row.get("customer_key"),
        "billing_key": row.get("billing_key"),
        "trial_ends_at": _aware(row.get("trial_ends_at")),
        "current_period_start": _aware(row.get("current_period_start")),
        "current_period_end": _aware(row.get("current_period_end")),
        "cancel_at_period_end": bool(row.get("cancel_at_period_end")),
        "last_payment_id": row.get("last_payment_id"),
        "last_payment_at": _aware(row.get("last_payment_at")),
        "failure_count": int(row.get("failure_count") or 0),
        "metadata": dict(row.get("metadata_json") or {}),
    }
    base.update(overrides)
    return SubscriptionInput(user_id=user_id, **base)

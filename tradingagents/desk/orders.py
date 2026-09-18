"""What has to be true before the desk sends an order, and what it writes after.

The broker will do whatever it is told. Everything that stops a typo becoming
a trade lives here: a cap on one order, a cap on the day, and a typed
confirmation that cannot be clicked through. Every attempt is written to the
same hash-chained ledger the harness uses, before the broker is called and
again after, so a crash mid-flight still leaves a record that it was tried.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

from tradingagents.execution.audit import AuditLedger

# Defaults chosen to be annoying rather than generous. Raising them is a
# decision someone makes in .env, which is a place you have to go on purpose.
DEFAULT_MAX_ORDER_KRW = 1_000_000
DEFAULT_MAX_DAILY_KRW = 3_000_000
DEFAULT_MAX_DAILY_ORDERS = 10

ORDER_EVENT = "desk.order"


class OrderRefused(RuntimeError):
    """The desk declined before the broker was ever asked."""


@dataclass(frozen=True)
class Limits:
    max_order_krw: int = DEFAULT_MAX_ORDER_KRW
    max_daily_krw: int = DEFAULT_MAX_DAILY_KRW
    max_daily_orders: int = DEFAULT_MAX_DAILY_ORDERS

    @classmethod
    def from_env(cls) -> "Limits":
        return cls(
            max_order_krw=_int("TRADINGAGENTS_DESK_MAX_ORDER_KRW", DEFAULT_MAX_ORDER_KRW),
            max_daily_krw=_int("TRADINGAGENTS_DESK_MAX_DAILY_KRW", DEFAULT_MAX_DAILY_KRW),
            max_daily_orders=_int("TRADINGAGENTS_DESK_MAX_DAILY_ORDERS", DEFAULT_MAX_DAILY_ORDERS),
        )


def _int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def ledger() -> AuditLedger:
    return AuditLedger.from_env(
        os.path.join(os.path.expanduser("~"), ".tradingagents", "desk", "orders.jsonl")
    )


def today_spent(book: AuditLedger, *, when: date | None = None) -> tuple[int, int]:
    """Won committed and orders placed today, read back out of the ledger.

    Counted from what was written rather than from a number held in memory, so
    restarting the desk does not reset the day's cap.

    An attempt the broker refused does not count. The market being shut is not
    a trade, and letting 14580 eat the daily cap would mean a closed market
    locks you out of the open one. An attempt with no ending does count: if it
    is not known whether the order landed, the cautious reading is that it did.
    """

    day = (when or datetime.now(timezone.utc).astimezone().date()).isoformat()
    attempts: dict[str, dict[str, Any]] = {}
    for record in book.iter_records():
        if record.event_type != ORDER_EVENT:
            continue
        payload = record.payload or {}
        if str(payload.get("date")) != day:
            continue
        key = str(payload.get("attempt") or f"seq-{record.sequence}")
        entry = attempts.setdefault(key, {"amount": 0, "failed": False})
        if str(payload.get("stage")) == "sent":
            entry["amount"] = int(payload.get("amount") or 0)
        elif str(payload.get("stage")) == "failed":
            entry["failed"] = True

    live = [entry for entry in attempts.values() if not entry["failed"] and entry["amount"]]
    return sum(entry["amount"] for entry in live), len(live)


def check(
    *,
    side: str,
    code: str,
    quantity: int,
    price: int,
    confirmation: str,
    mode: str,
    limits: Limits,
    spent_today: int,
    orders_today: int,
) -> int:
    """Everything that must hold before an order is sent. Returns the amount.

    ``confirmation`` is the quantity typed a second time. A button that only
    needs one click is a button that gets clicked by accident, and the number
    retyped is the one thing a slip is unlikely to reproduce.
    """

    if side not in {"buy", "sell"}:
        raise OrderRefused("매수 또는 매도만 가능합니다.")
    if quantity <= 0 or price <= 0:
        raise OrderRefused("수량과 가격은 0보다 커야 합니다.")
    if confirmation.strip() != str(quantity):
        raise OrderRefused(f"확인란에 수량 {quantity} 를 그대로 입력해 주세요.")

    amount = quantity * price
    if amount > limits.max_order_krw:
        raise OrderRefused(
            f"1회 한도 {limits.max_order_krw:,}원을 넘습니다. 이 주문은 {amount:,}원입니다."
        )
    if orders_today >= limits.max_daily_orders:
        raise OrderRefused(f"오늘 주문 {limits.max_daily_orders}건을 이미 채웠습니다.")
    if spent_today + amount > limits.max_daily_krw:
        raise OrderRefused(
            f"일일 한도 {limits.max_daily_krw:,}원을 넘습니다. "
            f"오늘 {spent_today:,}원 사용, 이 주문 {amount:,}원."
        )
    if mode not in {"paper", "live"}:
        raise OrderRefused("계좌 모드를 알 수 없습니다.")
    return amount


def new_attempt() -> str:
    """An id shared by every line of one order, so they can be tied together."""

    import uuid

    return uuid.uuid4().hex[:12]


def record(
    book: AuditLedger,
    *,
    stage: str,
    attempt: str,
    side: str,
    code: str,
    quantity: int,
    price: int,
    amount: int,
    mode: str,
    result: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """One line in the ledger. Written before the broker call and after it."""

    book.append(ORDER_EVENT, {
        "stage": stage,
        "attempt": attempt,
        "date": datetime.now(timezone.utc).astimezone().date().isoformat(),
        "mode": mode,
        "side": side,
        "code": code,
        "quantity": quantity,
        "price": price,
        "amount": amount,
        "result": dict(result) if result else None,
        "error": error,
    })

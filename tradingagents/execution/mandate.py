"""Mandate gate: account-level constraints every order must satisfy.

Inspired by Vibe-Trading's mandate/compliance gates and kill switch. The gate
runs *after* the LLM and the position sizer and *before* any broker adapter.
It is deliberately dumb: fixed limits, explicit reasons, fail-closed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Mapping

from .models import OrderIntent, OrderSide


@dataclass(frozen=True)
class TradingMandate:
    max_position_weight: float = 0.25
    max_gross_exposure: float = 1.0
    max_positions: int = 10
    max_order_notional: float | None = None
    max_daily_orders: int = 20
    max_daily_loss_pct: float = 0.03
    instrument_whitelist: tuple[str, ...] = ()
    instrument_blacklist: tuple[str, ...] = ()
    allow_short: bool = False
    require_regular_session: bool = False
    kill_switch_active: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.max_position_weight <= 1:
            raise ValueError("max_position_weight must be between 0 and 1")
        if not 0 < self.max_gross_exposure <= 3:
            raise ValueError("max_gross_exposure must be between 0 and 3")
        if self.max_positions <= 0:
            raise ValueError("max_positions must be positive")
        if self.max_daily_orders <= 0:
            raise ValueError("max_daily_orders must be positive")
        if not 0 <= self.max_daily_loss_pct <= 1:
            raise ValueError("max_daily_loss_pct must be between 0 and 1")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MandateContext:
    equity: float
    cash: float
    positions: Mapping[str, float]  # ticker -> market value
    price: float
    orders_today: int = 0
    realized_pnl_today: float = 0.0
    session_open: bool = True
    as_of: datetime | None = None


@dataclass(frozen=True)
class MandateDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MandateGate:
    def __init__(self, mandate: TradingMandate | None = None):
        self.mandate = mandate or TradingMandate()

    def evaluate(self, order: OrderIntent, context: MandateContext) -> MandateDecision:
        mandate = self.mandate
        reasons: list[str] = []
        checks: dict[str, bool] = {}
        ticker = order.ticker.upper()

        checks["kill_switch"] = not mandate.kill_switch_active
        if mandate.kill_switch_active:
            reasons.append("kill switch active")

        checks["instrument_allowed"] = _instrument_allowed(ticker, mandate)
        if not checks["instrument_allowed"]:
            reasons.append(f"{ticker} is not in the allowed instrument set")

        checks["session"] = context.session_open or not mandate.require_regular_session
        if not checks["session"]:
            reasons.append("outside regular trading session")

        checks["daily_orders"] = context.orders_today < mandate.max_daily_orders
        if not checks["daily_orders"]:
            reasons.append(f"daily order cap {mandate.max_daily_orders} reached")

        daily_loss = (-context.realized_pnl_today / context.equity) if context.equity > 0 else 0.0
        checks["daily_loss"] = daily_loss < mandate.max_daily_loss_pct or order.side == OrderSide.SELL
        if not checks["daily_loss"]:
            reasons.append(f"daily loss {daily_loss:.2%} exceeds limit {mandate.max_daily_loss_pct:.2%}")

        notional = order.quantity * context.price
        checks["order_notional"] = mandate.max_order_notional is None or notional <= mandate.max_order_notional
        if not checks["order_notional"]:
            reasons.append(f"order notional {notional:,.0f} exceeds {mandate.max_order_notional:,.0f}")

        if order.side == OrderSide.BUY:
            current_value = float(context.positions.get(ticker, 0.0))
            projected_weight = (current_value + notional) / context.equity if context.equity > 0 else 1.0
            checks["position_weight"] = projected_weight <= mandate.max_position_weight + 1e-9
            if not checks["position_weight"]:
                reasons.append(f"projected weight {projected_weight:.2%} exceeds {mandate.max_position_weight:.2%}")

            gross = sum(float(value) for value in context.positions.values()) + notional
            checks["gross_exposure"] = (gross / context.equity if context.equity > 0 else 1.0) <= mandate.max_gross_exposure + 1e-9
            if not checks["gross_exposure"]:
                reasons.append("gross exposure limit exceeded")

            new_position = ticker not in context.positions or context.positions.get(ticker, 0.0) <= 0
            checks["position_count"] = (len([v for v in context.positions.values() if v > 0]) + (1 if new_position else 0)) <= mandate.max_positions
            if not checks["position_count"]:
                reasons.append(f"position count would exceed {mandate.max_positions}")

            checks["cash"] = notional <= context.cash + 1e-9
            if not checks["cash"]:
                reasons.append("insufficient cash")
        else:
            checks["short"] = mandate.allow_short or float(context.positions.get(ticker, 0.0)) > 0
            if not checks["short"]:
                reasons.append("short selling is not allowed")

        return MandateDecision(approved=not reasons, reasons=reasons, checks=checks)


def _instrument_allowed(ticker: str, mandate: TradingMandate) -> bool:
    if ticker in {item.upper() for item in mandate.instrument_blacklist}:
        return False
    if mandate.instrument_whitelist and ticker not in {item.upper() for item in mandate.instrument_whitelist}:
        return False
    return True


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()

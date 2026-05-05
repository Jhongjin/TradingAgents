"""Risk gates for paper execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import floor

from .models import OrderIntent, TradeSignal


@dataclass(frozen=True)
class RiskLimits:
    max_position_weight: float = 0.25
    min_cash_reserve: float = 0.0
    max_order_notional: float | None = None
    allow_short: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.max_position_weight <= 1:
            raise ValueError("max_position_weight must be between 0 and 1")
        if self.min_cash_reserve < 0:
            raise ValueError("min_cash_reserve cannot be negative")
        if self.max_order_notional is not None and self.max_order_notional <= 0:
            raise ValueError("max_order_notional must be positive when set")


class RiskManager:
    """Apply conservative caps before orders reach the paper broker."""

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def apply_to_signal(self, signal: TradeSignal) -> TradeSignal:
        target_weight = signal.target_weight
        if target_weight is None:
            return signal
        if target_weight < 0 and not self.limits.allow_short:
            target_weight = 0.0
        capped = min(target_weight, self.limits.max_position_weight)
        return replace(signal, target_weight=capped)

    def apply_to_order(self, order: OrderIntent, price: float) -> OrderIntent | None:
        if price <= 0:
            raise ValueError("Order price must be positive")
        if self.limits.max_order_notional is None:
            return order
        max_quantity = floor(self.limits.max_order_notional / price)
        if max_quantity <= 0:
            return None
        if order.quantity <= max_quantity:
            return order
        return replace(order, quantity=max_quantity)

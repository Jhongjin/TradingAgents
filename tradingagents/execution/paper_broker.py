"""Immediate-fill broker for paper trading and deterministic tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .models import Fill, OrderIntent, OrderSide, TradeSignal
from .portfolio import Portfolio
from .risk import RiskLimits, RiskManager


@dataclass
class PaperBroker:
    portfolio: Portfolio = field(default_factory=Portfolio)
    risk_manager: RiskManager = field(default_factory=RiskManager)
    commission_per_trade: float = 0.0
    slippage_bps: float = 0.0
    execution_rules: object | None = None

    @classmethod
    def with_limits(
        cls,
        initial_cash: float = 100_000.0,
        limits: RiskLimits | None = None,
        commission_per_trade: float = 0.0,
        slippage_bps: float = 0.0,
        currency: str = "USD",
        execution_rules: object | None = None,
    ) -> "PaperBroker":
        return cls(
            portfolio=Portfolio(cash=initial_cash, currency=currency),
            risk_manager=RiskManager(limits),
            commission_per_trade=commission_per_trade,
            slippage_bps=slippage_bps,
            execution_rules=execution_rules,
        )

    def create_order(
        self,
        signal: TradeSignal,
        price: float,
        prices: Mapping[str, float] | None = None,
    ) -> OrderIntent | None:
        safe_signal = self.risk_manager.apply_to_signal(signal)
        order = self.portfolio.order_to_target_weight(
            safe_signal.ticker,
            price,
            safe_signal.target_weight,
            prices=prices,
            min_cash_reserve=self.risk_manager.limits.min_cash_reserve,
            reason=f"{safe_signal.rating}: {safe_signal.action}",
        )
        if order is None:
            return None
        return self.risk_manager.apply_to_order(order, price)

    def submit_order(self, order: OrderIntent, price: float) -> Fill:
        execution_price = self._execution_price(order.side, price)
        transaction_tax = self._transaction_tax(order, execution_price)
        fill = Fill(
            order=order,
            price=execution_price,
            quantity=order.quantity,
            commission=self.commission_per_trade,
            transaction_tax=transaction_tax,
        )
        self.portfolio.apply_fill(fill)
        return fill

    def rebalance(
        self,
        signal: TradeSignal,
        price: float,
        prices: Mapping[str, float] | None = None,
    ) -> Fill | None:
        order = self.create_order(signal, price, prices=prices)
        if order is None:
            return None
        return self.submit_order(order, price)

    def _execution_price(self, side: OrderSide, price: float) -> float:
        if price <= 0:
            raise ValueError("price must be positive")
        multiplier = self.slippage_bps / 10_000
        if side == OrderSide.BUY:
            raw_price = price * (1 + multiplier)
        else:
            raw_price = price * (1 - multiplier)
        if self.execution_rules is not None and hasattr(self.execution_rules, "round_price"):
            return float(self.execution_rules.round_price(raw_price, side=side))
        return raw_price

    def _transaction_tax(self, order: OrderIntent, execution_price: float) -> float:
        if order.side != OrderSide.SELL:
            return 0.0
        if self.execution_rules is None or not hasattr(self.execution_rules, "transaction_tax_rate"):
            return 0.0
        rate = float(self.execution_rules.transaction_tax_rate(order.ticker))
        return execution_price * order.quantity * rate

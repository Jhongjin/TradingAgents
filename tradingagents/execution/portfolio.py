"""Simple cash and position accounting for paper execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from typing import Mapping

from .models import Fill, OrderIntent, OrderSide


@dataclass
class Position:
    quantity: int = 0
    average_price: float = 0.0

    def market_value(self, price: float) -> float:
        return self.quantity * price


@dataclass
class Portfolio:
    cash: float = 100_000.0
    currency: str = "USD"
    positions: dict[str, Position] = field(default_factory=dict)

    def total_equity(self, prices: Mapping[str, float]) -> float:
        equity = self.cash
        for ticker, position in self.positions.items():
            if ticker not in prices:
                raise KeyError(f"Missing price for {ticker}")
            equity += position.market_value(prices[ticker])
        return equity

    def weight(self, ticker: str, prices: Mapping[str, float]) -> float:
        ticker = ticker.upper()
        equity = self.total_equity(prices)
        if equity <= 0:
            return 0.0
        position = self.positions.get(ticker, Position())
        return position.market_value(prices[ticker]) / equity

    def order_to_target_weight(
        self,
        ticker: str,
        price: float,
        target_weight: float | None,
        prices: Mapping[str, float] | None = None,
        min_cash_reserve: float = 0.0,
        reason: str = "",
    ) -> OrderIntent | None:
        if target_weight is None:
            return None
        if not 0 <= target_weight <= 1:
            raise ValueError("target_weight must be between 0 and 1")
        if price <= 0:
            raise ValueError("price must be positive")

        ticker = ticker.upper()
        all_prices = dict(prices or {})
        all_prices.setdefault(ticker, price)
        equity = self.total_equity(all_prices)
        current_quantity = self.positions.get(ticker, Position()).quantity
        current_value = current_quantity * price
        target_value = equity * target_weight
        delta_value = target_value - current_value
        quantity = floor(abs(delta_value) / price)

        if quantity <= 0:
            return None
        if delta_value > 0:
            max_affordable = floor(max(self.cash - min_cash_reserve, 0.0) / price)
            quantity = min(quantity, max_affordable)
            if quantity <= 0:
                return None
            return OrderIntent(ticker=ticker, side=OrderSide.BUY, quantity=quantity, reason=reason)

        quantity = min(quantity, current_quantity)
        if quantity <= 0:
            return None
        return OrderIntent(ticker=ticker, side=OrderSide.SELL, quantity=quantity, reason=reason)

    def apply_fill(self, fill: Fill) -> None:
        ticker = fill.order.ticker.upper()
        position = self.positions.get(ticker, Position())
        quantity = fill.quantity

        if fill.order.side == OrderSide.BUY:
            total_cost = quantity * fill.price + fill.commission + fill.transaction_tax
            if total_cost > self.cash + 1e-9:
                raise ValueError("Insufficient cash for paper fill")
            new_quantity = position.quantity + quantity
            if new_quantity <= 0:
                raise ValueError("Invalid resulting position quantity")
            position.average_price = (
                (position.quantity * position.average_price) + (quantity * fill.price)
            ) / new_quantity
            position.quantity = new_quantity
            self.cash -= total_cost
            self.positions[ticker] = position
            return

        if quantity > position.quantity:
            raise ValueError("Cannot sell more shares than the paper portfolio holds")
        self.cash += quantity * fill.price - fill.commission - fill.transaction_tax
        position.quantity -= quantity
        if position.quantity == 0:
            self.positions.pop(ticker, None)
        else:
            self.positions[ticker] = position

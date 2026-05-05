"""Manual portfolio calculations from user-entered trade history."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass
class ManualPosition:
    ticker_code: str
    ticker_name: str | None = None
    market: str = "KR"
    quantity: int = 0
    average_cost: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    total_taxes: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    @property
    def invested_cost(self) -> Decimal:
        return self.average_cost * Decimal(self.quantity)

    def market_value(self, current_price: Decimal) -> Decimal:
        return current_price * Decimal(self.quantity)

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        return self.market_value(current_price) - self.invested_cost


def calculate_manual_positions(trades: Iterable[dict]) -> dict[str, ManualPosition]:
    positions: dict[str, ManualPosition] = {}
    sorted_trades = sorted(trades, key=lambda row: (str(row["trade_date"]), str(row.get("created_at") or "")))

    for trade in sorted_trades:
        ticker = str(trade["ticker_code"]).upper()
        position = positions.setdefault(
            ticker,
            ManualPosition(
                ticker_code=ticker,
                ticker_name=trade.get("ticker_name"),
                market=trade.get("market") or "KR",
            ),
        )
        side = str(trade["side"]).lower()
        quantity = int(trade["quantity"])
        price = _decimal(trade["price"])
        fee = _decimal(trade.get("fee", 0))
        tax = _decimal(trade.get("tax", 0))
        if quantity <= 0:
            raise ValueError("manual trade quantity must be positive")
        if price <= 0:
            raise ValueError("manual trade price must be positive")

        position.total_fees += fee
        position.total_taxes += tax
        if side == "buy":
            previous_cost = position.average_cost * Decimal(position.quantity)
            added_cost = price * Decimal(quantity) + fee + tax
            new_quantity = position.quantity + quantity
            position.average_cost = (previous_cost + added_cost) / Decimal(new_quantity)
            position.quantity = new_quantity
            continue

        if side != "sell":
            raise ValueError("manual trade side must be buy or sell")
        if quantity > position.quantity:
            raise ValueError(f"manual trade sells more than the current {ticker} position")
        position.realized_pnl += (price - position.average_cost) * Decimal(quantity) - fee - tax
        position.quantity -= quantity
        if position.quantity == 0:
            position.average_cost = Decimal("0")

    return {ticker: position for ticker, position in positions.items() if position.quantity or position.realized_pnl}


def _decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

"""Shared execution models used by paper trading and backtests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class TradeSignal:
    """A portfolio target derived from an agent decision."""

    ticker: str
    rating: str
    action: str
    target_weight: Optional[float]
    rationale: str = ""


@dataclass(frozen=True)
class OrderIntent:
    """A market order request generated from a target portfolio weight."""

    ticker: str
    side: OrderSide
    quantity: int
    reason: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("Order quantity must be positive")


@dataclass(frozen=True)
class Fill:
    """An executed paper fill."""

    order: OrderIntent
    price: float
    quantity: int
    commission: float = 0.0
    transaction_tax: float = 0.0

    @property
    def notional(self) -> float:
        return self.price * self.quantity

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("Fill price must be positive")
        if self.quantity <= 0:
            raise ValueError("Fill quantity must be positive")
        if self.commission < 0:
            raise ValueError("Commission cannot be negative")
        if self.transaction_tax < 0:
            raise ValueError("Transaction tax cannot be negative")

"""Risk-based position sizing.

Borrowed from Binance-Agent's rule that every stop-loss hit should cost the
same fixed percentage of the account, and from AutoHedge's Risk agent output
(recommended size, max drawdown risk, risk score). The sizing is deterministic
so the LLM only decides *whether* to trade; *how much* is arithmetic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import floor
from typing import Any


@dataclass(frozen=True)
class PositionSizeRequest:
    ticker: str
    equity: float
    entry_price: float
    stop_price: float
    risk_percent_per_trade: float = 0.01
    max_position_weight: float = 0.25
    available_cash: float | None = None
    take_profit_price: float | None = None
    lot_size: int = 1

    def __post_init__(self) -> None:
        if self.equity <= 0:
            raise ValueError("equity must be positive")
        if self.entry_price <= 0:
            raise ValueError("entry_price must be positive")
        if self.stop_price <= 0:
            raise ValueError("stop_price must be positive")
        if self.stop_price >= self.entry_price:
            raise ValueError("stop_price must be below entry_price for a long position")
        if not 0 < self.risk_percent_per_trade <= 0.2:
            raise ValueError("risk_percent_per_trade must be between 0 and 0.2")
        if not 0 < self.max_position_weight <= 1:
            raise ValueError("max_position_weight must be between 0 and 1")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")


@dataclass(frozen=True)
class PositionSizePlan:
    ticker: str
    quantity: int
    entry_price: float
    stop_price: float
    take_profit_price: float | None
    notional: float
    weight: float
    risk_amount: float
    risk_percent: float
    reward_risk_ratio: float | None
    binding_constraint: str
    notes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def size_position(request: PositionSizeRequest) -> PositionSizePlan:
    """Return the largest quantity satisfying risk budget, weight cap, and cash.

    quantity = min(
        risk_budget / (entry - stop),      # fixed-fraction risk
        equity * max_weight / entry,       # concentration cap
        available_cash / entry,            # affordability
    )
    """

    per_share_risk = request.entry_price - request.stop_price
    risk_budget = request.equity * request.risk_percent_per_trade
    by_risk = floor(risk_budget / per_share_risk)
    by_weight = floor((request.equity * request.max_position_weight) / request.entry_price)
    by_cash = floor(request.available_cash / request.entry_price) if request.available_cash is not None else by_weight
    quantity = max(min(by_risk, by_weight, by_cash), 0)
    quantity -= quantity % request.lot_size

    if quantity == by_risk and by_risk <= by_weight and by_risk <= by_cash:
        binding = "risk_budget"
    elif quantity == by_weight and by_weight <= by_cash:
        binding = "max_position_weight"
    else:
        binding = "available_cash"

    notional = quantity * request.entry_price
    risk_amount = quantity * per_share_risk
    reward_risk = None
    if request.take_profit_price is not None and request.take_profit_price > request.entry_price:
        reward_risk = (request.take_profit_price - request.entry_price) / per_share_risk
    notes = []
    if quantity == 0:
        notes.append("계산된 수량이 0입니다. 손절폭이 너무 넓거나 자본이 부족합니다.")
    if reward_risk is not None and reward_risk < 1.5:
        notes.append(f"손익비 {reward_risk:.2f}가 1.5 미만입니다. 진입 근거를 다시 확인하세요.")
    return PositionSizePlan(
        ticker=request.ticker.upper(),
        quantity=quantity,
        entry_price=request.entry_price,
        stop_price=request.stop_price,
        take_profit_price=request.take_profit_price,
        notional=round(notional, 4),
        weight=round(notional / request.equity, 6),
        risk_amount=round(risk_amount, 4),
        risk_percent=round(risk_amount / request.equity, 6),
        reward_risk_ratio=round(reward_risk, 4) if reward_risk is not None else None,
        binding_constraint=binding,
        notes=notes,
    )


def stop_from_atr(entry_price: float, atr: float, multiplier: float = 2.0) -> float:
    """Volatility-scaled stop distance (entry minus ``multiplier`` ATRs)."""

    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if atr <= 0:
        raise ValueError("atr must be positive")
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    return max(entry_price - multiplier * atr, entry_price * 0.5)

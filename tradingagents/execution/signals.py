"""Convert TradingAgents decisions into execution-layer signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tradingagents.agents.utils.rating import parse_rating

from .models import TradeSignal


@dataclass(frozen=True)
class SignalPolicy:
    """Default rating-to-target mapping for paper execution.

    Hold intentionally maps to ``None`` so the paper broker keeps the current
    position instead of forcing a rebalance to cash.
    """

    buy_weight: float = 0.25
    overweight_weight: float = 0.15
    underweight_weight: float = 0.05
    sell_weight: float = 0.0

    def target_for_rating(self, rating: str) -> Optional[float]:
        normalized = rating.strip().lower()
        if normalized == "buy":
            return self.buy_weight
        if normalized == "overweight":
            return self.overweight_weight
        if normalized == "underweight":
            return self.underweight_weight
        if normalized == "sell":
            return self.sell_weight
        return None


def signal_from_decision(
    ticker: str,
    decision_text: str,
    policy: SignalPolicy | None = None,
) -> TradeSignal:
    """Build a paper-execution signal from a final PM decision or rating."""

    policy = policy or SignalPolicy()
    rating = parse_rating(decision_text)
    target_weight = policy.target_for_rating(rating)
    action = _action_for_rating(rating)
    return TradeSignal(
        ticker=ticker.upper(),
        rating=rating,
        action=action,
        target_weight=target_weight,
        rationale=decision_text,
    )


def _action_for_rating(rating: str) -> str:
    normalized = rating.strip().lower()
    if normalized in {"buy", "overweight"}:
        return "increase"
    if normalized == "underweight":
        return "trim"
    if normalized == "sell":
        return "exit"
    return "hold"

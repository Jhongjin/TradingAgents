"""Deterministic paper simulation from a single AI trade signal."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from .kr_rules import KoreaTradingRules
from .models import Fill, OrderSide, TradeSignal
from .paper_broker import PaperBroker
from .risk import RiskLimits


@dataclass(frozen=True)
class PaperSimulationConfig:
    initial_cash: float = 10_000_000.0
    take_profit_pct: float = 0.08
    stop_loss_pct: float = 0.05
    max_holding_days: int = 20
    max_position_weight: float = 0.25
    slippage_bps: float = 3.0
    commission_per_trade: float = 0.0
    currency: str = "KRW"

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be positive")
        if self.stop_loss_pct <= 0:
            raise ValueError("stop_loss_pct must be positive")
        if self.max_holding_days <= 0:
            raise ValueError("max_holding_days must be positive")
        if not 0 < self.max_position_weight <= 1:
            raise ValueError("max_position_weight must be between 0 and 1")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")
        if self.commission_per_trade < 0:
            raise ValueError("commission_per_trade cannot be negative")


@dataclass(frozen=True)
class PaperSimulationResult:
    status: str
    ticker: str
    currency: str
    initial_cash: float
    final_equity: float
    portfolio_return: float
    events: list[dict[str, Any]] = field(default_factory=list)
    entry_date: str | None = None
    exit_date: str | None = None
    exit_reason: str | None = None
    holding_days: int = 0
    trade_return: float | None = None
    target_weight: float | None = None
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ticker": self.ticker,
            "currency": self.currency,
            "initial_cash": self.initial_cash,
            "final_equity": self.final_equity,
            "portfolio_return": self.portfolio_return,
            "target_weight": self.target_weight,
            "entry_date": self.entry_date,
            "exit_date": self.exit_date,
            "exit_reason": self.exit_reason,
            "holding_days": self.holding_days,
            "trade_return": self.trade_return,
            "events": self.events,
            "message": self.message,
        }


def simulate_single_position(
    signal: TradeSignal,
    price_points: Iterable[Mapping[str, Any]],
    *,
    config: PaperSimulationConfig | None = None,
) -> PaperSimulationResult:
    """Open and close one paper position from daily OHLCV points.

    The simulator never sends orders to a broker. It reuses the paper broker so
    tick rounding, cash accounting, and Korean sell-side transaction tax stay
    consistent with the rest of the execution foundation.
    """

    config = config or PaperSimulationConfig()
    points = _normalize_points(price_points)
    if len(points) < 2:
        raise ValueError("price_points must contain at least two close prices")

    ticker = signal.ticker.upper()
    target_weight = signal.target_weight
    if target_weight is None or target_weight <= 0:
        return PaperSimulationResult(
            status="skipped",
            ticker=ticker,
            currency=config.currency,
            initial_cash=config.initial_cash,
            final_equity=config.initial_cash,
            portfolio_return=0.0,
            target_weight=target_weight,
            message="signal_did_not_open_position",
        )

    rules = KoreaTradingRules() if config.currency.upper() == "KRW" else None
    broker = PaperBroker.with_limits(
        initial_cash=config.initial_cash,
        limits=RiskLimits(max_position_weight=config.max_position_weight),
        commission_per_trade=config.commission_per_trade,
        slippage_bps=config.slippage_bps,
        currency=config.currency,
        execution_rules=rules,
    )
    entry_point = points[0]
    entry_fill = broker.rebalance(signal, entry_point["close"], prices={ticker: entry_point["close"]})
    if entry_fill is None:
        return PaperSimulationResult(
            status="skipped",
            ticker=ticker,
            currency=config.currency,
            initial_cash=config.initial_cash,
            final_equity=config.initial_cash,
            portfolio_return=0.0,
            target_weight=target_weight,
            message="paper_order_not_created",
        )

    events = [_event_from_fill("entry", entry_point["date"], entry_fill, reason=signal.action or signal.rating)]
    exit_point, exit_reason, holding_days = _select_exit_point(entry_fill.price, points[1:], config)
    if exit_point is None:
        final_equity = broker.portfolio.total_equity({ticker: entry_point["close"]})
        return PaperSimulationResult(
            status="open",
            ticker=ticker,
            currency=config.currency,
            initial_cash=config.initial_cash,
            final_equity=final_equity,
            portfolio_return=(final_equity / config.initial_cash) - 1,
            events=events,
            entry_date=entry_point["date"],
            holding_days=0,
            target_weight=target_weight,
            message="waiting_for_exit_price",
        )

    exit_signal = TradeSignal(
        ticker=ticker,
        rating="Sell",
        action="paper_exit",
        target_weight=0.0,
        rationale=exit_reason,
    )
    exit_fill = broker.rebalance(exit_signal, exit_point["close"], prices={ticker: exit_point["close"]})
    if exit_fill is not None:
        events.append(_event_from_fill("exit", exit_point["date"], exit_fill, reason=exit_reason))

    final_equity = broker.portfolio.total_equity({ticker: exit_point["close"]})
    return PaperSimulationResult(
        status="closed",
        ticker=ticker,
        currency=config.currency,
        initial_cash=config.initial_cash,
        final_equity=final_equity,
        portfolio_return=(final_equity / config.initial_cash) - 1,
        events=events,
        entry_date=entry_point["date"],
        exit_date=exit_point["date"],
        exit_reason=exit_reason,
        holding_days=holding_days,
        trade_return=(exit_fill.price / entry_fill.price) - 1 if exit_fill else None,
        target_weight=target_weight,
        message="paper_position_closed",
    )


def _select_exit_point(
    entry_price: float,
    candidates: list[dict[str, Any]],
    config: PaperSimulationConfig,
) -> tuple[dict[str, Any] | None, str | None, int]:
    if not candidates:
        return None, None, 0
    last_index = len(candidates) - 1
    for index, point in enumerate(candidates, start=1):
        move = (point["close"] / entry_price) - 1
        if move >= config.take_profit_pct:
            return point, "take_profit", index
        if move <= -config.stop_loss_pct:
            return point, "stop_loss", index
        if index >= config.max_holding_days:
            return point, "max_holding_days", index
        if index - 1 == last_index:
            return point, "latest_close", index
    return None, None, 0


def _event_from_fill(kind: str, event_date: str, fill: Fill, *, reason: str) -> dict[str, Any]:
    return {
        "type": kind,
        "side": fill.order.side.value if isinstance(fill.order.side, OrderSide) else str(fill.order.side),
        "date": event_date,
        "price": fill.price,
        "quantity": fill.quantity,
        "notional": fill.notional,
        "commission": fill.commission,
        "transaction_tax": fill.transaction_tax,
        "reason": reason,
    }


def _normalize_points(points: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for point in points:
        close = point.get("close")
        if close is None:
            continue
        close_value = float(close)
        if close_value <= 0:
            continue
        normalized.append({"date": _date_key(point.get("date")), "close": close_value})
    return sorted(normalized, key=lambda item: item["date"])


def _date_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)

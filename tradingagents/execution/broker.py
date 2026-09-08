"""Broker adapter protocol plus the in-memory paper implementation.

The protocol is the seam between the harness and any venue (FinceptTerminal
and Vibe-Trading both expose a uniform broker interface). The pipeline only
ever talks to ``BrokerAdapter``; whether that is the local paper broker, the
KIS 모의투자 (virtual trading) server, or a real account is decided by
configuration and the live-trading gate, never by the caller.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol

from .models import Fill, OrderIntent, OrderSide
from .paper_broker import PaperBroker


@dataclass(frozen=True)
class BrokerOrderResult:
    status: str  # accepted | filled | rejected | dry_run
    order: OrderIntent
    broker: str
    order_id: str | None = None
    fill: Fill | None = None
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "broker": self.broker,
            "order_id": self.order_id,
            "message": self.message,
            "order": {
                "ticker": self.order.ticker,
                "side": self.order.side.value,
                "quantity": self.order.quantity,
                "reason": self.order.reason,
            },
            "raw": self.raw,
        }
        if self.fill is not None:
            payload["fill"] = {
                "price": self.fill.price,
                "quantity": self.fill.quantity,
                "commission": self.fill.commission,
                "transaction_tax": self.fill.transaction_tax,
            }
        return payload


@dataclass(frozen=True)
class BrokerAccountSnapshot:
    broker: str
    cash: float
    equity: float
    positions: dict[str, dict[str, float]]
    currency: str = "KRW"
    is_paper: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class BrokerAdapter(Protocol):
    name: str
    is_paper: bool

    def account_snapshot(self, prices: Mapping[str, float] | None = None) -> BrokerAccountSnapshot: ...

    def place_order(self, order: OrderIntent, *, price: float, dry_run: bool = False) -> BrokerOrderResult: ...


class PaperBrokerAdapter:
    """Adapter around the existing immediate-fill ``PaperBroker``."""

    name = "paper"
    is_paper = True

    def __init__(self, broker: PaperBroker):
        self.broker = broker

    def account_snapshot(self, prices: Mapping[str, float] | None = None) -> BrokerAccountSnapshot:
        prices = dict(prices or {})
        portfolio = self.broker.portfolio
        positions: dict[str, dict[str, float]] = {}
        for ticker, position in portfolio.positions.items():
            price = float(prices.get(ticker, position.average_price))
            positions[ticker] = {
                "quantity": float(position.quantity),
                "average_price": float(position.average_price),
                "market_value": float(position.quantity * price),
            }
        equity = portfolio.cash + sum(item["market_value"] for item in positions.values())
        return BrokerAccountSnapshot(
            broker=self.name,
            cash=float(portfolio.cash),
            equity=float(equity),
            positions=positions,
            currency=portfolio.currency,
            is_paper=True,
        )

    def place_order(self, order: OrderIntent, *, price: float, dry_run: bool = False) -> BrokerOrderResult:
        if dry_run:
            return BrokerOrderResult(status="dry_run", order=order, broker=self.name, message="dry run, no fill")
        try:
            fill = self.broker.submit_order(order, price)
        except ValueError as exc:
            return BrokerOrderResult(status="rejected", order=order, broker=self.name, message=str(exc))
        return BrokerOrderResult(
            status="filled",
            order=order,
            broker=self.name,
            order_id=f"paper-{order.ticker}-{order.side.value}-{fill.quantity}",
            fill=fill,
            message="paper fill",
        )


def order_side_label(side: OrderSide) -> str:
    return "매수" if side == OrderSide.BUY else "매도"

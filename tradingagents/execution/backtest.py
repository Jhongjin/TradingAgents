"""Small deterministic backtest runner for generated TradingAgents ratings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from .models import Fill
from .kr_rules import KoreaTradingRules
from .paper_broker import PaperBroker
from .risk import RiskLimits
from .signals import SignalPolicy, signal_from_decision


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    fills: list[Fill]
    final_equity: float
    total_return: float


class BacktestEngine:
    """Run paper rebalances from date-keyed decisions over a price series."""

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        risk_limits: RiskLimits | None = None,
        signal_policy: SignalPolicy | None = None,
        commission_per_trade: float = 0.0,
        slippage_bps: float = 0.0,
        currency: str = "USD",
        execution_rules: object | None = None,
    ):
        self.initial_cash = initial_cash
        self.currency = currency
        self.signal_policy = signal_policy or SignalPolicy()
        rules = execution_rules
        if rules is None and currency.upper() == "KRW":
            rules = KoreaTradingRules()
        self.broker = PaperBroker.with_limits(
            initial_cash=initial_cash,
            limits=risk_limits,
            commission_per_trade=commission_per_trade,
            slippage_bps=slippage_bps,
            currency=currency,
            execution_rules=rules,
        )

    def run(
        self,
        ticker: str,
        prices: pd.DataFrame,
        decisions: Mapping[object, str],
    ) -> BacktestResult:
        frame = _normalize_price_frame(prices)
        decision_map = {_date_key(k): v for k, v in decisions.items()}
        fills: list[Fill] = []
        rows = []

        for date, row in frame.iterrows():
            price = float(row["close"])
            key = _date_key(date)
            if key in decision_map:
                signal = signal_from_decision(ticker, decision_map[key], self.signal_policy)
                fill = self.broker.rebalance(signal, price, prices={ticker.upper(): price})
                if fill is not None:
                    fills.append(fill)

            position = self.broker.portfolio.positions.get(ticker.upper())
            quantity = position.quantity if position else 0
            equity = self.broker.portfolio.total_equity({ticker.upper(): price})
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "close": price,
                    "cash": self.broker.portfolio.cash,
                    "quantity": quantity,
                    "equity": equity,
                    "currency": self.currency,
                }
            )

        equity_curve = pd.DataFrame(rows).set_index("date")
        final_equity = float(equity_curve["equity"].iloc[-1])
        return BacktestResult(
            equity_curve=equity_curve,
            fills=fills,
            final_equity=final_equity,
            total_return=(final_equity / self.initial_cash) - 1,
        )


def _normalize_price_frame(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        raise ValueError("prices cannot be empty")
    frame = prices.copy()
    if "Date" in frame.columns:
        frame["Date"] = pd.to_datetime(frame["Date"])
        frame = frame.set_index("Date")
    elif "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.set_index("date")
    else:
        frame.index = pd.to_datetime(frame.index)

    close_col = None
    for candidate in ("Close", "close", "Adj Close", "adj_close"):
        if candidate in frame.columns:
            close_col = candidate
            break
    if close_col is None:
        raise ValueError("prices must include a Close or close column")
    return frame.rename(columns={close_col: "close"}).sort_index()


def _date_key(value: object) -> str:
    return pd.Timestamp(value).date().isoformat()

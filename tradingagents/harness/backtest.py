"""Replay the harness rules over past prices.

The live record starts the day the account started, which is no answer to "how
has this done". This runs the same rules the account runs, day by day, over
history: the same factor score, the same ranking, the same sizing with its cash
reserve and sector cap, the same stop, target and holding limit, and the same
fees and sell-side tax.

What it is not: the account's record. A simulation over past prices can only
ever be an estimate, and this one carries two biases worth naming out loud.
The universe is chosen today, so companies that were delisted along the way are
absent (survivorship). The AI debate is not replayed, because past debates were
never held. Both are stated wherever the result is published, and the result is
never merged into the live numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Mapping, Sequence

from tradingagents.analytics.risk_metrics import risk_summary
from tradingagents.execution import (
    KoreaTradingRules,
    OrderIntent,
    OrderSide,
    PaperBroker,
    RiskLimits,
)
from tradingagents.screener.factors import compute_factor_scores

SectorLookup = Callable[[str], str]


@dataclass(frozen=True)
class BacktestConfig:
    """The rules to replay. Defaults mirror the live account."""

    top_n: int = 5
    min_composite: float = 0.0
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    max_holding_days: int = 20
    max_positions: int = 10
    max_positions_per_sector: int = 2
    min_cash_reserve_pct: float = 0.10
    commission_rate: float = 0.00015
    initial_cash: float = 50_000_000.0
    history_window: int = 140
    min_history: int = 121
    factor_weights: Mapping[str, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {key: value for key, value in self.__dict__.items()}
        payload["factor_weights"] = dict(self.factor_weights) if self.factor_weights else None
        return payload


@dataclass
class BacktestResult:
    config: dict[str, Any]
    start_date: str
    end_date: str
    universe_size: int
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "universe_size": self.universe_size,
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "metrics": self.metrics,
            "notes": self.notes,
        }


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _indexed(points: Sequence[Mapping[str, Any]]) -> list[tuple[date, dict[str, Any]]]:
    rows: list[tuple[date, dict[str, Any]]] = []
    for point in points or ():
        when = _as_date(point.get("date"))
        close = point.get("close")
        if when is None or close in (None, "") or float(close) <= 0:
            continue
        rows.append((when, dict(point)))
    rows.sort(key=lambda item: item[0])
    return rows


def run_rule_backtest(
    *,
    history: Mapping[str, Sequence[Mapping[str, Any]]],
    names: Mapping[str, str] | None = None,
    start: date | str,
    end: date | str,
    config: BacktestConfig | None = None,
    sector_lookup: SectorLookup | None = None,
    benchmark: Mapping[str, float] | None = None,
) -> BacktestResult:
    """Run the rules over ``history`` and return the curve, the trades and the metrics."""

    config = config or BacktestConfig()
    names = dict(names or {})
    start_date = _as_date(start)
    end_date = _as_date(end)
    if start_date is None or end_date is None or start_date >= end_date:
        raise ValueError("start must be a date before end")

    series = {code: _indexed(points) for code, points in (history or {}).items()}
    series = {code: rows for code, rows in series.items() if len(rows) >= config.min_history}
    if not series:
        raise ValueError("no ticker had enough history to score")

    trading_days = sorted({when for rows in series.values() for when, _ in rows if start_date <= when <= end_date})
    if len(trading_days) < 2:
        raise ValueError("the window contains fewer than two trading days")

    closes_by_day: dict[date, dict[str, float]] = {}
    points_before: dict[str, list[dict[str, Any]]] = {code: [] for code in series}
    cursor = {code: 0 for code in series}

    broker = PaperBroker.with_limits(
        initial_cash=config.initial_cash,
        limits=RiskLimits(max_position_weight=1.0),
        commission_rate=config.commission_rate,
        currency="KRW",
        execution_rules=KoreaTradingRules(),
    )
    entry_dates: dict[str, date] = {}
    entry_index: dict[str, int] = {}
    targets: dict[str, tuple[float, float]] = {}
    trades: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    notes: list[str] = []
    sector_of = sector_lookup or (lambda code: "")

    for day_number, today in enumerate(trading_days):
        # advance each ticker's window to everything known on or before today
        prices: dict[str, float] = {}
        for code, rows in series.items():
            index = cursor[code]
            while index < len(rows) and rows[index][0] <= today:
                points_before[code].append(rows[index][1])
                index += 1
            cursor[code] = index
            if points_before[code] and _as_date(points_before[code][-1].get("date")) == today:
                prices[code] = float(points_before[code][-1]["close"])
        closes_by_day[today] = prices

        # ---------------------------------------------------------- exits
        for code in list(broker.portfolio.positions):
            position = broker.portfolio.positions[code]
            price = prices.get(code)
            if price is None or position.quantity <= 0:
                continue
            average = float(position.average_price)
            move = (price / average) - 1 if average else 0.0
            reason = None
            if move <= -config.stop_loss_pct:
                reason = "stop_loss"
            elif move >= config.take_profit_pct:
                reason = "take_profit"
            elif entry_index.get(code) is not None and (day_number - entry_index[code]) >= config.max_holding_days:
                reason = "max_holding_days"
            if reason is None:
                continue
            quantity = int(position.quantity)
            cash_before = float(broker.portfolio.cash)
            broker.submit_order(OrderIntent(ticker=code, side=OrderSide.SELL, quantity=quantity, reason=reason), price)
            proceeds = float(broker.portfolio.cash) - cash_before
            cost = average * quantity
            trades.append(
                {
                    "ticker_code": code,
                    "ticker_name": names.get(code, code),
                    "entry_date": entry_dates.get(code).isoformat() if entry_dates.get(code) else None,
                    "entry_price": round(average, 2),
                    "exit_date": today.isoformat(),
                    "exit_price": round(price, 2),
                    "quantity": quantity,
                    "exit_reason": reason,
                    "realized_pnl": round(proceeds - cost, 2),
                    "realized_return": round((proceeds / cost) - 1, 6) if cost else None,
                    "holding_days": day_number - entry_index.get(code, day_number),
                }
            )
            entry_dates.pop(code, None)
            entry_index.pop(code, None)
            targets.pop(code, None)

        # -------------------------------------------------------- entries
        held = set(broker.portfolio.positions)
        equity = float(broker.portfolio.cash) + sum(
            float(position.quantity) * prices.get(code, float(position.average_price))
            for code, position in broker.portfolio.positions.items()
        )
        if len(held) < config.max_positions:
            ranked: list[tuple[float, str]] = []
            for code, window in points_before.items():
                if code in held or code not in prices or len(window) < config.min_history:
                    continue
                factors = compute_factor_scores(window[-config.history_window :], weights=config.factor_weights)
                if factors.momentum_20d is None or factors.composite < config.min_composite:
                    continue
                ranked.append((factors.composite, code))
            ranked.sort(reverse=True)

            slot_weight = 1.0 / max(config.max_positions, 1)
            for _score, code in ranked[: config.top_n]:
                if len(broker.portfolio.positions) >= config.max_positions:
                    break
                sector = sector_of(code)
                if sector and sum(1 for other in broker.portfolio.positions if sector_of(other) == sector) >= config.max_positions_per_sector:
                    continue
                spendable = max(float(broker.portfolio.cash) - equity * config.min_cash_reserve_pct, 0.0)
                price = prices[code]
                budget = min(equity * slot_weight, spendable)
                quantity = int(budget // price)
                if quantity <= 0:
                    continue
                try:
                    broker.submit_order(OrderIntent(ticker=code, side=OrderSide.BUY, quantity=quantity, reason="backtest entry"), price)
                except Exception:
                    continue
                entry_dates[code] = today
                entry_index[code] = day_number
                targets[code] = (round(price * (1 + config.take_profit_pct), 2), round(price * (1 - config.stop_loss_pct), 2))

        holdings_value = sum(
            float(position.quantity) * prices.get(code, float(position.average_price))
            for code, position in broker.portfolio.positions.items()
        )
        curve.append(
            {
                "date": today.isoformat(),
                "cash": round(float(broker.portfolio.cash), 2),
                "holdings_value": round(holdings_value, 2),
                "equity": round(float(broker.portfolio.cash) + holdings_value, 2),
                "position_count": len(broker.portfolio.positions),
            }
        )

    equities = [point["equity"] for point in curve]
    summary = risk_summary(equities)
    wins = [trade for trade in trades if (trade.get("realized_return") or 0) > 0]
    holding_days = [trade["holding_days"] for trade in trades if trade.get("holding_days") is not None]
    metrics = {
        **summary.as_dict(),
        "trade_count": len(trades),
        "win_count": len(wins),
        "hit_rate": round(len(wins) / len(trades), 4) if trades else None,
        "average_holding_days": round(sum(holding_days) / len(holding_days), 1) if holding_days else None,
        "final_equity": equities[-1] if equities else None,
        "open_positions": len(broker.portfolio.positions),
    }
    if benchmark:
        first = next((benchmark.get(point["date"]) for point in curve if benchmark.get(point["date"])), None)
        last = next((benchmark.get(point["date"]) for point in reversed(curve) if benchmark.get(point["date"])), None)
        if first and last:
            metrics["benchmark_return"] = round((float(last) / float(first)) - 1, 6)
            if metrics.get("total_return") is not None:
                metrics["excess_return"] = round(float(metrics["total_return"]) - metrics["benchmark_return"], 6)

    notes.append("과거 가격으로 규칙만 재현한 모의 결과입니다. 실제 실행 기록이 아닙니다.")
    notes.append("대상 종목을 오늘 기준으로 고정했기 때문에 그사이 상장폐지된 종목은 빠져 있습니다.")
    notes.append("AI 토론은 재현하지 않았습니다. 과거의 토론은 존재하지 않기 때문입니다.")
    return BacktestResult(
        config=config.as_dict(),
        start_date=trading_days[0].isoformat(),
        end_date=trading_days[-1].isoformat(),
        universe_size=len(series),
        equity_curve=curve,
        trades=trades,
        metrics=metrics,
        notes=notes,
    )

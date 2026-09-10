"""Carry the harness paper account across runs.

The pipeline builds a fresh :class:`PaperBroker` on every invocation, so a
scheduled run had no holdings to exit and the account always looked untouched.
Nothing new is stored to fix that: every executed order is already a harness
decision row, so the account is rebuilt by replaying those fills through the
same broker that produced them. Cash, tick rounding and the Korean sell-side
tax therefore stay identical to a single long-running process.

Only non-dry runs count. Dry runs record intent without a fill and must never
move the account.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from tradingagents.execution import (
    KoreaTradingRules,
    OrderIntent,
    OrderSide,
    PaperBroker,
    PaperBrokerAdapter,
    RiskLimits,
)

FILLED_STATUSES = {"filled", "accepted"}

# The account's starting capital. A 10% slot of 10,000,000원 cannot buy a single
# share of a name priced near 2,000,000원, so the account could only ever hold
# cheap stocks. Raising the capital widens what is buyable; it does not change
# concentration, because every cap is a share of equity.
_FALLBACK_INITIAL_CASH = 50_000_000.0


def default_initial_cash() -> float:
    """Starting capital, overridable with TRADINGAGENTS_PAPER_INITIAL_CASH."""

    raw = os.getenv("TRADINGAGENTS_PAPER_INITIAL_CASH")
    if not raw:
        return _FALLBACK_INITIAL_CASH
    try:
        value = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return _FALLBACK_INITIAL_CASH
    return value if value > 0 else _FALLBACK_INITIAL_CASH


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drop NaN


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def fill_price(row: Mapping[str, Any]) -> float | None:
    """Price the order actually filled at.

    Entries record the planned entry price in its own column; exits only carry
    the broker result, so the fill inside ``detail_json`` is the single place
    both can be read from.
    """

    order = ((row.get("detail_json") or {}).get("order") or {}) if isinstance(row.get("detail_json"), Mapping) else {}
    price = _as_float((order.get("fill") or {}).get("price"))
    if price and price > 0:
        return price
    return _as_float(row.get("entry_price"))


def fill_quantity(row: Mapping[str, Any]) -> int:
    order = ((row.get("detail_json") or {}).get("order") or {}) if isinstance(row.get("detail_json"), Mapping) else {}
    for candidate in ((order.get("fill") or {}).get("quantity"), (order.get("order") or {}).get("quantity"), row.get("quantity")):
        value = _as_float(candidate)
        if value and value > 0:
            return int(value)
    return 0


def replay_fills(
    rows: Iterable[Mapping[str, Any]],
    *,
    initial_cash: float,
    max_position_weight: float = 0.2,
    currency: str = "KRW",
) -> tuple[PaperBroker, list[str]]:
    """Rebuild the paper broker by re-submitting every recorded fill in order."""

    broker = PaperBroker.with_limits(
        initial_cash=initial_cash,
        limits=RiskLimits(max_position_weight=max_position_weight),
        currency=currency,
        execution_rules=KoreaTradingRules(),
    )
    notes: list[str] = []
    for row in rows:
        stage = str(row.get("stage") or "")
        status = str(row.get("order_status") or "").lower()
        if status not in FILLED_STATUSES or stage not in {"ordered", "exit"}:
            continue
        code = str(row.get("ticker_code") or "").strip().upper()
        price = fill_price(row)
        quantity = fill_quantity(row)
        if not code or not price or price <= 0 or quantity <= 0:
            notes.append(f"skipped an unreadable fill for {code or 'unknown'}")
            continue
        side = OrderSide.BUY if stage == "ordered" else OrderSide.SELL
        if side == OrderSide.SELL:
            held = broker.portfolio.positions.get(code)
            available = int(getattr(held, "quantity", 0) or 0)
            if available <= 0:
                notes.append(f"skipped a sell for {code} with no recorded holding")
                continue
            quantity = min(quantity, available)
        try:
            # replay at the recorded fill price: slippage was already applied
            broker.submit_order(OrderIntent(ticker=code, side=side, quantity=quantity, reason="replay"), price)
        except Exception as exc:
            notes.append(f"could not replay {code} ({exc.__class__.__name__})")
    return broker, notes


def restore_paper_account(repo: Any, *, initial_cash: float | None = None, max_position_weight: float = 0.2, broker: str = "paper", limit: int = 2000) -> tuple[PaperBrokerAdapter | None, list[str]]:
    """Return a broker holding whatever the recorded harness fills add up to."""

    initial_cash = default_initial_cash() if initial_cash is None else initial_cash
    if repo is None or not hasattr(repo, "list_harness_fills"):
        return None, []
    try:
        rows = repo.list_harness_fills(broker=broker, limit=limit)
    except Exception as exc:
        return None, [f"paper account history unavailable ({exc.__class__.__name__}); starting from cash"]
    broker, notes = replay_fills(rows, initial_cash=initial_cash, max_position_weight=max_position_weight)
    held = len(broker.portfolio.positions)
    notes.insert(0, f"restored paper account from {len(rows)} recorded fills: {held} holding(s), cash {broker.portfolio.cash:,.0f}")
    return PaperBrokerAdapter(broker), notes


def build_paper_account_payload(
    repo: Any,
    *,
    initial_cash: float | None = None,
    current_prices: Mapping[str, float] | None = None,
    broker: str = "paper",
    limit: int = 2000,
) -> dict[str, Any]:
    """Holdings, closed trades and totals for the public paper-account view.

    Cash and quantities come from replaying the fills through the paper broker,
    so the numbers here match what the harness itself holds, the Korean
    sell-side transaction tax included.
    """

    initial_cash = default_initial_cash() if initial_cash is None else initial_cash
    if repo is None or not hasattr(repo, "list_harness_fills"):
        return {"status": "not_configured", "positions": [], "closed": [], "summary": {}}
    try:
        rows = list(repo.list_harness_fills(broker=broker, limit=limit))
    except Exception as exc:
        return {"status": "unavailable", "error": f"{exc.__class__.__name__}: {exc}", "positions": [], "closed": [], "summary": {}}

    cash = float(initial_cash)
    summary_when_empty = {
        "initial_cash": round(cash, 2),
        "cash": round(cash, 2),
        "holdings_value": 0.0,
        "equity": round(cash, 2),
        "total_return": 0.0,
        "realized_pnl": 0.0,
        "open_count": 0,
        "closed_count": 0,
        "win_count": 0,
        "hit_rate": None,
        "priced_count": 0,
    }
    if not rows:
        return {"status": "empty", "positions": [], "closed": [], "summary": summary_when_empty}

    prices = {str(code).upper(): float(value) for code, value in (current_prices or {}).items() if value}
    broker = PaperBroker.with_limits(
        initial_cash=initial_cash,
        limits=RiskLimits(max_position_weight=1.0),
        currency="KRW",
        execution_rules=KoreaTradingRules(),
    )
    lots: dict[str, dict[str, Any]] = {}
    closed: list[dict[str, Any]] = []
    realized_total = 0.0

    for row in rows:
        stage = str(row.get("stage") or "")
        status = str(row.get("order_status") or "").lower()
        if status not in FILLED_STATUSES or stage not in {"ordered", "exit"}:
            continue
        code = str(row.get("ticker_code") or "").strip().upper()
        price = fill_price(row)
        quantity = fill_quantity(row)
        if not code or not price or price <= 0 or quantity <= 0:
            continue
        when = _as_date(row.get("as_of_date"))
        held = broker.portfolio.positions.get(code)
        available = int(getattr(held, "quantity", 0) or 0)
        if stage == "exit":
            if available <= 0:
                continue
            quantity = min(quantity, available)
        average_before = float(getattr(held, "average_price", 0.0) or 0.0)
        cash_before = float(broker.portfolio.cash)
        side = OrderSide.BUY if stage == "ordered" else OrderSide.SELL
        try:
            broker.submit_order(OrderIntent(ticker=code, side=side, quantity=quantity, reason="replay"), price)
        except Exception:
            continue
        cash_after = float(broker.portfolio.cash)

        if stage == "ordered":
            lot = lots.setdefault(code, {"ticker_name": row.get("ticker_name") or code, "market": row.get("market"), "entry_date": when})
            lot["ticker_name"] = row.get("ticker_name") or lot.get("ticker_name") or code
            lot["market"] = row.get("market") or lot.get("market")
            if lot.get("entry_date") is None:
                lot["entry_date"] = when
            lot["target_price"] = _as_float(row.get("take_profit_price")) or lot.get("target_price")
            lot["stop_price"] = _as_float(row.get("stop_price")) or lot.get("stop_price")
            continue

        lot = lots.get(code, {})
        proceeds = cash_after - cash_before  # net of the sell-side transaction tax
        cost = average_before * quantity
        realized_total += proceeds - cost
        reasons = [str(item) for item in (row.get("reasons_json") or [])]
        closed.append(
            {
                "ticker_code": code,
                "ticker_name": lot.get("ticker_name") or row.get("ticker_name") or code,
                "market": lot.get("market") or row.get("market"),
                "quantity": quantity,
                "entry_date": lot["entry_date"].isoformat() if lot.get("entry_date") else None,
                "entry_price": round(average_before, 2),
                "exit_date": when.isoformat() if when else None,
                "exit_price": round(price, 2),
                "exit_reason": reasons[0] if reasons else None,
                "realized_pnl": round(proceeds - cost, 2),
                "realized_return": round((proceeds / cost) - 1, 6) if cost else None,
            }
        )
        if code not in broker.portfolio.positions:
            lots.pop(code, None)

    positions = []
    holdings_value = 0.0
    for code, position in broker.portfolio.positions.items():
        quantity = int(position.quantity)
        if quantity <= 0:
            continue
        average = float(position.average_price)
        lot = lots.get(code, {})
        price = prices.get(code)
        market_value = (price or average) * quantity
        holdings_value += market_value
        positions.append(
            {
                "ticker_code": code,
                "ticker_name": lot.get("ticker_name") or code,
                "market": lot.get("market"),
                "quantity": quantity,
                "entry_date": lot["entry_date"].isoformat() if lot.get("entry_date") else None,
                "average_price": round(average, 2),
                "current_price": round(price, 2) if price else None,
                "target_price": lot.get("target_price"),
                "stop_price": lot.get("stop_price"),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round((price - average) * quantity, 2) if price else None,
                "unrealized_return": round((price / average) - 1, 6) if price and average else None,
                "priced": price is not None,
            }
        )
    positions.sort(key=lambda item: item["unrealized_return"] if item["unrealized_return"] is not None else -9, reverse=True)
    closed.sort(key=lambda item: (item.get("exit_date") or "", item["ticker_code"]), reverse=True)

    cash = float(broker.portfolio.cash)
    equity = cash + holdings_value
    wins = [item for item in closed if (item.get("realized_return") or 0) > 0]
    return {
        "status": "available" if (positions or closed) else "empty",
        "positions": positions,
        "closed": closed,
        "summary": {
            "initial_cash": round(float(initial_cash), 2),
            "cash": round(cash, 2),
            "holdings_value": round(holdings_value, 2),
            "equity": round(equity, 2),
            "total_return": round((equity / float(initial_cash)) - 1, 6) if initial_cash else None,
            "realized_pnl": round(realized_total, 2),
            "open_count": len(positions),
            "closed_count": len(closed),
            "win_count": len(wins),
            "hit_rate": round(len(wins) / len(closed), 4) if closed else None,
            "priced_count": sum(1 for item in positions if item["priced"]),
        },
    }

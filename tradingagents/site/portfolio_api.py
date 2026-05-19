"""Payload builders for member-entered manual portfolio pages."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker
from tradingagents.storage import StorageRepository
from tradingagents.storage.portfolio import ManualPosition, calculate_manual_positions

from .public_api import _json_ready


MANUAL_PORTFOLIO_NOTICE = (
    "Manual portfolio values are calculated from user-entered trades and supplied "
    "prices. They are recordkeeping estimates, not broker-verified account data."
)
RECENT_MANUAL_TRADE_LIMIT = 20


def build_manual_portfolio_payload(
    repo: StorageRepository,
    portfolio_id: str,
    *,
    current_prices: Mapping[str, Decimal | float | int | str] | None = None,
) -> dict[str, Any]:
    """Build a JSON-ready manual portfolio summary payload."""

    prices = _normalize_price_map(current_prices or {})
    trades = repo.manual_trades_for_portfolio(portfolio_id)
    positions = calculate_manual_positions(trades)
    targets = {
        str(row["ticker_code"]).upper(): row
        for row in repo.price_targets_for_portfolio(portfolio_id)
    }

    position_payloads = []
    total_invested = Decimal("0")
    total_market_value = Decimal("0")
    total_realized = Decimal("0")
    total_unrealized = Decimal("0")
    priced_count = 0

    for position in sorted(positions.values(), key=lambda item: item.ticker_code):
        target = targets.get(position.ticker_code)
        current_price = prices.get(position.ticker_code)
        rendered = _position_payload(position, current_price, target)
        position_payloads.append(rendered)

        total_invested += position.invested_cost
        total_realized += position.realized_pnl
        if current_price is not None:
            priced_count += 1
            total_market_value += position.market_value(current_price)
            total_unrealized += position.unrealized_pnl(current_price)

    all_priced = bool(position_payloads) and priced_count == len(position_payloads)
    if all_priced and total_market_value:
        for rendered in position_payloads:
            if rendered["market_value"] is not None:
                rendered["weight"] = Decimal(str(rendered["market_value"])) / total_market_value

    payload = {
        "portfolio_id": portfolio_id,
        "base_currency": "KRW",
        "pricing_status": _pricing_status(len(position_payloads), priced_count),
        "positions": position_payloads,
        "trades": [_trade_payload(row) for row in reversed(trades[-RECENT_MANUAL_TRADE_LIMIT:])],
        "trade_count": len(trades),
        "totals": {
            "position_count": len(position_payloads),
            "priced_position_count": priced_count,
            "invested_cost": total_invested,
            "market_value": total_market_value if all_priced else None,
            "realized_pnl": total_realized,
            "unrealized_pnl": total_unrealized if all_priced else None,
            "total_pnl": (total_realized + total_unrealized) if all_priced else None,
        },
        "alerts": _alerts(position_payloads),
        "notices": [MANUAL_PORTFOLIO_NOTICE],
    }
    return _json_ready(payload)


def build_manual_portfolio_list_payload(
    repo: StorageRepository,
    *,
    user_id: str,
    limit: int = 20,
    max_limit: int = 50,
) -> dict[str, Any]:
    """Build a member-owned manual portfolio list payload."""

    if max_limit <= 0:
        raise ValueError("max_limit must be positive")
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > max_limit:
        raise ValueError(f"limit cannot exceed {max_limit}")
    rows = repo.list_manual_portfolios(user_id=user_id, limit=limit)
    return _json_ready(
        {
            "status": "available",
            "limit": limit,
            "items": rows,
            "item_count": len(rows),
            "notices": [MANUAL_PORTFOLIO_NOTICE],
        }
    )


def _position_payload(
    position: ManualPosition,
    current_price: Decimal | None,
    target: dict[str, Any] | None,
) -> dict[str, Any]:
    market_value = None
    unrealized = None
    if current_price is not None:
        market_value = position.market_value(current_price)
        unrealized = position.unrealized_pnl(current_price)

    target_price = _decimal_or_none(target.get("target_price")) if target else None
    stop_price = _decimal_or_none(target.get("stop_price")) if target else None
    return {
        "ticker_code": position.ticker_code,
        "ticker_name": position.ticker_name,
        "market": position.market,
        "quantity": position.quantity,
        "average_cost": position.average_cost,
        "invested_cost": position.invested_cost,
        "current_price": current_price,
        "market_value": market_value,
        "unrealized_pnl": unrealized,
        "realized_pnl": position.realized_pnl,
        "total_fees": position.total_fees,
        "total_taxes": position.total_taxes,
        "target_price": target_price,
        "stop_price": stop_price,
        "target_memo": target.get("memo") if target else None,
        "target_hit": bool(current_price is not None and target_price is not None and current_price >= target_price),
        "stop_hit": bool(current_price is not None and stop_price is not None and current_price <= stop_price),
        "weight": None,
    }


def _trade_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "ticker_code": row.get("ticker_code"),
        "ticker_name": row.get("ticker_name"),
        "market": row.get("market"),
        "side": row.get("side"),
        "trade_date": row.get("trade_date"),
        "price": row.get("price"),
        "quantity": row.get("quantity"),
        "fee": row.get("fee"),
        "tax": row.get("tax"),
        "memo": row.get("memo"),
        "created_at": row.get("created_at"),
    }


def _alerts(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts = []
    for position in positions:
        if position["target_hit"]:
            alerts.append(
                {
                    "ticker_code": position["ticker_code"],
                    "type": "target_hit",
                    "message": "Current price is at or above the user-entered target price.",
                }
            )
        if position["stop_hit"]:
            alerts.append(
                {
                    "ticker_code": position["ticker_code"],
                    "type": "stop_hit",
                    "message": "Current price is at or below the user-entered stop price.",
                }
            )
    return alerts


def _pricing_status(position_count: int, priced_count: int) -> str:
    if position_count == 0:
        return "empty"
    if priced_count == 0:
        return "missing"
    if priced_count == position_count:
        return "complete"
    return "partial"


def _normalize_price_map(values: Mapping[str, Decimal | float | int | str]) -> dict[str, Decimal]:
    normalized: dict[str, Decimal] = {}
    for ticker, price in values.items():
        code = _normalize_ticker(str(ticker))
        parsed = _decimal_or_none(price)
        if parsed is None or parsed <= 0:
            raise ValueError("current_prices values must be positive")
        normalized[code] = parsed
    return normalized


def _normalize_ticker(value: str) -> str:
    if is_kr_ticker(value):
        return resolve_kr_ticker(value, lookup_pykrx=False).code
    return value.upper()


def normalize_portfolio_ticker(value: str) -> str:
    """Normalize ticker input the same way manual portfolio payloads do."""

    return _normalize_ticker(value)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))

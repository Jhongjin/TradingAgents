"""Match KIS 모의투자 orders to what actually filled.

The adapter records an order the moment KIS accepts it, using the limit price
we sent, because fills arrive asynchronously. Until those orders are matched
against the broker's own execution record, the KIS account's prices are
intentions and its profit is a guess. This reads 주식일별주문체결조회 and writes
the real fill price, the real quantity, and a status that says what happened.

Nothing here places or cancels an order.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from tradingagents.storage import StorageRepository

KST = ZoneInfo("Asia/Seoul")
PENDING_STATUS = "accepted"


def _order_block(row: Mapping[str, Any]) -> dict[str, Any]:
    detail = row.get("detail_json")
    order = (detail or {}).get("order") if isinstance(detail, Mapping) else None
    return dict(order) if isinstance(order, Mapping) else {}


def needs_reconciliation(row: Mapping[str, Any]) -> bool:
    if str(row.get("order_status") or "").lower() != PENDING_STATUS:
        return False
    return not _order_block(row).get("reconciled_at")


def _side(row: Mapping[str, Any]) -> str:
    order = _order_block(row).get("order") or {}
    side = str(order.get("side") or "").lower()
    if side in {"buy", "sell"}:
        return side
    return "sell" if str(row.get("stage") or "") == "exit" else "buy"


def _match(row: Mapping[str, Any], fills: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Prefer the broker's order id; fall back to the day's ticker and side."""

    order_id = str(_order_block(row).get("order_id") or "").strip()
    if order_id:
        for fill in fills:
            if str(fill.get("order_id") or "").strip() == order_id:
                return fill
    code = str(row.get("ticker_code") or "").strip()
    side = _side(row)
    candidates = [fill for fill in fills if str(fill.get("code") or "") == code and str(fill.get("side") or "") == side]
    return candidates[0] if len(candidates) == 1 else None


def reconcile_kis_fills(
    repo: StorageRepository,
    client: Any,
    *,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    lookback_days: int = 5,
    limit: int = 200,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Update accepted KIS orders with the fill KIS actually recorded."""

    now = now or datetime.now(KST)
    end = end_date if isinstance(end_date, date) else (datetime.strptime(str(end_date)[:10], "%Y-%m-%d").date() if end_date else now.date())
    start = start_date if isinstance(start_date, date) else (datetime.strptime(str(start_date)[:10], "%Y-%m-%d").date() if start_date else end - timedelta(days=max(lookback_days, 1)))

    try:
        rows = repo.list_harness_fills(broker="kis", limit=limit)
    except Exception as exc:
        return {"status": "storage_unavailable", "error": f"{exc.__class__.__name__}: {exc}"}
    pending = [row for row in rows if needs_reconciliation(row)]
    if not pending:
        return {"status": "nothing_to_reconcile", "reconciled": 0, "pending": 0}

    started = time.monotonic()
    try:
        fills = list(client.daily_orders(start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d")))
    except Exception as exc:
        return {
            "status": "broker_unavailable",
            "error": f"{exc.__class__.__name__}: {exc}",
            "pending": len(pending),
            "reconciled": 0,
        }
    if not fills:
        # 모의투자 sometimes reports only daily totals; leaving the rows alone
        # keeps the record honest rather than inventing a fill.
        return {"status": "no_broker_rows", "pending": len(pending), "reconciled": 0, "seconds": round(time.monotonic() - started, 2)}

    reconciled = unmatched = cancelled = partial = 0
    for row in pending:
        fill = _match(row, fills)
        if fill is None:
            unmatched += 1
            continue
        filled_quantity = int(float(fill.get("filled_quantity") or 0))
        price = fill.get("average_fill_price") or fill.get("order_price")
        stamp = now.isoformat()
        order = _order_block(row)
        order["reconciled_at"] = stamp
        order["reconciled_source"] = "kis_daily_ccld"
        order["broker_order"] = {
            "order_id": fill.get("order_id"),
            "ordered_quantity": fill.get("ordered_quantity"),
            "filled_quantity": fill.get("filled_quantity"),
            "average_fill_price": fill.get("average_fill_price"),
            "cancelled": bool(fill.get("cancelled")),
            "status": fill.get("status"),
        }

        if filled_quantity <= 0 or not price:
            order["status"] = "cancelled" if fill.get("cancelled") else "unfilled"
            order.pop("fill", None)
            new_status = "rejected"
            cancelled += 1
        else:
            order["fill"] = {"price": float(price), "quantity": filled_quantity}
            ordered_quantity = int(float(fill.get("ordered_quantity") or filled_quantity))
            if filled_quantity < ordered_quantity:
                partial += 1
                order["status"] = "partial"
            else:
                order["status"] = "filled"
            new_status = "filled"
            reconciled += 1

        repo.update_harness_decision_detail(str(row["id"]), {"order": order})
        repo.update_harness_decision_order_status(str(row["id"]), new_status)

    return {
        "status": "reconciled",
        "pending": len(pending),
        "reconciled": reconciled,
        "partial": partial,
        "unfilled": cancelled,
        "unmatched": unmatched,
        "broker_rows": len(fills),
        "range": [start.isoformat(), end.isoformat()],
        "seconds": round(time.monotonic() - started, 2),
    }

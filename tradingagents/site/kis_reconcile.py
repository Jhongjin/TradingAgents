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
        # 모의투자 answers 주식일별주문체결조회 with the day's totals and no
        # order rows, so there is nothing to match an order to. The totals are
        # still enough to settle a past day: see _reconcile_by_totals.
        if hasattr(client, "daily_order_summary"):
            result = _reconcile_by_totals(repo, client, rows, pending, start=start, end=end, now=now)
            result["seconds"] = round(time.monotonic() - started, 2)
            return result
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


def _quantity(row: Mapping[str, Any]) -> int:
    fill = _order_block(row).get("fill") or {}
    return int(float(fill.get("quantity") or row.get("quantity") or 0))


def _unique_subset(rows: list[Mapping[str, Any]], target: int) -> list[Mapping[str, Any]] | None:
    """The one combination of rows whose quantities add up to ``target``, if exactly one exists."""

    found: list[list[Mapping[str, Any]]] = []

    def walk(index: int, chosen: list[Mapping[str, Any]], total: int) -> None:
        if len(found) > 1 or total > target:
            return
        if total == target and chosen:
            found.append(list(chosen))
            return
        for position in range(index, len(rows)):
            chosen.append(rows[position])
            walk(position + 1, chosen, total + _quantity(rows[position]))
            chosen.pop()

    walk(0, [], 0)
    return found[0] if len(found) == 1 else None


def _settle(repo: StorageRepository, row: Mapping[str, Any], *, filled: bool, stamp: str, day_totals: Mapping[str, Any]) -> None:
    order = _order_block(row)
    order["reconciled_at"] = stamp
    order["reconciled_source"] = "kis_daily_totals"
    order["broker_day_totals"] = dict(day_totals)
    if filled:
        # Quantity is confirmed by the day's total; the price stays the limit
        # we sent, because the totals cannot say which order filled at what.
        order["status"] = "filled"
        order["fill_price_basis"] = "order_price"
        new_status = "filled"
    else:
        order["status"] = "unfilled"
        order.pop("fill", None)
        new_status = "rejected"
    repo.update_harness_decision_detail(str(row["id"]), {"order": order})
    repo.update_harness_decision_order_status(str(row["id"]), new_status)


def _reconcile_by_totals(
    repo: StorageRepository,
    client: Any,
    rows: list[Mapping[str, Any]],
    pending: list[Mapping[str, Any]],
    *,
    start: date,
    end: date,
    now: datetime,
) -> dict[str, Any]:
    """Settle past days from KIS's daily filled-share total.

    On 2026-09-30 a 031980 limit sell was accepted and never filled; KIS
    reported 0 shares that day, but with no order rows the reconciler left it
    "accepted" and the book counted a sale that happened the next morning. A
    day's total is enough to settle it:

    - recorded shares == KIS shares: every pending order that day filled.
    - KIS shares == 0: none of them did.
    - recorded > KIS: the gap is unfilled; settled only when exactly one
      combination of that day's pending orders adds up to it.
    - KIS > recorded: KIS filled something we never stored (2026-09-11). That
      cannot be rebuilt from totals, so it is reported, not invented.

    Today is never settled: an order still working can fill before the close.
    """

    by_day: dict[str, list[Mapping[str, Any]]] = {}
    for row in pending:
        day = str(row.get("as_of_date") or "")[:10]
        if start.isoformat() <= day <= end.isoformat() and day < now.date().isoformat():
            by_day.setdefault(day, []).append(row)

    stamp = now.isoformat()
    filled = unfilled = 0
    unresolved: list[dict[str, Any]] = []
    for day, waiting in sorted(by_day.items()):
        totals = client.daily_order_summary(start_date=day.replace("-", ""), end_date=day.replace("-", ""))
        broker_shares = int(float(totals.get("filled_quantity") or 0))
        recorded = sum(_quantity(row) for row in rows
                       if str(row.get("as_of_date") or "")[:10] == day
                       and str(row.get("order_status") or "").lower() in {"accepted", "filled"})
        day_totals = {"day": day, "broker_filled_shares": broker_shares, "recorded_shares": recorded,
                      "broker_filled_amount": totals.get("filled_amount")}
        if broker_shares == recorded:
            for row in waiting:
                _settle(repo, row, filled=True, stamp=stamp, day_totals=day_totals)
            filled += len(waiting)
        elif broker_shares == 0:
            for row in waiting:
                _settle(repo, row, filled=False, stamp=stamp, day_totals=day_totals)
            unfilled += len(waiting)
        elif broker_shares < recorded and (gap := _unique_subset(waiting, recorded - broker_shares)) is not None:
            gap_ids = {str(row["id"]) for row in gap}
            for row in waiting:
                _settle(repo, row, filled=str(row["id"]) not in gap_ids, stamp=stamp, day_totals=day_totals)
            unfilled += len(gap)
            filled += len(waiting) - len(gap)
        else:
            unresolved.append({**day_totals, "pending": len(waiting),
                               "reason": "unrecorded fills at KIS" if broker_shares > recorded else "ambiguous gap"})

    return {
        "status": "reconciled_by_totals",
        "pending": len(pending),
        "reconciled": filled,
        "unfilled": unfilled,
        "unresolved": unresolved,
        "range": [start.isoformat(), end.isoformat()],
    }

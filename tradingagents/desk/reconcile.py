"""Our record of what we traded, against the broker's record of what we traded.

The desk ledger and the harness both write what they believe happened. Both
are written by the same program that decided to trade, so neither is evidence.
NH's 종합거래내역 is the broker's own books, and disagreement between the two
is the only thing that can show a missing order, a double-sent one, or a fill
that never reached the ledger because the process died mid-flight.

Rows are matched on the day, the ticker and the side, and then on quantity.
Price is deliberately not matched: our record holds the limit that was sent and
the broker's holds the price it filled at, and those differ on every order that
did anything interesting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from tradingagents.execution.audit import AuditLedger

from .orders import ORDER_EVENT

# Sides as they appear in 종합거래내역's sps_cd_krl_anm, which spells out the
# route as well as the direction: '신용대출매수(코스피)(유통융자)', '코스피매도'.
SELL_MARK = "매도"
BUY_MARK = "매수"


@dataclass(frozen=True)
class Trade:
    day: str
    code: str
    name: str
    side: str
    quantity: float
    amount: float
    price: float | None = None
    note: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.day, self.code, self.side)

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day, "code": self.code, "name": self.name, "side": self.side,
            "quantity": self.quantity, "amount": self.amount, "price": self.price,
            "note": self.note,
        }


@dataclass
class Reconciliation:
    agreed: list[dict[str, Any]] = field(default_factory=list)
    broker_only: list[dict[str, Any]] = field(default_factory=list)
    ours_only: list[dict[str, Any]] = field(default_factory=list)
    quantity_differs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.broker_only or self.ours_only or self.quantity_differs)

    def as_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "agreed": self.agreed,
            "broker_only": self.broker_only,
            "ours_only": self.ours_only,
            "quantity_differs": self.quantity_differs,
        }


def broker_trades(raw: Mapping[str, Any]) -> list[Trade]:
    """The trades out of 종합거래내역, with the cash movements left out.

    A deposit carries no ticker and no quantity. It belongs on the cash line of
    the page, not in a comparison against orders that were never placed.
    """

    trades: list[Trade] = []
    for row in raw.get("Output_0") or []:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("sps_cd_krl_anm") or "")
        side = _side_from_label(label)
        code = str(row.get("iem_cd") or "").strip()
        if side is None or not code:
            continue
        trades.append(Trade(
            day=str(row.get("trd_dt") or "").strip(),
            code=code,
            name=str(row.get("iem_nm") or "").strip().lstrip("*"),
            side=side,
            quantity=_num(row.get("trd_qty")) or 0.0,
            amount=_num(row.get("trd_amt")) or 0.0,
            price=_num(row.get("trd_uit_pr")),
            note=label,
        ))
    return trades


def cash_movements(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Money in and out, which no order explains and which the balance reflects."""

    rows = []
    for row in raw.get("Output_0") or []:
        if not isinstance(row, Mapping):
            continue
        rows.append({
            "day": str(row.get("trd_dt") or "").strip(),
            "kind": str(row.get("act_trd_tp_nm") or "").strip(),
            "detail": str(row.get("sps_cd_krl_anm") or "").strip(),
            "amount": _num(row.get("trd_amt")),
            "balance_after": _num(row.get("trd_af_dca")),
        })
    return rows


def our_trades(book: AuditLedger, *, start: str, end: str, mode: str | None = None) -> list[Trade]:
    """What the desk ledger says it sent and the broker accepted.

    Only the accepted stage counts. A 'sent' with no ending is an order whose
    fate is unknown, and calling it a trade here would paper over exactly the
    case this comparison exists to surface.

    ``mode`` matters more than it looks. One ledger holds both the paper and the
    live account, and comparing every order in it against one account's books
    would report each of the other account's orders as a missing trade — noise
    that would drown the real mismatch this is for.
    """

    first, last = _day(start), _day(end)
    want_mode = str(mode).strip().lower() if mode else None
    trades: list[Trade] = []
    for record in book.iter_records():
        if record.event_type != ORDER_EVENT:
            continue
        payload = record.payload or {}
        if str(payload.get("stage")) != "accepted":
            continue
        if want_mode and str(payload.get("mode") or "").strip().lower() != want_mode:
            continue
        side = str(payload.get("side") or "")
        # cancels and reserved-order cancels move nothing
        if side not in {"buy", "sell", "reserve-buy", "reserve-sell"}:
            continue
        day = _day(str(payload.get("date") or ""))
        if not day or day < first or day > last:
            continue
        trades.append(Trade(
            day=day,
            code=str(payload.get("code") or "").strip(),
            name="",
            side="sell" if side.endswith("sell") else "buy",
            quantity=float(payload.get("quantity") or 0),
            amount=float(payload.get("amount") or 0),
            price=float(payload.get("price") or 0) or None,
            note=str(payload.get("mode") or ""),
        ))
    return trades


def reconcile(broker: Iterable[Trade], ours: Iterable[Trade]) -> Reconciliation:
    """Line up the two records and report where they part company."""

    theirs = _by_key(broker)
    mine = _by_key(ours)
    out = Reconciliation()

    for key in sorted(theirs.keys() | mine.keys()):
        left, right = theirs.get(key), mine.get(key)
        day, code, side = key
        if left and not right:
            out.broker_only.append(_pair(day, code, side, left, None))
        elif right and not left:
            out.ours_only.append(_pair(day, code, side, None, right))
        elif left and right and abs(_qty(left) - _qty(right)) > 1e-6:
            out.quantity_differs.append(_pair(day, code, side, left, right))
        elif left and right:
            out.agreed.append(_pair(day, code, side, left, right))
    return out


def _pair(day, code, side, left, right) -> dict[str, Any]:
    sample = (left or right)[0]
    return {
        "day": day, "code": code, "side": side,
        "name": next((trade.name for trade in (left or []) if trade.name), sample.name),
        "broker_quantity": _qty(left) if left else None,
        "our_quantity": _qty(right) if right else None,
        "broker_amount": sum(trade.amount for trade in left) if left else None,
        "our_amount": sum(trade.amount for trade in right) if right else None,
        "note": sample.note,
    }


def _by_key(trades: Iterable[Trade]) -> dict[tuple[str, str, str], list[Trade]]:
    grouped: dict[tuple[str, str, str], list[Trade]] = {}
    for trade in trades:
        grouped.setdefault(trade.key, []).append(trade)
    return grouped


def _qty(trades: list[Trade]) -> float:
    return sum(trade.quantity for trade in trades)


def _side_from_label(label: str) -> str | None:
    if SELL_MARK in label:
        return "sell"
    if BUY_MARK in label:
        return "buy"
    return None


def _day(value: str | date | None) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y%m%d")
    return "".join(character for character in str(value or "") if character.isdigit())[:8]


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None

"""What a margin position owes, when it is due, and how close it is to being closed.

A cash position can only lose what was put into it, and nothing happens to it
on a date. A margin position has two clocks the balance table does not show:
the loan comes due, and the collateral ratio can fall far enough that the
broker sells the position without asking.

NH returns all of it, per holding: xrn_dt is the day the loan expires,
lon_bnc_amt what is still owed on it, wtm_rt the deposit rate it was opened at,
and mgg_rt on the account is the collateral ratio right now.

The one number NH does not publish is the ratio at which it sells you out.
That is a contract term rather than an API field, so it is configuration here
with a default, and the page says it is a setting rather than a fact.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping

# 유통융자's usual maintenance line. Written down as a default to be corrected,
# not as something this project verified with NH.
DEFAULT_MAINTENANCE_PCT = 140.0

# A loan with under this many days left is worth saying out loud, because
# rolling it or closing it is a decision that needs lead time.
DUE_SOON_DAYS = 14


@dataclass(frozen=True)
class MarginLoan:
    code: str
    name: str
    loan_amount: float
    opened_on: date | None
    expires_on: date | None
    deposit_rate: str
    value: float

    def days_left(self, today: date) -> int | None:
        return (self.expires_on - today).days if self.expires_on else None

    def as_dict(self, today: date) -> dict[str, Any]:
        left = self.days_left(today)
        return {
            "code": self.code,
            "name": self.name,
            "loan_amount": self.loan_amount,
            "value": self.value,
            "opened_on": self.opened_on.isoformat() if self.opened_on else None,
            "expires_on": self.expires_on.isoformat() if self.expires_on else None,
            "days_left": left,
            "due_soon": left is not None and left <= DUE_SOON_DAYS,
            "deposit_rate": self.deposit_rate,
        }


def maintenance_pct() -> float:
    raw = (os.getenv("TRADINGAGENTS_DESK_MAINTENANCE_PCT") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MAINTENANCE_PCT
    return value if value > 0 else DEFAULT_MAINTENANCE_PCT


def margin_loans(rows: Iterable[Mapping[str, Any]]) -> list[MarginLoan]:
    """The borrowed positions out of a balance response."""

    loans: list[MarginLoan] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        owed = _num(row.get("lon_bnc_amt")) or 0.0
        opened = _date(row.get("lon_byn_dt"))
        if owed <= 0 and opened is None:
            continue                                   # bought with the account's own money
        loans.append(MarginLoan(
            code=str(row.get("iem_cd") or "").strip(),
            name=str(row.get("iem_nm") or "").strip().lstrip("*"),
            loan_amount=owed,
            opened_on=opened,
            expires_on=_date(row.get("xrn_dt")),
            deposit_rate=str(row.get("wtm_rt") or "").strip(),
            value=_num(row.get("eal_amt")) or 0.0,
        ))
    return loans


def margin_summary(
    account: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """The margin picture, or None when nothing is borrowed."""

    loans = margin_loans(rows)
    if not loans:
        return None

    when = today or date.today()
    ratio = _num(account.get("mgg_rt"))
    floor = maintenance_pct()
    soonest = min((loan for loan in loans if loan.expires_on),
                  key=lambda loan: loan.expires_on, default=None)

    return {
        "loans": [loan.as_dict(when) for loan in loans],
        "loan_total": sum(loan.loan_amount for loan in loans),
        "value_total": sum(loan.value for loan in loans),
        "ratio": ratio,
        "maintenance_pct": floor,
        "at_risk": ratio is not None and ratio <= floor,
        "room_pct": _room(ratio, floor, account),
        "next_due": soonest.expires_on.isoformat() if soonest and soonest.expires_on else None,
        "next_due_days": soonest.days_left(when) if soonest else None,
        "next_due_code": soonest.code if soonest else None,
    }


def _room(ratio: float | None, floor: float, account: Mapping[str, Any]) -> float | None:
    """Roughly how far the holdings can fall before the ratio reaches the floor.

    The collateral ratio is assets over what is owed, and what is owed does not
    move with the market — so the assets may fall to floor/ratio of where they
    are. Cash inside those assets does not fall with the market either, which is
    why the drop the *holdings* must take is the larger number computed here.

    Called an estimate on the page and meant as one. NH does not publish the
    formula behind mgg_rt, so this reproduces the textbook one; it is for
    knowing whether the answer is 5% or 30%, not for trading against.
    """

    if ratio is None or ratio <= 0 or ratio <= floor:
        return None

    assets = _num(account.get("tot_aet_amt")) or 0.0
    holdings = _num(account.get("tot_eal_amt")) or 0.0
    if assets <= 0 or holdings <= 0:
        return None

    # the value assets may fall to before the floor is reached
    allowed_fall = assets * (1 - floor / ratio)
    return round(min(allowed_fall / holdings, 1.0) * 100, 1)


def _date(value: Any) -> date | None:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) != 8 or digits == "00000000":
        return None
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None

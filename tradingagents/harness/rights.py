"""Corporate actions that move a price without anything happening to the company.

On the ex-dividend date a share opens lower by roughly the dividend, because
the dividend is no longer attached to it. Nothing has gone wrong; the value
moved from the share to the shareholder. A stop-loss that fires on that drop
sells a position for the crime of paying out, and then the account misses the
recovery as well as owning the loss.

NH's 권리예정 lists what is due on what is held, with the date the right comes
off the price. That is enough to hold one session through it.

What this does not do is adjust the cost basis. The dividend per share is not
in the answer NH gives — the amount fields come back as zero until the payout
is fixed — so the position keeps looking worse by the dividend until it is
sold. Holding through the ex-date is the part that can be done correctly, and
doing only that is better than guessing an adjustment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

# rit_tp_cd values seen in 권리예정. Only the ones that take value off the
# price on a known day matter here; a rights offering, for instance, changes
# the share count on a schedule of its own.
PRICE_MOVING_KINDS = {"배당", "무상증자", "주식배당", "액면분할"}


@dataclass(frozen=True)
class ExRight:
    code: str
    name: str
    kind: str
    ex_date: date | None
    base_date: date | None

    def moves_price_on(self, day: date) -> bool:
        return self.ex_date == day and any(mark in self.kind for mark in PRICE_MOVING_KINDS)


def ex_rights_from_nh(raw: Mapping[str, Any]) -> dict[str, ExRight]:
    """Parse 권리예정 into one entry per ticker, keeping the nearest date."""

    found: dict[str, ExRight] = {}
    rows = raw.get("Output_0")
    if isinstance(rows, Mapping):                 # 권리보유 nests its list one level down
        rows = raw.get("Output_1")
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("iem_cd") or "").strip()
        if not code:
            continue
        right = ExRight(
            code=code,
            name=str(row.get("iem_nm") or "").strip().lstrip("*"),
            kind=str(row.get("rit_tp_nm") or "").strip(),
            ex_date=_date(row.get("xgt_dt")),
            base_date=_date(row.get("bse_dt")),
        )
        existing = found.get(code)
        if existing is None or _earlier(right.ex_date, existing.ex_date):
            found[code] = right
    return found


def holds_through(rights: Mapping[str, ExRight] | None, code: str, day: date) -> ExRight | None:
    """The right that explains today's drop, if there is one."""

    if not rights:
        return None
    right = rights.get(str(code).strip())
    return right if right and right.moves_price_on(day) else None


def _earlier(left: date | None, right: date | None) -> bool:
    if left is None:
        return False
    return right is None or left < right


def _date(value: Any) -> date | None:
    """YYYYMMDD, with NH's 00000000 for 'not scheduled' read as nothing."""

    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) != 8 or digits == "00000000":
        return None
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        return None

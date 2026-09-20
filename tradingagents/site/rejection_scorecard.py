"""How the names that were turned down went on to do.

The screen rejects far more than it buys, and it rejects for stated, numeric
reasons — "expected return +1.40% below +2.00%", "sector 은행 already holds 2 of
2", "confirmer rating Underweight is not bullish". Each of those is a claim,
and until now none of them was ever marked. Only the picks were scored.

That is the wrong half to leave out, and not only for completeness. A month
where the picks lose money says nothing on its own about whether the filter
works. A month where the picks lose 3% and the names it turned down lose 8%
says the filter is discriminating, and that survives a drawdown in a way a
return figure does not.

Stated carefully on purpose: a rejected name that fell is not a loss avoided.
The capital would have gone somewhere, and where it went is already in the
record. What this measures is narrower and more defensible — whether the rules
tell the two groups apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Mapping, Sequence

from .harness_outcome_worker import REJECTED_STAGES

#: Reported at the horizon the outcome worker already fills in.
DEFAULT_HORIZON = 20

#: Below this the comparison is noise dressed as evidence.
MIN_EACH_SIDE = 3


@dataclass
class Side:
    label: str
    returns: list[float] = field(default_factory=list)
    names: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.returns)

    @property
    def mean(self) -> float | None:
        return sum(self.returns) / len(self.returns) if self.returns else None

    @property
    def median(self) -> float | None:
        return median(self.returns) if self.returns else None

    @property
    def fell(self) -> int:
        return sum(1 for value in self.returns if value < 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "count": self.count,
            "mean_return": self.mean,
            "median_return": self.median,
            "fell": self.fell,
            "names": self.names[:8],
        }


def build_rejection_scorecard(
    decisions: Sequence[Mapping[str, Any]],
    *,
    horizon_days: int = DEFAULT_HORIZON,
) -> dict[str, Any]:
    """Compare what was bought against what was turned down, at one horizon.

    ``decisions`` are rows from list_harness_decisions_for_outcomes, each
    carrying its own ``outcomes``. Only completed outcomes count: a horizon
    that has not elapsed tells you nothing yet, and including it would let a
    half-finished window decide the verdict.
    """

    bought = Side("고른 종목")
    passed = Side("거른 종목")
    reasons: dict[str, list[float]] = {}

    for decision in decisions:
        stage = str(decision.get("stage") or "")
        value = _completed_return(decision.get("outcomes") or [], horizon_days)
        if value is None:
            continue
        name = str(decision.get("ticker_name") or decision.get("ticker_code") or "")
        if stage == "ordered":
            bought.returns.append(value)
            bought.names.append(name)
        elif stage in REJECTED_STAGES:
            passed.returns.append(value)
            passed.names.append(name)
            head = _reason_of(decision)
            if head:
                reasons.setdefault(head, []).append(value)

    enough = bought.count >= MIN_EACH_SIDE and passed.count >= MIN_EACH_SIDE
    gap = None
    if enough and bought.mean is not None and passed.mean is not None:
        gap = bought.mean - passed.mean

    return {
        "horizon_days": horizon_days,
        "bought": bought.as_dict(),
        "passed": passed.as_dict(),
        # Positive means the names it kept did better than the ones it turned
        # down, which is the only direction that argues the filter works.
        "gap": gap,
        "verdict": _verdict(enough, gap),
        "by_reason": [
            {
                "reason": reason,
                "count": len(values),
                "mean_return": sum(values) / len(values),
                "fell": sum(1 for value in values if value < 0),
            }
            for reason, values in sorted(reasons.items(), key=lambda item: -len(item[1]))
        ],
    }


def _verdict(enough: bool, gap: float | None) -> str:
    if not enough or gap is None:
        return "not_enough_data"
    if gap > 0:
        return "filter_discriminated"
    return "filter_did_not_discriminate"


def _completed_return(outcomes: Sequence[Mapping[str, Any]], horizon_days: int) -> float | None:
    for row in outcomes:
        if int(row.get("horizon_days") or 0) != horizon_days:
            continue
        if str(row.get("status")) != "completed":
            return None
        value = row.get("raw_return")
        return float(value) if value is not None else None
    return None


def _reason_of(decision: Mapping[str, Any]) -> str:
    """The rule that turned it down, with the numbers filed off.

    "expected return +1.40% below +2.00%" and "+1.67% below +2.00%" are the
    same rule twice. Grouping needs the rule, not the reading.
    """

    reasons = decision.get("reasons_json") or []
    if not reasons:
        return ""
    head = str(reasons[0])
    for mark, label in (
        ("expected return", "기대수익 기준 미달"),
        ("confirmer rating", "AI 확인에서 탈락"),
        ("already holds", "섹터 한도 초과"),
        ("position count", "보유 종목수 한도"),
        ("forecast", "예측 신뢰도 부족"),
        ("이미", "종목 비중 한도"),
    ):
        if mark in head:
            return label
    return head[:40]

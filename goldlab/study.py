"""Did the pattern beat doing nothing?

A pattern with a 60% win rate proves nothing on its own: if gold rose on 60% of
all bars in the window, the pattern found the market, not an edge. So every
pattern here is measured against the base rate of the same instrument over the
same bars, and what is reported is the difference.

Also reported, because they decide whether a rule is tradable: how far the
price ran the right way before it turned (MFE) and how far it went against the
trade first (MAE). A pattern that eventually pays but draws down twice the
target is not one a stop can survive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence

from .contracts import ContractSpec
from .data import Bar, BarSeries
from .patterns import PATTERN_REGISTRY, PatternHit, detect_patterns

DEFAULT_HORIZONS = (4, 12, 24, 72)
MIN_OCCURRENCES = 30


@dataclass
class PatternStat:
    pattern: str
    label: str
    direction: str
    occurrences: int
    horizons: dict[int, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "label": self.label,
            "direction": self.direction,
            "occurrences": self.occurrences,
            "horizons": {str(key): value for key, value in self.horizons.items()},
        }


@dataclass
class StudyResult:
    symbol: str
    interval: str
    bars: int
    start: str
    end: str
    horizons: tuple[int, ...]
    base_rate: dict[int, dict[str, Any]] = field(default_factory=dict)
    patterns: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "bars": self.bars,
            "start": self.start,
            "end": self.end,
            "horizons": list(self.horizons),
            "base_rate": {str(key): value for key, value in self.base_rate.items()},
            "patterns": self.patterns,
            "notes": self.notes,
        }


def _forward(bars: Sequence[Bar], index: int, horizon: int, *, long: bool) -> dict[str, float] | None:
    """Return, best excursion and worst excursion over the next ``horizon`` bars."""

    if index + horizon >= len(bars):
        return None
    entry = bars[index].close
    if entry <= 0:
        return None
    window = bars[index + 1 : index + 1 + horizon]
    if not window:
        return None
    exit_price = window[-1].close
    highest = max(bar.high for bar in window)
    lowest = min(bar.low for bar in window)
    if long:
        return {
            "return": (exit_price / entry) - 1,
            "mfe": (highest / entry) - 1,
            "mae": (lowest / entry) - 1,
        }
    return {
        "return": (entry / exit_price) - 1,
        "mfe": (entry / lowest) - 1,
        "mae": (entry / highest) - 1,
    }


def _summarize(samples: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    if not samples:
        return {"count": 0}
    returns = [row["return"] for row in samples]
    average = mean(returns)
    deviation = pstdev(returns) if len(returns) > 1 else 0.0
    wins = [value for value in returns if value > 0]
    return {
        "count": len(returns),
        "win_rate": round(len(wins) / len(returns), 4),
        "average_return": round(average, 6),
        "median_return": round(sorted(returns)[len(returns) // 2], 6),
        "return_std": round(deviation, 6),
        "average_mfe": round(mean(row["mfe"] for row in samples), 6),
        "average_mae": round(mean(row["mae"] for row in samples), 6),
        # how many standard errors the mean sits from zero; under about 2 the
        # pattern has not shown itself apart from noise
        "t_stat": round(average / (deviation / (len(returns) ** 0.5)), 2) if deviation > 0 else None,
    }


def base_rates(bars: Sequence[Bar], horizons: Sequence[int], *, long: bool = True) -> dict[int, dict[str, Any]]:
    """What an arbitrary bar does, which is what a pattern has to beat."""

    result: dict[int, dict[str, Any]] = {}
    for horizon in horizons:
        samples = []
        for index in range(len(bars)):
            measured = _forward(bars, index, horizon, long=long)
            if measured:
                samples.append(measured)
        result[horizon] = _summarize(samples)
    return result


def run_pattern_study(
    series: BarSeries,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    patterns: Sequence[str] | None = None,
    min_occurrences: int = MIN_OCCURRENCES,
    contract: ContractSpec | None = None,
) -> StudyResult:
    """Count every pattern, measure what followed, and compare with the base rate."""

    bars = series.bars
    if len(bars) < max(horizons) + 60:
        raise ValueError("not enough bars to measure the longest horizon")

    horizons = tuple(sorted(set(int(value) for value in horizons if int(value) > 0)))
    long_base = base_rates(bars, horizons, long=True)
    short_base = base_rates(bars, horizons, long=False)

    hits = detect_patterns(series, patterns=patterns)
    grouped: dict[str, list[PatternHit]] = {}
    for hit in hits:
        grouped.setdefault(hit.pattern, []).append(hit)

    rows: list[dict[str, Any]] = []
    for name, (label, direction, _detector) in PATTERN_REGISTRY.items():
        if patterns and name not in patterns:
            continue
        occurrences = grouped.get(name, [])
        stat = PatternStat(pattern=name, label=label, direction=direction, occurrences=len(occurrences))
        long = direction == "bullish"
        base = long_base if long else short_base
        for horizon in horizons:
            samples = []
            for hit in occurrences:
                measured = _forward(bars, hit.index, horizon, long=long)
                if measured:
                    samples.append(measured)
            summary = _summarize(samples)
            reference = base.get(horizon, {})
            if summary.get("count") and reference.get("count"):
                summary["base_win_rate"] = reference.get("win_rate")
                summary["base_average_return"] = reference.get("average_return")
                summary["edge_win_rate"] = round((summary["win_rate"] or 0) - (reference.get("win_rate") or 0), 4)
                summary["edge_return"] = round((summary["average_return"] or 0) - (reference.get("average_return") or 0), 6)
            if contract is not None and summary.get("count"):
                # one contract, entered and exited at the close, fees included
                summary["money_per_trade"] = round(
                    (summary["average_return"] or 0) * bars[-1].close * contract.multiplier
                    - contract.commission_per_side * 2
                    - contract.typical_slippage_ticks * contract.tick_value * 2,
                    2,
                )
            summary["enough_samples"] = bool(summary.get("count", 0) >= min_occurrences)
            stat.horizons[horizon] = summary
        rows.append(stat.as_dict())

    rows.sort(
        key=lambda row: (
            max((horizon.get("edge_return") or 0) for horizon in row["horizons"].values()) if row["horizons"] else 0
        ),
        reverse=True,
    )
    return StudyResult(
        symbol=series.symbol,
        interval=series.interval,
        bars=len(bars),
        start=bars[0].timestamp.isoformat() if bars else "",
        end=bars[-1].timestamp.isoformat() if bars else "",
        horizons=horizons,
        base_rate={horizon: {"long": long_base[horizon], "short": short_base[horizon]} for horizon in horizons},
        patterns=rows,
        notes=[
            "수익률은 패턴 완성 봉의 종가에서 진입한 것으로 계산했습니다.",
            f"'기준 대비'는 같은 구간 아무 봉에서나 진입했을 때와의 차이입니다. 이 값이 0 근처면 패턴이 시장을 따라간 것일 뿐입니다.",
            f"표본이 {min_occurrences}회 미만이면 통계로 말할 수 없습니다.",
            "MAE는 진입 뒤 반대로 갔던 폭입니다. 손절 폭을 정할 때 이 값을 봐야 합니다.",
        ],
    )

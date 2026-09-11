"""Does each part of the score predict anything?

The rule score adds trend, momentum and traded-value terms with fixed weights,
and nobody ever measured whether each term earns its place. This ranks every
name by one factor on a past date, ranks the same names by what they actually
returned over the following days, and correlates the two. Averaged over many
dates, that correlation is the factor's information coefficient: positive means
the factor pointed the right way, near zero means it was noise, negative means
it pointed backwards.

It also splits the names into quintiles by factor value and reports the average
forward return of each, which answers the question the number alone does not:
whether the relationship holds across the range or only at one extreme.

Nothing here trades. It reads prices and reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import mean
from typing import Any, Mapping, Sequence

from tradingagents.screener.factors import compute_factor_scores

FACTORS = (
    ("composite", "규칙 점수"),
    ("momentum_20d", "20일 모멘텀"),
    ("momentum_60d", "60일 모멘텀"),
    ("momentum_120d", "120일 모멘텀"),
    ("ma_alignment", "이동평균 정렬"),
    ("rsi_14", "RSI"),
    ("volume_surge", "거래량 급증"),
    ("volatility_20d", "변동성"),
    ("distance_from_high_60d", "60일 고점 이격"),
)


@dataclass
class FactorStudyResult:
    start_date: str
    end_date: str
    horizon_days: int
    universe_size: int
    sample_dates: int
    factors: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "horizon_days": self.horizon_days,
            "universe_size": self.universe_size,
            "sample_dates": self.sample_dates,
            "factors": self.factors,
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


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks, so ties do not bias the correlation."""

    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2 + 1
        for index in range(position, end + 1):
            ranks[order[index]] = shared
        position = end + 1
    return ranks


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Rank correlation, the shape a factor study needs rather than a linear one."""

    if len(left) != len(right) or len(left) < 5:
        return None
    x = _ranks(left)
    y = _ranks(right)
    mean_x, mean_y = mean(x), mean(y)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    left_var = sum((a - mean_x) ** 2 for a in x)
    right_var = sum((b - mean_y) ** 2 for b in y)
    if left_var <= 0 or right_var <= 0:
        return None
    return numerator / ((left_var * right_var) ** 0.5)


def run_factor_study(
    *,
    history: Mapping[str, Sequence[Mapping[str, Any]]],
    start: date | str,
    end: date | str,
    horizon_days: int = 20,
    sample_every: int = 5,
    min_history: int = 121,
    history_window: int = 140,
    min_names: int = 20,
    factor_weights: Mapping[str, float] | None = None,
) -> FactorStudyResult:
    """Correlate each factor with the return that followed it."""

    start_date = _as_date(start)
    end_date = _as_date(end)
    if start_date is None or end_date is None or start_date >= end_date:
        raise ValueError("start must be a date before end")
    if horizon_days <= 0 or sample_every <= 0:
        raise ValueError("horizon_days and sample_every must be positive")

    series: dict[str, list[tuple[date, float, dict[str, Any]]]] = {}
    for code, points in (history or {}).items():
        rows = []
        for point in points or ():
            when = _as_date(point.get("date"))
            close = point.get("close")
            if when is None or not close or float(close) <= 0:
                continue
            rows.append((when, float(close), dict(point)))
        rows.sort(key=lambda item: item[0])
        if len(rows) >= min_history + horizon_days:
            series[code] = rows
    if not series:
        raise ValueError("no ticker had enough history for the horizon")

    all_days = sorted({when for rows in series.values() for when, _price, _point in rows})
    index_of = {day: position for position, day in enumerate(all_days)}
    sample_days = [
        day
        for position, day in enumerate(all_days)
        if start_date <= day <= end_date and position % sample_every == 0 and position + horizon_days < len(all_days)
    ]
    if not sample_days:
        raise ValueError("the window has no sample dates with a full forward horizon")

    per_factor: dict[str, list[float]] = {key: [] for key, _label in FACTORS}
    quintiles: dict[str, list[list[float]]] = {key: [[] for _ in range(5)] for key, _label in FACTORS}
    used_dates = 0

    for day in sample_days:
        forward_day = all_days[index_of[day] + horizon_days]
        observations: dict[str, list[tuple[float, float]]] = {key: [] for key, _label in FACTORS}
        for code, rows in series.items():
            window = [point for when, _price, point in rows if when <= day]
            if len(window) < min_history:
                continue
            prices = {when: price for when, price, _point in rows}
            price_now = prices.get(day)
            price_then = prices.get(forward_day)
            if not price_now or not price_then:
                continue
            forward_return = (price_then / price_now) - 1
            scores = compute_factor_scores(window[-history_window:], weights=factor_weights)
            if scores.momentum_20d is None:
                continue
            for key, _label in FACTORS:
                value = getattr(scores, key, None)
                if value is None:
                    continue
                observations[key].append((float(value), forward_return))

        counted = False
        for key, _label in FACTORS:
            rows_for_factor = observations[key]
            if len(rows_for_factor) < min_names:
                continue
            counted = True
            values = [value for value, _ret in rows_for_factor]
            returns = [ret for _value, ret in rows_for_factor]
            correlation = spearman(values, returns)
            if correlation is not None:
                per_factor[key].append(correlation)
            ordered = sorted(rows_for_factor, key=lambda item: item[0])
            bucket_size = max(len(ordered) // 5, 1)
            for bucket in range(5):
                chunk = ordered[bucket * bucket_size : (bucket + 1) * bucket_size] if bucket < 4 else ordered[4 * bucket_size :]
                if chunk:
                    quintiles[key][bucket].append(mean(ret for _value, ret in chunk))
        if counted:
            used_dates += 1

    results = []
    for key, label in FACTORS:
        samples = per_factor[key]
        if not samples:
            continue
        average = mean(samples)
        deviation = (sum((value - average) ** 2 for value in samples) / len(samples)) ** 0.5 if len(samples) > 1 else 0.0
        buckets = [round(mean(values), 6) if values else None for values in quintiles[key]]
        spread = None
        if buckets[0] is not None and buckets[-1] is not None:
            spread = round(buckets[-1] - buckets[0], 6)
        results.append(
            {
                "key": key,
                "label": label,
                "information_coefficient": round(average, 6),
                "ic_std": round(deviation, 6),
                # how many standard errors the average sits from zero: under ~2
                # the factor has not shown itself apart from noise
                "ic_t_stat": round(average / (deviation / (len(samples) ** 0.5)), 3) if deviation > 0 else None,
                "positive_rate": round(sum(1 for value in samples if value > 0) / len(samples), 4),
                "sample_count": len(samples),
                "quintile_returns": buckets,
                "top_minus_bottom": spread,
            }
        )
    results.sort(key=lambda item: abs(item["information_coefficient"]), reverse=True)

    return FactorStudyResult(
        start_date=sample_days[0].isoformat(),
        end_date=sample_days[-1].isoformat(),
        horizon_days=horizon_days,
        universe_size=len(series),
        sample_dates=used_dates,
        factors=results,
        notes=[
            f"{horizon_days}거래일 뒤 수익률과의 순위 상관을 {used_dates}개 시점에서 평균했습니다.",
            "값이 0에 가까우면 그 요소는 예측에 기여하지 않았다는 뜻입니다.",
            "대상 종목을 오늘 기준으로 골랐기 때문에 그사이 상장폐지된 종목은 빠져 있습니다.",
        ],
    )

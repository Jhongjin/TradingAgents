"""Transparent factor scores computed from daily OHLCV history.

Each factor is normalised to a -1..1 style score with a short Korean label so
the screener output doubles as an explanation for the LLM confirmation step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class FactorScores:
    momentum_20d: float | None
    momentum_60d: float | None
    momentum_120d: float | None
    ma_alignment: float
    rsi_14: float | None
    volume_surge: float | None
    volatility_20d: float | None
    distance_from_high_60d: float | None
    composite: float
    labels: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_factor_scores(
    points: Sequence[Mapping[str, Any]],
    *,
    weights: Mapping[str, float] | None = None,
) -> FactorScores:
    """Compute factor scores from ascending daily OHLCV points (dicts with close/volume)."""

    closes = [float(point["close"]) for point in points if point.get("close") is not None and float(point["close"]) > 0]
    volumes = [float(point.get("volume") or 0.0) for point in points if point.get("close") is not None and float(point["close"]) > 0]
    if len(closes) < 21:
        return FactorScores(
            momentum_20d=None,
            momentum_60d=None,
            momentum_120d=None,
            ma_alignment=0.0,
            rsi_14=None,
            volume_surge=None,
            volatility_20d=None,
            distance_from_high_60d=None,
            composite=0.0,
            labels=["가격 이력 부족"],
        )

    latest = closes[-1]
    momentum_20d = _return(closes[-21], latest)
    momentum_60d = _return(closes[-61], latest) if len(closes) >= 61 else None
    momentum_120d = _return(closes[-121], latest) if len(closes) >= 121 else None
    ma5 = mean(closes[-5:])
    ma20 = mean(closes[-20:])
    ma60 = mean(closes[-60:]) if len(closes) >= 60 else None
    ma_alignment = _ma_alignment(latest, ma5, ma20, ma60)
    rsi_14 = _rsi(closes, 14)
    avg_volume_20 = mean(volumes[-21:-1]) if len(volumes) >= 21 else None
    volume_surge = (volumes[-1] / avg_volume_20) if avg_volume_20 and avg_volume_20 > 0 else None
    daily_returns = [_return(previous, current) for previous, current in zip(closes[-21:-1], closes[-20:])]
    volatility_20d = pstdev(daily_returns) * sqrt(252) if len(daily_returns) >= 2 else None
    window = closes[-60:] if len(closes) >= 60 else closes
    distance_from_high = (latest / max(window)) - 1 if window else None

    weights = dict(_DEFAULT_WEIGHTS, **(weights or {}))
    composite = 0.0
    composite += weights["momentum"] * _clip(momentum_20d * 4)
    if momentum_60d is not None:
        composite += weights["momentum_long"] * _clip(momentum_60d * 2)
    composite += weights["trend"] * ma_alignment
    if rsi_14 is not None:
        composite += weights["rsi"] * _rsi_score(rsi_14)
    if volume_surge is not None:
        composite += weights["volume"] * _clip((volume_surge - 1.0))
    if volatility_20d is not None:
        composite -= weights["volatility_penalty"] * _clip(max(volatility_20d - 0.45, 0.0) * 2)
    if distance_from_high is not None:
        composite += weights["breakout"] * _clip(1 + distance_from_high * 5)

    labels = _labels(
        momentum_20d=momentum_20d,
        ma_alignment=ma_alignment,
        rsi_14=rsi_14,
        volume_surge=volume_surge,
        volatility_20d=volatility_20d,
        distance_from_high=distance_from_high,
    )
    return FactorScores(
        momentum_20d=_round(momentum_20d),
        momentum_60d=_round(momentum_60d),
        momentum_120d=_round(momentum_120d),
        ma_alignment=_round(ma_alignment) or 0.0,
        rsi_14=_round(rsi_14, 2),
        volume_surge=_round(volume_surge, 3),
        volatility_20d=_round(volatility_20d),
        distance_from_high_60d=_round(distance_from_high),
        composite=round(composite, 4),
        labels=labels,
    )


_DEFAULT_WEIGHTS = {
    "momentum": 1.0,
    "momentum_long": 0.6,
    "trend": 0.8,
    "rsi": 0.5,
    "volume": 0.5,
    "volatility_penalty": 0.7,
    "breakout": 0.4,
}


def _ma_alignment(latest: float, ma5: float, ma20: float, ma60: float | None) -> float:
    score = 0.0
    score += 0.4 if latest > ma20 else -0.4
    score += 0.3 if ma5 > ma20 else -0.3
    if ma60 is not None:
        score += 0.3 if ma20 > ma60 else -0.3
    return score


def _rsi(closes: Sequence[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    gains = []
    losses = []
    for previous, current in zip(closes[-period - 1 : -1], closes[-period:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = mean(gains)
    average_loss = mean(losses)
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def _rsi_score(rsi: float) -> float:
    """Favour healthy momentum (50-70), penalise overbought (>80) and weak (<40)."""

    if rsi >= 80:
        return -0.6
    if rsi >= 50:
        return min((rsi - 50) / 20, 1.0)
    if rsi >= 40:
        return 0.0
    return -0.5


def _labels(
    *,
    momentum_20d: float,
    ma_alignment: float,
    rsi_14: float | None,
    volume_surge: float | None,
    volatility_20d: float | None,
    distance_from_high: float | None,
) -> list[str]:
    labels: list[str] = []
    if ma_alignment >= 0.9:
        labels.append("정배열 상승추세")
    elif ma_alignment <= -0.9:
        labels.append("역배열 하락추세")
    if momentum_20d >= 0.08:
        labels.append("20일 강한 모멘텀")
    elif momentum_20d <= -0.08:
        labels.append("20일 약세")
    if rsi_14 is not None and rsi_14 >= 75:
        labels.append("RSI 과열")
    if volume_surge is not None and volume_surge >= 1.8:
        labels.append("거래량 급증")
    if volatility_20d is not None and volatility_20d >= 0.6:
        labels.append("고변동성")
    if distance_from_high is not None and distance_from_high >= -0.03:
        labels.append("60일 고점 근접")
    return labels or ["중립"]


def _return(start: float, end: float) -> float:
    if start <= 0:
        return 0.0
    return (end / start) - 1


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)

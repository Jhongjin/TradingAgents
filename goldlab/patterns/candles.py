"""Candlestick patterns, each written as arithmetic on the bars.

Every detector below asks the same three questions in some form: where the body
sits inside the range, how the body compares with the bars around it, and where
the close lands relative to the previous bar. The thresholds are stated as
named constants rather than buried, so a study can be re-run with different
ones and the difference attributed.
"""

from __future__ import annotations

from statistics import mean
from typing import Sequence

from ..data import Bar
from . import PatternHit, register

SMALL_BODY = 0.30        # body at most this share of the bar's range
LONG_BODY = 0.60         # body at least this share of the bar's range
LONG_SHADOW = 2.0        # shadow at least this many times the body
TINY_BODY = 0.10         # doji
TREND_LOOKBACK = 10      # bars used to say the market had been going somewhere
TREND_MOVE = 0.004       # how far it must have gone to count as a trend


def _body(bar: Bar) -> float:
    return abs(bar.close - bar.open)


def _range(bar: Bar) -> float:
    return max(bar.high - bar.low, 1e-9)


def _body_share(bar: Bar) -> float:
    return _body(bar) / _range(bar)


def _upper_shadow(bar: Bar) -> float:
    return bar.high - max(bar.open, bar.close)


def _lower_shadow(bar: Bar) -> float:
    return min(bar.open, bar.close) - bar.low


def _is_up(bar: Bar) -> bool:
    return bar.close > bar.open


def _average_body(bars: Sequence[Bar], index: int, window: int = 14) -> float:
    start = max(index - window, 0)
    sample = bars[start:index]
    return mean(_body(bar) for bar in sample) if sample else _body(bars[index])


def _downtrend(bars: Sequence[Bar], index: int) -> bool:
    start = index - TREND_LOOKBACK
    if start < 0:
        return False
    return bars[index].close < bars[start].close * (1 - TREND_MOVE)


def _uptrend(bars: Sequence[Bar], index: int) -> bool:
    start = index - TREND_LOOKBACK
    if start < 0:
        return False
    return bars[index].close > bars[start].close * (1 + TREND_MOVE)


def _hit(name: str, label: str, direction: str, bars: Sequence[Bar], index: int, **detail) -> PatternHit:
    bar = bars[index]
    return PatternHit(
        pattern=name,
        label=label,
        direction=direction,
        index=index,
        timestamp=bar.timestamp,
        price=bar.close,
        detail=detail,
    )


@register("bullish_engulfing", "상승 장악형", "bullish")
def bullish_engulfing(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(1, len(bars)):
        previous, current = bars[index - 1], bars[index]
        if _is_up(previous) or not _is_up(current):
            continue
        if current.close <= previous.open or current.open >= previous.close:
            continue
        if _body(current) < _body(previous):
            continue
        if not _downtrend(bars, index - 1):
            continue
        hits.append(_hit("bullish_engulfing", "상승 장악형", "bullish", bars, index, body_ratio=round(_body(current) / max(_body(previous), 1e-9), 3)))
    return hits


@register("bearish_engulfing", "하락 장악형", "bearish")
def bearish_engulfing(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(1, len(bars)):
        previous, current = bars[index - 1], bars[index]
        if not _is_up(previous) or _is_up(current):
            continue
        if current.close >= previous.open or current.open <= previous.close:
            continue
        if _body(current) < _body(previous):
            continue
        if not _uptrend(bars, index - 1):
            continue
        hits.append(_hit("bearish_engulfing", "하락 장악형", "bearish", bars, index, body_ratio=round(_body(current) / max(_body(previous), 1e-9), 3)))
    return hits


@register("hammer", "망치형", "bullish")
def hammer(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(TREND_LOOKBACK, len(bars)):
        bar = bars[index]
        body = _body(bar)
        if body <= 0 or _body_share(bar) > SMALL_BODY:
            continue
        if _lower_shadow(bar) < LONG_SHADOW * body or _upper_shadow(bar) > body:
            continue
        if not _downtrend(bars, index):
            continue
        hits.append(_hit("hammer", "망치형", "bullish", bars, index, shadow_ratio=round(_lower_shadow(bar) / max(body, 1e-9), 2)))
    return hits


@register("shooting_star", "유성형", "bearish")
def shooting_star(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(TREND_LOOKBACK, len(bars)):
        bar = bars[index]
        body = _body(bar)
        if body <= 0 or _body_share(bar) > SMALL_BODY:
            continue
        if _upper_shadow(bar) < LONG_SHADOW * body or _lower_shadow(bar) > body:
            continue
        if not _uptrend(bars, index):
            continue
        hits.append(_hit("shooting_star", "유성형", "bearish", bars, index, shadow_ratio=round(_upper_shadow(bar) / max(body, 1e-9), 2)))
    return hits


@register("morning_star", "샛별형", "bullish")
def morning_star(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(2, len(bars)):
        first, middle, last = bars[index - 2], bars[index - 1], bars[index]
        if _is_up(first) or not _is_up(last):
            continue
        if _body_share(middle) > SMALL_BODY:
            continue
        if _body(first) < _average_body(bars, index - 2) or _body(last) < _average_body(bars, index):
            continue
        if middle.close > first.close or last.close < (first.open + first.close) / 2:
            continue
        hits.append(_hit("morning_star", "샛별형", "bullish", bars, index))
    return hits


@register("evening_star", "석별형", "bearish")
def evening_star(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(2, len(bars)):
        first, middle, last = bars[index - 2], bars[index - 1], bars[index]
        if not _is_up(first) or _is_up(last):
            continue
        if _body_share(middle) > SMALL_BODY:
            continue
        if _body(first) < _average_body(bars, index - 2) or _body(last) < _average_body(bars, index):
            continue
        if middle.close < first.close or last.close > (first.open + first.close) / 2:
            continue
        hits.append(_hit("evening_star", "석별형", "bearish", bars, index))
    return hits


@register("doji", "도지", "bullish")
def doji(bars: Sequence[Bar]) -> list[PatternHit]:
    """Indecision. Registered as bullish only so the study has one side to measure."""

    hits = []
    for index in range(TREND_LOOKBACK, len(bars)):
        bar = bars[index]
        if _body_share(bar) > TINY_BODY:
            continue
        if _range(bar) < _average_body(bars, index):
            continue
        hits.append(_hit("doji", "도지", "bullish", bars, index, body_share=round(_body_share(bar), 4)))
    return hits


@register("three_white_soldiers", "적삼병", "bullish")
def three_white_soldiers(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(2, len(bars)):
        trio = bars[index - 2 : index + 1]
        if not all(_is_up(bar) for bar in trio):
            continue
        if not all(_body_share(bar) >= LONG_BODY for bar in trio):
            continue
        if not (trio[1].close > trio[0].close and trio[2].close > trio[1].close):
            continue
        if not (trio[1].open > trio[0].open and trio[2].open > trio[1].open):
            continue
        hits.append(_hit("three_white_soldiers", "적삼병", "bullish", bars, index))
    return hits


@register("three_black_crows", "흑삼병", "bearish")
def three_black_crows(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(2, len(bars)):
        trio = bars[index - 2 : index + 1]
        if any(_is_up(bar) for bar in trio):
            continue
        if not all(_body_share(bar) >= LONG_BODY for bar in trio):
            continue
        if not (trio[1].close < trio[0].close and trio[2].close < trio[1].close):
            continue
        if not (trio[1].open < trio[0].open and trio[2].open < trio[1].open):
            continue
        hits.append(_hit("three_black_crows", "흑삼병", "bearish", bars, index))
    return hits


@register("bullish_harami", "상승 잉태형", "bullish")
def bullish_harami(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(1, len(bars)):
        previous, current = bars[index - 1], bars[index]
        if _is_up(previous) or not _is_up(current):
            continue
        if not (current.open > previous.close and current.close < previous.open):
            continue
        if _body(previous) < _average_body(bars, index - 1):
            continue
        hits.append(_hit("bullish_harami", "상승 잉태형", "bullish", bars, index))
    return hits


@register("bearish_harami", "하락 잉태형", "bearish")
def bearish_harami(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(1, len(bars)):
        previous, current = bars[index - 1], bars[index]
        if not _is_up(previous) or _is_up(current):
            continue
        if not (current.open < previous.close and current.close > previous.open):
            continue
        if _body(previous) < _average_body(bars, index - 1):
            continue
        hits.append(_hit("bearish_harami", "하락 잉태형", "bearish", bars, index))
    return hits


@register("inside_bar", "인사이드 바", "bullish")
def inside_bar(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(1, len(bars)):
        previous, current = bars[index - 1], bars[index]
        if current.high < previous.high and current.low > previous.low:
            hits.append(_hit("inside_bar", "인사이드 바", "bullish", bars, index))
    return hits


@register("bullish_outside_bar", "상승 아웃사이드 바", "bullish")
def bullish_outside_bar(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(1, len(bars)):
        previous, current = bars[index - 1], bars[index]
        if current.high > previous.high and current.low < previous.low and _is_up(current):
            hits.append(_hit("bullish_outside_bar", "상승 아웃사이드 바", "bullish", bars, index))
    return hits


@register("bearish_outside_bar", "하락 아웃사이드 바", "bearish")
def bearish_outside_bar(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    for index in range(1, len(bars)):
        previous, current = bars[index - 1], bars[index]
        if current.high > previous.high and current.low < previous.low and not _is_up(current):
            hits.append(_hit("bearish_outside_bar", "하락 아웃사이드 바", "bearish", bars, index))
    return hits

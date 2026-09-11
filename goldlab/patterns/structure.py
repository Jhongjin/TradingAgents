"""Multi-bar chart patterns, found through swing points.

The shapes traders name — double tops, head and shoulders, triangles, flags —
are all statements about where the swing highs and lows sit relative to one
another. So the swings are found first, with a fixed lookback so the same chart
always yields the same pivots, and each shape is then a comparison between a
handful of them.

A pattern is dated at the bar that completes it, never at the bar that made it
visible in hindsight. Every detector confirms on a break, so a hit could have
been acted on when it was recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..data import Bar
from . import PatternHit, register

PIVOT_SPAN = 3          # bars either side that a swing must beat
TOLERANCE = 0.004       # how close two prices count as "the same level"
MIN_DEPTH = 0.006       # how far the middle must travel for a shape to be real
FLAG_IMPULSE = 0.012    # the move a flag consolidates after
FLAG_MAX_BARS = 15
TRIANGLE_MIN_SWINGS = 4


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float
    kind: str  # "high" | "low"


def find_pivots(bars: Sequence[Bar], span: int = PIVOT_SPAN) -> list[Pivot]:
    """Swing highs and lows that stand out from ``span`` bars on either side."""

    pivots: list[Pivot] = []
    for index in range(span, len(bars) - span):
        window = bars[index - span : index + span + 1]
        bar = bars[index]
        if bar.high == max(item.high for item in window) and bar.high > bars[index - 1].high:
            pivots.append(Pivot(index=index, price=bar.high, kind="high"))
        elif bar.low == min(item.low for item in window) and bar.low < bars[index - 1].low:
            pivots.append(Pivot(index=index, price=bar.low, kind="low"))
    return pivots


def _close_enough(left: float, right: float, tolerance: float = TOLERANCE) -> bool:
    reference = max(abs(left), abs(right), 1e-9)
    return abs(left - right) / reference <= tolerance


def _confirm_break(bars: Sequence[Bar], start: int, level: float, *, above: bool, limit: int = 20) -> int | None:
    """The first bar after ``start`` that closes through ``level``."""

    for index in range(start + 1, min(start + 1 + limit, len(bars))):
        close = bars[index].close
        if (above and close > level) or (not above and close < level):
            return index
    return None


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


@register("double_bottom", "이중 바닥", "bullish")
def double_bottom(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    pivots = find_pivots(bars)
    lows = [pivot for pivot in pivots if pivot.kind == "low"]
    for first, second in zip(lows, lows[1:]):
        if not _close_enough(first.price, second.price):
            continue
        middle = [pivot for pivot in pivots if pivot.kind == "high" and first.index < pivot.index < second.index]
        if not middle:
            continue
        neckline = max(pivot.price for pivot in middle)
        if neckline < max(first.price, second.price) * (1 + MIN_DEPTH):
            continue
        confirmed = _confirm_break(bars, second.index, neckline, above=True)
        if confirmed is None:
            continue
        hits.append(_hit("double_bottom", "이중 바닥", "bullish", bars, confirmed, neckline=round(neckline, 2), low=round(min(first.price, second.price), 2)))
    return hits


@register("double_top", "이중 천장", "bearish")
def double_top(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    pivots = find_pivots(bars)
    highs = [pivot for pivot in pivots if pivot.kind == "high"]
    for first, second in zip(highs, highs[1:]):
        if not _close_enough(first.price, second.price):
            continue
        middle = [pivot for pivot in pivots if pivot.kind == "low" and first.index < pivot.index < second.index]
        if not middle:
            continue
        neckline = min(pivot.price for pivot in middle)
        if neckline > min(first.price, second.price) * (1 - MIN_DEPTH):
            continue
        confirmed = _confirm_break(bars, second.index, neckline, above=False)
        if confirmed is None:
            continue
        hits.append(_hit("double_top", "이중 천장", "bearish", bars, confirmed, neckline=round(neckline, 2), high=round(max(first.price, second.price), 2)))
    return hits


@register("head_and_shoulders", "헤드앤숄더", "bearish")
def head_and_shoulders(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    pivots = find_pivots(bars)
    highs = [pivot for pivot in pivots if pivot.kind == "high"]
    for left, head, right in zip(highs, highs[1:], highs[2:]):
        if not (head.price > left.price and head.price > right.price):
            continue
        if not _close_enough(left.price, right.price, TOLERANCE * 2):
            continue
        troughs = [pivot for pivot in pivots if pivot.kind == "low" and left.index < pivot.index < right.index]
        if len(troughs) < 2:
            continue
        neckline = min(pivot.price for pivot in troughs)
        if head.price < neckline * (1 + MIN_DEPTH * 2):
            continue
        confirmed = _confirm_break(bars, right.index, neckline, above=False)
        if confirmed is None:
            continue
        hits.append(_hit("head_and_shoulders", "헤드앤숄더", "bearish", bars, confirmed, neckline=round(neckline, 2), head=round(head.price, 2)))
    return hits


@register("inverse_head_and_shoulders", "역 헤드앤숄더", "bullish")
def inverse_head_and_shoulders(bars: Sequence[Bar]) -> list[PatternHit]:
    hits = []
    pivots = find_pivots(bars)
    lows = [pivot for pivot in pivots if pivot.kind == "low"]
    for left, head, right in zip(lows, lows[1:], lows[2:]):
        if not (head.price < left.price and head.price < right.price):
            continue
        if not _close_enough(left.price, right.price, TOLERANCE * 2):
            continue
        peaks = [pivot for pivot in pivots if pivot.kind == "high" and left.index < pivot.index < right.index]
        if len(peaks) < 2:
            continue
        neckline = max(pivot.price for pivot in peaks)
        if head.price > neckline * (1 - MIN_DEPTH * 2):
            continue
        confirmed = _confirm_break(bars, right.index, neckline, above=True)
        if confirmed is None:
            continue
        hits.append(_hit("inverse_head_and_shoulders", "역 헤드앤숄더", "bullish", bars, confirmed, neckline=round(neckline, 2), head=round(head.price, 2)))
    return hits


def _triangle(bars: Sequence[Bar], *, ascending: bool) -> list[PatternHit]:
    """Ascending: a flat ceiling with rising lows. Descending: the mirror."""

    hits = []
    pivots = find_pivots(bars)
    highs = [pivot for pivot in pivots if pivot.kind == "high"]
    lows = [pivot for pivot in pivots if pivot.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return hits

    for position in range(1, min(len(highs), len(lows))):
        recent_highs = highs[position - 1 : position + 1]
        recent_lows = lows[position - 1 : position + 1]
        if len(recent_highs) < 2 or len(recent_lows) < 2:
            continue
        start = min(recent_highs[0].index, recent_lows[0].index)
        end = max(recent_highs[-1].index, recent_lows[-1].index)
        if end - start < TRIANGLE_MIN_SWINGS:
            continue
        flat_top = _close_enough(recent_highs[0].price, recent_highs[1].price)
        rising_lows = recent_lows[1].price > recent_lows[0].price * (1 + TOLERANCE)
        flat_bottom = _close_enough(recent_lows[0].price, recent_lows[1].price)
        falling_highs = recent_highs[1].price < recent_highs[0].price * (1 - TOLERANCE)
        if ascending and not (flat_top and rising_lows):
            continue
        if not ascending and not (flat_bottom and falling_highs):
            continue
        level = recent_highs[1].price if ascending else recent_lows[1].price
        confirmed = _confirm_break(bars, end, level, above=ascending)
        if confirmed is None:
            continue
        name = "ascending_triangle" if ascending else "descending_triangle"
        label = "상승 삼각형" if ascending else "하락 삼각형"
        hits.append(_hit(name, label, "bullish" if ascending else "bearish", bars, confirmed, level=round(level, 2)))
    return hits


@register("ascending_triangle", "상승 삼각형", "bullish")
def ascending_triangle(bars: Sequence[Bar]) -> list[PatternHit]:
    return _triangle(bars, ascending=True)


@register("descending_triangle", "하락 삼각형", "bearish")
def descending_triangle(bars: Sequence[Bar]) -> list[PatternHit]:
    return _triangle(bars, ascending=False)


def _flag(bars: Sequence[Bar], *, bullish: bool) -> list[PatternHit]:
    """A sharp move, a tight drift against it, then a break the original way."""

    hits = []
    span = 8
    for index in range(span * 2, len(bars) - 1):
        impulse_start = bars[index - span * 2]
        impulse_end = bars[index - span]
        move = (impulse_end.close / impulse_start.close) - 1
        if bullish and move < FLAG_IMPULSE:
            continue
        if not bullish and move > -FLAG_IMPULSE:
            continue
        window = bars[index - span : index + 1]
        if len(window) < 4 or len(window) > FLAG_MAX_BARS:
            continue
        top = max(bar.high for bar in window)
        bottom = min(bar.low for bar in window)
        if (top - bottom) / max(impulse_end.close, 1e-9) > abs(move) * 0.7:
            continue  # the drift must be tighter than the move it follows
        level = top if bullish else bottom
        confirmed = _confirm_break(bars, index, level, above=bullish, limit=5)
        if confirmed is None:
            continue
        name = "bull_flag" if bullish else "bear_flag"
        label = "상승 깃발형" if bullish else "하락 깃발형"
        hits.append(_hit(name, label, "bullish" if bullish else "bearish", bars, confirmed, impulse=round(move, 4), level=round(level, 2)))
    return hits


@register("bull_flag", "상승 깃발형", "bullish")
def bull_flag(bars: Sequence[Bar]) -> list[PatternHit]:
    return _flag(bars, bullish=True)


@register("bear_flag", "하락 깃발형", "bearish")
def bear_flag(bars: Sequence[Bar]) -> list[PatternHit]:
    return _flag(bars, bullish=False)


@register("range_breakout_up", "박스 상단 돌파", "bullish")
def range_breakout_up(bars: Sequence[Bar], window: int = 20) -> list[PatternHit]:
    hits = []
    for index in range(window, len(bars)):
        prior = bars[index - window : index]
        ceiling = max(bar.high for bar in prior)
        floor = min(bar.low for bar in prior)
        if (ceiling - floor) / max(ceiling, 1e-9) > 0.03:
            continue  # a wide swing is not a box
        if bars[index].close > ceiling:
            hits.append(_hit("range_breakout_up", "박스 상단 돌파", "bullish", bars, index, ceiling=round(ceiling, 2)))
    return hits


@register("range_breakout_down", "박스 하단 이탈", "bearish")
def range_breakout_down(bars: Sequence[Bar], window: int = 20) -> list[PatternHit]:
    hits = []
    for index in range(window, len(bars)):
        prior = bars[index - window : index]
        ceiling = max(bar.high for bar in prior)
        floor = min(bar.low for bar in prior)
        if (ceiling - floor) / max(ceiling, 1e-9) > 0.03:
            continue
        if bars[index].close < floor:
            hits.append(_hit("range_breakout_down", "박스 하단 이탈", "bearish", bars, index, floor=round(floor, 2)))
    return hits

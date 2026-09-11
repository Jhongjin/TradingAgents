"""Lines drawn from the bars themselves: averages and trend lines.

A moving average is arithmetic and needs no explanation. A trend line is a
choice, because any two points make one, so the choice is stated: the two most
recent swing lows for support and the two most recent swing highs for
resistance, each extended to the last bar so the chart shows where price sits
against it now.
"""

from __future__ import annotations

from typing import Sequence

from .data import Bar
from .patterns.structure import Pivot, find_pivots

MA_PERIODS: tuple[int, ...] = (20, 50, 200)
TREND_LOOKBACK = 160


def simple_moving_average(values: Sequence[float], period: int) -> list[float | None]:
    """The plain average of the last ``period`` values; None until there are enough."""

    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= period:
            running -= values[index - period]
        out.append(round(running / period, 2) if index >= period - 1 else None)
    return out


def exponential_moving_average(values: Sequence[float], period: int) -> list[float | None]:
    """Seeded with the simple average so the first value is not one bar's whim."""

    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = []
    weight = 2 / (period + 1)
    current: float | None = None
    for index, value in enumerate(values):
        if index < period - 1:
            out.append(None)
            continue
        if current is None:
            current = sum(values[index - period + 1 : index + 1]) / period
        else:
            current = value * weight + current * (1 - weight)
        out.append(round(current, 2))
    return out


def moving_averages(bars: Sequence[Bar], periods: Sequence[int] = MA_PERIODS) -> dict[str, list[float | None]]:
    closes = [bar.close for bar in bars]
    return {str(period): simple_moving_average(closes, period) for period in periods if len(closes) >= period}


def _line_through(first: Pivot, second: Pivot, until: int) -> dict:
    slope = (second.price - first.price) / max(second.index - first.index, 1)
    return {
        "kind": first.kind,
        "from_index": first.index,
        "from_price": round(first.price, 2),
        "to_index": until,
        "to_price": round(second.price + slope * (until - second.index), 2),
        "slope": round(slope, 4),
        "anchor_index": second.index,
        "anchor_price": round(second.price, 2),
    }


def trend_lines(bars: Sequence[Bar], *, lookback: int = TREND_LOOKBACK) -> list[dict]:
    """Support through the last two swing lows, resistance through the last two highs.

    Both are extended to the final bar. A line that price has already closed
    through is still drawn, because a broken trend line is what a trader is
    looking for, and the ``broken`` flag says so.
    """

    if len(bars) < 10:
        return []
    offset = max(0, len(bars) - lookback)
    window = bars[offset:]
    pivots = find_pivots(window)
    lines: list[dict] = []
    last = len(bars) - 1
    last_close = bars[-1].close
    for kind in ("low", "high"):
        mine = [pivot for pivot in pivots if pivot.kind == kind]
        if len(mine) < 2:
            continue
        first, second = mine[-2], mine[-1]
        shifted_first = Pivot(index=first.index + offset, price=first.price, kind=kind)
        shifted_second = Pivot(index=second.index + offset, price=second.price, kind=kind)
        line = _line_through(shifted_first, shifted_second, last)
        line["label"] = "지지선" if kind == "low" else "저항선"
        line["direction"] = "rising" if line["slope"] > 0 else ("falling" if line["slope"] < 0 else "flat")
        line["broken"] = last_close < line["to_price"] if kind == "low" else last_close > line["to_price"]
        lines.append(line)
    return lines

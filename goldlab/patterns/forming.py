"""Shapes that are on the chart now but have not yet resolved.

The detectors in ``structure`` date a pattern at the bar that confirms it,
because that is the only bar a trader could have acted on. But a trader is
looking at the chart before that bar, asking what is taking shape and where it
would confirm. These are the same shapes with the confirmation step removed:
each one names the level a close would have to pass, how far price is from it,
and which completed pattern it would then become, so the measured record for
that pattern can be quoted as the forecast.

Nothing here predicts. It says: if this level goes, the pattern that completes
has done such-and-such before.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..data import Bar
from .structure import (
    FLAG_IMPULSE,
    FLAG_MAX_BARS,
    MIN_DEPTH,
    TOLERANCE,
    TRIANGLE_MIN_SWINGS,
    Pivot,
    _close_enough,
    find_pivots,
)

RECENT_BARS = 40           # a shape whose last swing is older than this is stale
MAX_DISTANCE = 0.10        # a trigger further than this from price is not 'now'
RANGE_WINDOW = 20
RANGE_MAX_WIDTH = 0.03


def _crossed(bars: Sequence[Bar], start: int, level: float, *, above: bool) -> bool:
    """Has any close since ``start`` already gone through the level?"""

    for bar in bars[start + 1 :]:
        if (above and bar.close > level) or (not above and bar.close < level):
            return True
    return False


def _entry(
    name: str,
    label: str,
    direction: str,
    bars: Sequence[Bar],
    *,
    start_index: int,
    last_pivot_index: int,
    trigger: float,
    trigger_label: str,
    stage: str,
    **detail: Any,
) -> dict[str, Any]:
    last = bars[-1]
    distance = (trigger - last.close) / max(last.close, 1e-9)
    return {
        "pattern": name,
        "label": label,
        "direction": direction,
        "start_index": start_index,
        "last_pivot_index": last_pivot_index,
        "trigger": round(trigger, 2),
        "trigger_label": trigger_label,
        "distance": round(distance, 5),
        "stage": stage,
        "detail": detail,
    }


def _double(bars: Sequence[Bar], pivots: list[Pivot], *, bottom: bool, cutoff: int) -> dict[str, Any] | None:
    kind, other = ("low", "high") if bottom else ("high", "low")
    mine = [pivot for pivot in pivots if pivot.kind == kind]
    for first, second in reversed(list(zip(mine, mine[1:]))):
        if second.index < cutoff:
            break
        if not _close_enough(first.price, second.price):
            continue
        middle = [pivot for pivot in pivots if pivot.kind == other and first.index < pivot.index < second.index]
        if not middle:
            continue
        if bottom:
            neckline = max(pivot.price for pivot in middle)
            if neckline < max(first.price, second.price) * (1 + MIN_DEPTH):
                continue
            if _crossed(bars, second.index, neckline, above=True):
                continue
            return _entry(
                "double_bottom", "이중 바닥", "bullish", bars,
                start_index=first.index, last_pivot_index=second.index,
                trigger=neckline, trigger_label="넥라인 돌파",
                stage="두 번째 바닥 확인, 넥라인 대기",
                low=round(min(first.price, second.price), 2),
            )
        neckline = min(pivot.price for pivot in middle)
        if neckline > min(first.price, second.price) * (1 - MIN_DEPTH):
            continue
        if _crossed(bars, second.index, neckline, above=False):
            continue
        return _entry(
            "double_top", "이중 천장", "bearish", bars,
            start_index=first.index, last_pivot_index=second.index,
            trigger=neckline, trigger_label="넥라인 이탈",
            stage="두 번째 천장 확인, 넥라인 대기",
            high=round(max(first.price, second.price), 2),
        )
    return None


def _head_and_shoulders(bars: Sequence[Bar], pivots: list[Pivot], *, inverse: bool, cutoff: int) -> dict[str, Any] | None:
    kind, other = ("low", "high") if inverse else ("high", "low")
    mine = [pivot for pivot in pivots if pivot.kind == kind]
    for left, head, right in reversed(list(zip(mine, mine[1:], mine[2:]))):
        if right.index < cutoff:
            break
        extreme = head.price < left.price and head.price < right.price if inverse else head.price > left.price and head.price > right.price
        if not extreme or not _close_enough(left.price, right.price, TOLERANCE * 2):
            continue
        between = [pivot for pivot in pivots if pivot.kind == other and left.index < pivot.index < right.index]
        if len(between) < 2:
            continue
        if inverse:
            neckline = max(pivot.price for pivot in between)
            if head.price > neckline * (1 - MIN_DEPTH * 2) or _crossed(bars, right.index, neckline, above=True):
                continue
            return _entry(
                "inverse_head_and_shoulders", "역 헤드앤숄더", "bullish", bars,
                start_index=left.index, last_pivot_index=right.index,
                trigger=neckline, trigger_label="넥라인 돌파",
                stage="오른쪽 어깨 형성, 넥라인 대기", head=round(head.price, 2),
            )
        neckline = min(pivot.price for pivot in between)
        if head.price < neckline * (1 + MIN_DEPTH * 2) or _crossed(bars, right.index, neckline, above=False):
            continue
        return _entry(
            "head_and_shoulders", "헤드앤숄더", "bearish", bars,
            start_index=left.index, last_pivot_index=right.index,
            trigger=neckline, trigger_label="넥라인 이탈",
            stage="오른쪽 어깨 형성, 넥라인 대기", head=round(head.price, 2),
        )
    return None


def _triangle(bars: Sequence[Bar], pivots: list[Pivot], *, ascending: bool, cutoff: int) -> dict[str, Any] | None:
    highs = [pivot for pivot in pivots if pivot.kind == "high"]
    lows = [pivot for pivot in pivots if pivot.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return None
    for position in range(min(len(highs), len(lows)) - 1, 0, -1):
        recent_highs = highs[position - 1 : position + 1]
        recent_lows = lows[position - 1 : position + 1]
        start = min(recent_highs[0].index, recent_lows[0].index)
        end = max(recent_highs[-1].index, recent_lows[-1].index)
        if end < cutoff:
            break
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
        if _crossed(bars, end, level, above=ascending):
            continue
        if ascending:
            return _entry(
                "ascending_triangle", "상승 삼각형", "bullish", bars,
                start_index=start, last_pivot_index=end,
                trigger=level, trigger_label="윗변 돌파",
                stage="저점 높아지는 중, 윗변 대기",
                floor=round(recent_lows[1].price, 2),
            )
        return _entry(
            "descending_triangle", "하락 삼각형", "bearish", bars,
            start_index=start, last_pivot_index=end,
            trigger=level, trigger_label="아랫변 이탈",
            stage="고점 낮아지는 중, 아랫변 대기",
            ceiling=round(recent_highs[1].price, 2),
        )
    return None


def _flag(bars: Sequence[Bar], *, bullish: bool) -> dict[str, Any] | None:
    """An impulse and a tight drift that reaches the last bar, not yet broken."""

    span = 8
    last = len(bars) - 1
    for drift_len in range(4, min(FLAG_MAX_BARS, span) + 1):
        index = last
        impulse_start = index - drift_len - span
        impulse_end = index - drift_len
        if impulse_start < 0:
            continue
        move = (bars[impulse_end].close / bars[impulse_start].close) - 1
        if bullish and move < FLAG_IMPULSE:
            continue
        if not bullish and move > -FLAG_IMPULSE:
            continue
        window = bars[impulse_end : index + 1]
        top = max(bar.high for bar in window)
        bottom = min(bar.low for bar in window)
        if (top - bottom) / max(bars[impulse_end].close, 1e-9) > abs(move) * 0.7:
            continue
        level = top if bullish else bottom
        if bullish and bars[-1].close > level:
            continue
        if not bullish and bars[-1].close < level:
            continue
        if bullish:
            return _entry(
                "bull_flag", "상승 깃발형", "bullish", bars,
                start_index=impulse_start, last_pivot_index=impulse_end,
                trigger=level, trigger_label="깃발 상단 돌파",
                stage=f"급등 뒤 {drift_len}봉 횡보 중", impulse=round(move, 4),
            )
        return _entry(
            "bear_flag", "하락 깃발형", "bearish", bars,
            start_index=impulse_start, last_pivot_index=impulse_end,
            trigger=level, trigger_label="깃발 하단 이탈",
            stage=f"급락 뒤 {drift_len}봉 횡보 중", impulse=round(move, 4),
        )
    return None


def _range(bars: Sequence[Bar]) -> list[dict[str, Any]]:
    """A box the last ``RANGE_WINDOW`` bars have stayed inside, with both exits."""

    if len(bars) <= RANGE_WINDOW:
        return []
    prior = bars[-RANGE_WINDOW - 1 : -1]
    ceiling = max(bar.high for bar in prior)
    floor = min(bar.low for bar in prior)
    if (ceiling - floor) / max(ceiling, 1e-9) > RANGE_MAX_WIDTH:
        return []
    last = bars[-1].close
    if last > ceiling or last < floor:
        return []
    start = len(bars) - 1 - RANGE_WINDOW
    return [
        _entry(
            "range_breakout_up", "박스 상단 돌파", "bullish", bars,
            start_index=start, last_pivot_index=len(bars) - 2,
            trigger=ceiling, trigger_label="박스 상단 돌파",
            stage=f"{RANGE_WINDOW}봉 박스권", floor=round(floor, 2),
        ),
        _entry(
            "range_breakout_down", "박스 하단 이탈", "bearish", bars,
            start_index=start, last_pivot_index=len(bars) - 2,
            trigger=floor, trigger_label="박스 하단 이탈",
            stage=f"{RANGE_WINDOW}봉 박스권", ceiling=round(ceiling, 2),
        ),
    ]


def detect_forming(bars: Sequence[Bar], *, recent: int = RECENT_BARS, max_distance: float = MAX_DISTANCE) -> list[dict[str, Any]]:
    """Every unresolved shape whose last swing is recent and whose trigger is near.

    A double top whose neckline sits half the price away is a shape from
    another era, not something forming now, so the trigger must be within
    ``max_distance`` of the last close.
    """

    if len(bars) < 30:
        return []
    pivots = find_pivots(bars)
    cutoff = max(0, len(bars) - recent)
    found: list[dict[str, Any]] = []
    for candidate in (
        _double(bars, pivots, bottom=True, cutoff=cutoff),
        _double(bars, pivots, bottom=False, cutoff=cutoff),
        _head_and_shoulders(bars, pivots, inverse=True, cutoff=cutoff),
        _head_and_shoulders(bars, pivots, inverse=False, cutoff=cutoff),
        _triangle(bars, pivots, ascending=True, cutoff=cutoff),
        _triangle(bars, pivots, ascending=False, cutoff=cutoff),
        _flag(bars, bullish=True),
        _flag(bars, bullish=False),
    ):
        if candidate is not None:
            found.append(candidate)
    found.extend(_range(bars))
    found = [row for row in found if abs(row["distance"]) <= max_distance]
    found.sort(key=lambda row: abs(row["distance"]))
    return found


def attach_record(forming: Sequence[dict[str, Any]], study: Mapping[str, Any] | None, *, min_samples: int = 30) -> list[dict[str, Any]]:
    """Quote, for each forming shape, what its completed form did before."""

    lookup: dict[str, dict] = {}
    for row in (study or {}).get("patterns") or []:
        best = None
        for stats in (row.get("horizons") or {}).values():
            if int(stats.get("count") or 0) < min_samples:
                continue
            if best is None or abs(stats.get("t_stat") or 0) > abs(best.get("t_stat") or 0):
                best = stats
        if best:
            lookup[str(row.get("pattern"))] = best

    rows = []
    for entry in forming:
        stats = lookup.get(entry["pattern"]) or {}
        samples = int(stats.get("count") or 0)
        edge = stats.get("edge_win_rate")
        t_stat = abs(float(stats.get("t_stat") or 0))
        if not samples:
            confidence = "측정 없음"
        elif edge is None or edge <= 0:
            confidence = "기준 미달"
        elif t_stat >= 3:
            confidence = "강함"
        elif t_stat >= 2:
            confidence = "보통"
        else:
            confidence = "약함"
        rows.append(
            {
                **entry,
                "samples": samples,
                "win_rate": stats.get("win_rate"),
                "edge_win_rate": edge,
                "average_return": stats.get("average_return"),
                "t_stat": stats.get("t_stat"),
                "confidence": confidence,
            }
        )
    return rows

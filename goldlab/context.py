"""What the market was like when a signal fired, using only what was known then.

A pattern's record means little pooled across every circumstance: a flag in the
New York session after a payrolls print is not the same bet as one in the quiet
hours of Tokyo. Each bar gets four tags, and every tag is computed from bars up
to and including that bar, so tagging a signal can never leak the future into
its own statistics.

* session: the latest-opening of the three markets that is open (us > europe >
  asia), or ``off``. Daily and longer bars carry ``all``: a day has no session.
* trend: close against the 50-bar and 200-bar averages. ``up`` is close above a
  50 that is above the 200, ``down`` the mirror, anything else ``range``.
* vol: the last 20 bars' mean range, ranked against the 500 bars before it.
  Ranking against the past keeps the cut-offs from peeking at a later, wilder
  market. Under about 100 bars of history the tag is ``unknown``.
* event: ``near`` within an hour either side of a scheduled release, else
  ``far``. Release dates come from events.py (computed rules plus the operator's
  file), so a missing hand-entered date reads as ``far``; that is a known gap.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

from .data import Bar
from .events import macro_events
from .sessions import sessions_for

DIMENSIONS = ("session", "trend", "vol", "event")
TREND_FAST = 50
TREND_SLOW = 200
VOL_WINDOW = 20
VOL_HISTORY = 500
VOL_MIN_HISTORY = 100
NEAR_EVENT_MINUTES = 60
LONG_INTERVALS = {"1d", "1wk", "1mo"}
SESSION_PRIORITY = ("us", "europe", "asia")


@dataclass(frozen=True)
class Context:
    session: str
    trend: str
    vol: str
    event: str
    event_minutes: float | None = None     # bar time minus the nearest release; negative = release ahead
    sessions: tuple[str, ...] = ()
    atr_pct: float | None = None           # mean bar range over the last 14 bars, as a share of the close

    def key(self) -> tuple[str, str, str, str]:
        return (self.session, self.trend, self.vol, self.event)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "trend": self.trend,
            "vol": self.vol,
            "event": self.event,
            "event_minutes": self.event_minutes,
            "sessions": list(self.sessions),
            "atr_pct": self.atr_pct,
        }


def _prefix(values: Sequence[float]) -> list[float]:
    total, out = 0.0, [0.0]
    for value in values:
        total += value
        out.append(total)
    return out


class ContextTagger:
    """Tags any bar index from the bars at or before it."""

    def __init__(self, bars: Sequence[Bar], *, interval: str, events: Sequence[datetime] | None = None):
        self.bars = bars
        self.interval = interval
        self._close = _prefix([bar.close for bar in bars])
        self._range = [(bar.high - bar.low) / max(bar.close, 1e-9) for bar in bars]
        self._range_sum = _prefix(self._range)
        # the 20-bar mean range at every bar, from prefix sums, so ranking a bar against
        # its past is a slice and not a recomputation
        self._mean20 = [self._mean_range(index, VOL_WINDOW) for index in range(len(bars))]
        if events is None and bars:
            events = [
                datetime.fromisoformat(row["timestamp"])
                for row in macro_events(bars[0].timestamp - timedelta(days=1), bars[-1].timestamp + timedelta(days=2), min_stars=2)
            ]
        self._events = sorted(stamp.timestamp() for stamp in (events or []))
        self._cache: dict[int, Context] = {}

    def _sma(self, index: int, period: int) -> float | None:
        if index + 1 < period:
            return None
        return (self._close[index + 1] - self._close[index + 1 - period]) / period

    def _mean_range(self, index: int, window: int) -> float | None:
        if index + 1 < window:
            return None
        return (self._range_sum[index + 1] - self._range_sum[index + 1 - window]) / window

    def _session(self, index: int) -> tuple[str, tuple[str, ...]]:
        if self.interval in LONG_INTERVALS:
            return "all", ()
        open_now = tuple(sessions_for(self.bars[index].timestamp))
        for key in SESSION_PRIORITY:
            if key in open_now:
                return key, open_now
        return "off", open_now

    def _trend(self, index: int) -> str:
        fast, slow = self._sma(index, TREND_FAST), self._sma(index, TREND_SLOW)
        if fast is None or slow is None:
            return "unknown"
        close = self.bars[index].close
        if close > fast > slow:
            return "up"
        if close < fast < slow:
            return "down"
        return "range"

    def _vol(self, index: int) -> str:
        current = self._mean20[index]
        if current is None:
            return "unknown"
        history = [value for value in self._mean20[max(VOL_WINDOW - 1, index - VOL_HISTORY) : index] if value is not None]
        if len(history) < VOL_MIN_HISTORY:
            return "unknown"
        rank = sum(1 for value in history if value < current) / len(history)
        return "low" if rank < 1 / 3 else ("high" if rank > 2 / 3 else "mid")

    def _event(self, index: int) -> tuple[str, float | None]:
        if not self._events:
            return "far", None
        at = self.bars[index].timestamp.timestamp()
        position = bisect_left(self._events, at)
        nearest = min(
            (self._events[item] for item in (position - 1, position) if 0 <= item < len(self._events)),
            key=lambda stamp: abs(stamp - at),
        )
        minutes = (at - nearest) / 60.0
        return ("near" if abs(minutes) <= NEAR_EVENT_MINUTES else "far"), round(minutes, 1)

    def tag(self, index: int) -> Context:
        if index in self._cache:
            return self._cache[index]
        session, open_now = self._session(index)
        event, minutes = self._event(index)
        atr = self._mean_range(index, 14)
        context = Context(
            session=session,
            trend=self._trend(index),
            vol=self._vol(index),
            event=event,
            event_minutes=minutes,
            sessions=open_now,
            atr_pct=round(atr, 6) if atr is not None else None,
        )
        self._cache[index] = context
        return context

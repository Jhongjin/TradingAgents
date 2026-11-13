"""Find signals the way a trader would have seen them: one bar at a time.

The detectors in ``patterns`` look at a whole series at once. That is right for
drawing a chart but wrong for measuring a record, because a swing high is only
confirmed three bars after it prints, and a detector handed the full history
will happily date a pattern on a bar that could not yet have known about it.

So nothing here ever shows a detector a bar after the one being judged.
``detect_at`` is the single gate: it cuts the series at bar ``t``, runs every
detector on that prefix, and returns what that prefix contains. A signal is
recorded on the first bar at which it is visible, with that bar's close as the
entry. The tests pin this: change any bar after ``t`` and the signals at ``t``
must not change.

Two bounded approximations, both deliberate:

* Detectors see the last ``SCAN_WINDOW`` bars, not all history, so a scan of
  eleven thousand bars costs a thousand times the window, not the square of it.
  A pattern whose first swing is older than the window is not seen.
* A hit confirmed on bar ``c`` but only knowable on a later bar ``t`` (its swing
  needed three more bars) is accepted if ``t - c`` is at most ``MAX_LAG``, and
  dated ``t``. Anything older was never actionable and is dropped.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterator, Sequence

from .context import Context, ContextTagger
from .data import Bar, BarSeries
from .patterns import PATTERN_REGISTRY, PatternHit, detect_patterns

SCAN_WINDOW = 240
MAX_LAG = 3
MIN_BARS = 60

INTERVAL_SECONDS = {
    "1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600, "90m": 5400,
    "4h": 14400, "1d": 86400, "1wk": 604800, "1mo": 2678400,
}


def detect_at(
    bars: Sequence[Bar],
    t: int,
    *,
    window: int = SCAN_WINDOW,
    patterns: Sequence[str] | None = None,
) -> list[PatternHit]:
    """Every hit visible with bars up to and including ``t`` and none after it."""

    low = max(0, t - window + 1)
    prefix = tuple(bars[low : t + 1])        # the gate: nothing past t gets through
    return [replace(hit, index=hit.index + low) for hit in detect_patterns(prefix, patterns=patterns)]


def completed_bars(series: BarSeries, *, now: datetime | None = None) -> tuple[Bar, ...]:
    """Drop the bar still being drawn. A signal on an unfinished bar can vanish at its close."""

    bars = series.bars
    if not bars:
        return bars
    seconds = INTERVAL_SECONDS.get(series.interval, 60)
    clock = (now or datetime.now(timezone.utc)).timestamp()
    if bars[-1].timestamp.timestamp() + seconds > clock:
        return bars[:-1]
    return bars


def signal_id(symbol: str, interval: str, pattern: str, stamp: datetime) -> str:
    return f"{symbol}|{interval}|{pattern}|{stamp.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _signal(series: BarSeries, hit: PatternHit, t: int, context: Context) -> dict[str, Any]:
    bar = series.bars[t]
    return {
        "id": signal_id(series.symbol, series.interval, hit.pattern, bar.timestamp),
        "symbol": series.symbol,
        "interval": series.interval,
        "pattern": hit.pattern,
        "label": hit.label,
        "direction": hit.direction,
        "ts": bar.timestamp.astimezone(timezone.utc).isoformat(),
        "entry": bar.close,
        "lag_bars": t - hit.index,
        "detail": dict(hit.detail),
        "context": context.as_dict(),
        "index": t,                       # position in the scanned series; not stored
    }


def scan_series(
    series: BarSeries,
    *,
    last_bars: int | None = None,
    patterns: Sequence[str] | None = None,
    window: int = SCAN_WINDOW,
    tagger: ContextTagger | None = None,
    now: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    """Signals in time order, each judged on the bars up to its own.

    A signal is emitted on bar ``t`` when it is visible with bars up to ``t`` and
    was not visible with bars up to ``t - 1``. That rule needs no memory of
    earlier runs, so scanning the last 800 bars today and all history next week
    name the same signal on the same bar.
    """

    done = completed_bars(series, now=now)
    clean = BarSeries(symbol=series.symbol, interval=series.interval, bars=done)
    if len(done) <= MIN_BARS:
        return
    wanted = [name for name in (patterns or PATTERN_REGISTRY) if name in PATTERN_REGISTRY]
    tagger = tagger or ContextTagger(done, interval=series.interval)
    start = MIN_BARS if not last_bars else max(MIN_BARS, len(done) - last_bars)
    previous = {(hit.pattern, hit.index) for hit in detect_at(done, start - 1, window=window, patterns=wanted)}
    for t in range(start, len(done)):
        hits = detect_at(done, t, window=window, patterns=wanted)
        seen = {(hit.pattern, hit.index) for hit in hits}
        named: set[str] = set()
        for hit in hits:
            if (hit.pattern, hit.index) in previous or t - hit.index > MAX_LAG or hit.pattern in named:
                continue
            named.add(hit.pattern)        # one signal per pattern per bar, whichever swing it came from
            yield _signal(clean, hit, t, tagger.tag(t))
        previous = seen

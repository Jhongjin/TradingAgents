"""Chart patterns written as rules a computer can count.

A pattern that lives in the eye cannot be measured, because the eye finds one
wherever it looks. Each detector here turns a familiar shape into arithmetic on
OHLC bars, so the same chart always yields the same hits and the hits can be
counted, dated and followed.

A detector returns hits, never opinions. Whether a hit was worth trading is the
study's question, not the detector's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from ..data import Bar, BarSeries


@dataclass(frozen=True)
class PatternHit:
    pattern: str
    label: str
    direction: str            # "bullish" | "bearish"
    index: int                # bar the pattern completes on
    timestamp: datetime
    price: float              # close of the completing bar
    detail: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "label": self.label,
            "direction": self.direction,
            "index": self.index,
            "timestamp": self.timestamp.isoformat(),
            "price": self.price,
            "detail": dict(self.detail),
        }


Detector = Callable[[Sequence[Bar]], list[PatternHit]]
PATTERN_REGISTRY: dict[str, tuple[str, str, Detector]] = {}


def register(name: str, label: str, direction: str) -> Callable[[Detector], Detector]:
    def _wrap(function: Detector) -> Detector:
        PATTERN_REGISTRY[name] = (label, direction, function)
        return function

    return _wrap


def detect_patterns(
    series: BarSeries | Sequence[Bar],
    *,
    patterns: Sequence[str] | None = None,
) -> list[PatternHit]:
    """Every hit from every requested detector, in time order."""

    bars = series.bars if isinstance(series, BarSeries) else tuple(series)
    wanted = list(patterns) if patterns else list(PATTERN_REGISTRY)
    hits: list[PatternHit] = []
    for name in wanted:
        entry = PATTERN_REGISTRY.get(name)
        if entry is None:
            continue
        _label, _direction, detector = entry
        hits.extend(detector(bars))
    hits.sort(key=lambda hit: (hit.index, hit.pattern))
    return hits


from . import candles, structure  # noqa: E402,F401  (import registers the detectors)

"""When the United States prints a number that moves gold.

Three-star releases are the ones that reprice the metal in seconds, and most of
them arrive on a rule rather than a whim: non-farm payrolls on the first Friday,
jobless claims every Thursday, all at 8:30 in New York, which is 12:30 or 13:30
UTC depending on the season. Those are computed here so they are always right.

The ones set by committee — FOMC decisions, CPI, PPI, PCE, GDP — have no rule to
compute, and guessing a date would be worse than leaving it out. They are read
from a file the operator keeps, so what appears on the chart is either derived
or entered, never invented.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from .data import cache_dir

NY = ZoneInfo("America/New_York")
RELEASE_TIME = time(8, 30)     # most macro prints
FOMC_TIME = time(14, 0)        # the statement


@dataclass(frozen=True)
class MacroEvent:
    timestamp: datetime
    name: str
    stars: int = 3
    source: str = "rule"

    def as_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "name": self.name,
            "stars": self.stars,
            "source": self.source,
        }


def events_file() -> Path:
    return cache_dir().parent / "events.csv"


def _ny(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=NY).astimezone(timezone.utc)


def first_friday(year: int, month: int) -> date:
    day = date(year, month, 1)
    while day.weekday() != 4:
        day += timedelta(days=1)
    return day


def rule_based_events(start: datetime, end: datetime) -> list[MacroEvent]:
    """The releases whose date follows a rule, so they need no calendar."""

    events: list[MacroEvent] = []
    first = start.astimezone(NY).date()
    last = end.astimezone(NY).date()

    # Non-farm payrolls: first Friday of each month.
    month_cursor = date(first.year, first.month, 1)
    while month_cursor <= last:
        payrolls = first_friday(month_cursor.year, month_cursor.month)
        if first <= payrolls <= last:
            events.append(MacroEvent(_ny(payrolls, RELEASE_TIME), "고용지표 (비농업 고용)", 3, "rule"))
        month_cursor = date(month_cursor.year + (month_cursor.month // 12), (month_cursor.month % 12) + 1, 1)

    # Initial jobless claims: every Thursday.
    day = first
    while day <= last:
        if day.weekday() == 3:
            events.append(MacroEvent(_ny(day, RELEASE_TIME), "주간 실업수당 청구", 2, "rule"))
        day += timedelta(days=1)

    events.sort(key=lambda event: event.timestamp)
    return events


def load_events_file(path: Path | None = None) -> list[MacroEvent]:
    """Dates the operator entered: FOMC, CPI, PPI, PCE, GDP.

    Format: ``date,time,name,stars`` with the time in New York local, e.g.
    ``2026-09-17,14:00,FOMC 금리 결정,3``. A missing file is not an error.
    """

    source = path or events_file()
    if not source.exists():
        return []
    events: list[MacroEvent] = []
    with source.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            raw_date = str(row.get("date") or "").strip()
            if not raw_date:
                continue
            try:
                day = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
                clock = datetime.strptime(str(row.get("time") or "08:30").strip()[:5], "%H:%M").time()
                stars = int(str(row.get("stars") or 3).strip() or 3)
            except ValueError:
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            events.append(MacroEvent(_ny(day, clock), name, max(1, min(stars, 3)), "file"))
    events.sort(key=lambda event: event.timestamp)
    return events


def write_events_template(path: Path | None = None) -> Path:
    """Create the file with a header and one worked example."""

    target = path or events_file()
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "time", "name", "stars"])
        writer.writerow(["2026-09-17", "14:00", "FOMC 금리 결정", 3])
        writer.writerow(["2026-09-11", "08:30", "소비자물가지수 (CPI)", 3])
    return target


def macro_events(
    start: datetime,
    end: datetime,
    *,
    min_stars: int = 3,
    include_rules: bool = True,
    path: Path | None = None,
) -> list[dict]:
    """Everything scheduled inside the window, at or above ``min_stars``."""

    collected: list[MacroEvent] = []
    if include_rules:
        collected.extend(rule_based_events(start, end))
    collected.extend(load_events_file(path))
    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    for event in sorted(collected, key=lambda item: item.timestamp):
        if event.stars < min_stars:
            continue
        if not (start <= event.timestamp <= end):
            continue
        key = (event.timestamp.isoformat(), event.name)
        if key in seen:
            continue
        seen.add(key)
        rows.append(event.as_dict())
    return rows

"""Which session a bar belongs to, and what each session did.

Gold futures trade almost around the clock, so "the day's high" hides more than
it tells: a high made while Tokyo was the only desk open means something
different from one made after New York arrived. These are the three windows a
gold trader actually watches, defined in each market's own local time so they
follow daylight saving on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from .data import Bar


@dataclass(frozen=True)
class Session:
    key: str
    label: str
    zone: str
    open_time: time
    close_time: time
    colour: str

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.zone)


# Local hours, so each follows its own daylight saving without a table of dates.
SESSIONS: tuple[Session, ...] = (
    Session("asia", "아시아", "Asia/Tokyo", time(9, 0), time(17, 0), "#d8a544"),
    Session("europe", "유럽", "Europe/London", time(8, 0), time(16, 30), "#4c8dff"),
    Session("us", "미국", "America/New_York", time(8, 20), time(17, 0), "#ff5d5d"),
)
SESSION_BY_KEY = {session.key: session for session in SESSIONS}


def session_of(stamp: datetime, session: Session) -> bool:
    """Is this instant inside that market's hours, on a weekday there?"""

    local = stamp.astimezone(session.tz)
    if local.weekday() >= 5:
        return False
    return session.open_time <= local.time() < session.close_time


def sessions_for(stamp: datetime) -> list[str]:
    """Every session open at that instant; the overlaps are the busy hours."""

    return [session.key for session in SESSIONS if session_of(stamp, session)]


def session_windows(bars: Sequence[Bar], session: Session) -> list[dict]:
    """Each contiguous run of bars inside one session, with what it printed.

    A window is dated by the session's own local day, so a New York session that
    runs past midnight UTC is still one window and not two.
    """

    windows: list[dict] = []
    current: dict | None = None
    for index, bar in enumerate(bars):
        inside = session_of(bar.timestamp, session)
        local_day = bar.timestamp.astimezone(session.tz).date().isoformat()
        if inside and current is not None and current["day"] != local_day:
            windows.append(current)
            current = None
        if inside:
            if current is None:
                current = {
                    "session": session.key,
                    "label": session.label,
                    "colour": session.colour,
                    "day": local_day,
                    "start_index": index,
                    "end_index": index,
                    "start": bar.timestamp.isoformat(),
                    "end": bar.timestamp.isoformat(),
                    "high": bar.high,
                    "low": bar.low,
                    "open": bar.open,
                    "close": bar.close,
                }
            else:
                current["end_index"] = index
                current["end"] = bar.timestamp.isoformat()
                current["high"] = max(current["high"], bar.high)
                current["low"] = min(current["low"], bar.low)
                current["close"] = bar.close
        elif current is not None:
            windows.append(current)
            current = None
    if current is not None:
        windows.append(current)

    for window in windows:
        window["range"] = round(window["high"] - window["low"], 2)
        window["change"] = round(window["close"] - window["open"], 2)
        window["bars"] = window["end_index"] - window["start_index"] + 1
    return windows


def all_session_windows(bars: Sequence[Bar], sessions: Iterable[Session] = SESSIONS) -> list[dict]:
    windows: list[dict] = []
    for session in sessions:
        windows.extend(session_windows(bars, session))
    windows.sort(key=lambda window: window["start_index"])
    return windows


def session_summary(windows: Sequence[dict], *, last: int = 5) -> list[dict]:
    """The most recent windows per session, newest first."""

    rows: list[dict] = []
    for session in SESSIONS:
        mine = [window for window in windows if window["session"] == session.key]
        for window in mine[-last:][::-1]:
            rows.append(window)
    return rows

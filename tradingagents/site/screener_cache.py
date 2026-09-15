"""Work the screener out once, on a schedule, and let everyone read the answer.

Ranking the whole KOSPI and KOSDAQ tape means pulling every listed name from
the vendors, which takes around half a minute. The result is the same for every
visitor, so a cron works it out and parks it; the public endpoint reads the
parked copy and only falls back to computing when there is nothing to read or
what is there has gone stale.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

CACHE_KEY = "screener"
# Long enough to survive a missed cron or a quiet weekend, short enough that a
# visitor is never shown last week's tape without the page saying so.
MAX_AGE = timedelta(hours=18)


def _created_at(row: dict[str, Any]) -> datetime | None:
    value = row.get("created_at")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def read(repo: Any, *, now: datetime | None = None) -> tuple[dict[str, Any] | None, bool]:
    """The parked screener and whether it has gone stale.

    Returns ``(payload, fresh)``. A stale payload is still returned, because
    showing yesterday's ranking with a date on it beats making the visitor wait
    half a minute when the vendors are slow.
    """

    if repo is None:
        return None, False
    try:
        row = repo.latest_cached_payload(CACHE_KEY)
    except Exception:                                   # noqa: BLE001 - a cache that fails is just a miss
        return None, False
    if not row:
        return None, False
    payload = row.get("payload_json")
    if not isinstance(payload, dict) or not payload:
        return None, False
    created = _created_at(row)
    if created is None:
        return payload, False
    fresh = (now or datetime.now(timezone.utc)) - created <= MAX_AGE
    return payload, fresh


def write(repo: Any, payload: dict[str, Any]) -> bool:
    """Park a freshly computed screener. A storage failure is not fatal."""

    if repo is None or not payload:
        return False
    try:
        repo.save_cached_payload(CACHE_KEY, payload, as_of_date=payload.get("as_of_date"))
    except Exception:                                   # noqa: BLE001
        return False
    return True


def refresh(repo: Any, *, builder: Any = None) -> dict[str, Any]:
    """Compute the screener now and park it. This is what the cron calls."""

    from .screener_api import build_screener_payload

    build = builder or build_screener_payload
    started = datetime.now(timezone.utc)
    payload = build()
    stored = write(repo, payload)
    return {
        "status": payload.get("status", "unknown"),
        "candidates": len(payload.get("candidates") or []),
        "as_of_date": payload.get("as_of_date"),
        "stored": stored,
        "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
    }

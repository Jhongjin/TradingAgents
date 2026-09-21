"""Make the daily video a job that can be attempted more than once.

The record so far, read off the publish ledger: six weekday attempts between
09-14 and 09-21, one confirmed video id. Each failure had its own cause — a
console encoding that could not write an em dash, n8n answering with uploadId
instead of id, a machine still booting at 08:40, npx refused with WinError 5 —
and each got its own fix afterwards. The next one will have a cause nobody has
seen yet.

So this stops trying to predict the cause. The job runs at 08:40; if that
attempt does not end with a video published, it runs again later, and again
after that. One mechanism covers a transient subprocess refusal, a GPU that
was busy, a network blip and a machine that was asleep, without knowing which
of them happened.

What makes repeated attempts safe is a claim. The story for a day is chosen
once and written down before any work starts, so a second attempt continues
the same video rather than picking a fresh one — otherwise a retry publishes a
second, different short, which is worse than publishing none. And an attempt
that finds the day already finished exits without doing anything.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Written beside the publish ledger, not inside it: the ledger is the record
#: of what went out, and a claim is a note about work in progress.
CLAIM_ENV = "TRADINGAGENTS_SHORTS_CLAIM"
DEFAULT_CLAIM = Path("shorts-out/claim.json")


@dataclass(frozen=True)
class Claim:
    day: str
    story: str
    reason: str
    attempts: int

    def as_dict(self) -> dict[str, Any]:
        return {"day": self.day, "story": self.story, "reason": self.reason,
                "attempts": self.attempts}


def claim_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    raw = (os.getenv(CLAIM_ENV) or "").strip()
    return Path(raw) if raw else DEFAULT_CLAIM


def published_today(ledger: Sequence[Mapping[str, Any]], *, day: str) -> Mapping[str, Any] | None:
    """The row for today that actually reached YouTube, if there is one.

    A row with no video id is an attempt that did not finish. Treating it as
    done is how a failed morning became a day with no video and no retry.
    """

    for row in reversed(list(ledger)):
        if str(row.get("date") or "") != day:
            continue
        if str(row.get("video_id") or "").strip():
            return row
    return None


def read_claim(*, day: str, path: Path | None = None) -> Claim | None:
    """Today's claim, or None when the day has not been started yet."""

    target = claim_path(path)
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, Mapping) or str(raw.get("day") or "") != day:
        return None
    story = str(raw.get("story") or "")
    if not story:
        return None
    return Claim(day=day, story=story, reason=str(raw.get("reason") or ""),
                 attempts=int(raw.get("attempts") or 0))


def write_claim(claim: Claim, *, path: Path | None = None) -> Claim:
    target = claim_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(claim.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return claim


def start_attempt(
    *,
    day: str,
    story: str,
    reason: str,
    path: Path | None = None,
) -> Claim:
    """Claim the day for a story, or count another attempt at the same one."""

    existing = read_claim(day=day, path=path)
    if existing is not None:
        return write_claim(
            Claim(day=day, story=existing.story, reason=existing.reason,
                  attempts=existing.attempts + 1),
            path=path,
        )
    return write_claim(Claim(day=day, story=story, reason=reason, attempts=1), path=path)


def clear_claim(*, path: Path | None = None) -> None:
    """Drop the claim once the day is done, so tomorrow starts clean."""

    target = claim_path(path)
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass


def _today() -> str:
    return date.today().isoformat()

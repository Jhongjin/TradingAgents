"""Run something with a wall clock, because vendors stop answering.

Every market vendor this project speaks to has now been seen hanging: pykrx
began demanding a site login and falls through to per-ticker scrapes, one KOSPI
ticker never returns at all, and the quote host simply stops replying some
afternoons. Each call carries its own HTTP timeout and none of that helped —
the hangs are not one slow request, they are a sequence of them with no limit
on the sequence.

The damage is always the same shape: a job that was going to produce something
useful produces nothing, and the part of it that had already succeeded is lost
with it. Three mornings of video and two intraday stop-loss passes went that
way inside two days.

So the rule is that a step which has a fallback must be given a deadline, and
the fallback must be taken when the clock runs out rather than only when the
call raises. A daemon thread is used rather than a pool: a pool cannot abandon
a call already in flight, and the call in flight is somebody else's function
with no timeout of its own. The abandoned thread leaks until the process exits,
which is the right trade for a job that runs once and then ends.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class Overran(Exception):
    """The work did not finish inside its budget."""


def run_within(work: Callable[[], T], *, seconds: float, default: T | None = None) -> T | None:
    """``work()`` if it finishes in ``seconds``, else ``default``.

    An exception raised by ``work`` propagates, because a caller that wants a
    failure treated as a timeout can say so with its own try. Silently turning
    the two into one value is how a broken vendor and a slow one become
    indistinguishable in a log.
    """

    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = work()
        except BaseException as exc:                     # noqa: BLE001 - re-raised below
            box["error"] = exc

    worker = threading.Thread(target=run, name="deadline", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        return default
    error = box.get("error")
    if error is not None:
        raise error
    return box.get("value", default)


def outcome(work: Callable[[], T], *, seconds: float) -> tuple[T | None, bool, BaseException | None]:
    """``(value, overran, failure)`` — for callers that report the difference."""

    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = work()
        except BaseException as exc:                     # noqa: BLE001 - handed back, not raised
            box["error"] = exc

    worker = threading.Thread(target=run, name="deadline", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        return None, True, None
    return box.get("value"), False, box.get("error")

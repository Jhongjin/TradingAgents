"""A deadline that stops a vendor call which never returns.

Measured on today's index: one ticker in a hundred and fifty hangs forever.
Through a thread pool that one ticker took the whole screener with it, because
a pool's deadline can cancel the queue but still has to join what is in flight.
"""

import threading
import time

from tradingagents.screener.universe import fetch_histories_by_code

POINTS = [{"date": "2026-09-18", "close": 10_000, "volume": 500_000, "value": 5e9}]


def _fetcher(*, hang=(), slow=(), delay=0.05, fail=()):
    started = threading.Event()

    def fetch(code, start, end):
        if code in hang:
            started.set()
            time.sleep(3600)                  # never returns, as 047810 does not
        if code in fail:
            raise RuntimeError(f"vendor said no to {code}")
        if code in slow:
            time.sleep(delay)
        return POINTS

    fetch.started = started
    return fetch


def test_every_ticker_comes_back_when_nothing_misbehaves():
    codes = [f"{n:06d}" for n in range(30)]
    out = fetch_histories_by_code(codes, _fetcher(), "2026-01-01", "2026-09-18")
    assert set(out) == set(codes)
    assert all(error is None for _, error in out.values())


def test_one_ticker_that_never_returns_does_not_take_the_rest_with_it():
    codes = [f"{n:06d}" for n in range(30)]
    stuck = codes[0]

    started = time.monotonic()
    out = fetch_histories_by_code(
        codes, _fetcher(hang={stuck}), "2026-01-01", "2026-09-18",
        max_workers=4, deadline=started + 30, grace_seconds=0.3,
    )
    took = time.monotonic() - started

    assert took < 5                            # it does not wait out the deadline
    assert stuck not in out
    assert len(out) == len(codes) - 1


def test_the_deadline_is_honoured_when_the_queue_cannot_drain():
    codes = [f"{n:06d}" for n in range(200)]
    started = time.monotonic()
    out = fetch_histories_by_code(
        codes, _fetcher(slow=set(codes), delay=0.05), "2026-01-01", "2026-09-18",
        max_workers=2, deadline=started + 0.5, grace_seconds=0.2,
    )
    took = time.monotonic() - started

    assert took < 2
    assert 0 < len(out) < len(codes)           # some done, the rest never reached


def test_a_vendor_error_is_one_ticker_and_is_reported_not_swallowed():
    codes = ["000001", "000002", "000003"]
    out = fetch_histories_by_code(codes, _fetcher(fail={"000002"}), "2026-01-01", "2026-09-18")

    assert out["000001"][0] == POINTS
    assert out["000002"][0] == [] and isinstance(out["000002"][1], RuntimeError)
    assert out["000003"][0] == POINTS


def test_the_workers_are_daemons_so_a_hung_fetch_cannot_hold_the_process():
    """The whole reason this is not a ThreadPoolExecutor."""

    names = []
    codes = [f"{n:06d}" for n in range(4)]

    def watching(code, start, end):
        names.extend(t for t in threading.enumerate() if t.name.startswith("history-"))
        return POINTS

    fetch_histories_by_code(codes, watching, "2026-01-01", "2026-09-18", max_workers=2)
    assert names and all(thread.daemon for thread in names)


def test_no_codes_is_no_work_and_no_threads():
    assert fetch_histories_by_code([], _fetcher(), "2026-01-01", "2026-09-18") == {}


def test_a_single_worker_still_stops_at_the_deadline():
    codes = [f"{n:06d}" for n in range(50)]
    started = time.monotonic()
    out = fetch_histories_by_code(
        codes, _fetcher(slow=set(codes), delay=0.02), "2026-01-01", "2026-09-18",
        max_workers=1, deadline=started + 0.3, grace_seconds=0.1,
    )
    assert time.monotonic() - started < 1.5
    assert 0 < len(out) < len(codes)

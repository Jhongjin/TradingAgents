"""A story that will not finish must not take the morning with it.

The builders behind the shelf of stories were wrapped in a try, which the
comment above them read as "a cut that cannot be drawn drops off the list". It
caught a builder that failed and said nothing about one that never returned.

Measured 2026-09-23: "rejected" scores a twenty-name shortlist per stored run
through a vendor that falls through to Yahoo on every call, and pays those
twenty calls even for runs it then discards. Over 90 seconds and still going
against 10s for the next slowest, on a job that had produced nothing in the
thirty-six minutes since it started — and worse each day, because the number of
stored runs only grows.
"""

import time

import pytest

from cli.main import _within_budget


def test_a_builder_that_finishes_hands_back_its_value():
    value, overran, failure = _within_budget(lambda: {"rows": [1, 2]}, seconds=5)

    assert value == {"rows": [1, 2]}
    assert overran is False and failure is None


def test_a_builder_that_overruns_is_dropped_rather_than_waited_on():
    started = time.monotonic()
    value, overran, failure = _within_budget(lambda: time.sleep(30), seconds=0.2)

    assert overran is True
    assert value is None and failure is None
    # the point is that it came back, not that it finished
    assert time.monotonic() - started < 5


def test_a_builder_that_raises_is_reported_not_swallowed():
    def broken():
        raise RuntimeError("vendor said no")

    value, overran, failure = _within_budget(broken, seconds=5)

    assert overran is False and value is None
    assert isinstance(failure, RuntimeError) and "vendor said no" in str(failure)


def test_the_budget_is_short_enough_to_leave_a_morning():
    """Seven builders run before the claim is written, let alone the render."""

    from cli.main import SHORTS_STORY_BUDGET_SECONDS

    assert SHORTS_STORY_BUDGET_SECONDS * 7 < 8 * 60


def test_a_slow_story_does_not_stop_the_ones_after_it(monkeypatch):
    import cli.main as M

    # The account itself comes over HTTP when --from is given, and a test that
    # reaches agenttrust.kr to prove a timeout works is testing the network.
    class _Response:
        status_code = 200

        def raise_for_status(self): return None
        def json(self): return {"summary": {}, "positions": []}

    import requests

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(M, "SHORTS_STORY_BUDGET_SECONDS", 0.2)
    monkeypatch.setattr(M, "_latest_debate", lambda source: {"ok": "debate"})
    monkeypatch.setattr(M, "_latest_funnel", lambda source: {"ok": "funnel"})
    monkeypatch.setattr(M, "_rejected_after", lambda source: time.sleep(30))
    monkeypatch.setattr(M, "_stored_backtests", lambda source: {"ok": "backtests"})
    monkeypatch.setattr(M, "_latest_sweep", lambda source: None)
    monkeypatch.setattr(M, "_account_curve", lambda source: {"ok": "curve"})
    monkeypatch.setattr(M, "_biggest_mover", lambda payload, source: {"ok": "candles"})

    payload = M._shorts_payload("https://agenttrust.kr")

    assert "rejected" not in payload
    assert payload["debate"] == {"ok": "debate"}
    assert payload["backtests"] == {"ok": "backtests"}
    assert payload["candles"] == {"ok": "candles"}


# --------------------------------------------------------------------------
# And do not pay for a run that was never going to qualify
# --------------------------------------------------------------------------

def _run(codes, *, as_of="2026-09-15", universe=180):
    return {"run": {"as_of_date": as_of, "universe_size": universe,
                    "metadata": {"screener_candidates": [
                        {"code": code, "name": f"종목{code}", "rank": index + 1}
                        for index, code in enumerate(codes)]}}}


def test_a_run_that_cannot_qualify_is_dropped_before_it_is_priced():
    """Twenty vendor calls, then discarded on counts known up front."""

    from cli.main import _rejected_in

    asked = []

    def fetcher(code, as_of, horizon):
        asked.append(code)
        return 0.01, 0.005, horizon

    codes = [f"{index:06d}" for index in range(1, 13)]
    # only one of the twelve was bought, and the cut needs two
    assert _rejected_in(_run(codes), {codes[0]}, fetcher) is None
    assert asked == []


def test_a_run_that_can_qualify_is_still_scored():
    from cli.main import _rejected_in

    asked = []

    def fetcher(code, as_of, horizon):
        asked.append(code)
        return (0.02, 0.01, horizon) if code.endswith(("1", "2")) else (-0.01, -0.02, horizon)

    codes = [f"{index:06d}" for index in range(1, 13)]
    item = _rejected_in(_run(codes), {codes[0], codes[1]}, fetcher)

    assert item is not None
    assert len(asked) == len(codes)
    assert item["bought_count"] == 2


# --------------------------------------------------------------------------
# A stop that is never checked is worse than one checked against yesterday
# --------------------------------------------------------------------------

def test_live_pricing_gives_up_and_leaves_the_rest_to_the_daily_fallback(monkeypatch):
    """Two of five exit passes were killed at 45 minutes on 2026-09-22.

    Both stopped after "restored ... holding(s)" and before "priced N/N", so
    the run never reached the exit rule — and the books queued behind the
    stalled one never ran at all.
    """

    import cli.main as M

    class _Config:
        configured = True

        @staticmethod
        def from_env(paper=False): return _Config()

    class _Client:
        def __init__(self, config=None): self.asked = []

        def current_price(self, code):
            self.asked.append(code)
            if len(self.asked) > 2:
                time.sleep(5)          # the vendor stops answering
            return {"Output_0": {"stck_prpr": "71000"}}

    client = _Client()
    monkeypatch.setattr(M, "LIVE_PRICE_BUDGET_SECONDS", 0.3)
    import tradingagents.execution.nh_client as nh

    monkeypatch.setattr(nh, "NHConfig", _Config)
    monkeypatch.setattr(nh, "NHClient", lambda config=None: client)

    prices, counts = M._live_prices([f"{index:06d}" for index in range(1, 11)])

    # The deadline is read before each call, so the one already in flight when
    # it passes still finishes — the guarantee is that it stops, not that it
    # stops instantly.
    assert 0 < counts["NH"] < 10
    assert counts["timed_out"] >= 1             # and it says it gave up
    assert len(prices) == counts["NH"]
    assert len(client.asked) < 10


def test_the_price_budget_leaves_room_inside_the_scheduler_window():
    from cli.main import LIVE_PRICE_BUDGET_SECONDS

    # three books per pass, inside a 45-minute task limit, with the exit rule
    # and the notify step still to run afterwards
    assert LIVE_PRICE_BUDGET_SECONDS * 3 < 10 * 60

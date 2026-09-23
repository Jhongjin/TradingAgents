"""Vendors stop answering, and the fallback has to be reachable from that.

Every hang found in two days had the same shape: each HTTP call carried its own
timeout, and none of them was the problem — the problem was a sequence of calls
with no limit on the sequence. Three mornings of video and two intraday
stop-loss passes were lost inside a step that already had a documented
fallback it could not reach, because the fallback was wired to the exception
and not to the clock.
"""

import time

import pytest

from tradingagents.dataflows.deadline import outcome, run_within


def test_work_that_finishes_hands_back_its_value():
    assert run_within(lambda: 7, seconds=5) == 7


def test_work_that_overruns_takes_the_default():
    started = time.monotonic()
    assert run_within(lambda: time.sleep(3), seconds=0.2, default="fallback") == "fallback"
    assert time.monotonic() - started < 5          # it came back, not finished


def test_an_error_is_raised_rather_than_disguised_as_a_timeout():
    """A broken vendor and a slow one must not become the same log line."""

    def broken():
        raise RuntimeError("vendor said no")

    with pytest.raises(RuntimeError, match="vendor said no"):
        run_within(broken, seconds=5)


def test_outcome_reports_which_of_the_three_happened():
    assert outcome(lambda: 7, seconds=5) == (7, False, None)

    value, overran, failure = outcome(lambda: time.sleep(3), seconds=0.2)
    assert (value, overran, failure) == (None, True, None)

    def broken():
        raise ValueError("no")

    value, overran, failure = outcome(broken, seconds=5)
    assert value is None and overran is False and isinstance(failure, ValueError)


def test_pricing_the_books_falls_back_to_cost_when_the_vendor_stalls(monkeypatch):
    """Ten minutes on two seconds of CPU, and the morning went with it."""

    import tradingagents.harness.paper_state as P

    monkeypatch.setattr(P, "LATEST_PRICE_BUDGET_SECONDS", 0.3)
    monkeypatch.setattr(P, "restore_paper_account",
                        lambda repo, account_key=None, limit=None: (_Adapter(), None))
    import tradingagents.site.market_api as market

    monkeypatch.setattr(market, "build_latest_prices_payload",
                        lambda *args, **kwargs: time.sleep(3))

    started = time.monotonic()
    assert P.latest_prices_for(object()) == {}
    assert time.monotonic() - started < 5


class _Position:
    quantity = 10


class _Portfolio:
    positions = {"005930": _Position()}


class _Broker:
    portfolio = _Portfolio()


class _Adapter:
    broker = _Broker()

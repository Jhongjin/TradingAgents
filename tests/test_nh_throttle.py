"""NH allows five business calls a second, and the desk opens with more."""

import threading
import time

import pytest

from tradingagents.execution.throttle import Throttle as _Throttle
from tradingagents.execution.nh_client import (
    CALLS_PER_SECOND,
    NHClient,
    NHConfig,
    NHError,
)


def test_calls_are_spaced_so_the_sixth_waits_for_the_window():
    throttle = _Throttle(5)
    start = time.monotonic()
    for _ in range(5):
        throttle.wait()
    assert time.monotonic() - start < 0.2        # the first five go straight through

    throttle.wait()
    assert time.monotonic() - start >= 0.9       # the sixth waits out the second


def test_the_limiter_holds_across_threads_not_just_within_one():
    """The desk fetches its panels in parallel; a per-call limiter would not help."""

    throttle = _Throttle(5)
    stamps, lock = [], threading.Lock()

    def one():
        throttle.wait()
        with lock:
            stamps.append(time.monotonic())

    workers = [threading.Thread(target=one) for _ in range(10)]
    start = time.monotonic()
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(stamps) == 10
    # no second anywhere in the run contains more than five
    for stamp in stamps:
        assert sum(1 for other in stamps if stamp <= other < stamp + 1.0) <= 5
    assert time.monotonic() - start >= 0.9


def test_every_real_client_shares_one_limiter():
    """One key, one gateway: two clients together must not do what one cannot."""

    first = NHClient(config=NHConfig(app_key="K", app_secret_key="S"))
    second = NHClient(config=NHConfig(app_key="K", app_secret_key="S", is_paper=False))
    assert first.throttle is second.throttle
    assert first.throttle.limit == CALLS_PER_SECOND


def test_a_client_with_its_own_transport_is_not_talking_to_nh_and_is_not_spaced():
    """Otherwise the suite sleeps through a rate limit nobody is hitting."""

    faked = NHClient(config=NHConfig(app_key="K", app_secret_key="S"),
                     transport=lambda *a: {"rsp_cd": "00000"})
    assert faked.throttle is not NHClient(config=NHConfig()).throttle
    assert faked.throttle.limit > CALLS_PER_SECOND

    # asking for one explicitly still wins
    chosen = _Throttle(2)
    assert NHClient(config=NHConfig(), transport=lambda *a: {}, throttle=chosen).throttle is chosen


def test_a_business_call_waits_its_turn():
    seen = []

    def transport(method, url, headers, params, data):
        seen.append(time.monotonic())
        if url.endswith("/oauth2/token"):
            return {"access_token": "T", "expires_in": 86400}
        return {"rsp_cd": "00166", "Output_0": {}}

    client = NHClient(config=NHConfig(app_key="K", app_secret_key="S", account_no="50001004611"),
                      transport=transport)
    client.throttle = _Throttle(2)

    start = time.monotonic()
    for _ in range(3):
        client.balance()
    assert time.monotonic() - start >= 0.9


def test_the_gateway_still_gets_the_last_word_and_one_retry():
    """Spacing here cannot know about another process holding the same key."""

    state = {"refused": False}

    def transport(method, url, headers, params, data):
        if url.endswith("/oauth2/token"):
            return {"access_token": "T", "expires_in": 86400}
        if not state["refused"]:
            state["refused"] = True
            raise NHError('NH ... -> 429: {"rsp_cd":"IGW42903","rsp_msg":"API 호출 거래건수를 초과하였습니다."}')
        return {"rsp_cd": "00166", "Output_0": {"dca": 1}}

    client = NHClient(config=NHConfig(app_key="K", app_secret_key="S", account_no="50001004611"),
                      transport=transport)
    client.throttle = _Throttle(50)
    assert client.balance()["Output_0"]["dca"] == 1
    assert state["refused"]


def test_a_second_refusal_is_a_real_one():
    def transport(method, url, headers, params, data):
        if url.endswith("/oauth2/token"):
            return {"access_token": "T", "expires_in": 86400}
        raise NHError('NH ... -> 429: {"rsp_cd":"IGW42903"}')

    client = NHClient(config=NHConfig(app_key="K", app_secret_key="S", account_no="50001004611"),
                      transport=transport)
    client.throttle = _Throttle(50)
    with pytest.raises(NHError, match="IGW42903"):
        client.balance()


def test_the_page_asks_for_the_panels_below_the_fold_only_when_they_are_seen():
    from tradingagents.desk.page import render_desk

    page = render_desk(mode="live")
    assert "IntersectionObserver" in page
    for panel in ("pnl-panel", "reconcile-panel", "reserved-panel"):
        assert f'id="{panel}"' in page, panel
    # the account and today's orders are still fetched straight away
    assert "loadAccount();" in page and "loadOrders();" in page
    # and a hidden tab stops spending the rate limit
    assert "visibilitychange" in page and "document.hidden" in page

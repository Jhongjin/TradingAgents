"""KIS answers an over-eager caller with an error instead of data.

An exits pass over eighteen holdings hit "초당 거래건수를 초과하였습니다" every
time, so the KIS book was never evaluated — and it turned out to be holding a
position already at its target.
"""

import time

from tradingagents.execution.kis import KISConfig
from tradingagents.execution.kis_client import (
    KIS_PAPER_CALLS_PER_SECOND,
    KISClient,
)
from tradingagents.execution.throttle import Throttle


def _config():
    return KISConfig(account_no="12345678", account_product_code="01",
                     app_key="K", app_secret="S", is_paper=True)


def test_a_client_that_really_calls_kis_is_spaced():
    client = KISClient(config=_config())
    assert client.throttle.limit == KIS_PAPER_CALLS_PER_SECOND == 2


def test_every_client_shares_the_ceiling():
    """One key, one gateway, however many objects hold it."""

    assert KISClient(config=_config()).throttle is KISClient(config=_config()).throttle


def test_an_injected_transport_is_not_the_gateway_and_is_not_spaced():
    """A bound-method identity check would never be true; the test is on transport."""

    calls = []

    def transport(method, url, headers, params, json):
        calls.append(url)
        return {"rt_cd": "0"}

    client = KISClient(config=_config(), transport=transport)
    client.throttle = Throttle(1)          # would cost seconds if it were used

    started = time.monotonic()
    for _ in range(6):
        client._request("GET", "/x", headers={})       # noqa: SLF001
    assert time.monotonic() - started < 1.0
    assert len(calls) == 6


def test_the_spacing_check_does_not_compare_bound_methods():
    import inspect

    source = inspect.getsource(KISClient._request)
    assert "self.transport is None" in source
    assert "transport is self._requests_transport" not in source


def test_the_shared_throttle_is_the_one_nh_uses_too():
    from tradingagents.execution import nh_client

    assert nh_client.Throttle is Throttle

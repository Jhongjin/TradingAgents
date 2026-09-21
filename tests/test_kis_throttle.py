"""KIS answers an over-eager caller with an error instead of data.

An exits pass over eighteen holdings hit "초당 거래건수를 초과하였습니다" every
time, so the KIS book was never evaluated — and it turned out to be holding a
position already at its target.
"""

import time

import pytest

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


def test_a_rate_limit_is_retried_rather_than_treated_as_a_refusal():
    """On 2026-09-21 a take-profit exit on 010170 was rejected by it and the
    position stayed open."""

    from tradingagents.execution.kis_client import KISError

    attempts = {"n": 0}

    def transport(method, url, headers, params, json):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise KISError("KIS HTTP 500: 초당 거래건수를 초과하였습니다.")
        return {"rt_cd": "0"}

    client = KISClient(config=_config())
    client.transport = None                    # make it look like a real call
    real = client._requests_transport          # noqa: SLF001
    client._requests_transport = transport     # noqa: SLF001
    client.throttle = Throttle(1_000_000)
    try:
        assert client._request("POST", "/order", headers={}) == {"rt_cd": "0"}  # noqa: SLF001
    finally:
        client._requests_transport = real      # noqa: SLF001
    assert attempts["n"] == 3


def test_any_other_error_is_not_retried():
    """A closed market is not a rate limit, and retrying it wastes the budget."""

    from tradingagents.execution.kis_client import KISError

    attempts = {"n": 0}

    def transport(method, url, headers, params, json):
        attempts["n"] += 1
        raise KISError("KIS HTTP 500: 장운영일이 아닙니다")

    client = KISClient(config=_config())
    client.transport = None
    real = client._requests_transport          # noqa: SLF001
    client._requests_transport = transport     # noqa: SLF001
    client.throttle = Throttle(1_000_000)
    try:
        with pytest.raises(KISError, match="장운영일"):
            client._request("POST", "/order", headers={})   # noqa: SLF001
    finally:
        client._requests_transport = real      # noqa: SLF001
    assert attempts["n"] == 1


def test_the_marker_matches_what_kis_actually_sends():
    from tradingagents.execution.kis_client import KISError, _is_rate_limited

    assert _is_rate_limited(KISError("KIS HTTP 500: 초당 거래건수를 초과하였습니다."))
    assert not _is_rate_limited(KISError("KIS HTTP 500: 주문가능금액이 부족합니다"))


def test_an_injected_transport_is_still_never_retried():
    """Tests must not sit through a backoff for a failure they staged."""

    from tradingagents.execution.kis_client import KISError

    attempts = {"n": 0}

    def transport(method, url, headers, params, json):
        attempts["n"] += 1
        raise KISError("KIS HTTP 500: 초당 거래건수를 초과하였습니다.")

    client = KISClient(config=_config(), transport=transport)
    with pytest.raises(KISError):
        client._request("POST", "/order", headers={})       # noqa: SLF001
    assert attempts["n"] == 1

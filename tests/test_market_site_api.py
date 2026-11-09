import pytest

from tradingagents.dataflows.chart_data import LatestPrice
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.site.market_api import build_latest_prices_payload


def _latest_price(ticker_code: str, close: float) -> LatestPrice:
    return LatestPrice(
        ticker_code=ticker_code,
        ticker_name=ticker_code,
        market="KOSPI",
        currency="KRW",
        vendor="pykrx",
        date="2026-01-05",
        close=close,
    )


def test_latest_prices_payload_collects_prices_and_errors(monkeypatch):
    def fake_latest(ticker, *args, **kwargs):
        if ticker == "005930":
            return _latest_price("005930", 71200.0)
        raise VendorUnavailableError("offline")

    monkeypatch.setattr("tradingagents.site.market_api.get_latest_close_price", fake_latest)

    payload = build_latest_prices_payload(
        ["005930", "000660"],
        end_date="2026-01-06",
        ignore_errors=True,
    )

    assert payload["status"] == "partial"
    assert payload["as_of_date"] == "2026-01-06"
    assert payload["prices"]["005930"]["close"] == 71200.0
    assert payload["errors"]["000660"] == "offline"


def test_latest_prices_payload_raises_when_errors_are_not_ignored(monkeypatch):
    def fake_latest(*args, **kwargs):
        raise VendorUnavailableError("offline")

    monkeypatch.setattr("tradingagents.site.market_api.get_latest_close_price", fake_latest)

    with pytest.raises(VendorUnavailableError, match="offline"):
        build_latest_prices_payload(["005930"], end_date="2026-01-06", ignore_errors=False)


def test_latest_prices_payload_validates_request_size():
    with pytest.raises(ValueError, match="at least one ticker"):
        build_latest_prices_payload([], end_date="2026-01-06")

    with pytest.raises(ValueError, match="more than 1"):
        build_latest_prices_payload(["005930", "000660"], end_date="2026-01-06", max_tickers=1)


def test_latest_prices_fetched_concurrently_not_one_after_another(monkeypatch):
    """A paper account with N held tickers used to pay N sequential vendor
    round trips here (measured 18-19s on the live site for 7-9 tickers in the
    2026-11-09 QA sweep). Each ticker is independent, so the wall-clock time
    for several of them should stay close to one of them, not add up."""

    import threading
    import time

    tickers = ["005930", "000660", "035420", "051910", "005380"]
    per_call_seconds = 0.2
    started_at = {}
    lock = threading.Lock()

    def fake_latest(ticker, *args, **kwargs):
        with lock:
            started_at[ticker] = time.monotonic()
        time.sleep(per_call_seconds)
        return _latest_price(ticker, 1000.0)

    monkeypatch.setattr("tradingagents.site.market_api.get_latest_close_price", fake_latest)

    t0 = time.monotonic()
    payload = build_latest_prices_payload(tickers, end_date="2026-01-06", max_tickers=len(tickers))
    elapsed = time.monotonic() - t0

    assert payload["status"] == "available"
    assert len(payload["prices"]) == len(tickers)
    # Serial would take len(tickers) * per_call_seconds (~1.0s); concurrent
    # stays near a single call's duration.
    assert elapsed < per_call_seconds * len(tickers) * 0.6
    # All five fetches actually overlapped in time rather than queueing.
    spread = max(started_at.values()) - min(started_at.values())
    assert spread < per_call_seconds


def test_a_stuck_ticker_times_out_without_holding_up_the_others(monkeypatch):
    import time

    def fake_latest(ticker, *args, **kwargs):
        if ticker == "999999":
            time.sleep(2.0)  # longer than the test's short per-ticker budget
            return _latest_price(ticker, 1.0)
        return _latest_price(ticker, 500.0)

    monkeypatch.setattr("tradingagents.site.market_api.get_latest_close_price", fake_latest)
    monkeypatch.setattr("tradingagents.site.market_api.LATEST_PRICE_FETCH_TIMEOUT_SECONDS", 0.1)

    t0 = time.monotonic()
    payload = build_latest_prices_payload(["005930", "999999"], end_date="2026-01-06", ignore_errors=True)
    elapsed = time.monotonic() - t0

    assert payload["prices"]["005930"]["close"] == 500.0
    assert "999999" in payload["errors"]
    # The call returned on the short timeout, not after the 2s sleep.
    assert elapsed < 1.0

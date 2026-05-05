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

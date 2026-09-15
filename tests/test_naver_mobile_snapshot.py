"""The market-cap ranking, read from the JSON the Naver app itself reads.

Naver Finance became a client-rendered app, so the ranking table the old
scraper looked for is no longer in the HTML the server sends. It returned zero
rows without failing, and the screener quietly fell back to a twenty-name
stand-in universe - which looked like it was working.
"""

import pytest

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.screener.universe import (
    load_naver_market_snapshot,
    load_naver_mobile_snapshot,
    parse_naver_mobile_stock,
)


def _entry(code: str, name: str, *, end_type: str = "stock", close: str = "250500") -> dict:
    return {
        "itemCode": code,
        "stockName": name,
        "stockEndType": end_type,
        "closePrice": "250,500",
        "closePriceRaw": close,
        "accumulatedTradingVolumeRaw": "1780016",
        "accumulatedTradingValueRaw": "443324000000",
        "marketValueRaw": "1464492791304000",
        "fluctuationsRatio": "0.60",
    }


def test_one_entry_becomes_a_row_with_its_numbers_unformatted():
    row = parse_naver_mobile_stock(_entry("005930", "삼성전자"), "KOSPI")

    assert (row.code, row.name, row.market) == ("005930", "삼성전자", "KOSPI")
    assert row.close == 250_500 and row.volume == 1_780_016
    assert row.market_cap == 1_464_492_791_304_000
    assert row.change_rate == pytest.approx(0.006)      # a fraction, not a percentage
    assert row.per is None                              # the ranking carries no valuation ratios


@pytest.mark.parametrize(
    "entry",
    [
        _entry("069500", "KODEX 200", end_type="etf"),
        _entry("00000A", "이상한코드"),
        _entry("005930", "삼성전자", close="0"),
        _entry("123456", "엔에이치스팩29호"),
    ],
)
def test_what_is_not_a_tradable_share_is_dropped(entry):
    assert parse_naver_mobile_stock(entry, "KOSPI") is None


def test_an_etf_is_kept_when_the_caller_asks_for_one():
    row = parse_naver_mobile_stock(_entry("069500", "KODEX 200", end_type="etf"), "KOSPI", include_non_equity=True)
    assert row is not None and row.code == "069500"


def test_the_walk_stops_at_the_depth_asked_for():
    pages = []

    def fetch(market, page, page_size):
        pages.append((market, page, page_size))
        return {"stocks": [_entry(f"{100000 + page * 10 + index:06d}", f"종목{page}-{index}")
                           for index in range(page_size)]}

    snapshot = load_naver_mobile_snapshot(markets=("KOSPI",), max_rows_per_market=150, rows_fetcher=fetch)

    assert len(snapshot.rows) == 150
    assert snapshot.vendor == "naver_mobile"
    assert [page for _market, page, _size in pages] == [1, 2]     # 100 then the rest, no more


def test_a_short_page_ends_the_walk():
    def fetch(market, page, page_size):
        return {"stocks": [_entry(f"{200000 + index:06d}", f"종목{index}") for index in range(7)]}

    snapshot = load_naver_mobile_snapshot(markets=("KOSDAQ",), max_rows_per_market=150, rows_fetcher=fetch)
    assert len(snapshot.rows) == 7


def test_an_empty_answer_is_reported_rather_than_returned_as_a_snapshot():
    with pytest.raises(VendorUnavailableError, match="no rows"):
        load_naver_mobile_snapshot(markets=("KOSPI",), rows_fetcher=lambda *args: {"stocks": []})

    with pytest.raises(VendorUnavailableError, match="RuntimeError"):
        def sulk(*args):
            raise RuntimeError("naver said no")

        load_naver_mobile_snapshot(markets=("KOSPI",), rows_fetcher=sulk)


def test_the_page_walk_is_only_the_fallback(monkeypatch):
    """With no fetcher injected the JSON is asked first; the HTML walk is spare."""

    called = []
    monkeypatch.setattr(
        "tradingagents.screener.universe.load_naver_mobile_snapshot",
        lambda *args, **kwargs: called.append(kwargs) or _snapshot(),
    )

    snapshot = load_naver_market_snapshot(markets=("KOSPI",), max_rows_per_market=10)

    assert snapshot.vendor == "naver_mobile"
    assert called and called[0]["max_rows_per_market"] == 10


def _snapshot():
    from tradingagents.screener.universe import MarketSnapshot

    return MarketSnapshot(
        as_of_date="2026-09-15",
        markets=("KOSPI",),
        rows=[parse_naver_mobile_stock(_entry("005930", "삼성전자"), "KOSPI")],
        vendor="naver_mobile",
    )


def test_when_the_json_is_down_the_old_page_walk_still_runs(monkeypatch):
    def down(*args, **kwargs):
        raise VendorUnavailableError("json gone")

    monkeypatch.setattr("tradingagents.screener.universe.load_naver_mobile_snapshot", down)

    with pytest.raises(VendorUnavailableError):
        # the HTML path is reached and fails on its own terms, not on a NameError
        load_naver_market_snapshot(markets=("KOSPI",), page_fetcher=None, max_rows_per_market=5)

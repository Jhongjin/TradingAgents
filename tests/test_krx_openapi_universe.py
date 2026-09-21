"""The whole tape, from the vendor that still answers.

pykrx stopped working everywhere at once — data.krx.co.kr now wants a site
login and returns a six-byte LOGOUT body without one — and Naver deleted the
constituent page the index loader read. Measured from Vercel, from the Windows
box and from a Korean server on 2026-09-21, all three fail identically, so this
was never about which network asked.

What the stored-membership fallback cannot do is say how big a company is or
how much of it traded, so the cap and turnover prefilters get skipped and the
screen ranks on price history alone. The Open API carries both, which is the
whole reason to prefer it.
"""

import pytest

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.screener.universe import load_krx_openapi_snapshot


def _entry(code, name, close, *, cap=500_000_000_000, value=5_000_000_000, rate=0.5):
    return {"ISU_CD": code, "ISU_NM": name, "TDD_CLSPRC": close, "ACC_TRDVOL": 10_000,
            "ACC_TRDVAL": value, "MKTCAP": cap, "FLUC_RT": rate}


class _Client:
    """Stands in for KRXOpenAPI: one method per market, keyed by date."""

    def __init__(self, by_date, kosdaq_by_date=None):
        self.by_date = by_date
        self.kosdaq_by_date = kosdaq_by_date or {}
        self.asked = []

    def get_stock_daily_trade(self, bas_dd):
        self.asked.append(("KOSPI", bas_dd))
        return {"OutBlock_1": self.by_date.get(bas_dd, [])}

    def get_kosdaq_stock_daily_trade(self, bas_dd):
        self.asked.append(("KOSDAQ", bas_dd))
        return {"OutBlock_1": self.kosdaq_by_date.get(bas_dd, [])}


def test_a_daily_trade_response_carries_size_and_turnover():
    """The two fields the stored-membership snapshot has to leave empty."""

    client = _Client({"20260918": [_entry("005930", "삼성전자", 71_000, cap=4.2e14, value=8.1e11)]})
    snapshot = load_krx_openapi_snapshot("2026-09-18", markets=("KOSPI",), client=client)

    assert snapshot.vendor == "krx-openapi"
    assert snapshot.as_of_date == "2026-09-18"
    row = snapshot.rows[0]
    assert (row.code, row.name, row.market) == ("005930", "삼성전자", "KOSPI")
    assert row.close == 71_000
    assert row.market_cap == pytest.approx(4.2e14)
    assert row.trading_value == pytest.approx(8.1e11)


def test_both_markets_come_from_their_own_service():
    client = _Client(
        {"20260918": [_entry("005930", "삼성전자", 71_000)]},
        {"20260918": [_entry("060310", "3S", 1_133)]},
    )
    snapshot = load_krx_openapi_snapshot("2026-09-18", client=client)

    assert {row.market for row in snapshot.rows} == {"KOSPI", "KOSDAQ"}
    assert {row.code for row in snapshot.rows} == {"005930", "060310"}


def test_a_suspended_listing_is_dropped_rather_than_ranked():
    """A zero close reads as 'cheap' to the price prefilter, then divides by zero."""

    client = _Client({"20260918": [
        _entry("005930", "삼성전자", 71_000),
        _entry("900110", "거래정지", 0),
    ]})
    snapshot = load_krx_openapi_snapshot("2026-09-18", markets=("KOSPI",), client=client)

    assert [row.code for row in snapshot.rows] == ["005930"]


def test_a_holiday_walks_back_to_the_last_session():
    """Sunday returns an empty block, not an error, so it must not read as 'no data'."""

    client = _Client({"20260918": [_entry("005930", "삼성전자", 71_000)]})
    snapshot = load_krx_openapi_snapshot("2026-09-20", markets=("KOSPI",), client=client)

    assert snapshot.as_of_date == "2026-09-18"
    assert [day for _, day in client.asked] == ["20260920", "20260919", "20260918"]


def test_numbers_that_arrive_as_text_are_still_numbers():
    client = _Client({"20260918": [
        {"ISU_CD": "005930", "ISU_NM": "삼성전자", "TDD_CLSPRC": "71,000",
         "ACC_TRDVOL": "10,000", "ACC_TRDVAL": "-", "MKTCAP": "", "FLUC_RT": "0.5"},
    ]})
    row = load_krx_openapi_snapshot("2026-09-18", markets=("KOSPI",), client=client).rows[0]

    assert row.close == 71_000
    assert row.volume == 10_000
    # An empty cell is missing, not zero: a zero cap would fail the cap filter
    # and silently drop a name the vendor simply did not price.
    assert row.trading_value is None
    assert row.market_cap is None


def test_a_dead_market_does_not_take_the_live_one_with_it():
    class _HalfDead(_Client):
        def get_kosdaq_stock_daily_trade(self, bas_dd):
            raise RuntimeError("service unavailable")

    client = _HalfDead({"20260918": [_entry("005930", "삼성전자", 71_000)]})
    snapshot = load_krx_openapi_snapshot("2026-09-18", client=client)

    assert [row.code for row in snapshot.rows] == ["005930"]


def test_nothing_anywhere_refuses_rather_than_returning_an_empty_screen():
    with pytest.raises(VendorUnavailableError, match="no rows"):
        load_krx_openapi_snapshot("2026-09-18", markets=("KOSPI",), client=_Client({}))


def test_without_a_key_it_says_so_rather_than_calling(monkeypatch):
    monkeypatch.delenv("KRX_API_KEY", raising=False)
    monkeypatch.delenv("KRX_OPENAPI_KEY", raising=False)

    with pytest.raises(VendorUnavailableError, match="KRX_API_KEY"):
        load_krx_openapi_snapshot("2026-09-18", markets=("KOSPI",))


def test_the_suite_cannot_reach_the_paid_vendor():
    """A guard, because the leak was silent and the bill is per call.

    conftest blanks the KRX keys for the same reason it blanks the broker
    credentials. Without this, a developer with a working `.env` runs a
    different suite from CI — and the difference only shows up as a test that
    mocked every vendor and still came back with 943 live rows.
    """

    import os

    assert not (os.getenv("KRX_API_KEY") or "").strip()
    assert not (os.getenv("KRX_OPENAPI_KEY") or "").strip()


# --------------------------------------------------------------------------
# Sized from one source, priced from another
# --------------------------------------------------------------------------

def _history(code, start, end):
    return [{"date": f"2026-09-{day:02d}", "close": 10_000 + day * 10,
             "volume": 500_000, "value": 5_000_000_000}
            for day in (16, 17, 18, 21)]


def test_size_comes_from_the_api_and_the_price_from_the_session_that_closed():
    """The Open API publishes T+1; a screen published today must not show Friday.

    Measured on 2026-09-21 at 23:27 KST: the 09-21 session had closed at 15:30
    and `get_stock_daily_trade('20260921')` still returned zero rows, while
    '20260918' returned 942. Taking prices from there would have dated the whole
    screen to the previous week.
    """

    from tradingagents.screener.universe import load_krx_ranked_snapshot

    client = _Client({"20260918": [_entry("005930", "삼성전자", 69_000, cap=4.2e14)]})
    snapshot = load_krx_ranked_snapshot("2026-09-21", _history, markets=("KOSPI",), client=client)

    row = snapshot.rows[0]
    assert snapshot.as_of_date == "2026-09-21"       # priced to the closed session
    assert row.close == 10_210                       # from history, not the API
    assert row.market_cap == pytest.approx(4.2e14)   # sized from the API
    assert row.name == "삼성전자"
    assert "sized 2026-09-18" in snapshot.vendor and "priced 2026-09-21" in snapshot.vendor


def test_the_biggest_names_survive_the_cut_rather_than_an_arbitrary_slice():
    from tradingagents.screener.universe import load_krx_ranked_snapshot

    client = _Client({"20260918": [
        _entry("000001", "작은회사", 1_000, cap=1e10),
        _entry("000002", "큰회사", 1_000, cap=9e13),
        _entry("000003", "중간회사", 1_000, cap=5e12),
    ]})
    snapshot = load_krx_ranked_snapshot(
        "2026-09-21", _history, markets=("KOSPI",), client=client, limit=2,
    )

    assert {row.code for row in snapshot.rows} == {"000002", "000003"}


def test_a_name_the_api_never_listed_is_not_smuggled_in_by_history():
    """Without size it cannot be filtered, so it must not reach the screen."""

    from tradingagents.screener.universe import load_krx_ranked_snapshot

    client = _Client({"20260918": [_entry("005930", "삼성전자", 69_000)]})
    snapshot = load_krx_ranked_snapshot("2026-09-21", _history, markets=("KOSPI",), client=client)

    assert [row.code for row in snapshot.rows] == ["005930"]
    assert all(row.market_cap is not None for row in snapshot.rows)


def test_no_history_refuses_rather_than_publishing_stale_prices():
    from tradingagents.screener.universe import load_krx_ranked_snapshot

    client = _Client({"20260918": [_entry("005930", "삼성전자", 69_000)]})
    with pytest.raises(VendorUnavailableError, match="no priced rows"):
        load_krx_ranked_snapshot("2026-09-21", lambda *a: [], markets=("KOSPI",), client=client)


# --------------------------------------------------------------------------
# Where it sits in the chain
# --------------------------------------------------------------------------

def _series(days: int = 80, end: str = "2026-09-18"):
    """Long enough for a 20-day momentum; shorter and every row scores None."""

    from datetime import date as _date, timedelta as _td

    last = _date.fromisoformat(end)
    return [
        {"date": (last - _td(days=offset)).isoformat(),
         "close": 10_000 + (days - offset) * 40,
         "volume": 400_000, "value": 4_000_000_000}
        for offset in range(days - 1, -1, -1)
    ]


_POINTS = _series()


def _dead(*args, **kwargs):
    raise VendorUnavailableError("blocked on this host")


def test_auto_prefers_the_open_api_over_the_vendors_that_stopped_answering(monkeypatch):
    from tradingagents.screener import ScreenerConfig, screener as S

    from tradingagents.screener.universe import load_krx_ranked_snapshot

    monkeypatch.setenv("TRADINGAGENTS_SCREENER_SNAPSHOT_MODE", "auto")
    monkeypatch.setattr(S, "load_market_snapshot", _dead)
    monkeypatch.setattr(S, "load_naver_market_snapshot", _dead)
    monkeypatch.setattr(
        S, "load_krx_ranked_snapshot",
        lambda as_of_date, fetcher, **kwargs: load_krx_ranked_snapshot(
            as_of_date, fetcher, markets=("KOSPI",),
            client=_Client({"20260918": [_entry("005930", "삼성전자", 10_720, cap=4.2e14)]}),
        ),
    )

    result = S.screen_korean_market(
        "2026-09-18",
        config=ScreenerConfig(top_n=5, min_composite=-10),
        history_fetcher=lambda code, s, e: _POINTS,
    )

    assert any("krx-ranked" in note for note in result.notes)
    # The point of preferring it: the cap filter had something to filter on.
    assert result.candidates[0].market_cap == pytest.approx(4.2e14)


def test_a_loader_that_spends_the_whole_budget_still_produces_a_screen(monkeypatch):
    """Paying for the data and then publishing nothing is the worst outcome.

    The ranked KRX universe fetches history inside the loader, so on a slow host
    it can reach the deadline before scoring starts. Scoring asks for the same
    tickers, which are now cached — but the deadline check ran before the cache
    was consulted, so every row came back "not scored" and the screen was empty.
    """

    from tradingagents.screener import ScreenerConfig, screener as S
    from tradingagents.screener.universe import load_krx_ranked_snapshot

    monkeypatch.setenv("TRADINGAGENTS_SCREENER_SNAPSHOT_MODE", "auto")
    monkeypatch.setattr(S, "load_market_snapshot", _dead)
    monkeypatch.setattr(S, "load_naver_market_snapshot", _dead)

    def slow_loader(as_of_date, fetcher, **kwargs):
        snapshot = load_krx_ranked_snapshot(
            as_of_date, fetcher, markets=("KOSPI",),
            client=_Client({"20260918": [_entry("005930", "삼성전자", 10_720, cap=4.2e14)]}),
        )
        kwargs["deadline"] = 0.0        # the budget is gone by the time it returns
        return snapshot

    monkeypatch.setattr(S, "load_krx_ranked_snapshot", slow_loader)

    result = S.screen_korean_market(
        "2026-09-18",
        config=ScreenerConfig(top_n=5, min_composite=-10, time_budget_seconds=0.0),
        history_fetcher=lambda code, s, e: _POINTS,
    )

    assert result.scored_size == 1
    assert [c.code for c in result.candidates] == ["005930"]


def test_auto_falls_back_to_stored_membership_instead_of_twenty_tickers(monkeypatch):
    """A missing env var should cost a worse ranking, not 94% of the universe.

    Before this, the stored-membership loader was registered only when
    snapshot_mode was exactly "index". Production sets that variable, so the
    gap was invisible — but unset it on Vercel and the screen silently went
    from 343 names to the 20-ticker fallback.
    """

    from tradingagents.screener import ScreenerConfig, screener as S

    monkeypatch.setenv("TRADINGAGENTS_SCREENER_SNAPSHOT_MODE", "auto")
    monkeypatch.setattr(S, "load_krx_ranked_snapshot", _dead)
    monkeypatch.setattr(S, "load_market_snapshot", _dead)
    monkeypatch.setattr(S, "load_naver_market_snapshot", _dead)

    result = S.screen_korean_market(
        "2026-09-18",
        config=ScreenerConfig(top_n=5, min_composite=-10, universe_size=30),
        history_fetcher=lambda code, s, e: _POINTS,
    )

    assert any("stored membership" in note for note in result.notes)
    assert result.universe_size == 30

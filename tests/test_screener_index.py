import pytest

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.screener import ScreenerConfig, load_index_snapshot, screen_korean_market
from tradingagents.screener.universe import load_kospi200_rows, parse_naver_kospi200_page

K200_HEADERS = ("종목별", "현재가", "전일비", "등락률", "거래량", "거래대금(백만)", "시가총액(억)")


def _k200_page(rows):
    head = "".join(f"<th>{h}</th>" for h in K200_HEADERS)
    body = "".join(
        f'<tr><td><a href="/item/main.naver?code={code}">{name}</a></td><td>{price}</td><td>보합0</td><td>+0.50%</td><td>{volume}</td><td>{value}</td><td>{cap}</td></tr>'
        for code, name, price, volume, value, cap in rows
    )
    return f'<html><table class="type_1"><tr>{head}</tr>{body}</table></html>'


def _sum_page(rows):
    headers = ("N", "종목명", "현재가", "전일비", "등락률", "액면가", "시가총액", "상장주식수", "외국인비율", "거래량", "PER", "ROE", "토론")
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(
        f'<tr><td>{i}</td><td><a href="/item/main.naver?code={code}">{name}</a></td><td>{price}</td><td>상승 1</td><td>+0.10%</td><td>500</td><td>{cap}</td><td>1</td><td>1</td><td>{volume}</td><td>10</td><td>1</td><td></td></tr>'
        for i, (code, name, price, cap, volume) in enumerate(rows, start=1)
    )
    return f'<html><table class="type_2"><tr>{head}</tr>{body}</table></html>'


def test_parse_kospi200_page_reads_value_and_cap_units():
    rows = parse_naver_kospi200_page(_k200_page([("005930", "삼성전자", "269,500", "16,080,982", "4,357,868", "15,755,721")]))
    assert rows[0].code == "005930" and rows[0].market == "KOSPI"
    assert rows[0].trading_value == 4_357_868 * 1_000_000
    assert rows[0].market_cap == 15_755_721 * 100_000_000
    assert rows[0].change_rate == pytest.approx(0.005)
    assert parse_naver_kospi200_page("<html></html>") == []


def test_load_kospi200_rows_walks_pages_until_short_page():
    pages = {1: [(f"{i:06d}", f"K{i}", "10,000", "1,000", "10", "5,000") for i in range(10)], 2: [("000099", "K99", "10,000", "1,000", "10", "5,000")]}
    calls = []

    def fetcher(page):
        calls.append(page)
        return _k200_page(pages.get(page, []))

    rows = load_kospi200_rows(page_fetcher=fetcher)
    assert len(rows) == 11 and calls == [1, 2]
    with pytest.raises(VendorUnavailableError):
        load_kospi200_rows(page_fetcher=lambda page: "<html></html>")


def test_index_snapshot_uses_constituents_or_proxy(monkeypatch):
    monkeypatch.delenv("KRX_ID", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_KOSDAQ150_CODES", raising=False)
    kospi_page = lambda page: _k200_page([("005930", "삼성전자", "269,500", "1,000", "10", "15,755,721")]) if page == 1 else _k200_page([])
    kosdaq_rows = [(f"{200000 + i:06d}", f"Q{i}", "10,000", "5,000", "1,000") for i in range(200)]

    def sum_page(market, page):
        assert market == "KOSDAQ"
        return _sum_page(kosdaq_rows[(page - 1) * 50 : page * 50])

    proxy = load_index_snapshot("2026-09-09", kospi200_page_fetcher=kospi_page, market_sum_page_fetcher=sum_page)
    assert proxy.vendor.startswith("index:") and "proxy" in proxy.vendor
    assert sum(1 for r in proxy.rows if r.market == "KOSPI") == 1 and sum(1 for r in proxy.rows if r.market == "KOSDAQ") == 150

    real = load_index_snapshot("2026-09-09", kospi200_page_fetcher=kospi_page, market_sum_page_fetcher=sum_page, kosdaq150_codes=["200001", "200150", "999999"])
    assert "2 of 3 matched" in real.vendor
    assert {r.code for r in real.rows if r.market == "KOSDAQ"} == {"200001", "200150"}

    monkeypatch.setenv("TRADINGAGENTS_KOSDAQ150_CODES", "200002,200003")
    from tradingagents.screener.universe import _kosdaq150_codes_from_pykrx

    assert _kosdaq150_codes_from_pykrx() == ["200002", "200003"]


def test_screener_index_mode_scores_full_universe(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_SCREENER_SNAPSHOT_MODE", "index")
    monkeypatch.delenv("KRX_ID", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_KOSDAQ150_CODES", raising=False)
    kospi_page = lambda page: _k200_page([(f"{i:06d}", f"K{i}", "10,000", "1,000,000", "10,000", "5,000") for i in range(10)]) if page == 1 else _k200_page([])
    sum_page = lambda market, page: _sum_page([(f"{200000 + i:06d}", f"Q{i}", "10,000", "5,000", "1,000,000") for i in range(5)]) if page == 1 else _sum_page([])
    monkeypatch.setattr("tradingagents.screener.screener.load_index_snapshot", lambda when, markets: load_index_snapshot(when, markets=markets, kospi200_page_fetcher=kospi_page, market_sum_page_fetcher=sum_page))
    points = [{"date": f"d{i}", "close": 9_000 * (1 + 0.003) ** i, "volume": 1_000_000} for i in range(120)]
    result = screen_korean_market("2026-09-09", config=ScreenerConfig(top_n=50, min_composite=-10), history_fetcher=lambda code, s, e: points)
    assert result.universe_size == 15 and result.prefiltered_size == 15 and result.scored_size == 15
    assert result.notes[0].startswith("snapshot 2026-09-09 from index:")

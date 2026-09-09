import pytest

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.screener import ScreenerConfig, screen_korean_market
from tradingagents.screener.universe import load_naver_market_snapshot, parse_naver_market_sum

HEADERS = ("N", "종목명", "현재가", "전일비", "등락률", "액면가", "시가총액", "상장주식수", "외국인비율", "거래량", "PER", "ROE", "토론")


def _page(rows, headers=HEADERS):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = ""
    for rank, (code, name, price, cap, volume, per) in enumerate(rows, start=1):
        body += (
            f'<tr><td>{rank}</td><td><a href="/item/main.naver?code={code}">{name}</a></td><td>{price}</td>'
            f"<td><span>상승 800</span></td><td>+0.99%</td><td>500</td><td>{cap}</td><td>69,655</td><td>14.69</td>"
            f"<td>{volume}</td><td>{per}</td><td>39.42</td><td></td></tr>"
        )
    return f'<html><table class="type_2"><tr>{head}</tr>{body}</table></html>'


def test_parse_naver_market_sum_reads_price_cap_volume_and_per():
    html = _page(
        [
            ("196170", "알테오젠", "277,000", "192,945", "267,212", "101.32"),
            ("086520", "에코프로", "81,900", "111,201", "162,603", "N/A"),
        ]
    )
    rows = parse_naver_market_sum(html, "KOSDAQ")
    assert [row.code for row in rows] == ["196170", "086520"]
    first = rows[0]
    assert first.name == "알테오젠"
    assert first.market == "KOSDAQ"
    assert first.close == 277_000
    assert first.market_cap == 192_945 * 100_000_000
    assert first.volume == 267_212
    assert first.trading_value == 277_000 * 267_212
    assert first.per == pytest.approx(101.32)
    assert first.change_rate == pytest.approx(0.0099)
    assert rows[1].per is None
    assert parse_naver_market_sum("<html>no table</html>", "KOSPI") == []


def test_load_naver_market_snapshot_pages_and_caps_rows():
    calls = []

    def fetcher(market, page):
        calls.append((market, page))
        base = 100_000 if market == "KOSPI" else 200_000
        rows = [(f"{base + (page - 1) * 50 + i:06d}", f"{market}{i}", "10,000", "5,000", "1,000", "10") for i in range(50)]
        return _page(rows)

    snapshot = load_naver_market_snapshot("2026-09-09", markets=("KOSPI", "KOSDAQ"), max_rows_per_market=120, page_fetcher=fetcher)
    assert snapshot.vendor == "naver"
    assert snapshot.as_of_date == "2026-09-09"
    assert len(snapshot.rows) == 240
    assert calls == [("KOSPI", 1), ("KOSPI", 2), ("KOSPI", 3), ("KOSDAQ", 1), ("KOSDAQ", 2), ("KOSDAQ", 3)]
    assert {row.market for row in snapshot.rows} == {"KOSPI", "KOSDAQ"}


def test_load_naver_market_snapshot_raises_when_empty():
    with pytest.raises(VendorUnavailableError):
        load_naver_market_snapshot(markets=("KOSPI",), page_fetcher=lambda market, page: "<html></html>")

    def boom(market, page):
        raise ConnectionError("offline")

    with pytest.raises(VendorUnavailableError, match="ConnectionError"):
        load_naver_market_snapshot(markets=("KOSPI",), page_fetcher=boom)
    with pytest.raises(ValueError):
        load_naver_market_snapshot(markets=("KOSPI",), max_rows_per_market=0, page_fetcher=boom)


def test_screener_auto_mode_falls_through_pykrx_to_naver(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_SCREENER_SNAPSHOT_MODE", raising=False)
    monkeypatch.setenv("TRADINGAGENTS_SCREENER_UNIVERSE_SIZE", "2")

    def blocked(*args, **kwargs):
        raise VendorUnavailableError("krx blocked")

    def naver_page(market, page):
        return _page(
            [
                ("005930", "삼성전자", "70,000", "4,000,000", "10,000,000", "12"),
                ("000660", "SK하이닉스", "180,000", "1,300,000", "3,000,000", "8"),
            ]
        )

    monkeypatch.setattr("tradingagents.screener.screener.load_market_snapshot", blocked)
    monkeypatch.setattr(
        "tradingagents.screener.screener.load_naver_market_snapshot",
        lambda when, markets, max_rows_per_market: load_naver_market_snapshot(
            when, markets=markets, max_rows_per_market=max_rows_per_market, page_fetcher=naver_page
        ),
    )
    points = [{"date": f"d{i}", "close": 60_000 * (1 + 0.003) ** i, "volume": 1_000_000} for i in range(120)]
    result = screen_korean_market(
        "2026-09-09",
        config=ScreenerConfig(markets=("KOSPI",), top_n=5, min_composite=-10),
        history_fetcher=lambda code, s, e: points,
    )
    assert result.universe_size == 2
    assert result.notes[0] == "snapshot 2026-09-09 from naver"
    assert {c.name for c in result.candidates} == {"삼성전자", "SK하이닉스"}


def test_screener_rejects_unknown_snapshot_mode():
    with pytest.raises(ValueError):
        screen_korean_market("2026-09-09", config=ScreenerConfig(snapshot_mode="bogus"), history_fetcher=lambda c, s, e: [])

"""KRX 금현물: a different instrument from the COMEX future, fetched differently."""

import pytest

from goldlab.data import (
    KRX_GOLD_INTERVALS,
    KRX_GOLD_SYMBOLS,
    _parse_krx_gold_date,
    fetch_bars,
    fetch_krx_gold_bars,
)

DAYS = [
    {"bsop_date": "26/09/18", "stck_oprc": 193450, "stck_hgpr": 195380,
     "stck_lwpr": 193450, "stck_prpr": 195310, "acml_vol": 148033},
    {"bsop_date": "26/09/17", "stck_oprc": 192000, "stck_hgpr": 192400,
     "stck_lwpr": 191000, "stck_prpr": 191970, "acml_vol": 120000},
    {"bsop_date": "26/09/16", "stck_oprc": 190000, "stck_hgpr": 191000,
     "stck_lwpr": 189500, "stck_prpr": 190500, "acml_vol": 90000},
]


class _Gold:
    def __init__(self, rows=None):
        self.asked = []
        self.rows = DAYS if rows is None else rows

    def gold_candles(self, *, start, end, code="M04020000", period="1"):
        self.asked.append((start, end, code, period))
        return {"rsp_cd": "00000", "Output_0": list(self.rows)}


def _patch(monkeypatch, client):
    import tradingagents.execution.nh_client as nh

    monkeypatch.setattr(nh.NHConfig, "from_env", classmethod(lambda cls, **kw: object()))
    monkeypatch.setattr(nh, "NHClient", lambda **kwargs: client)
    return client


def test_the_bars_come_back_oldest_first_in_won_per_gram(monkeypatch):
    client = _patch(monkeypatch, _Gold())
    series = fetch_krx_gold_bars(interval="1d")

    assert len(series) == 3
    assert series.symbol == "KRXGOLD" and series.interval == "1d"
    # NH hands these back newest first; a series reads the other way
    assert [bar.timestamp.date().isoformat() for bar in series.bars] == \
        ["2026-09-16", "2026-09-17", "2026-09-18"]
    assert series.bars[-1].close == 195_310


def test_the_symbol_routes_away_from_yahoo(monkeypatch):
    """fetch_bars must not ask Yahoo for a ticker Yahoo does not have."""

    client = _patch(monkeypatch, _Gold())
    monkeypatch.setattr("goldlab.data._fetch_from_yahoo",
                        lambda *a, **k: pytest.fail("Yahoo was asked for KRX gold"))
    for symbol in KRX_GOLD_SYMBOLS:
        assert len(fetch_bars(symbol, interval="1d")) == 3
    assert len(client.asked) == len(KRX_GOLD_SYMBOLS)


def test_intervals_the_exchange_does_not_serve_are_refused_by_name(monkeypatch):
    """gubun is documented as daily/weekly/monthly but answers daily for all three."""

    _patch(monkeypatch, _Gold())
    for missing in ("1h", "5m", "1mo"):
        with pytest.raises(ValueError, match="KRX gold has no"):
            fetch_krx_gold_bars(interval=missing)
    assert set(KRX_GOLD_INTERVALS) == {"1d", "1wk"}


def test_the_weekly_view_is_grouped_here_rather_than_asked_for(monkeypatch):
    rows = [{"bsop_date": f"26/09/{day:02d}", "stck_oprc": 100 + day, "stck_hgpr": 110 + day,
             "stck_lwpr": 90 + day, "stck_prpr": 105 + day, "acml_vol": 10}
            for day in range(1, 11)]
    client = _patch(monkeypatch, _Gold(rows))

    weekly = fetch_krx_gold_bars(interval="1wk")
    assert len(weekly) == 2 and weekly.interval == "1wk"
    # the vendor is still only ever asked for dailies
    assert all(asked[3] == "1" for asked in client.asked)
    # a grouped bar keeps the true extremes of its five sessions
    assert weekly.bars[0].high == max(110 + day for day in range(1, 6))
    assert weekly.bars[0].low == min(90 + day for day in range(1, 6))


def test_an_empty_answer_is_an_error_rather_than_an_empty_chart(monkeypatch):
    _patch(monkeypatch, _Gold([]))
    with pytest.raises(RuntimeError, match="no KRX gold bars"):
        fetch_krx_gold_bars(interval="1d")


def test_the_two_digit_year_nh_uses_is_read_as_this_century():
    assert _parse_krx_gold_date("26/09/18").date().isoformat() == "2026-09-18"
    assert _parse_krx_gold_date("") is None
    assert _parse_krx_gold_date("20260918") is None
    assert _parse_krx_gold_date("aa/bb/cc") is None


def test_the_desk_serves_the_krx_chart_behind_the_same_guard():
    from fastapi.testclient import TestClient
    from tradingagents.desk import create_desk_app

    app = create_desk_app(token="T0KEN", client_factory=lambda: None)
    with TestClient(app, base_url="http://127.0.0.1:8787") as http:
        assert http.get("/krxgold").status_code == 401
        assert http.get("/krxgold/data").status_code == 401

    with TestClient(app, base_url="http://127.0.0.1:8787") as http:
        page = http.get("/?t=T0KEN").text
    assert 'href="/krxgold"' in page

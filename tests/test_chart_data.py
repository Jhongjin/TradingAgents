from unittest.mock import MagicMock

import pandas as pd
import pytest

from tradingagents.dataflows import chart_data, krx_openapi, pykrx_vendor
from tradingagents.dataflows.errors import VendorUnavailableError


def test_ohlcv_chart_series_returns_api_friendly_points(monkeypatch):
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": [70000, 70500],
            "고가": [71000, 71500],
            "저가": [69000, 70000],
            "종가": [70500, 71200],
            "거래량": [123456, 234567],
            "거래대금": [8_700_000_000, 16_500_000_000],
            "등락률": [0.8, 0.99],
        },
        index=[pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")],
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)

    series = chart_data.get_ohlcv_chart_series("005930", "2026-01-02", "2026-01-05")

    assert series.ticker_code == "005930"
    assert series.ticker_name == "삼성전자"
    assert series.market == "KOSPI"
    assert series.currency == "KRW"
    assert series.vendor == "pykrx"
    assert series.points[0].as_dict() == {
        "date": "2026-01-02",
        "open": 70000.0,
        "high": 71000.0,
        "low": 69000.0,
        "close": 70500.0,
        "volume": 123456,
        "value": 8700000000.0,
        "change_rate": 0.8,
    }


def test_ohlcv_chart_series_rejects_non_korean_ticker():
    with pytest.raises(VendorUnavailableError, match="Korean 6-digit"):
        chart_data.get_ohlcv_chart_series("AAPL", "2026-01-02", "2026-01-05")


def test_ohlcv_chart_series_supports_krx_openapi_vendor(monkeypatch):
    class FakeKRXClient:
        def get_stock_daily_trade(self, bas_dd):
            return {
                "OutBlock_1": [
                    {
                        "BAS_DD": bas_dd,
                        "ISU_SRT_CD": "005930",
                        "ISU_NM": "삼성전자",
                        "TDD_OPNPRC": "70,000",
                        "TDD_HGPRC": "71,000",
                        "TDD_LWPRC": "69,000",
                        "TDD_CLSPRC": "70,500",
                        "ACC_TRDVOL": "123,456",
                        "ACC_TRDVAL": "8,700,000,000",
                    }
                ]
            }

    monkeypatch.setattr(krx_openapi, "_get_krx_client", lambda: FakeKRXClient())

    series = chart_data.get_ohlcv_chart_series("005930", "2026-01-02", "2026-01-02", vendor="krx")

    assert series.vendor == "krx"
    assert series.points[0].close == 70500.0
    assert series.points[0].volume == 123456
    assert series.points[0].value == 8_700_000_000.0


def test_ohlcv_chart_series_rejects_unknown_vendor():
    with pytest.raises(VendorUnavailableError, match="Unsupported chart data vendor"):
        chart_data.get_ohlcv_chart_series("005930", "2026-01-02", "2026-01-05", vendor="bogus")


def test_latest_close_price_uses_last_available_ohlcv_row(monkeypatch):
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": [70000, 70500],
            "고가": [71000, 71500],
            "저가": [69000, 70000],
            "종가": [70500, 71200],
            "거래량": [123456, 234567],
        },
        index=[pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")],
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)

    price = chart_data.get_latest_close_price("005930.KS", "2026-01-06")

    assert price.as_dict() == {
        "ticker_code": "005930",
        "ticker_name": "삼성전자",
        "market": "KOSPI",
        "currency": "KRW",
        "vendor": "pykrx",
        "date": "2026-01-05",
        "close": 71200.0,
    }


def test_latest_close_prices_can_ignore_unavailable_symbols(monkeypatch):
    calls = []

    def fake_latest(symbol, *args, **kwargs):
        calls.append(symbol)
        if symbol == "005930":
            return chart_data.LatestPrice(
                ticker_code="005930",
                ticker_name="삼성전자",
                market="KOSPI",
                currency="KRW",
                vendor="pykrx",
                date="2026-01-05",
                close=71200.0,
            )
        raise VendorUnavailableError("offline")

    monkeypatch.setattr(chart_data, "get_latest_close_price", fake_latest)

    prices = chart_data.get_latest_close_prices(["005930", "000660"], "2026-01-06", ignore_errors=True)

    assert calls == ["005930", "000660"]
    assert list(prices) == ["005930"]
    assert prices["005930"].close == 71200.0

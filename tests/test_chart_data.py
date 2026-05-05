from unittest.mock import MagicMock

import pandas as pd
import pytest

from tradingagents.dataflows import chart_data, pykrx_vendor
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


def test_ohlcv_chart_series_rejects_unknown_vendor():
    with pytest.raises(VendorUnavailableError, match="Unsupported chart data vendor"):
        chart_data.get_ohlcv_chart_series("005930", "2026-01-02", "2026-01-05", vendor="krx")

from datetime import datetime
import sys
import types
from unittest.mock import MagicMock

import pandas as pd
import pytest

from tradingagents.dataflows import dart, kr_returns, krx_openapi, naver_news, pykrx_vendor
from tradingagents.dataflows.errors import VendorUnavailableError


def test_pykrx_ohlcv_adapter_formats_korean_columns(monkeypatch):
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": [70000],
            "고가": [71000],
            "저가": [69000],
            "종가": [70500],
            "거래량": [123456],
        },
        index=[pd.Timestamp("2026-01-02")],
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)

    result = pykrx_vendor.get_stock("005930", "2026-01-02", "2026-01-02")

    assert "KRX OHLCV data for 삼성전자" in result
    assert "Open,High,Low,Close,Volume" in result
    assert "70500" in result


def test_pykrx_ohlcv_adapter_includes_optional_snapshot(monkeypatch):
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": [70000],
            "고가": [71000],
            "저가": [69000],
            "종가": [70500],
            "거래량": [123456],
        },
        index=[pd.Timestamp("2026-01-02")],
    )
    fake_stock.get_market_cap_by_date.return_value = pd.DataFrame(
        {
            "시가총액": [420_000_000_000_000],
            "상장주식수": [5_969_782_550],
            "거래대금": [1_200_000_000_000],
        },
        index=[pd.Timestamp("2026-01-02")],
    )
    fake_stock.get_market_fundamental_by_date.return_value = pd.DataFrame(
        {
            "PER": [11.2],
            "PBR": [1.3],
            "EPS": [6_200],
        },
        index=[pd.Timestamp("2026-01-02")],
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)

    result = pykrx_vendor.get_stock("005930", "2026-01-02", "2026-01-02")

    assert "Latest pykrx snapshot" in result
    assert "Market cap: 420,000,000,000,000 KRW" in result
    assert "PER: 11.2" in result


def test_pykrx_indicator_adapter_calculates_indicator(monkeypatch):
    dates = pd.date_range("2025-01-01", periods=280, freq="D")
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": range(1000, 1280),
            "고가": range(1001, 1281),
            "저가": range(999, 1279),
            "종가": range(1000, 1280),
            "거래량": [10000] * 280,
        },
        index=dates,
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)

    result = pykrx_vendor.get_indicator("005930", "rsi", "2025-10-07", look_back_days=5)

    assert "rsi values for 삼성전자" in result
    assert "Relative Strength Index" in result


def test_pykrx_korean_returns_calculates_benchmark_alpha(monkeypatch):
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {"종가": [70_000, 71_000, 72_000]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
    )
    fake_stock.get_index_ohlcv_by_date.return_value = pd.DataFrame(
        {"종가": [2_700, 2_710, 2_720]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
    )
    monkeypatch.setattr(kr_returns, "_get_pykrx_stock_module", lambda: fake_stock)

    raw, alpha, days = kr_returns.fetch_korean_returns("005930", "2026-01-02", holding_days=2)

    assert raw == pytest.approx((72_000 / 70_000) - 1)
    assert alpha == pytest.approx(((72_000 / 70_000) - 1) - ((2_720 / 2_700) - 1))
    assert days == 2
    fake_stock.get_index_ohlcv_by_date.assert_called_once()


def test_naver_news_adapter_uses_credentials_and_formats_items(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")

    response = MagicMock()
    response.json.return_value = {
        "items": [
            {
                "title": "<b>삼성전자</b> 실적 개선",
                "description": "반도체 업황 회복",
                "pubDate": "Fri, 02 Jan 2026 09:00:00 +0900",
                "originallink": "https://example.com/article",
            }
        ]
    }
    captured = {}

    def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(naver_news.requests, "get", fake_get)

    result = naver_news.get_news("005930", "2026-01-01", "2026-01-03")

    assert "삼성전자 실적 개선" in result
    assert "반도체 업황 회복" in result
    assert captured["verify"] is True


def test_naver_news_adapter_allows_custom_ca_bundle(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_HTTP_CA_BUNDLE", "C:/certs/corp.pem")

    assert naver_news._requests_verify_setting() == "C:/certs/corp.pem"


def test_dart_fundamentals_adapter_formats_company_and_disclosures(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "dart-key")

    def fake_request(endpoint, params):
        if endpoint == "company.json":
            return {
                "corp_code": params["corp_code"],
                "corp_name": "삼성전자",
                "ceo_nm": "한종희",
                "induty_code": "264",
                "est_dt": "19690113",
                "acc_mt": "12",
            }
        if endpoint == "list.json":
            return {
                "list": [
                    {
                        "rcept_dt": "20260102",
                        "report_nm": "주요사항보고서",
                        "rcept_no": "20260102000001",
                    }
                ]
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(dart, "_request_json", fake_request)

    result = dart.get_fundamentals("005930", "2026-01-03")

    assert "DART fundamentals for 삼성전자" in result
    assert "주요사항보고서" in result


def test_dart_statement_adapter_uses_latest_quarterly_report_code(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "dart-key")
    captured = {}

    def fake_request(endpoint, params):
        captured.update(params)
        return {
            "list": [
                {
                    "sj_div": "BS",
                    "account_nm": "자산총계",
                    "thstrm_amount": "100000",
                    "frmtrm_amount": "90000",
                }
            ]
        }

    monkeypatch.setattr(dart, "_request_json", fake_request)

    result = dart.get_balance_sheet("005930", "quarterly", "2026-08-20")

    assert captured["bsns_year"] == "2026"
    assert captured["reprt_code"] == "11012"
    assert "Half-year report" in result
    assert "자산총계" in result


def test_krx_openapi_scaffold_is_fallback_friendly(monkeypatch):
    monkeypatch.delenv("KRX_API_KEY", raising=False)
    monkeypatch.delenv("KRX_OPENAPI_KEY", raising=False)

    try:
        krx_openapi.get_stock("005930", "2026-01-02", "2026-01-02")
    except VendorUnavailableError as exc:
        assert "KRX_API_KEY" in str(exc)
    else:
        raise AssertionError("KRX Open API scaffold must require an API key")


def test_krx_openapi_adapter_formats_daily_trade_rows(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "krx-key")

    class FakeKRXClient:
        def get_stock_daily_trade(self, bas_dd):
            return {
                "OutBlock_1": [
                    {
                        "BAS_DD": bas_dd,
                        "ISU_SRT_CD": "005930",
                        "ISU_NM": "삼성전자",
                        "TDD_OPNPRC": 70000,
                        "TDD_HGPRC": 71000,
                        "TDD_LWPRC": 69000,
                        "TDD_CLSPRC": 70500,
                        "ACC_TRDVOL": 123456,
                        "ACC_TRDVAL": 8_700_000_000,
                        "MKTCAP": 420_000_000_000_000,
                    }
                ]
            }

    monkeypatch.setattr(krx_openapi, "_get_krx_client", lambda: FakeKRXClient())

    result = krx_openapi.get_stock("005930", "2026-01-02", "2026-01-02")

    assert "KRX Open API daily trade data for 삼성전자" in result
    assert "Open,High,Low,Close,Volume,Value,MarketCap" in result
    assert "70500" in result


def test_krx_openapi_applies_system_truststore_before_client_import(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    calls = []

    class FakeKRXOpenAPI:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs["api_key"]))

    fake_module = types.SimpleNamespace(KRXOpenAPI=FakeKRXOpenAPI)
    monkeypatch.setitem(sys.modules, "pykrx_openapi", fake_module)
    monkeypatch.setattr(krx_openapi, "apply_system_truststore_if_available", lambda: calls.append(("trust", None)))

    krx_openapi._get_krx_client()

    assert calls == [("trust", None), ("client", "krx-key")]

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from tradingagents.dataflows import krx_openapi, pykrx_vendor
from tradingagents.dataflows.chart_data import ChartSeries
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.site import build_public_stock_payload
from tradingagents.storage import (
    AgentReportInput,
    AnalysisOutcomeInput,
    AnalysisRunInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def _seed_public_analysis(repo: StorageRepository) -> str:
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
            model_provider="openai",
        )
    )
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=run_id,
            role="market",
            title="Market report",
            content="Korean OHLCV context",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Hold",
            action="hold",
            target_weight=None,
            rationale="Wait for stronger evidence.",
            raw_decision="Rating: Hold",
        )
    )
    repo.complete_analysis_run(run_id)
    return run_id


def test_public_stock_payload_combines_analysis_and_chart(monkeypatch):
    repo = _repo()
    run_id = _seed_public_analysis(repo)
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=5,
            raw_return=0.04,
            benchmark_return=0.01,
            alpha_return=0.03,
            status="completed",
        )
    )
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": [70000],
            "고가": [71000],
            "저가": [69000],
            "종가": [70500],
            "거래량": [123456],
        },
        index=[pd.Timestamp("2026-05-04")],
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)

    payload = build_public_stock_payload(
        "005930",
        repo=repo,
        chart_start="2026-05-04",
        chart_end="2026-05-05",
        as_of_date="2026-05-05",
    )

    assert payload["ticker"] == {
        "code": "005930",
        "name": "삼성전자",
        "market": "KOSPI",
        "currency": "KRW",
        "benchmark_symbol": "^KS11",
    }
    assert payload["analysis"]["status"] == "available"
    assert payload["analysis"]["run"]["id"] == run_id
    assert payload["analysis"]["run"]["trade_date"] == "2026-05-05"
    assert payload["analysis"]["reports"][0]["role"] == "market"
    assert payload["analysis"]["decision"]["rating"] == "Hold"
    assert payload["analysis"]["outcomes"][0]["horizon_days"] == 5
    assert payload["analysis"]["outcomes"][0]["alpha_return"] == 0.03
    assert payload["analysis_refresh"]["recommended"] is False
    assert payload["analysis_refresh"]["reason"] == "fresh"
    assert payload["chart"]["status"] == "available"
    assert payload["chart"]["points"][0]["close"] == 70500.0
    assert len(payload["strategy_lenses"]) == 6
    assert payload["strategy_lenses"][0]["id"] == "trend"
    assert "notices" in payload
    assert payload["generated_at"]


def test_public_stock_payload_handles_missing_optional_sources(monkeypatch):
    def unavailable(*args, **kwargs):
        raise VendorUnavailableError("chart vendor is offline")

    monkeypatch.setattr("tradingagents.site.public_api.get_ohlcv_chart_series", unavailable)

    payload = build_public_stock_payload(
        "005930",
        repo=None,
        chart_start="2026-05-04",
        chart_end="2026-05-05",
        as_of_date="2026-05-05",
    )

    assert payload["analysis"]["status"] == "not_configured"
    assert payload["chart"]["status"] == "unavailable"
    assert payload["chart"]["error"] == "chart vendor is offline"


def test_public_stock_payload_uses_configured_chart_vendor(monkeypatch):
    repo = _repo()
    _seed_public_analysis(repo)
    monkeypatch.setenv("TRADINGAGENTS_CHART_DATA_VENDOR", "krx")

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
                    }
                ]
            }

    monkeypatch.setattr(krx_openapi, "_get_krx_client", lambda: FakeKRXClient())

    payload = build_public_stock_payload(
        "005930",
        repo=repo,
        chart_start="2026-05-04",
        chart_end="2026-05-04",
        as_of_date="2026-05-05",
    )

    assert payload["chart"]["status"] == "available"
    assert payload["chart"]["vendor"] == "krx"
    assert payload["chart"]["points"][0]["close"] == 70500.0


def test_public_stock_payload_limits_default_krx_diagnostic_window(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_KRX_CHART_MAX_DAYS", "7")
    captured: dict[str, str] = {}

    def fake_chart_series(symbol, start_date, end_date, *, vendor):
        captured.update(
            {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "vendor": vendor,
            }
        )
        return ChartSeries(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            currency="KRW",
            vendor="krx",
            points=[],
        )

    monkeypatch.setattr("tradingagents.site.public_api.get_ohlcv_chart_series", fake_chart_series)

    payload = build_public_stock_payload(
        "005930",
        chart_end="2026-05-19",
        as_of_date="2026-05-19",
        chart_vendor="krx",
        include_analysis=False,
    )

    assert captured == {
        "symbol": "005930",
        "start_date": "2026-05-12",
        "end_date": "2026-05-19",
        "vendor": "krx",
    }
    assert payload["chart"]["status"] == "available"
    assert payload["chart"]["start_date"] == "2026-05-12"
    assert payload["chart"]["vendor"] == "krx"


def test_public_stock_payload_recommends_refresh_for_stale_or_missing_analysis():
    repo = _repo()
    old_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 1),
            visibility="public",
        )
    )
    repo.complete_analysis_run(old_run_id)

    stale_payload = build_public_stock_payload(
        "005930",
        repo=repo,
        include_chart=False,
        as_of_date="2026-05-05",
        max_analysis_age_days=1,
    )
    missing_payload = build_public_stock_payload(
        "000660",
        repo=repo,
        include_chart=False,
        as_of_date="2026-05-05",
    )

    assert stale_payload["analysis"]["status"] == "available"
    assert stale_payload["analysis_refresh"]["recommended"] is True
    assert stale_payload["analysis_refresh"]["reason"] == "stale"
    assert stale_payload["analysis_refresh"]["age_days"] == 4
    assert missing_payload["analysis"]["status"] == "missing"
    assert missing_payload["analysis_refresh"]["recommended"] is True
    assert missing_payload["analysis_refresh"]["reason"] == "no_completed_public_analysis"


def test_public_stock_payload_rejects_non_korean_ticker():
    with pytest.raises(VendorUnavailableError, match="Korean 6-digit"):
        build_public_stock_payload("AAPL", include_chart=False)

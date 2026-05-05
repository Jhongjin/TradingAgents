from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from tradingagents.dataflows import pykrx_vendor
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.site import build_public_stock_payload
from tradingagents.storage import (
    AgentReportInput,
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
    assert payload["chart"]["status"] == "available"
    assert payload["chart"]["points"][0]["close"] == 70500.0
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
    )

    assert payload["analysis"]["status"] == "not_configured"
    assert payload["chart"]["status"] == "unavailable"
    assert payload["chart"]["error"] == "chart vendor is offline"


def test_public_stock_payload_rejects_non_korean_ticker():
    with pytest.raises(VendorUnavailableError, match="Korean 6-digit"):
        build_public_stock_payload("AAPL", include_chart=False)

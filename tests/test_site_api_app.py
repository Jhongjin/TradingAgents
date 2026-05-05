from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
from fastapi.testclient import TestClient

from tradingagents.dataflows import pykrx_vendor
from tradingagents.site.api_app import create_app
from tradingagents.storage import (
    AgentReportInput,
    AnalysisRunInput,
    ManualTradeInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)


USER_ID = "00000000-0000-0000-0000-000000000001"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def _seed_public_analysis(repo: StorageRepository) -> None:
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=run_id,
            role="market",
            content="market report",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Hold",
            action="hold",
            raw_decision="Rating: Hold",
        )
    )
    repo.complete_analysis_run(run_id)


def test_api_app_serves_public_stock_payload(monkeypatch):
    repo = _repo()
    _seed_public_analysis(repo)
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": [70000],
            "고가": [71000],
            "저가": [69000],
            "종가": [70500],
            "거래량": [123456],
        },
        index=[pd.Timestamp("2026-05-05")],
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)

    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    response = client.get(
        "/api/stocks/005930",
        params={
            "chart_start": "2026-05-05",
            "chart_end": "2026-05-05",
            "as_of_date": "2026-05-05",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"]["code"] == "005930"
    assert body["analysis"]["status"] == "available"
    assert body["chart"]["points"][0]["close"] == 70500.0


def test_api_app_rejects_non_korean_public_stock_ticker():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/stocks/AAPL", params={"include_chart": "false"})

    assert response.status_code == 400
    assert "Korean 6-digit" in response.json()["detail"]


def test_api_app_serves_manual_portfolio_payload():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="005930",
            side="buy",
            trade_date=date(2026, 1, 2),
            price=Decimal("70000"),
            quantity=10,
        )
    )

    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    response = client.get(
        f"/api/portfolio/{portfolio_id}",
        params={"current_prices": "005930:83000"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pricing_status"] == "complete"
    assert body["totals"]["market_value"] == 830000.0


def test_api_app_portfolio_requires_storage_repo():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get(f"/api/portfolio/{USER_ID}")

    assert response.status_code == 503
    assert response.json()["detail"] == "Storage repository is not configured"


def test_api_app_rejects_malformed_current_prices():
    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get(f"/api/portfolio/{USER_ID}", params={"current_prices": "005930"})

    assert response.status_code == 400
    assert "ticker:price" in response.json()["detail"]

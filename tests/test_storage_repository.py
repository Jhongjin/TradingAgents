from datetime import date
from decimal import Decimal

import pytest

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


def test_storage_repository_persists_public_analysis_bundle():
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            model_provider="openai",
            metadata={"source": "smoke"},
        )
    )

    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=run_id,
            role="market",
            title="Market report",
            content="KRX OHLCV and benchmark alpha",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Neutral",
            action="hold",
            target_weight=0.0,
            rationale="No edge after costs.",
            raw_decision="Rating: Neutral",
        )
    )
    repo.complete_analysis_run(run_id)

    bundle = repo.get_analysis_bundle(run_id)

    assert bundle is not None
    assert bundle["run"]["ticker_code"] == "005930"
    assert bundle["run"]["status"] == "completed"
    assert bundle["reports"][0]["role"] == "market"
    assert bundle["decision"]["rating"] == "Neutral"


def test_storage_repository_lists_latest_public_analysis_bundle():
    repo = _repo()
    older_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 4),
            visibility="public",
        )
    )
    latest_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    private_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 6),
            visibility="private",
        )
    )
    repo.complete_analysis_run(older_id)
    repo.complete_analysis_run(latest_id)
    repo.complete_analysis_run(private_id)
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=latest_id,
            role="market",
            content="latest public report",
        )
    )

    runs = repo.list_public_analysis_runs(ticker_code="005930")
    bundle = repo.latest_public_analysis_bundle("005930.KS")

    assert [run["id"] for run in runs] == [latest_id, older_id]
    assert bundle is not None
    assert bundle["run"]["id"] == latest_id
    assert bundle["reports"][0]["content"] == "latest public report"


def test_storage_repository_calculates_manual_portfolio_positions():
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
            fee=Decimal("100"),
        )
    )
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="005930",
            side="buy",
            trade_date=date(2026, 1, 5),
            price=Decimal("72000"),
            quantity=5,
            fee=Decimal("100"),
        )
    )
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="005930",
            side="sell",
            trade_date=date(2026, 1, 6),
            price=Decimal("73000"),
            quantity=4,
            fee=Decimal("50"),
            tax=Decimal("584"),
        )
    )

    positions = repo.manual_positions(portfolio_id)

    samsung = positions["005930"]
    assert samsung.ticker_name == "삼성전자"
    assert samsung.market == "KOSPI"
    assert samsung.quantity == 11
    assert samsung.average_cost == Decimal("70680.0000")
    assert samsung.realized_pnl == Decimal("8646.0000")
    assert samsung.unrealized_pnl(Decimal("74000")) == Decimal("36520.0000")


def test_storage_repository_upserts_manual_price_targets():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")

    target_id = repo.set_price_target(
        portfolio_id=portfolio_id,
        ticker_code="005930.KS",
        target_price=Decimal("80000"),
        stop_price=Decimal("65000"),
        memo="initial",
    )
    first_row = repo.price_targets_for_portfolio(portfolio_id)[0]

    updated_id = repo.set_price_target(
        portfolio_id=portfolio_id,
        ticker_code="005930",
        target_price=Decimal("82000"),
        stop_price=Decimal("66000"),
        memo="updated",
    )
    rows = repo.price_targets_for_portfolio(portfolio_id)

    assert updated_id == target_id
    assert len(rows) == 1
    assert rows[0]["ticker_code"] == "005930"
    assert rows[0]["target_price"] == Decimal("82000.0000")
    assert rows[0]["stop_price"] == Decimal("66000.0000")
    assert rows[0]["memo"] == "updated"
    assert rows[0]["updated_at"] >= first_row["updated_at"]


def test_storage_repository_rejects_invalid_manual_trade():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")

    with pytest.raises(ValueError, match="side must be buy or sell"):
        repo.add_manual_trade(
            ManualTradeInput(
                portfolio_id=portfolio_id,
                ticker_code="005930",
                side="hold",
                trade_date=date(2026, 1, 2),
                price=Decimal("70000"),
                quantity=10,
            )
        )


def test_storage_repository_rejects_invalid_user_uuid():
    repo = _repo()

    with pytest.raises(ValueError, match="portfolio user_id must be a UUID string"):
        repo.create_manual_portfolio(user_id="user-1", name="Main")

    with pytest.raises(ValueError, match="analysis user_id must be a UUID string"):
        repo.create_analysis_run(
            AnalysisRunInput(
                ticker_code="005930",
                trade_date=date(2026, 5, 5),
                user_id="user-1",
            )
        )


def test_storage_engine_normalizes_postgres_urls_to_psycopg_driver():
    engine = create_storage_engine("postgres://user:pass@example.com:5432/postgres")

    assert engine.url.drivername == "postgresql+psycopg"

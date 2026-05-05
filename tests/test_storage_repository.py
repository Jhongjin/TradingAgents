from datetime import date
from decimal import Decimal

import pytest

from tradingagents.storage import (
    AgentReportInput,
    AnalysisRequestInput,
    AnalysisRunInput,
    ManualTradeInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)
from tradingagents.storage.repository import _normalize_storage_url


USER_ID = "00000000-0000-0000-0000-000000000001"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def test_storage_engine_defaults_postgres_urls_to_pg8000(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_POSTGRES_DRIVER", raising=False)

    assert (
        _normalize_storage_url("postgresql://user:password@example.supabase.co:6543/postgres")
        == "postgresql+pg8000://user:password@example.supabase.co:6543/postgres"
    )
    assert (
        _normalize_storage_url("postgres://user:password@example.supabase.co:6543/postgres")
        == "postgresql+pg8000://user:password@example.supabase.co:6543/postgres"
    )


def test_storage_engine_allows_postgres_driver_override(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_POSTGRES_DRIVER", "psycopg")

    assert (
        _normalize_storage_url("postgresql://user:password@example.supabase.co:6543/postgres")
        == "postgresql+psycopg://user:password@example.supabase.co:6543/postgres"
    )


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
    pending_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 7),
            visibility="public",
        )
    )
    failed_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 8),
            visibility="public",
        )
    )
    repo.complete_analysis_run(older_id)
    repo.complete_analysis_run(latest_id)
    repo.complete_analysis_run(private_id)
    repo.complete_analysis_run(failed_id, status="failed")
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=latest_id,
            role="market",
            content="latest public report",
        )
    )

    runs = repo.list_public_analysis_runs(ticker_code="005930")
    all_status_runs = repo.list_public_analysis_runs(ticker_code="005930", status=None)
    bundle = repo.latest_public_analysis_bundle("005930.KS")

    assert [run["id"] for run in runs] == [latest_id, older_id]
    assert [run["id"] for run in all_status_runs] == [failed_id, pending_id, latest_id, older_id]
    assert bundle is not None
    assert bundle["run"]["id"] == latest_id
    assert bundle["reports"][0]["content"] == "latest public report"


def test_storage_repository_queues_analysis_refresh_requests():
    repo = _repo()
    request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930.KS",
            requested_trade_date=date(2026, 5, 5),
            reason="stale public page",
        )
    )

    queued = repo.list_analysis_requests(user_id=USER_ID)
    repo.update_analysis_request_status(request_id, status="running")
    running = repo.list_analysis_requests(status="running", user_id=USER_ID)
    fetched = repo.get_analysis_request(request_id)

    assert len(queued) == 1
    assert queued[0]["ticker_code"] == "005930"
    assert queued[0]["ticker_name"] == "삼성전자"
    assert queued[0]["market"] == "KOSPI"
    assert queued[0]["reason"] == "stale public page"
    assert running[0]["id"] == request_id
    assert running[0]["status"] == "running"
    assert fetched is not None
    assert fetched["id"] == request_id


def test_storage_repository_finds_active_analysis_request_for_deduping():
    repo = _repo()
    request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930.KS",
            requested_trade_date=date(2026, 5, 5),
            reason="stale public page",
        )
    )

    existing = repo.find_active_analysis_request(
        user_id=USER_ID,
        ticker_code="005930",
        requested_trade_date=date(2026, 5, 5),
    )
    repo.update_analysis_request_status(request_id, status="completed")
    completed = repo.find_active_analysis_request(
        user_id=USER_ID,
        ticker_code="005930",
        requested_trade_date=date(2026, 5, 5),
    )

    assert existing is not None
    assert existing["id"] == request_id
    assert completed is None


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


def test_storage_repository_manages_manual_watchlists():
    repo = _repo()
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")

    samsung_id = repo.add_watchlist_item(
        watchlist_id=watchlist_id,
        ticker_code="005930.KS",
        memo="core holding candidate",
    )
    updated_id = repo.add_watchlist_item(
        watchlist_id=watchlist_id,
        ticker_code="005930",
        memo="updated memo",
    )
    repo.add_watchlist_item(watchlist_id=watchlist_id, ticker_code="000660")
    repo.remove_watchlist_item(watchlist_id=watchlist_id, ticker_code="000660")

    watchlist = repo.get_watchlist(watchlist_id)
    items = repo.watchlist_items(watchlist_id)

    assert watchlist is not None
    assert watchlist["name"] == "관심종목"
    assert updated_id == samsung_id
    assert len(items) == 1
    assert items[0]["ticker_code"] == "005930"
    assert items[0]["ticker_name"] == "삼성전자"
    assert items[0]["market"] == "KOSPI"
    assert items[0]["memo"] == "updated memo"


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


def test_storage_engine_normalizes_postgres_urls_to_configured_driver(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_POSTGRES_DRIVER", "psycopg")

    assert _normalize_storage_url("postgres://user:pass@example.com:5432/postgres").startswith("postgresql+psycopg://")

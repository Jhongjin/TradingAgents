from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tradingagents.storage import (
    AgentReportInput,
    AnalysisOutcomeInput,
    AnalysisRequestInput,
    AnalysisRunInput,
    ManualTradeInput,
    PaperSimulationAccountInput,
    PaperSimulationEventInput,
    PaperSimulationPositionInput,
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


def test_storage_repository_upserts_analysis_outcomes():
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.complete_analysis_run(run_id)

    outcome_id = repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=5,
            actual_holding_days=5,
            raw_return=0.04,
            benchmark_return=0.01,
            alpha_return=0.03,
            decision_rating="Hold",
            decision_action="hold",
            status="completed",
        )
    )
    same_id = repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 13),
            horizon_days=5,
            actual_holding_days=5,
            raw_return=0.05,
            benchmark_return=0.02,
            alpha_return=0.03,
            status="completed",
        )
    )

    outcomes = repo.list_analysis_outcomes(analysis_run_id=run_id)
    bundle = repo.get_analysis_bundle(run_id)

    assert same_id == outcome_id
    assert len(outcomes) == 1
    assert outcomes[0]["raw_return"] == 0.05
    assert outcomes[0]["alpha_return"] == 0.03
    assert bundle is not None
    assert bundle["outcomes"][0]["id"] == outcome_id


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


def test_storage_repository_lists_public_analysis_feed_items_without_full_bundles():
    repo = _repo()
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
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=20,
            raw_return=0.02,
            benchmark_return=0.01,
            alpha_return=0.01,
            status="completed",
        )
    )
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
    repo.complete_analysis_run(run_id)
    latest_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 6),
            visibility="public",
            model_provider="openai",
        )
    )
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=latest_id,
            role="market",
            content="latest market report",
        )
    )
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=latest_id,
            role="news",
            content="latest news report",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=latest_id,
            rating="Buy",
            action="buy",
            raw_decision="Rating: Buy",
        )
    )
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=latest_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 6),
            evaluated_at=date(2026, 6, 3),
            horizon_days=20,
            raw_return=0.05,
            benchmark_return=0.02,
            alpha_return=0.03,
            status="completed",
        )
    )
    repo.complete_analysis_run(latest_id)

    items = repo.list_public_analysis_feed_items(ticker_code="005930")

    assert [item["id"] for item in items] == [latest_id, run_id]
    assert items[0]["report_count"] == 2
    assert items[0]["decision_rating"] == "Buy"
    assert items[0]["decision_action"] == "buy"
    assert items[0]["completed_outcome_count"] == 1
    assert items[0]["outcome_horizon_days"] == 20
    assert items[0]["alpha_return"] == 0.03
    assert items[0]["report_path"] == f"/analyses/{latest_id}"
    assert items[0]["api_path"] == f"/api/analyses/{latest_id}"
    assert items[1]["report_count"] == 1
    assert items[1]["decision_rating"] == "Hold"
    assert items[1]["decision_action"] == "hold"
    assert items[1]["completed_outcome_count"] == 2
    assert items[1]["outcome_horizon_days"] == 5
    assert items[1]["alpha_return"] == 0.03
    assert items[1]["report_path"] == f"/analyses/{run_id}"
    assert items[1]["api_path"] == f"/api/analyses/{run_id}"


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


def test_storage_repository_counts_analysis_requests_for_quotas():
    repo = _repo()
    request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    repo.create_analysis_request(
        AnalysisRequestInput(
            user_id="00000000-0000-0000-0000-000000000002",
            ticker_code="000660",
            requested_trade_date=date(2026, 5, 5),
        )
    )

    assert repo.count_analysis_requests(user_id=USER_ID) == 1
    assert repo.count_analysis_requests(user_id=USER_ID, statuses=("queued", "running")) == 1
    assert repo.count_analysis_requests(
        user_id=USER_ID,
        created_at_from=datetime.now(timezone.utc) + timedelta(seconds=1),
    ) == 0

    repo.update_analysis_request_status(request_id, status="completed")

    assert repo.count_analysis_requests(user_id=USER_ID) == 1
    assert repo.count_analysis_requests(user_id=USER_ID, statuses=("queued", "running")) == 0


def test_storage_repository_calculates_manual_portfolio_positions():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    repo.create_manual_portfolio(user_id="00000000-0000-0000-0000-000000000002", name="Other")

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
    portfolios = repo.list_manual_portfolios(user_id=USER_ID)

    samsung = positions["005930"]
    assert [portfolio["id"] for portfolio in portfolios] == [portfolio_id]
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
    repo.create_watchlist(user_id="00000000-0000-0000-0000-000000000002", name="Other")

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
    watchlists = repo.list_watchlists(user_id=USER_ID)
    items = repo.watchlist_items(watchlist_id)

    assert watchlist is not None
    assert watchlist["name"] == "관심종목"
    assert [watchlist["id"] for watchlist in watchlists] == [watchlist_id]
    assert updated_id == samsung_id
    assert len(items) == 1
    assert items[0]["ticker_code"] == "005930"
    assert items[0]["ticker_name"] == "삼성전자"
    assert items[0]["market"] == "KOSPI"
    assert items[0]["memo"] == "updated memo"


def test_storage_repository_manages_paper_simulation_records():
    repo = _repo()
    request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            user_id=USER_ID,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Buy",
            action="buy",
            target_weight=0.2,
        )
    )
    repo.complete_analysis_run(run_id)
    repo.update_analysis_request_status(request_id, status="completed", analysis_run_id=run_id)

    candidates = repo.list_paper_simulation_candidates()
    account = repo.ensure_paper_simulation_account(PaperSimulationAccountInput(user_id=USER_ID))
    same_account = repo.ensure_paper_simulation_account(PaperSimulationAccountInput(user_id=USER_ID))
    position_id = repo.record_paper_simulation_position(
        PaperSimulationPositionInput(
            account_id=account["id"],
            user_id=USER_ID,
            analysis_run_id=run_id,
            analysis_request_id=request_id,
            ticker_code="005930",
            status="closed",
            quantity=10,
            entry_date=date(2026, 5, 5),
            entry_price=Decimal("70000"),
            average_price=Decimal("70000"),
            exit_date=date(2026, 5, 7),
            exit_price=Decimal("76000"),
            realized_pnl=Decimal("60000"),
            realized_return=0.0857,
            decision_rating="Buy",
            decision_action="buy",
            target_weight=0.2,
        )
    )
    event_id = repo.add_paper_simulation_event(
        PaperSimulationEventInput(
            account_id=account["id"],
            position_id=position_id,
            user_id=USER_ID,
            analysis_run_id=run_id,
            event_type="entry",
            side="buy",
            event_date=date(2026, 5, 5),
            ticker_code="005930",
            price=Decimal("70000"),
            quantity=10,
            notional=Decimal("700000"),
            reason="buy",
        )
    )

    positions = repo.list_paper_simulation_positions(user_id=USER_ID)
    events = repo.list_paper_simulation_events(user_id=USER_ID)

    assert candidates[0]["analysis_run_id"] == run_id
    assert candidates[0]["analysis_request_id"] == request_id
    assert same_account["id"] == account["id"]
    assert positions[0]["id"] == position_id
    assert positions[0]["ticker_name"] == "삼성전자"
    assert positions[0]["status"] == "closed"
    assert repo.count_paper_simulation_positions(user_id=USER_ID, statuses=("closed",)) == 1
    assert repo.list_paper_simulation_candidates() == []
    assert events[0]["id"] == event_id
    assert events[0]["event_type"] == "entry"


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

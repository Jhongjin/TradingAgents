from datetime import date

from tradingagents.site.outcome_worker import evaluate_public_analysis_outcomes
from tradingagents.storage import (
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


def test_evaluate_public_analysis_outcomes_upserts_completed_returns(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 1),
            visibility="public",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Buy",
            action="buy",
        )
    )
    repo.complete_analysis_run(run_id)

    monkeypatch.setattr(
        "tradingagents.site.outcome_worker.fetch_korean_returns",
        lambda ticker, trade_date, holding_days: (0.05, 0.02, holding_days),
    )

    results = evaluate_public_analysis_outcomes(repo, horizons=(5, 20), limit=3, as_of_date="2026-06-01")
    outcomes = repo.list_analysis_outcomes(analysis_run_id=run_id)

    assert [result.status for result in results] == ["completed", "completed"]
    assert [outcome["horizon_days"] for outcome in outcomes] == [5, 20]
    assert outcomes[0]["raw_return"] == 0.05
    assert outcomes[0]["benchmark_return"] == 0.030000000000000002
    assert outcomes[0]["alpha_return"] == 0.02
    assert outcomes[0]["decision_rating"] == "Buy"


def test_evaluate_public_analysis_outcomes_marks_incomplete_horizon_pending(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            trade_date=date(2026, 5, 1),
            visibility="public",
        )
    )
    repo.complete_analysis_run(run_id)

    monkeypatch.setattr(
        "tradingagents.site.outcome_worker.fetch_korean_returns",
        lambda ticker, trade_date, holding_days: (0.01, 0.005, 3),
    )

    results = evaluate_public_analysis_outcomes(repo, horizons=(5,), as_of_date="2026-05-06")
    outcomes = repo.list_analysis_outcomes(analysis_run_id=run_id)

    assert results[0].status == "pending"
    assert results[0].error == "insufficient_holding_days"
    assert outcomes[0]["status"] == "pending"
    assert outcomes[0]["raw_return"] is None


def test_evaluate_public_analysis_outcomes_marks_vendor_errors_unavailable(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            trade_date=date(2026, 5, 1),
            visibility="public",
        )
    )
    repo.complete_analysis_run(run_id)

    def fail(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("tradingagents.site.outcome_worker.fetch_korean_returns", fail)

    results = evaluate_public_analysis_outcomes(repo, horizons=(5,), as_of_date="2026-06-01")
    outcomes = repo.list_analysis_outcomes(analysis_run_id=run_id)

    assert results[0].status == "unavailable"
    assert "RuntimeError" in results[0].error
    assert outcomes[0]["status"] == "unavailable"


def test_evaluate_public_analysis_outcomes_skips_completed_horizons(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            trade_date=date(2026, 5, 1),
            visibility="public",
        )
    )
    repo.complete_analysis_run(run_id)
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            trade_date=date(2026, 5, 1),
            evaluated_at=date(2026, 6, 1),
            horizon_days=5,
            actual_holding_days=5,
            raw_return=0.05,
            benchmark_return=0.03,
            alpha_return=0.02,
            status="completed",
        )
    )

    def should_not_fetch(*args, **kwargs):
        raise AssertionError("completed outcomes should not be fetched again")

    monkeypatch.setattr("tradingagents.site.outcome_worker.fetch_korean_returns", should_not_fetch)

    results = evaluate_public_analysis_outcomes(repo, horizons=(5,), as_of_date="2026-06-02")

    assert results[0].status == "skipped"
    assert results[0].error == "already_completed"
    assert results[0].alpha_return == 0.02
    assert len(repo.list_analysis_outcomes(analysis_run_id=run_id)) == 1

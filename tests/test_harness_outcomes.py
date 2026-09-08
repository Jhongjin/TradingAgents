from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cli.main import app
from tradingagents.site.api_app import create_app
from tradingagents.site.harness_api import build_harness_outcomes_payload, build_harness_run_payload
from tradingagents.site.harness_outcome_worker import (
    evaluate_harness_outcomes,
    summarize_harness_outcome_results,
    summarize_stored_harness_outcomes,
)
from tradingagents.storage import HarnessDecisionInput, HarnessOutcomeInput, HarnessRunInput, StorageRepository, create_storage_engine


def _repo():
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def _seed(repo, *, visibility="public", stage="ordered"):
    run_id = repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 8, 1), confirmer="debate", visibility=visibility, order_count=1))
    decision_id = repo.add_harness_decision(
        HarnessDecisionInput(
            harness_run_id=run_id,
            as_of_date=date(2026, 8, 1),
            ticker_code="005930",
            stage=stage,
            screener_rank=1,
            confirmation_rating="Buy",
            confirmation_source="debate",
            quantity=3,
            entry_price=Decimal("70000"),
            order_status="dry_run",
        )
    )
    return run_id, decision_id


def test_evaluate_harness_outcomes_completes_pending_and_unavailable():
    repo = _repo()
    run_id, decision_id = _seed(repo)
    _seed(repo, stage="forecast_rejected")  # must be ignored

    def fetcher(code, entry, horizon):
        if horizon == 5:
            return 0.04, 0.01, 5
        return 0.02, -0.01, 12  # 20D not elapsed yet

    results = evaluate_harness_outcomes(repo, limit=10, as_of_date="2026-08-20", returns_fetcher=fetcher)
    assert [(r.horizon_days, r.status) for r in results] == [(5, "completed"), (20, "pending")]
    stored = repo.list_harness_outcomes(harness_run_id=run_id)
    assert {row["horizon_days"]: row["status"] for row in stored} == {5: "completed", 20: "pending"}
    completed = next(row for row in stored if row["horizon_days"] == 5)
    assert completed["raw_return"] == pytest.approx(0.04)
    assert completed["benchmark_return"] == pytest.approx(0.03)
    assert completed["benchmark_symbol"] == "^KS11"
    assert completed["confirmation_rating"] == "Buy"

    # second pass: completed horizon is skipped, pending re-evaluated, errors become unavailable
    def failing(code, entry, horizon):
        raise RuntimeError("network")

    results = evaluate_harness_outcomes(repo, limit=10, as_of_date="2026-08-21", returns_fetcher=failing)
    assert [(r.horizon_days, r.status) for r in results] == [(5, "skipped"), (20, "unavailable")]
    summary = summarize_harness_outcome_results(results)
    assert summary["skipped_count"] == 1 and summary["unavailable_count"] == 1

    # no data yet on the entry day itself → pending, not unavailable
    repo2 = _repo()
    _seed(repo2)
    fresh = evaluate_harness_outcomes(repo2, limit=10, as_of_date="2026-08-01", returns_fetcher=lambda c, e, h: (None, None, None))
    assert [(r.horizon_days, r.status, r.error) for r in fresh] == [(5, "pending", "horizon_not_elapsed"), (20, "pending", "horizon_not_elapsed")]
    stale = evaluate_harness_outcomes(repo2, limit=10, as_of_date="2026-10-01", returns_fetcher=lambda c, e, h: (None, None, None))
    assert [r.status for r in stale] == ["unavailable", "unavailable"]
    with pytest.raises(ValueError):
        evaluate_harness_outcomes(repo, horizons=[0])


def test_summaries_and_payloads():
    repo = _repo()
    run_id, decision_id = _seed(repo)
    repo.upsert_harness_outcome(
        HarnessOutcomeInput(harness_decision_id=decision_id, harness_run_id=run_id, ticker_code="005930", entry_date=date(2026, 8, 1), evaluated_at=date(2026, 8, 20), horizon_days=5, actual_holding_days=5, raw_return=0.05, benchmark_return=0.01, alpha_return=0.04, status="completed")
    )
    repo.upsert_harness_outcome(
        HarnessOutcomeInput(harness_decision_id=decision_id, harness_run_id=run_id, ticker_code="005930", entry_date=date(2026, 8, 1), evaluated_at=date(2026, 8, 20), horizon_days=20, status="pending", error="insufficient_holding_days")
    )
    rows = repo.list_harness_outcomes()
    summary = summarize_stored_harness_outcomes(rows)
    assert summary["5"]["hit_rate"] == 1.0
    assert summary["5"]["average_alpha"] == pytest.approx(0.04)
    assert summary["20"]["pending"] == 1

    payload = build_harness_outcomes_payload(repo, ticker_code="005930")
    assert payload["item_count"] == 2
    assert payload["items"][0]["run_path"] == f"/harness/{run_id}"
    assert payload["summary"]["5"]["completed"] == 1
    assert build_harness_outcomes_payload(repo, status="completed")["item_count"] == 1
    with pytest.raises(ValueError):
        build_harness_outcomes_payload(repo, status="weird")

    run_payload = build_harness_run_payload(repo, harness_run_id=run_id)
    decision = run_payload["decisions"][0]
    assert [o["horizon_days"] for o in decision["outcomes"]] == [5, 20]
    assert run_payload["outcome_summary"]["5"]["hit_rate"] == 1.0


def test_private_run_outcomes_hidden_and_routes(monkeypatch):
    repo = _repo()
    run_id, decision_id = _seed(repo)
    repo.upsert_harness_outcome(
        HarnessOutcomeInput(harness_decision_id=decision_id, harness_run_id=run_id, ticker_code="005930", entry_date=date(2026, 8, 1), evaluated_at=date(2026, 8, 20), horizon_days=5, raw_return=0.05, alpha_return=0.04, benchmark_return=0.01, actual_holding_days=5, status="completed")
    )
    private_run, private_decision = _seed(repo, visibility="private")
    repo.upsert_harness_outcome(
        HarnessOutcomeInput(harness_decision_id=private_decision, harness_run_id=private_run, ticker_code="005930", entry_date=date(2026, 8, 1), evaluated_at=date(2026, 8, 20), horizon_days=5, status="pending")
    )
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/harness/outcomes")
    assert response.status_code == 200
    assert response.json()["item_count"] == 1
    assert client.get("/api/harness/outcomes", params={"status": "bogus"}).status_code == 422

    page = client.get(f"/harness/{run_id}")
    assert page.status_code == 200
    assert "사후 결과" in page.text
    assert "5D +5.0%" in page.text

    assert client.post("/api/admin/harness-outcomes/process", json={"dry_run": True}).status_code == 401
    dry = client.post("/api/admin/harness-outcomes/process", json={"dry_run": True}, headers={"Authorization": "Bearer secret"})
    assert dry.status_code == 200
    assert dry.json()["decision_count"] == 1

    monkeypatch.setattr("tradingagents.site.harness_outcome_worker.fetch_korean_returns", lambda code, entry, horizon: (0.03, 0.02, horizon))
    processed = client.get("/api/cron/process-harness-outcomes", headers={"Authorization": "Bearer secret"})
    assert processed.status_code == 200
    body = processed.json()
    assert body["summary"]["completed_count"] == 1  # 20D newly completed; 5D skipped
    assert body["summary"]["skipped_count"] == 1


def test_cli_process_harness_outcomes(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(app, ["process-harness-outcomes", "--help"])
    assert result.exit_code == 0
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = runner.invoke(app, ["process-harness-outcomes", "--dry-run"])
    assert result.exit_code != 0
    assert "DATABASE_URL is required" in result.output

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tradingagents.site.api_app import create_app
from tradingagents.site.harness_api import build_harness_run_payload, build_harness_runs_payload, run_harness_for_web
from tradingagents.site.harness_pages import render_harness_page
from tradingagents.storage import HarnessDecisionInput, HarnessRunInput, StorageRepository, create_storage_engine


def _repo():
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def _seed(repo, *, visibility="public"):
    run_id = repo.create_harness_run(
        HarnessRunInput(
            as_of_date=date(2026, 9, 5),
            confirmer="playbook",
            visibility=visibility,
            candidate_count=2,
            order_count=1,
            cash_before=Decimal("10000000"),
            cash_after=Decimal("10000000"),
            notes=["snapshot from pykrx"],
        )
    )
    repo.add_harness_decision(
        HarnessDecisionInput(
            harness_run_id=run_id,
            as_of_date=date(2026, 9, 5),
            ticker_code="005930",
            stage="ordered",
            screener_rank=1,
            composite_score=0.42,
            forecast_expected_return=0.03,
            forecast_probability_up=0.61,
            confirmation_rating="Buy",
            confirmation_confidence=0.8,
            confirmation_source="playbook",
            quantity=7,
            entry_price=Decimal("70000"),
            stop_price=Decimal("66500"),
            order_status="dry_run",
            reasons=["dry run, no fill"],
        )
    )
    repo.add_harness_decision(
        HarnessDecisionInput(
            harness_run_id=run_id,
            as_of_date=date(2026, 9, 5),
            ticker_code="000660",
            stage="forecast_rejected",
            screener_rank=2,
            reasons=["probability up 40% below 55%"],
        )
    )
    return run_id


def test_harness_payloads_from_repository():
    repo = _repo()
    run_id = _seed(repo)
    runs = build_harness_runs_payload(repo)
    assert runs["status"] == "available"
    assert runs["items"][0]["id"] == run_id
    assert runs["items"][0]["detail_path"] == f"/harness/{run_id}"

    detail = build_harness_run_payload(repo, harness_run_id=run_id)
    assert detail["run"]["confirmer"] == "playbook"
    assert detail["summary"] == {"decision_count": 2, "stage_counts": {"ordered": 1, "forecast_rejected": 1}, "ordered_count": 1, "exit_count": 0, "rejected_count": 1}
    assert detail["decisions"][0]["ticker_name"] == "삼성전자"
    assert detail["decisions"][0]["stage_label"] == "가상 주문"
    assert detail["execution_boundary"] == "dry_run_no_orders"
    assert build_harness_run_payload(repo)["run"]["id"] == run_id
    assert build_harness_runs_payload(None)["status"] == "not_configured"
    with pytest.raises(ValueError):
        build_harness_runs_payload(repo, limit=0)


def test_private_runs_are_hidden_from_public_payloads():
    repo = _repo()
    _seed(repo, visibility="private")
    assert build_harness_runs_payload(repo)["status"] == "empty"
    assert build_harness_run_payload(repo) is None


def test_api_app_serves_harness_routes_and_page():
    repo = _repo()
    run_id = _seed(repo)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/harness/runs")
    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("public")
    assert response.json()["item_count"] == 1

    assert client.get("/api/harness/runs/latest").json()["run"]["id"] == run_id
    assert client.get(f"/api/harness/runs/{run_id}").json()["summary"]["ordered_count"] == 1
    assert client.get("/api/harness/runs/00000000-0000-0000-0000-000000000009").status_code == 404
    assert client.get("/api/harness/tickers/005930").json()["item_count"] == 1
    assert client.get("/api/harness/tickers/AAPL").status_code == 400

    page = client.get("/harness")
    assert page.status_code == 200
    assert page.headers["cache-control"].startswith("public")
    assert "삼성전자" in page.text
    assert "가상 주문" in page.text
    assert "일일 하네스" in page.text
    assert client.get(f"/harness/{run_id}").status_code == 200
    assert client.get("/harness/00000000-0000-0000-0000-000000000009").status_code == 404


def test_render_harness_page_without_repo():
    html = render_harness_page(repo=None)
    assert "저장소 미연결" in html
    assert "tradingagents pipeline --persist" in html


def test_admin_harness_run_requires_token_and_dry_run(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    assert client.post("/api/admin/harness/run", json={}).status_code == 401
    response = client.post(
        "/api/admin/harness/run",
        json={"dry_run": False},
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 400
    assert "dry-run only" in response.json()["detail"]

    captured = {}

    def fake_run(repo_arg, **kwargs):
        captured.update(kwargs)
        return {"status": "processed", "run_id": "x"}

    monkeypatch.setattr("tradingagents.site.harness_api.run_harness_for_web", fake_run)
    response = client.post(
        "/api/admin/harness/run",
        json={"confirmer": "playbook", "confirm_top_n": 2, "markets": "KOSPI"},
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 200
    assert captured["confirmer"] == "playbook"
    assert captured["confirm_top_n"] == 2
    assert captured["markets"] == "KOSPI"

    monkeypatch.setenv("TRADINGAGENTS_HARNESS_CRON_CONFIRMER", "debate")
    response = client.get("/api/cron/run-harness", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    assert captured["confirmer"] == "debate"
    assert captured["confirm_top_n"] == 3


def test_run_harness_for_web_persists_dry_run(monkeypatch):
    from tradingagents.screener import MarketSnapshot, MarketSnapshotRow

    def _points(count=200, drift=0.004):
        rows = []
        close = 50_000.0
        for index in range(count):
            close *= 1 + drift
            rows.append({"date": f"d{index}", "close": round(close, 2), "volume": 1_000_000})
        return rows

    def fake_snapshot(when, markets):
        return MarketSnapshot(
            as_of_date="2026-09-05",
            markets=tuple(markets),
            rows=[MarketSnapshotRow("005930", "삼성전자", "KOSPI", 70_000.0, 1e7, 5e11, 4e14, 0.5, 12.0, 1.2, 2.0)],
        )

    monkeypatch.setattr("tradingagents.screener.screener.load_market_snapshot", fake_snapshot)
    monkeypatch.setattr("tradingagents.screener.screener._chart_history_fetcher", lambda code, s, e: _points())
    monkeypatch.setattr("tradingagents.harness.pipeline._chart_history_fetcher", lambda code, s, e: _points())
    monkeypatch.setenv("TRADINGAGENTS_AUDIT_LOG_PATH", "")

    repo = _repo()
    payload = run_harness_for_web(repo, confirmer="none", confirm_top_n=1, markets="KOSPI")
    assert payload["status"] == "processed"
    assert payload["dry_run"] is True
    assert payload["run_id"]
    assert payload["inspect_path"] == f"/api/harness/runs/{payload['run_id']}"
    assert repo.get_harness_run(payload["run_id"])["confirmer"] == "none"

    with pytest.raises(ValueError):
        run_harness_for_web(repo, confirmer="graph")

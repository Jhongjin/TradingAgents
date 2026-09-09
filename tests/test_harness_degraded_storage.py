from fastapi.testclient import TestClient
from sqlalchemy import text

from tradingagents.screener import MarketSnapshot, MarketSnapshotRow, ScreenerConfig, screen_korean_market
from tradingagents.site.api_app import create_app
from tradingagents.storage.repository import TEST_DATABASE_URL  # noqa: E402
from tradingagents.storage import StorageRepository, create_storage_engine


def _repo_without_harness_tables():
    repo = StorageRepository(create_storage_engine(TEST_DATABASE_URL))
    repo.create_schema()
    with repo.engine.begin() as conn:
        conn.execute(text("drop table harness_decisions"))
        conn.execute(text("drop table harness_runs"))
    return repo


def test_harness_routes_degrade_when_tables_missing():
    client = TestClient(create_app(repo=_repo_without_harness_tables(), load_repo_from_env=False))

    runs = client.get("/api/harness/runs")
    assert runs.status_code == 200
    assert runs.json()["status"] == "not_migrated"
    assert "202609080001" in runs.json()["error"]

    latest = client.get("/api/harness/runs/latest")
    assert latest.status_code == 200
    assert latest.json()["status"] == "not_migrated"

    page = client.get("/harness")
    assert page.status_code == 200
    assert "마이그레이션 필요" in page.text


def _points(count=200, drift=0.004):
    rows = []
    close = 50_000.0
    for index in range(count):
        close *= 1 + drift
        rows.append({"date": f"2026-{(index // 28) % 12 + 1:02d}-{index % 28 + 1:02d}", "close": round(close, 2), "volume": 1_000_000})
    return rows


def test_screener_fallback_mode_skips_whole_market_and_honours_time_budget(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_SCREENER_UNIVERSE", "005930,000660,035420")
    calls = []

    def loader(when, markets):
        raise AssertionError("whole-market loader must not be called in fallback mode")

    def fetcher(code, start, end):
        calls.append(code)
        return _points()

    result = screen_korean_market(
        "2026-09-05",
        config=ScreenerConfig(top_n=5, snapshot_mode="fallback"),
        snapshot_loader=loader,
        history_fetcher=fetcher,
    )
    assert len(result.candidates) == 3
    assert len(calls) == 3  # history fetched once per ticker, reused for scoring
    assert any("snapshot_mode=fallback" in note for note in result.notes)

    monkeypatch.setenv("TRADINGAGENTS_SCREENER_SNAPSHOT_MODE", "fallback")
    result = screen_korean_market("2026-09-05", config=ScreenerConfig(top_n=5), snapshot_loader=loader, history_fetcher=fetcher)
    assert len(result.candidates) == 3

    import time

    slow_calls = []

    def slow_fetcher(code, start, end):
        slow_calls.append(code)
        time.sleep(0.05)
        return _points()

    snapshot = MarketSnapshot(
        as_of_date="2026-09-05",
        markets=("KOSPI",),
        rows=[MarketSnapshotRow(f"00{i:04d}", f"T{i}", "KOSPI", 50_000.0, 1e7, 5e11, 4e14, 0.5, 12.0, 1.2, 2.0) for i in range(10)],
    )
    # Sequential fetching (max_workers=1) stops at the deadline; with the default
    # thread pool the same ten rows finish inside the budget, so pin one worker here.
    result = screen_korean_market(
        snapshot=snapshot,
        history_fetcher=slow_fetcher,
        config=ScreenerConfig(top_n=10, time_budget_seconds=0.12, max_workers=1),
    )
    assert 0 < len(slow_calls) < 10
    assert any("time budget" in note for note in result.notes)

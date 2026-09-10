"""The harness paper account: replayed fills, holdings, exits, and its page."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from tradingagents.harness.paper_state import build_paper_account_payload, replay_fills, restore_paper_account
from tradingagents.site import create_app
from tradingagents.storage import HarnessDecisionInput, HarnessRunInput, StorageRepository, create_storage_engine


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _run(repo: StorageRepository, *, when: date, dry_run: bool) -> str:
    return repo.create_harness_run(
        HarnessRunInput(as_of_date=when, confirmer="debate", visibility="public", dry_run=dry_run, candidate_count=1, order_count=1)
    )


def _fill(repo: StorageRepository, run_id: str, *, when: date, code: str, stage: str, price: float, quantity: int, name: str = "", reasons=("paper fill",)) -> None:
    repo.add_harness_decision(
        HarnessDecisionInput(
            harness_run_id=run_id,
            as_of_date=when,
            ticker_code=code,
            ticker_name=name or code,
            stage=stage,
            quantity=quantity,
            entry_price=Decimal(str(price)) if stage == "ordered" else None,
            stop_price=Decimal(str(round(price * 0.95, 2))) if stage == "ordered" else None,
            take_profit_price=Decimal(str(round(price * 1.10, 2))) if stage == "ordered" else None,
            order_status="filled",
            reasons=list(reasons),
            detail={"order": {"status": "filled", "fill": {"price": price, "quantity": quantity}}},
        )
    )


def _seed_account(repo: StorageRepository) -> None:
    run_one = _run(repo, when=date(2026, 9, 9), dry_run=False)
    _fill(repo, run_one, when=date(2026, 9, 9), code="010950", stage="ordered", price=165900, quantity=12, name="S-Oil")
    _fill(repo, run_one, when=date(2026, 9, 9), code="096770", stage="ordered", price=153500, quantity=13, name="SK이노베이션")
    run_two = _run(repo, when=date(2026, 9, 21), dry_run=False)
    _fill(repo, run_two, when=date(2026, 9, 21), code="010950", stage="exit", price=182600, quantity=12, reasons=("take_profit", "paper fill"))


def test_dry_runs_never_move_the_account():
    repo = _repo()
    dry = _run(repo, when=date(2026, 9, 8), dry_run=True)
    repo.add_harness_decision(
        HarnessDecisionInput(
            harness_run_id=dry,
            as_of_date=date(2026, 9, 8),
            ticker_code="005930",
            stage="ordered",
            quantity=10,
            entry_price=Decimal("70000"),
            order_status="dry_run",
            reasons=["dry run, no fill"],
        )
    )
    assert repo.list_harness_fills() == []
    payload = build_paper_account_payload(repo)
    assert payload["status"] == "empty" and payload["summary"]["cash"] == 10_000_000.0


def test_account_replays_fills_into_holdings_and_closed_trades():
    repo = _repo()
    _seed_account(repo)

    payload = build_paper_account_payload(repo, current_prices={"096770": 160000})
    summary = payload["summary"]
    assert summary["open_count"] == 1 and summary["closed_count"] == 1
    assert summary["win_count"] == 1 and summary["hit_rate"] == 1.0

    held = payload["positions"][0]
    assert held["ticker_code"] == "096770" and held["quantity"] == 13
    assert held["average_price"] == 153500.0 and held["current_price"] == 160000.0
    assert held["target_price"] == 168850.0 and held["stop_price"] == 145825.0
    assert held["unrealized_pnl"] == 84500.0

    closed = payload["closed"][0]
    assert closed["ticker_code"] == "010950" and closed["exit_reason"] == "take_profit"
    assert closed["entry_price"] == 165900.0 and closed["exit_price"] == 182600.0
    assert closed["realized_pnl"] > 0 and 0.09 < closed["realized_return"] < 0.10

    # the page's numbers must be the broker's numbers, tax included
    broker, _notes = replay_fills(repo.list_harness_fills(), initial_cash=10_000_000)
    assert round(broker.portfolio.cash, 2) == summary["cash"]
    assert summary["equity"] == round(summary["cash"] + summary["holdings_value"], 2)


def test_restored_broker_carries_holdings_into_the_next_run():
    repo = _repo()
    _seed_account(repo)
    adapter, notes = restore_paper_account(repo, initial_cash=10_000_000)
    assert adapter is not None and notes and "restored paper account" in notes[0]
    snapshot = adapter.account_snapshot({"096770": 160000.0})
    assert set(snapshot.positions) == {"096770"}
    assert snapshot.positions["096770"]["quantity"] == 13
    assert snapshot.cash < 10_000_000  # cash was spent on the entries


def test_a_sell_without_a_holding_is_skipped_not_shorted():
    repo = _repo()
    run_id = _run(repo, when=date(2026, 9, 9), dry_run=False)
    _fill(repo, run_id, when=date(2026, 9, 9), code="005930", stage="exit", price=70000, quantity=5)
    broker, notes = replay_fills(repo.list_harness_fills(), initial_cash=1_000_000)
    assert broker.portfolio.positions == {} and broker.portfolio.cash == 1_000_000
    assert any("no recorded holding" in note for note in notes)


def test_paper_account_page_and_api():
    repo = _repo()
    _seed_account(repo)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    api = client.get("/api/paper-account")
    assert api.status_code == 200 and api.json()["summary"]["open_count"] == 1

    page = client.get("/paper")
    assert page.status_code == 200
    html = page.text
    assert "AI 모의 계좌" in html
    assert "SK이노베이션" in html and "S-Oil" in html
    assert "목표가 도달" in html  # the exit reason, in Korean
    assert "153,500" in html and "168,850" in html
    assert "/api/prices/latest" in html  # current prices arrive client-side


def test_paper_account_is_linked_and_indexed():
    from tradingagents.site.design_system import NAV_ITEMS
    from tradingagents.site.seo import build_sitemap_xml

    assert ("/paper", "모의 계좌") in NAV_ITEMS
    assert "https://agenttrust.kr/paper" in build_sitemap_xml(site_base_url="https://agenttrust.kr")

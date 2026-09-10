"""The harness paper account: replayed fills, holdings, exits, and its page."""

from datetime import date, datetime, timedelta, timezone
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


def _seed_account(repo: StorageRepository) -> tuple[date, date]:
    """Two entries and one exit, all on days that have already settled."""

    from tradingagents.site.billing import KST

    today = datetime.now(KST).date()
    entered = today - timedelta(days=30)
    exited = today - timedelta(days=10)
    run_one = _run(repo, when=entered, dry_run=False)
    _fill(repo, run_one, when=entered, code="010950", stage="ordered", price=165900, quantity=12, name="S-Oil")
    _fill(repo, run_one, when=entered, code="096770", stage="ordered", price=153500, quantity=13, name="SK이노베이션")
    run_two = _run(repo, when=exited, dry_run=False)
    _fill(repo, run_two, when=exited, code="010950", stage="exit", price=182600, quantity=12, reasons=("take_profit", "paper fill"))
    return entered, exited


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


def _seed_today(repo: StorageRepository, today: date) -> None:
    """One settled position plus an entry and an exit dated today."""

    old_run = _run(repo, when=date(2026, 9, 9), dry_run=False)
    _fill(repo, old_run, when=date(2026, 9, 9), code="010950", stage="ordered", price=165900, quantity=12, name="S-Oil")
    _fill(repo, old_run, when=date(2026, 9, 9), code="096770", stage="ordered", price=153500, quantity=13, name="SK이노베이션")
    today_run = _run(repo, when=today, dry_run=False)
    _fill(repo, today_run, when=today, code="131290", stage="ordered", price=308000, quantity=4, name="티에스이")
    _fill(repo, today_run, when=today, code="010950", stage="exit", price=182600, quantity=12, reasons=("take_profit", "paper fill"))


def test_free_visitors_see_the_settled_record_but_not_todays_moves():
    from datetime import datetime

    from tradingagents.site.billing import KST, gate_paper_account_payload, resolve_plan_access

    today = datetime.now(KST).date()
    repo = _repo()
    _seed_today(repo, today)
    raw = build_paper_account_payload(repo)
    assert len(raw["positions"]) == 2 and len(raw["closed"]) == 1

    free = gate_paper_account_payload(raw, resolve_plan_access(None, None))
    codes = {item["ticker_code"] for item in free["positions"]}
    assert codes == {"096770"}  # yesterday's entry stays visible
    assert "131290" not in codes  # today's entry is withheld
    assert free["closed"] == []  # today's exit is withheld too
    gate = free["plan_gate"]
    assert gate["locked"] is True
    assert gate["locked_position_count"] == 1 and gate["locked_closed_count"] == 1
    # totals stay public: they prove the record without naming today's picks
    assert free["summary"] == raw["summary"]


def test_paid_members_see_todays_moves():
    from datetime import datetime, timedelta, timezone

    from tradingagents.site.billing import KST, gate_paper_account_payload, resolve_plan_access
    from tradingagents.storage import SubscriptionInput

    user = "11111111-1111-4111-8111-111111111111"
    today = datetime.now(KST).date()
    repo = _repo()
    _seed_today(repo, today)
    repo.upsert_subscription(
        SubscriptionInput(user_id=user, plan="daily", status="active", current_period_end=datetime.now(timezone.utc) + timedelta(days=20))
    )
    paid = gate_paper_account_payload(build_paper_account_payload(repo), resolve_plan_access(repo, user))
    assert {item["ticker_code"] for item in paid["positions"]} == {"096770", "131290"}
    assert len(paid["closed"]) == 1
    assert paid["plan_gate"]["locked"] is False


def test_paper_account_api_and_page_hide_todays_rows_from_anonymous_callers(monkeypatch):
    from datetime import datetime

    from tradingagents.site.billing import KST

    today = datetime.now(KST).date()
    repo = _repo()
    _seed_today(repo, today)
    monkeypatch.setenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "true")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    anonymous = client.get("/api/paper-account").json()
    assert {item["ticker_code"] for item in anonymous["positions"]} == {"096770"}
    assert anonymous["plan_gate"]["locked"] is True

    html = client.get("/paper").text
    assert "티에스이" not in html and "131290" not in html
    assert "SK이노베이션" in html
    assert "오늘 편입 1종목" in html and "오늘 청산 1건" in html
    assert "/pricing" in html


def _record_days(repo: StorageRepository, rows: list[tuple[int, float, float]]) -> None:
    """rows: (days_ago, held price, benchmark close), oldest first."""

    from tradingagents.site.paper_snapshot_worker import record_paper_account_snapshot

    today = datetime.now(timezone.utc).date()
    for days_ago, price, benchmark in rows:
        record_paper_account_snapshot(
            repo,
            as_of=(today - timedelta(days=days_ago)).isoformat(),
            price_loader=lambda _codes, value=price: {"096770": value},
            benchmark_loader=lambda _when, value=benchmark: value,
        )


def test_each_day_is_recorded_once_and_rerunning_overwrites_it():
    from tradingagents.site.paper_snapshot_worker import build_paper_curve_payload

    repo = _repo()
    _seed_account(repo)
    _record_days(repo, [(2, 153500, 2700.0), (1, 157500, 2727.0), (0, 161500, 2673.0)])
    _record_days(repo, [(0, 161500, 2673.0)])  # the same day again

    curve = build_paper_curve_payload(repo)
    assert curve["status"] == "available"
    assert len(curve["points"]) == 3
    assert [point["date"] for point in curve["points"]] == sorted(point["date"] for point in curve["points"])


def test_curve_measures_the_account_against_kospi_from_the_first_recorded_day():
    from tradingagents.site.paper_snapshot_worker import build_paper_curve_payload

    repo = _repo()
    _seed_account(repo)
    _record_days(repo, [(2, 153500, 2700.0), (1, 157500, 2727.0), (0, 161500, 2673.0)])

    summary = build_paper_curve_payload(repo)["summary"]
    assert summary["day_count"] == 3 and summary["benchmark_name"] == "KOSPI"
    assert summary["benchmark_return"] == round((2673.0 / 2700.0) - 1, 6)  # anchored to day one
    assert summary["account_return"] > 0  # the held position rose over the window
    assert summary["excess_return"] == round(summary["account_return"] - summary["benchmark_return"], 6)
    assert summary["max_drawdown"] <= 0


def test_a_missing_benchmark_still_records_the_day():
    from tradingagents.site.paper_snapshot_worker import record_paper_account_snapshot

    repo = _repo()
    _seed_account(repo)

    def _explode(_when):
        raise RuntimeError("krx blocked")

    result = record_paper_account_snapshot(repo, price_loader=lambda _codes: {}, benchmark_loader=_explode)
    assert result["status"] == "recorded" and result["benchmark_close"] is None
    assert any("benchmark unavailable" in note for note in result["notes"])
    assert len(repo.list_paper_account_snapshots()) == 1


def test_curve_is_public_and_reaches_the_page():
    repo = _repo()
    _seed_account(repo)
    _record_days(repo, [(2, 153500, 2700.0), (1, 157500, 2727.0), (0, 161500, 2673.0)])
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    curve = client.get("/api/paper-account/curve").json()
    assert curve["status"] == "available" and len(curve["points"]) == 3

    html = client.get("/paper").text
    assert "수익률 추이" in html and "polyline" in html
    assert "지수 대비" in html and "최대 낙폭" in html


def test_snapshot_cron_needs_the_worker_token(monkeypatch):
    repo = _repo()
    _seed_account(repo)
    monkeypatch.setenv("OPERATOR_ACCESS_CODE", "op-token")
    monkeypatch.setattr(
        "tradingagents.site.paper_snapshot_worker._default_price_loader", lambda tickers: {}
    )
    monkeypatch.setattr(
        "tradingagents.site.paper_snapshot_worker._default_benchmark_loader", lambda on_date: 2700.0
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    assert client.get("/api/cron/record-paper-snapshot").status_code == 401
    body = client.get("/api/cron/record-paper-snapshot", headers={"X-TradingAgents-Worker-Token": "op-token"}).json()
    assert body["status"] == "recorded" and body["benchmark_close"] == 2700.0


def test_one_day_of_picks_can_no_longer_take_the_whole_account():
    """Sizing keeps a slot per position and a cash reserve, so later picks still fit."""

    from tradingagents.execution import TradingMandate
    from tradingagents.harness.pipeline import PipelineConfig

    config = PipelineConfig(mandate=TradingMandate(max_positions=10))
    slot_weight = 1.0 / config.mandate.max_positions
    weight_cap = min(config.max_position_weight, config.mandate.max_position_weight, slot_weight)
    assert weight_cap == 0.1  # was 0.2, which let four names fill the account
    assert config.min_cash_reserve_pct == 0.10

    equity = 10_000_000.0
    spendable = equity - equity * config.min_cash_reserve_pct
    # ten slots at the capped weight fit inside the spendable balance
    assert config.mandate.max_positions * (equity * weight_cap) >= spendable

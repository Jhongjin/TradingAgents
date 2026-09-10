"""The harness paper account: replayed fills, holdings, exits, and its page."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from tradingagents.harness.paper_state import (
    build_paper_account_payload,
    default_initial_cash,
    replay_fills,
    restore_paper_account,
)
from tradingagents.site import create_app
from tradingagents.storage import HarnessDecisionInput, HarnessRunInput, StorageRepository, create_storage_engine


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _run(repo: StorageRepository, *, when: date, dry_run: bool) -> str:
    return repo.create_harness_run(
        HarnessRunInput(as_of_date=when, confirmer="debate", visibility="public", dry_run=dry_run, broker="paper", candidate_count=1, order_count=1)
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
    assert payload["status"] == "empty" and payload["summary"]["cash"] == default_initial_cash()


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
    broker, _notes = replay_fills(repo.list_harness_fills(), initial_cash=default_initial_cash())
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
    assert body["status"] == "recorded"
    # one row per account, so both books get an equity curve
    assert set(body["accounts"]) == {"paper", "kis"}
    assert body["accounts"]["paper"]["benchmark_close"] == 2700.0


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


def test_rules_card_reports_current_rules_and_when_they_changed():
    from tradingagents.site.paper_rules import build_rules_payload

    runs = [
        {"as_of_date": "2026-09-11", "metadata": {"config": {"stop_loss_pct": 0.05, "take_profit_pct": 0.10, "max_position_weight": 0.1, "min_cash_reserve_pct": 0.1}}},
        {"as_of_date": "2026-09-09", "metadata": {"config": {"stop_loss_pct": 0.05, "take_profit_pct": 0.10, "max_position_weight": 0.2}}},
    ]
    payload = build_rules_payload(runs)
    assert payload["status"] == "available" and payload["as_of"] == "2026-09-11"
    values = {item["label"]: item["value"] for item in payload["current"]}
    assert values["손절가"] == "5%" and values["종목당 비중 상한"] == "10%"
    change = payload["changes"][0]
    assert change["label"] == "종목당 비중 상한" and change["before"] == "20%" and change["after"] == "10%"
    assert build_rules_payload([])["status"] == "empty"


def test_copying_holdings_writes_a_journal_the_member_could_have_typed(monkeypatch):
    user = "11111111-1111-4111-8111-111111111111"
    repo = _repo()
    _seed_account(repo)
    monkeypatch.setenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "true")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))
    headers = {"X-TradingAgents-User-Id": user}

    first = client.post("/api/member/paper-account/copy", headers=headers).json()
    assert first["status"] == "copied" and first["copied"] == 1 and first["portfolio_name"] == "AI 모의 계좌 따라하기"

    trades = repo.manual_trades_for_portfolio(first["portfolio_id"])
    assert [trade["ticker_code"] for trade in trades] == ["096770"]
    assert float(trades[0]["price"]) == 153500.0 and int(trades[0]["quantity"]) == 13

    targets = repo.price_targets_for_portfolio(first["portfolio_id"])
    assert float(targets[0]["target_price"]) == 168850.0 and float(targets[0]["stop_price"]) == 145825.0

    again = client.post("/api/member/paper-account/copy", headers=headers).json()
    assert again["copied"] == 0 and again["skipped"] == 1  # no duplicates


def test_the_daily_message_carries_the_account_record_for_free_members():
    from tradingagents.site.notifications import account_line, compose_issue_messages

    account = {"summary": {"account_return": 0.0321, "benchmark_return": -0.0102, "benchmark_name": "KOSPI", "day_count": 12}}
    line = account_line(account, base="https://agenttrust.kr")
    assert "모의 계좌 누적 +3.21%" in line and "KOSPI -1.02%" in line and "12일 기록" in line
    assert "https://agenttrust.kr/paper" in line

    run_payload = {"run": {"id": "abc", "as_of_date": "2026-09-10"}, "decisions": []}
    messages = compose_issue_messages(run_payload, issue_number=3, site_base_url="https://agenttrust.kr", account=account)
    assert "모의 계좌 누적 +3.21%" in messages["free"]
    assert "모의 계좌 누적 +3.21%" in messages["paid"]
    assert account_line(None) == ""


def test_the_kis_account_and_the_local_paper_account_stay_separate():
    """Both brokers write here; replaying them together would invent holdings."""

    repo = _repo()
    today = datetime.now(timezone.utc).date()
    paper_run = repo.create_harness_run(
        HarnessRunInput(as_of_date=today - timedelta(days=5), confirmer="debate", visibility="public", dry_run=False, broker="paper", candidate_count=1, order_count=1)
    )
    _fill(repo, paper_run, when=today - timedelta(days=5), code="096770", stage="ordered", price=153500, quantity=13, name="SK이노베이션")
    kis_run = repo.create_harness_run(
        HarnessRunInput(as_of_date=today - timedelta(days=5), confirmer="debate", visibility="public", dry_run=False, broker="kis", candidate_count=1, order_count=1)
    )
    _fill(repo, kis_run, when=today - timedelta(days=5), code="000660", stage="ordered", price=1852000, quantity=3, name="SK하이닉스")

    paper = build_paper_account_payload(repo)
    assert {item["ticker_code"] for item in paper["positions"]} == {"096770"}

    kis = build_paper_account_payload(repo, broker="kis")
    assert {item["ticker_code"] for item in kis["positions"]} == {"000660"}

    both = build_paper_account_payload(repo, broker=None)
    assert {item["ticker_code"] for item in both["positions"]} == {"096770", "000660"}


def _kis_order(repo: StorageRepository, *, when: date, code: str, name: str, price: float, quantity: int, order_id: str) -> str:
    run = repo.create_harness_run(
        HarnessRunInput(as_of_date=when, confirmer="debate", visibility="public", dry_run=False, broker="kis", candidate_count=1, order_count=1)
    )
    return repo.add_harness_decision(
        HarnessDecisionInput(
            harness_run_id=run,
            as_of_date=when,
            ticker_code=code,
            ticker_name=name,
            stage="ordered",
            quantity=quantity,
            entry_price=Decimal(str(price)),
            order_status="accepted",
            reasons=["order accepted"],
            detail={"order": {"status": "accepted", "order_id": order_id, "order": {"side": "buy", "quantity": quantity}, "fill": {"price": price, "quantity": quantity}}},
        )
    )


class _FakeKIS:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def daily_orders(self, *, start_date=None, end_date=None, code=None):
        self.calls += 1
        return self.rows


def test_kis_orders_are_replaced_by_the_fill_the_broker_recorded():
    from tradingagents.site.kis_reconcile import reconcile_kis_fills

    repo = _repo()
    today = datetime.now(timezone.utc).date()
    _kis_order(repo, when=today, code="000660", name="SK하이닉스", price=1852000, quantity=3, order_id="0001")
    _kis_order(repo, when=today, code="096770", name="SK이노베이션", price=155200, quantity=8, order_id="0002")
    client = _FakeKIS([
        {"order_id": "0001", "code": "000660", "side": "buy", "ordered_quantity": 3, "filled_quantity": 3, "average_fill_price": 1849500.0, "cancelled": False, "status": "filled"},
        {"order_id": "0002", "code": "096770", "side": "buy", "ordered_quantity": 8, "filled_quantity": 0, "average_fill_price": None, "cancelled": True, "status": "open"},
    ])

    result = reconcile_kis_fills(repo, client)
    assert result["status"] == "reconciled"
    assert result["reconciled"] == 1 and result["unfilled"] == 1 and result["unmatched"] == 0

    fills = repo.list_harness_fills(broker="kis")
    assert [row["ticker_code"] for row in fills] == ["000660"]  # the cancelled order dropped out
    assert fills[0]["detail_json"]["order"]["fill"]["price"] == 1849500.0  # not the 1,852,000 limit

    assert reconcile_kis_fills(repo, client)["status"] == "nothing_to_reconcile"


def test_reconciliation_leaves_rows_alone_when_the_broker_reports_nothing():
    from tradingagents.site.kis_reconcile import reconcile_kis_fills

    repo = _repo()
    today = datetime.now(timezone.utc).date()
    decision_id = _kis_order(repo, when=today, code="000660", name="SK하이닉스", price=1852000, quantity=3, order_id="0001")

    result = reconcile_kis_fills(repo, _FakeKIS([]))
    assert result["status"] == "no_broker_rows" and result["pending"] == 1
    rows = repo.list_harness_fills(broker="kis")
    assert rows[0]["id"] == decision_id and rows[0]["order_status"] == "accepted"


def test_the_combined_account_sums_two_books_without_mixing_their_cash():
    from tradingagents.harness.paper_state import build_combined_account_payload, default_initial_cash

    repo = _repo()
    _seed_account(repo)  # the local paper book
    today = datetime.now(timezone.utc).date()
    kis_run = repo.create_harness_run(
        HarnessRunInput(as_of_date=today - timedelta(days=6), confirmer="debate", visibility="public", dry_run=False, broker="kis", candidate_count=1, order_count=1)
    )
    _fill(repo, kis_run, when=today - timedelta(days=6), code="000660", stage="ordered", price=1852000, quantity=3, name="SK하이닉스")

    combined = build_combined_account_payload(repo)
    sources = {item["ticker_code"]: item["account"] for item in combined["positions"]}
    assert sources == {"096770": "paper", "000660": "kis"}
    assert {item["account_label"] for item in combined["positions"]} == {"자체 모의", "KIS 모의투자"}

    summary = combined["summary"]
    assert summary["initial_cash"] == default_initial_cash("paper") + default_initial_cash("kis")
    books = {book["key"]: book["summary"] for book in combined["accounts"]}
    assert round(books["paper"]["cash"] + books["kis"]["cash"], 2) == summary["cash"]
    # neither book paid for the other's shares
    assert books["kis"]["cash"] < default_initial_cash("kis")
    assert books["paper"]["cash"] < default_initial_cash("paper")
    assert books["kis"]["open_count"] == 1 and books["paper"]["open_count"] == 1


def test_the_page_shows_both_books_and_labels_every_row():
    repo = _repo()
    _seed_account(repo)
    today = datetime.now(timezone.utc).date()
    kis_run = repo.create_harness_run(
        HarnessRunInput(as_of_date=today - timedelta(days=6), confirmer="debate", visibility="public", dry_run=False, broker="kis", candidate_count=1, order_count=1)
    )
    _fill(repo, kis_run, when=today - timedelta(days=6), code="000660", stage="ordered", price=1852000, quantity=3, name="SK하이닉스")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    html = client.get("/paper").text
    assert "계좌별 성적" in html
    assert "KIS 모의투자" in html and "자체 모의" in html
    assert "SK하이닉스" in html and "SK이노베이션" in html

    api = client.get("/api/paper-account").json()
    assert {book["key"] for book in api["accounts"]} == {"paper", "kis"}


def test_every_row_says_why_it_was_bought():
    repo = _repo()
    today = datetime.now(timezone.utc).date()
    run = repo.create_harness_run(
        HarnessRunInput(as_of_date=today - timedelta(days=8), confirmer="debate", visibility="public", dry_run=False, broker="paper", candidate_count=1, order_count=1)
    )
    repo.add_harness_decision(
        HarnessDecisionInput(
            harness_run_id=run,
            as_of_date=today - timedelta(days=8),
            ticker_code="096770",
            ticker_name="SK이노베이션",
            stage="ordered",
            quantity=13,
            entry_price=Decimal("153500"),
            stop_price=Decimal("145825"),
            take_profit_price=Decimal("168850"),
            confirmation_rating="Buy",
            confirmation_confidence=0.72,
            order_status="filled",
            reasons=["paper fill"],
            detail={
                "order": {"status": "filled", "fill": {"price": 153500.0, "quantity": 13}},
                "confirmation": {"rating": "Buy", "confidence": 0.72, "rationale": "정제 마진 반등과 거래대금 증가가 겹쳤습니다."},
            },
        )
    )

    position = build_paper_account_payload(repo)["positions"][0]
    assert position["decision_rating"] == "Buy" and position["decision_confidence"] == 0.72
    assert "정제 마진 반등" in position["entry_reason"]

    html = TestClient(create_app(repo=repo, load_repo_from_env=False)).get("/paper").text
    assert "담은 이유" in html and "정제 마진 반등" in html
    assert "비중 확대" in html or "매수" in html  # the rating, in Korean


def test_the_account_pays_a_brokerage_fee():
    from tradingagents.harness.paper_state import default_commission_rate

    repo = _repo()
    _seed_account(repo)
    assert default_commission_rate() > 0

    broker, _notes = replay_fills(repo.list_harness_fills(), initial_cash=10_000_000, commission_rate=0.0)
    free_cash = broker.portfolio.cash
    charged, _notes = replay_fills(repo.list_harness_fills(), initial_cash=10_000_000, commission_rate=0.001)
    assert charged.portfolio.cash < free_cash  # the fee actually leaves the account


def test_an_exits_only_pass_buys_nothing_and_skips_the_screener():
    from tradingagents.harness.pipeline import PipelineConfig, run_daily_pipeline

    calls = {"screener": 0}

    def _runner(when, config):  # pragma: no cover - must not be reached
        calls["screener"] += 1
        raise AssertionError("the screener must not run on an exits-only pass")

    result = run_daily_pipeline(
        "2026-09-10",
        config=PipelineConfig(exits_only=True, require_llm_confirmation=True),
        confirmer=None,
    )
    assert calls["screener"] == 0
    assert result.as_of_date == "2026-09-10"
    assert [decision for decision in result.decisions if decision.stage == "ordered"] == []
    assert any("exits-only" in note for note in result.notes)


def test_the_record_publishes_its_own_hash_chain():
    from tradingagents.site.audit_trail import build_audit_payload

    payload = build_audit_payload([
        {"id": "run-1", "as_of_date": "2026-09-10", "broker": "paper", "audit_sequence_start": 10, "audit_sequence_end": 42, "metadata": {"audit_head_hash": "a" * 64}},
        {"id": "run-0", "as_of_date": "2026-09-09", "broker": "paper", "audit_sequence_start": 1, "audit_sequence_end": 9, "metadata": {}},
    ])
    assert payload["summary"]["run_count"] == 2 and payload["summary"]["hashed_count"] == 1
    newest = payload["entries"][0]
    assert newest["as_of_date"] == "2026-09-10" and newest["step_count"] == 33
    assert newest["head_short"].startswith("aaaaaaaaaaaa") and newest["detail_path"] == "/harness/run-1"
    assert build_audit_payload([])["status"] == "empty"


def test_the_account_page_shows_the_chain_when_runs_carry_it():
    repo = _repo()
    today = datetime.now(timezone.utc).date()
    run_id = repo.create_harness_run(
        HarnessRunInput(
            as_of_date=today - timedelta(days=3),
            confirmer="debate",
            visibility="public",
            dry_run=False,
            broker="paper",
            candidate_count=1,
            order_count=1,
            audit_sequence_start=1,
            audit_sequence_end=20,
            metadata={"audit_head_hash": "b" * 64, "config": {"stop_loss_pct": 0.05, "take_profit_pct": 0.1, "commission_rate": 0.00015}},
        )
    )
    _fill(repo, run_id, when=today - timedelta(days=3), code="096770", stage="ordered", price=153500, quantity=13, name="SK이노베이션")

    html = TestClient(create_app(repo=repo, load_repo_from_env=False)).get("/paper").text
    assert "기록 검증" in html and "bbbbbbbbbbbb" in html
    assert "매매 수수료" in html and "0.015%" in html  # the fee is published as a rule


def test_intraday_exit_passes_are_scheduled_and_never_buy():
    from pathlib import Path

    workflow = Path(".github/workflows/harness-intraday-exits.yml").read_text(encoding="utf-8")
    assert "--exits-only" in workflow and "--execute" in workflow
    assert "--broker kis" not in workflow  # the local paper book only
    assert workflow.count('cron: "20') == 3

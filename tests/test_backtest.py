"""The rule backtest: same rules, past prices, kept apart from the record."""

import random
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from tradingagents.harness.backtest import BacktestConfig, run_rule_backtest
from tradingagents.site import create_app
from tradingagents.storage import StorageRepository, create_storage_engine


def _series(drift: float, *, seed: int, days: int = 400, start: date = date(2026, 1, 1),
            noise: float = 0.015) -> list[dict]:
    """A synthetic price path. ``noise`` is the daily swing, so it is volatility.

    It is a parameter because every name used to get the same one, which made
    the twenty names in the variability-filter test statistically identical —
    the filter had nothing to tell them apart and the test passed on the
    incidental ordering of a set.
    """

    rng = random.Random(seed)
    points = []
    price = 10_000.0
    day = start
    for step in range(days):
        day += timedelta(days=1)
        if day.weekday() >= 5:
            continue
        price *= 1 + drift + rng.uniform(-noise, noise)
        points.append({"date": day.isoformat(), "close": round(price, 1), "volume": 100_000 + step})
    return points


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


HISTORY = {
    "000001": _series(0.004, seed=1),
    "000002": _series(-0.003, seed=2),
    "000003": _series(0.002, seed=3),
    "000004": _series(0.000, seed=4),
}
NAMES = {"000001": "오름", "000002": "내림", "000003": "완만", "000004": "횡보"}


def test_the_replay_produces_a_curve_trades_and_metrics():
    result = run_rule_backtest(
        history=HISTORY,
        names=NAMES,
        start=date(2026, 7, 1),
        end=date(2027, 2, 1),
        config=BacktestConfig(top_n=2, max_positions=3, initial_cash=10_000_000.0),
    )
    assert result.universe_size == 4
    assert len(result.equity_curve) > 100
    assert result.metrics["trade_count"] > 0
    for key in ("total_return", "max_drawdown", "sharpe_ratio", "hit_rate", "average_holding_days"):
        assert key in result.metrics
    first, last = result.equity_curve[0], result.equity_curve[-1]
    assert first["date"] == result.start_date and last["date"] == result.end_date
    assert first["equity"] == pytest.approx(first["cash"] + first["holdings_value"], rel=1e-9)


def test_every_exit_names_a_rule():
    result = run_rule_backtest(history=HISTORY, names=NAMES, start=date(2026, 7, 1), end=date(2027, 2, 1), config=BacktestConfig(top_n=2))
    assert result.trades
    assert {trade["exit_reason"] for trade in result.trades} <= {"stop_loss", "take_profit", "max_holding_days"}
    for trade in result.trades:
        assert trade["entry_date"] <= trade["exit_date"]
        assert trade["quantity"] > 0 and trade["holding_days"] >= 0


def test_the_caps_hold_through_the_whole_run():
    result = run_rule_backtest(
        history=HISTORY,
        names=NAMES,
        start=date(2026, 7, 1),
        end=date(2027, 2, 1),
        config=BacktestConfig(top_n=4, max_positions=4, max_positions_per_sector=2),
        sector_lookup=lambda code: "테스트",
    )
    assert max(point["position_count"] for point in result.equity_curve) <= 2  # the sector cap binds first
    assert all(point["cash"] >= -1e-6 for point in result.equity_curve)


def test_fees_make_a_difference():
    free = run_rule_backtest(history=HISTORY, names=NAMES, start=date(2026, 7, 1), end=date(2027, 2, 1), config=BacktestConfig(commission_rate=0.0))
    charged = run_rule_backtest(history=HISTORY, names=NAMES, start=date(2026, 7, 1), end=date(2027, 2, 1), config=BacktestConfig(commission_rate=0.005))
    assert charged.metrics["final_equity"] < free.metrics["final_equity"]


def test_the_result_says_what_it_is_not():
    result = run_rule_backtest(history=HISTORY, names=NAMES, start=date(2026, 7, 1), end=date(2027, 2, 1))
    joined = " ".join(result.notes)
    assert "실제 실행 기록이 아닙니다" in joined
    assert "상장폐지" in joined and "AI 토론은 재현하지 않았습니다" in joined


def test_a_window_without_enough_history_is_refused():
    with pytest.raises(ValueError):
        run_rule_backtest(history={"000001": _series(0.001, seed=9, days=30)}, start=date(2026, 7, 1), end=date(2026, 8, 1))
    with pytest.raises(ValueError):
        run_rule_backtest(history=HISTORY, start=date(2027, 2, 1), end=date(2026, 7, 1))


def test_the_stored_replay_reaches_the_api_and_the_page():
    repo = _repo()
    repo.save_backtest_run(
        {
            "start_date": "2023-09-11",
            "end_date": "2026-09-10",
            "universe_size": 180,
            "metrics": {"total_return": 0.42, "sharpe_ratio": 1.12, "max_drawdown": -0.181, "hit_rate": 0.55, "trade_count": 214, "average_holding_days": 9.4, "benchmark_return": 0.2, "excess_return": 0.22},
            "config": {"top_n": 5},
            "equity_curve": [{"date": "2023-09-11", "equity": 50_000_000}],
            "trades": [],
            "notes": ["과거 가격으로 규칙만 재현한 모의 결과입니다. 실제 실행 기록이 아닙니다."],
        }
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    payload = client.get("/api/backtest").json()
    assert payload["status"] == "available" and payload["metrics"]["total_return"] == 0.42
    assert payload["universe_size"] == 180

    html = client.get("/paper").text
    assert "과거 시뮬레이션" in html and "실행 기록 아님" in html
    assert "미래를 보장하지 않습니다" in html
    # the simulation must not be presented as the account's own record
    assert html.index("보유 종목") < html.index("과거 시뮬레이션")


def test_no_stored_replay_shows_no_card():
    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    assert client.get("/api/backtest").json()["status"] == "empty"
    assert "과거 시뮬레이션" not in client.get("/paper").text


def test_the_variability_filter_narrows_what_can_be_bought():
    """The factor study's one consistent signal, made testable.

    Named by what it excludes rather than by how many names got traded. The
    old version counted distinct tickers across seven months and compared the
    two totals, which measured how often the book rotated rather than what it
    was allowed to buy — over that long a window nearly every name passes
    through the calm decile at some point. Widening the stop on 2026-09-22 cut
    the rotation, the two totals crossed, and the test failed without anything
    being wrong with the filter.
    """

    # Four names that swing 6% a day against sixteen that swing 0.4%.
    wild = {f"{index:06d}" for index in range(1, 5)}
    history = {
        f"{index:06d}": _series(0.002, seed=index, noise=0.06 if index < 5 else 0.004)
        for index in range(1, 21)
    }

    def traded(**overrides):
        result = run_rule_backtest(
            history=history, start=date(2026, 7, 1), end=date(2027, 2, 1),
            config=BacktestConfig(top_n=3, max_positions=6, **overrides),
        )
        return result, {trade["ticker_code"] for trade in result.trades}

    unfiltered, bought_freely = traded()
    strict, bought_under_filter = traded(volatility_exclude_top_pct=0.2)

    # Without the filter the wild names are exactly the ones momentum reaches for.
    assert wild & bought_freely
    # With it, none of them can be bought at all.
    assert not (wild & bought_under_filter)

    assert unfiltered.config["volatility_exclude_top_pct"] == 0.0  # off unless asked for
    assert strict.config["volatility_exclude_top_pct"] == 0.2


def test_the_result_breaks_down_by_year():
    result = run_rule_backtest(history=HISTORY, start=date(2026, 7, 1), end=date(2027, 2, 1), config=BacktestConfig(top_n=2))
    yearly = result.metrics["yearly_returns"]
    assert [row["year"] for row in yearly] == ["2026", "2027"]
    assert all(row["days"] > 0 for row in yearly)

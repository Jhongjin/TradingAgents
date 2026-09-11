"""Factor study: did each part of the score predict the return that followed."""

import random
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from tradingagents.harness.factor_study import run_factor_study, spearman
from tradingagents.site import create_app
from tradingagents.storage import StorageRepository, create_storage_engine


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _series(drift: float, *, seed: int, days: int = 600) -> list[dict]:
    rng = random.Random(seed)
    points, price, day = [], 10_000.0, date(2025, 1, 1)
    for step in range(days):
        day += timedelta(days=1)
        if day.weekday() >= 5:
            continue
        price *= 1 + drift + rng.uniform(-0.015, 0.015)
        points.append({"date": day.isoformat(), "close": round(price, 1), "volume": 100_000 + step})
    return points


def test_rank_correlation_handles_order_and_ties():
    assert spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == 1.0
    assert spearman([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == -1.0
    assert spearman([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None  # no variation, no answer
    assert spearman([1, 2], [1, 2]) is None  # too few names to mean anything


def test_a_factor_that_predicts_shows_a_positive_coefficient():
    history = {f"{index:06d}": _series(0.003 if index % 2 == 0 else -0.002, seed=index) for index in range(1, 41)}
    result = run_factor_study(history=history, start=date(2025, 9, 1), end=date(2026, 6, 1), horizon_days=20, sample_every=10)

    assert result.sample_dates > 5 and result.universe_size == 40
    by_key = {row["key"]: row for row in result.factors}
    assert by_key["momentum_60d"]["information_coefficient"] > 0.2  # trends persist by construction
    assert by_key["momentum_60d"]["quintile_returns"][-1] > by_key["momentum_60d"]["quintile_returns"][0]
    assert by_key["composite"]["sample_count"] == result.sample_dates
    assert "0에 가까우면" in " ".join(result.notes)


def test_noise_does_not_look_predictive():
    history = {f"{index:06d}": _series(0.0, seed=1000 + index) for index in range(1, 41)}
    result = run_factor_study(history=history, start=date(2025, 9, 1), end=date(2026, 6, 1), horizon_days=20, sample_every=20)
    composite = next(row for row in result.factors if row["key"] == "composite")
    assert abs(composite["information_coefficient"]) < 0.35


def test_a_window_that_cannot_be_measured_is_refused():
    history = {f"{index:06d}": _series(0.001, seed=index) for index in range(1, 41)}
    with pytest.raises(ValueError):
        run_factor_study(history=history, start=date(2026, 6, 1), end=date(2025, 9, 1))
    with pytest.raises(ValueError):
        run_factor_study(history={"000001": _series(0.001, seed=1, days=40)}, start=date(2025, 9, 1), end=date(2026, 1, 1))
    with pytest.raises(ValueError):
        run_factor_study(history=history, start=date(2025, 9, 1), end=date(2026, 6, 1), horizon_days=0)


def test_the_study_reaches_the_api_and_the_page():
    repo = _repo()
    repo.save_backtest_run(
        {
            "start_date": "2024-09-11",
            "end_date": "2026-09-10",
            "universe_size": 150,
            "metrics": {
                "horizon_days": 20,
                "sample_dates": 98,
                "trade_count": 98,
                "factors": [
                    {"key": "momentum_20d", "label": "20일 모멘텀", "information_coefficient": 0.031, "ic_t_stat": 2.4, "positive_rate": 0.58, "top_minus_bottom": 0.021},
                    {"key": "rsi_14", "label": "RSI", "information_coefficient": -0.002, "ic_t_stat": 0.2, "positive_rate": 0.49, "top_minus_bottom": -0.001},
                ],
            },
            "config": {"horizon_days": 20},
            "equity_curve": [],
            "trades": [],
            "notes": ["측정 결과입니다."],
        },
        label="factors",
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    payload = client.get("/api/factor-study").json()
    assert payload["status"] == "available" and payload["horizon_days"] == 20
    assert [row["key"] for row in payload["factors"]] == ["momentum_20d", "rsi_14"]

    html = client.get("/paper").text
    assert "점수 요소별 예측력" in html and "20일 모멘텀" in html
    assert "잡음과 구분되지 않습니다" in html

    # the equity replay and the factor study are separate records
    assert client.get("/api/backtest").json()["status"] == "empty"

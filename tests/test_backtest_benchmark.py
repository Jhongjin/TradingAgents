"""A market that returned nothing is a claim, not a blank.

The walk-forward on 2026-09-22 recorded all seven variants beating a flat
market across 2025-09~2026-09 — a year in which KOSPI200 returned 139.4%. The
benchmark passed in held only the two endpoints of the full replay range, so
each sub-window found the same point at both ends, divided it by itself, and
got 0.0%. Excess return then equalled the strategy's own return.
"""

import pytest

from tradingagents.harness.backtest import BacktestConfig, run_rule_backtest


def _history(days: int = 200, start_close: float = 10_000.0, drift: float = 0.002):
    from datetime import date, timedelta

    first = date(2025, 1, 1)
    return [
        {"date": (first + timedelta(days=offset)).isoformat(),
         "open": start_close * (1 + drift) ** offset,
         "high": start_close * (1 + drift) ** offset * 1.01,
         "low": start_close * (1 + drift) ** offset * 0.99,
         "close": start_close * (1 + drift) ** offset,
         "volume": 500_000}
        for offset in range(days)
    ]


def _run(benchmark):
    history = {"005930": _history(), "000660": _history(start_close=8_000.0, drift=0.0015)}
    return run_rule_backtest(
        history=history,
        names={"005930": "삼성전자", "000660": "SK하이닉스"},
        start=__import__("datetime").date(2025, 5, 1),
        end=__import__("datetime").date(2025, 7, 1),
        config=BacktestConfig(top_n=2, initial_cash=10_000_000.0),
        benchmark=benchmark,
    )


def test_a_benchmark_that_only_brackets_a_wider_range_is_refused():
    """One point at both ends is not a 0% market, it is no market."""

    result = _run({"2025-01-01": 2_400.0, "2025-12-31": 5_700.0})

    assert "benchmark_return" not in result.metrics
    assert "excess_return" not in result.metrics


def test_a_benchmark_covering_the_window_is_reported():
    from datetime import date, timedelta

    first = date(2025, 1, 1)
    series = {(first + timedelta(days=offset)).isoformat(): 2_400.0 * (1 + 0.001) ** offset
              for offset in range(200)}
    result = _run(series)

    assert result.metrics["benchmark_return"] > 0
    assert result.metrics["excess_return"] == pytest.approx(
        result.metrics["total_return"] - result.metrics["benchmark_return"], abs=1e-6)


def test_no_benchmark_at_all_reports_neither_number():
    result = _run({})

    assert "benchmark_return" not in result.metrics
    assert "excess_return" not in result.metrics

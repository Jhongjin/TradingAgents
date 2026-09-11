"""The gold pattern lab: detectors count, the study compares with doing nothing."""

import random
from datetime import datetime, timedelta, timezone

import pytest

from goldlab.contracts import GOLD_FUTURES, MICRO_GOLD_FUTURES
from goldlab.data import bars_from_rows, resample
from goldlab.patterns import PATTERN_REGISTRY, detect_patterns
from goldlab.patterns.structure import find_pivots
from goldlab.study import base_rates, run_pattern_study


def _bar(stamp, open_, high, low, close, volume=1000.0):
    return {"timestamp": stamp, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def _synthetic(bars: int = 3000, seed: int = 3):
    rng = random.Random(seed)
    rows, price, stamp = [], 2400.0, datetime(2025, 1, 1, tzinfo=timezone.utc)
    for step in range(bars):
        stamp += timedelta(hours=1)
        drift = 0.0002 if (step // 200) % 2 == 0 else -0.0002
        price *= 1 + drift + rng.uniform(-0.004, 0.004)
        high = price * (1 + abs(rng.gauss(0, 0.002)))
        low = price * (1 - abs(rng.gauss(0, 0.002)))
        rows.append(_bar(stamp, round(low + (high - low) * rng.random(), 1), round(high, 1), round(low, 1), round(price, 1), 1000 + step))
    return bars_from_rows(rows, symbol="GC=F", interval="1h")


def test_contract_maths_is_in_money_not_percent():
    # gold moves one dollar, one contract of 100 ounces moves one hundred
    gross = GOLD_FUTURES.pnl(2400.0, 2401.0, contracts=1, long=True)
    assert 60 < gross < 100  # a dollar, less two-sided slippage and commission
    assert GOLD_FUTURES.tick_value == pytest.approx(10.0)
    assert MICRO_GOLD_FUTURES.tick_value == pytest.approx(1.0)
    assert GOLD_FUTURES.pnl(2400.0, 2399.0, long=True) < 0
    assert GOLD_FUTURES.pnl(2400.0, 2399.0, long=False) > 0
    assert GOLD_FUTURES.round_to_tick(2400.037) == pytest.approx(2400.0)
    assert GOLD_FUTURES.contracts_for_risk(risk_amount=1000, entry=2400.0, stop=2395.0) == 2
    assert GOLD_FUTURES.contracts_for_risk(risk_amount=1000, entry=2400.0, stop=2400.0) == 0


def test_every_registered_pattern_runs_and_dates_its_hits():
    series = _synthetic()
    hits = detect_patterns(series)
    assert len(PATTERN_REGISTRY) >= 20
    assert hits and all(0 <= hit.index < len(series) for hit in hits)
    assert all(hit.timestamp == series.bars[hit.index].timestamp for hit in hits)
    assert hits == sorted(hits, key=lambda hit: (hit.index, hit.pattern))
    assert {hit.direction for hit in hits} <= {"bullish", "bearish"}


def test_a_hand_drawn_engulfing_is_found():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 2500.0
    for step in range(12):  # a decline, so the pattern has a trend to reverse
        price -= 3
        rows.append(_bar(stamp + timedelta(hours=step), price + 1, price + 2, price - 2, price))
    rows.append(_bar(stamp + timedelta(hours=12), price, price + 1, price - 6, price - 5))      # down bar
    rows.append(_bar(stamp + timedelta(hours=13), price - 6, price + 4, price - 7, price + 3))  # engulfs it
    series = bars_from_rows(rows, symbol="GC=F", interval="1h")

    hits = detect_patterns(series, patterns=["bullish_engulfing"])
    assert [hit.index for hit in hits] == [13]
    assert hits[0].direction == "bullish" and hits[0].label == "상승 장악형"


def test_pivots_sit_on_the_turns():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    shape = [10, 11, 12, 15, 12, 11, 10, 9, 8, 5, 8, 9, 10, 11, 12]
    rows = [_bar(stamp + timedelta(hours=index), value, value + 0.5, value - 0.5, value) for index, value in enumerate(shape)]
    series = bars_from_rows(rows, symbol="GC=F", interval="1h")

    pivots = find_pivots(series.bars, span=3)
    kinds = {pivot.index: pivot.kind for pivot in pivots}
    assert kinds.get(3) == "high"  # the peak at 15
    assert kinds.get(9) == "low"   # the trough at 5


def test_resampling_keeps_the_true_high_and_low():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_bar(stamp + timedelta(hours=index), 100 + index, 110 + index, 90 + index, 105 + index) for index in range(8)]
    series = bars_from_rows(rows, symbol="GC=F", interval="1h")

    four_hour = resample(series, factor=4, interval="4h")
    assert len(four_hour) == 2
    first = four_hour.bars[0]
    assert first.open == 100 and first.close == 108
    assert first.high == max(row["high"] for row in rows[:4])
    assert first.low == min(row["low"] for row in rows[:4])
    assert first.volume == sum(row["volume"] for row in rows[:4])


def test_the_study_reports_the_edge_over_doing_nothing():
    series = _synthetic()
    result = run_pattern_study(series, horizons=(4, 12), min_occurrences=20, contract=GOLD_FUTURES)

    assert result.bars == len(series) and result.horizons == (4, 12)
    assert result.base_rate[12]["long"]["count"] > 1000
    assert 0 < result.base_rate[12]["long"]["win_rate"] < 1

    measured = [row for row in result.patterns if (row["horizons"].get("12") or {}).get("count")]
    assert measured
    for row in measured:
        stats = row["horizons"]["12"]
        assert "edge_win_rate" in stats and "edge_return" in stats
        # the edge is the pattern minus the base rate, not the raw number
        assert stats["edge_return"] == pytest.approx(stats["average_return"] - stats["base_average_return"], abs=1e-9)
        assert stats["average_mae"] <= 0 <= stats["average_mfe"]
        assert isinstance(stats["enough_samples"], bool)
    assert any("기준 대비" in note for note in result.notes)


def test_a_short_pattern_is_measured_short():
    series = _synthetic()
    result = run_pattern_study(series, horizons=(12,), min_occurrences=5)
    bearish = next((row for row in result.patterns if row["direction"] == "bearish" and (row["horizons"].get("12") or {}).get("count")), None)
    assert bearish is not None
    short_base = result.base_rate[12]["short"]
    assert short_base["count"] > 0
    # a falling market is a win for a short, so the two base rates disagree
    assert short_base["win_rate"] != result.base_rate[12]["long"]["win_rate"]


def test_too_few_bars_is_refused():
    series = _synthetic(bars=40)
    with pytest.raises(ValueError):
        run_pattern_study(series, horizons=(72,))


def test_base_rate_counts_every_bar_it_can():
    series = _synthetic(bars=500)
    rates = base_rates(series.bars, (10,))
    assert rates[10]["count"] == len(series) - 10

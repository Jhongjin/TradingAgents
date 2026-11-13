"""The ledger and the honest statistics: no look-ahead, no rewriting, no free edges."""

import random
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from goldlab import barstore
from goldlab.barstore import import_bars, merge_bars, on_grid, sync_bars
from goldlab.context import ContextTagger
from goldlab.data import Bar, BarSeries, bars_from_rows
from goldlab.ledger import FileLedger, grade_signals, scan_into_ledger
from goldlab.patterns import PATTERN_REGISTRY
from goldlab.scanner import detect_at, scan_series
from goldlab.walkforward import (
    WalkForward,
    benjamini_hochberg,
    beta_shrink,
    binomial_two_sided_p,
    estimate_prior_strength,
    pick_record,
)

START = datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc)
FAR_FUTURE = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _series(count=700, seed=5, interval="5m", symbol="GC=F", start=START, source="yahoo"):
    rng = random.Random(seed)
    price, rows = 2400.0, []
    for step in range(count):
        price *= 1 + rng.uniform(-0.0012, 0.0012) + (0.0004 if (step // 70) % 2 == 0 else -0.0004)
        high = price * (1 + abs(rng.gauss(0, 0.0006)))
        low = price * (1 - abs(rng.gauss(0, 0.0006)))
        rows.append(
            {
                "timestamp": start + timedelta(minutes=5 * step),
                "open": round(low + (high - low) * rng.random(), 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(price, 2),
                "volume": 100 + step,
                "source": source,
            }
        )
    return bars_from_rows(rows, symbol=symbol, interval=interval)


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path / "bars"))


# ---------------------------------------------------------------- point in time
def test_detectors_are_never_shown_a_bar_after_the_one_being_judged():
    series = _series()
    seen = []

    def spy(bars):
        seen.append((len(bars), bars[-1].timestamp))
        return []

    PATTERN_REGISTRY["_spy"] = ("spy", "bullish", spy)
    try:
        detect_at(series.bars, 300, window=240, patterns=["_spy"])
    finally:
        del PATTERN_REGISTRY["_spy"]
    assert seen == [(240, series.bars[300].timestamp)]


def test_signals_at_t_do_not_change_when_later_bars_change():
    full = _series(count=700, seed=5)
    cut = 420
    # a different future: same first bars, then a different market
    other_future = _series(count=700, seed=99, start=full.bars[cut + 1].timestamp)
    altered = BarSeries(symbol="GC=F", interval="5m", bars=full.bars[: cut + 1] + other_future.bars[: 700 - cut - 1])
    for t in (300, 380, cut):
        assert detect_at(full.bars, t) == detect_at(altered.bars, t)

    truncated = BarSeries(symbol="GC=F", interval="5m", bars=full.bars[: cut + 1])
    left = [s["id"] for s in scan_series(truncated, now=FAR_FUTURE)]
    right = [s["id"] for s in scan_series(full, now=FAR_FUTURE) if s["index"] <= cut]
    assert left == right and left


def test_scan_is_independent_of_where_it_starts():
    series = _series()
    everything = {s["id"] for s in scan_series(series, now=FAR_FUTURE)}
    recent = {s["id"] for s in scan_series(series, last_bars=150, now=FAR_FUTURE)}
    assert recent and recent <= everything


def test_the_forming_bar_is_not_scanned():
    series = _series(count=200)
    just_after_last_open = series.bars[-1].timestamp + timedelta(minutes=1)
    ids = {s["ts"] for s in scan_series(series, now=just_after_last_open)}
    assert series.bars[-1].timestamp.isoformat() not in ids


# ---------------------------------------------------------------- grading
def test_grading_is_idempotent_and_never_rewrites_a_grade():
    series = _series(count=400)
    signals = list(scan_series(BarSeries("GC=F", "5m", series.bars[:200]), now=FAR_FUTURE))
    rows = [dict(s, grades={}, complete=False) for s in signals]
    for row in rows:
        row.pop("index", None)

    first = grade_signals(BarSeries("GC=F", "5m", series.bars[:230]), rows, now=FAR_FUTURE)
    assert first
    snapshot = deepcopy(rows)
    assert grade_signals(BarSeries("GC=F", "5m", series.bars[:230]), rows, now=FAR_FUTURE) == []
    assert rows == snapshot

    # more bars arrive: later horizons fill in, earlier grades stay exactly as they were
    grade_signals(series, rows, now=FAR_FUTURE)
    for before, after in zip(snapshot, rows):
        for key, grade in before["grades"].items():
            assert after["grades"][key] == grade
    assert any(len(after["grades"]) > len(before["grades"]) for before, after in zip(snapshot, rows))


def test_grade_fields_and_stop_target_ties_go_to_the_stop():
    rows = [
        {"timestamp": START + timedelta(minutes=5 * i), "open": 100, "high": 100.1, "low": 99.9, "close": 100, "volume": 1}
        for i in range(6)
    ]
    rows[1].update(high=102.0, low=98.0, close=101.0)        # one bar reaches both target and stop
    series = bars_from_rows(rows, symbol="GC=F", interval="5m")
    signal = {
        "id": "x", "symbol": "GC=F", "interval": "5m", "pattern": "p", "direction": "bullish",
        "ts": series.bars[0].timestamp.isoformat(), "entry": 100.0, "grades": {},
        "context": {"atr_pct": 0.001},
    }
    grade_signals(series, [signal], horizons=(4,), now=FAR_FUTURE)
    grade = signal["grades"]["4"]
    assert grade["first_touch"] == "stop"
    assert grade["hit"] is False and grade["return"] == pytest.approx(0.0)    # flat close is not a win
    assert set(grade) >= {"return", "hit", "mfe", "mae", "first_touch", "resolved_at"}
    assert grade["mfe"] == pytest.approx(0.02, abs=1e-4) and grade["mae"] == pytest.approx(-0.02, abs=1e-4)
    assert signal["complete"] is True


def test_ledger_scan_twice_adds_nothing_the_second_time(tmp_path):
    series = _series(count=500)
    store = FileLedger("GC=F", "5m", path=tmp_path / "ledger.json")
    first = scan_into_ledger(series, store, last_bars=None, now=FAR_FUTURE)
    again = scan_into_ledger(series, store, last_bars=None, now=FAR_FUTURE)
    live = scan_into_ledger(series, store, last_bars=100, now=FAR_FUTURE)
    assert first["added"] > 0 and again["added"] == 0 and live["added"] == 0
    row = store.all()[0]
    assert row["origin"] == "backfill" and row["claim_source"] == "walkforward_asof"
    assert {"session", "trend", "vol", "event"} <= set(row["context"])


# ---------------------------------------------------------------- bar store
def _bar(minute, close, source="yahoo"):
    stamp = START + timedelta(minutes=minute)
    return Bar(stamp, close, close + 1, close - 1, close, 10.0, source)


def test_merge_dedupes_keeps_old_values_and_refreshes_only_the_tail():
    old = [_bar(5 * i, 100 + i) for i in range(20)]
    fresh = [_bar(5 * i, 500 + i) for i in range(10, 25)]
    merged = merge_bars(old, fresh, refresh_tail=3)
    assert [bar.timestamp for bar in merged] == sorted({bar.timestamp for bar in merged})
    assert len(merged) == 25
    by_ts = {bar.timestamp: bar for bar in merged}
    assert by_ts[old[12].timestamp].close == 112          # inside the old history: untouched
    assert by_ts[old[19].timestamp].close == 519          # in the last 3 stored bars: refreshed
    assert by_ts[_bar(5 * 24, 0).timestamp].close == 524  # new
    assert merged[0].timestamp == old[0].timestamp        # nothing older was dropped


def test_vendor_bars_outrank_yahoo_and_yahoo_never_overwrites_them():
    yahoo = [_bar(5 * i, 100 + i) for i in range(30)]
    vendor = [_bar(5 * i, 200 + i, "databento") for i in range(5, 15)]
    merged = merge_bars(yahoo, vendor, refresh_tail=0)
    assert all(bar.source == "databento" for bar in merged[5:15]) and merged[5].close == 205
    again = merge_bars(merged, yahoo, refresh_tail=6)      # a routine Yahoo fetch afterwards
    assert again[5].close == 205 and again[5].source == "databento"
    assert merge_bars(again, vendor, refresh_tail=0) == again


def test_off_grid_quote_bar_is_not_stored():
    bars = tuple(_bar(5 * i, 100) for i in range(3)) + (Bar(START + timedelta(minutes=12, seconds=43), 1, 2, 1, 1, 0.0),)
    cleaned = on_grid(BarSeries("GC=F", "5m", bars))
    assert len(cleaned.bars) == 3


def test_sync_accumulates_past_the_vendor_window_and_reports_gaps():
    first = _series(count=300, start=START)
    later = _series(count=300, start=START + timedelta(days=10))      # the vendor window slid; days are missing
    barstore.sync_bars("GC=F", "5m", fetch=lambda symbol, interval: first)
    report = barstore.sync_bars("GC=F", "5m", fetch=lambda symbol, interval: later)
    assert report.total == 600 and report.added == 300 and report.gap
    from goldlab.data import read_cache

    assert len(read_cache("GC=F", "5m").bars) == 600


def test_vendor_csv_import_resamples_and_survives_a_later_yahoo_sync(tmp_path):
    path = tmp_path / "export.csv"
    lines = ["ts_event,symbol,open,high,low,close,volume"]
    for minute in range(0, 20):
        stamp = (START + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
        lines.append(f"{stamp},GCZ6,{100 + minute},{101 + minute},{99 + minute},{100.5 + minute},2")
    path.write_text("\n".join(lines), encoding="utf-8")
    report = import_bars(path, "GC=F", "5m", source="databento", from_interval="1m", raw_symbol="GCZ6")
    assert report.total == 4 and report.sources == {"databento": 4}
    from goldlab.data import read_cache

    stored = read_cache("GC=F", "5m").bars
    assert stored[0].open == 100 and stored[0].close == 104.5 and stored[0].high == 105 and stored[0].volume == 10
    yahoo = bars_from_rows(
        [{"timestamp": START + timedelta(minutes=5 * i), "open": 1, "high": 2, "low": 1, "close": 1, "volume": 1} for i in range(8)],
        symbol="GC=F", interval="5m",
    )
    sync_bars("GC=F", "5m", fetch=lambda symbol, interval: yahoo)
    merged = read_cache("GC=F", "5m").bars
    assert [bar.source for bar in merged[:4]] == ["databento"] * 4 and merged[0].close == 104.5
    assert [bar.source for bar in merged[4:]] == ["yahoo"] * 4
    with pytest.raises(ValueError):
        import_bars(path, "GC=F", "5m", source="yahoo")


def test_database_store_round_trips_and_keeps_vendor_rows():
    from tradingagents.storage import StorageRepository, create_storage_engine

    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    rows = [dict(ts=START + timedelta(minutes=5 * i), open=1, high=2, low=1, close=1.5, volume=3, source="databento") for i in range(3)]
    assert repo.goldlab_upsert_bars("GC=F", "5m", rows) == {"inserted": 3, "updated": 0}
    yahoo = [dict(rows[0], close=9.0, source="yahoo"), dict(ts=START + timedelta(minutes=15), open=1, high=2, low=1, close=1.2, volume=3)]
    assert repo.goldlab_upsert_bars("GC=F", "5m", yahoo) == {"inserted": 1, "updated": 0}
    stored = repo.goldlab_load_bars("GC=F", "5m")
    assert [row["close"] for row in stored] == [1.5, 1.5, 1.5, 1.2] and stored[0]["source"] == "databento"
    assert stored[0]["ts"].tzinfo is not None

    signal = {"id": "s1", "symbol": "GC=F", "interval": "5m", "pattern": "doji", "direction": "bullish", "ts": START.isoformat(), "grades": {}, "complete": False}
    assert repo.goldlab_add_signals([signal]) == 1
    assert repo.goldlab_add_signals([signal]) == 0
    graded = dict(signal, grades={"4": {"hit": True}}, complete=True)
    repo.goldlab_update_signals([graded])
    assert repo.goldlab_load_signals("GC=F", "5m", pending_only=True) == []
    assert repo.goldlab_load_signals("GC=F", "5m")[0]["grades"] == {"4": {"hit": True}}


# ---------------------------------------------------------------- honest statistics
def _wf(signal_indices, bars=None, horizons=(4,), contexts=None):
    series = bars or _series(count=900, seed=11)
    tagger = ContextTagger(series.bars, interval="5m", events=[])
    signals = [
        {"index": i, "pattern": "p", "direction": "bullish", "context": tagger.tag(i).as_dict()}
        for i in signal_indices
    ]
    return series, tagger, WalkForward(series.bars, tagger, signals, horizons)


def test_walk_forward_record_uses_only_outcomes_finished_by_t():
    indices = list(range(250, 700, 3))
    series, tagger, full = _wf(indices)
    for t in (400, 555, 690):
        got = full.record("p", "bullish", t, 4)
        expected = sum(1 for i in indices if i + 4 <= t)
        assert got["count"] == expected                      # a signal whose outcome is still open is not counted
        # rebuilt from nothing but bars up to t, the answer is the same
        cut = BarSeries("GC=F", "5m", series.bars[: t + 1])
        _s, _t, early = _wf([i for i in indices if i <= t], bars=cut)
        assert early.record("p", "bullish", t, 4) == got


def test_rolling_window_drops_old_outcomes():
    indices = list(range(250, 700, 2))
    series, tagger, _ = _wf(indices)
    rolling = WalkForward(
        series.bars, tagger,
        [{"index": i, "pattern": "p", "direction": "bullish", "context": tagger.tag(i).as_dict()} for i in indices],
        (4,), window_bars=100,
    )
    assert rolling.record("p", "bullish", 690, 4)["count"] < _wf(indices)[2].record("p", "bullish", 690, 4)["count"]


def test_shrinkage_pulls_small_samples_harder_and_toward_the_base_rate():
    base = 0.50
    small = beta_shrink(wins=8, n=10, base=base, strength=60)       # 80% on ten samples
    large = beta_shrink(wins=800, n=1000, base=base, strength=60)   # 80% on a thousand
    assert base < small < large < 0.80
    assert (0.80 - small) > (0.80 - large) * 5
    assert beta_shrink(0, 0, base, 60) == base
    # patterns that together show no dispersion beyond noise are shrunk as hard as allowed
    quiet = [(50, 100, 0.5)] * 8
    assert estimate_prior_strength(quiet) >= 1000
    # real dispersion lets the data speak more
    spread = [(70, 100, 0.5), (30, 100, 0.5), (65, 100, 0.5), (35, 100, 0.5), (72, 100, 0.5), (28, 100, 0.5)]
    assert estimate_prior_strength(spread) < estimate_prior_strength(quiet)


def test_binomial_test_and_benjamini_hochberg():
    assert binomial_two_sided_p(50, 100, 0.5) == pytest.approx(1.0, abs=1e-6)
    assert binomial_two_sided_p(70, 100, 0.5) < 0.001
    assert binomial_two_sided_p(5, 0, 0.5) is None and binomial_two_sided_p(5, 10, 1.0) is None
    # classic: five tests at q=0.10; only the ones under their staircase survive
    p_values = [0.001, 0.008, 0.039, 0.041, 0.60, None]
    assert benjamini_hochberg(p_values, q=0.10) == [True, True, True, True, False, False]
    assert benjamini_hochberg([0.04, 0.30, 0.50, 0.70], q=0.05) == [False, False, False, False]
    # the family size is what makes a lone 0.04 stop counting: 0.04 alone passes, among many it does not
    assert benjamini_hochberg([0.04], q=0.05) == [True]
    assert benjamini_hochberg([0.04] + [0.9] * 30, q=0.05) == [False] * 31


def test_context_split_is_used_only_with_enough_samples_else_pooled():
    series = _series(count=900, seed=11)
    tagger = ContextTagger(series.bars, interval="5m", events=[])
    indices = list(range(250, 800, 2))
    wf = WalkForward(
        series.bars, tagger,
        [{"index": i, "pattern": "p", "direction": "bullish", "context": tagger.tag(i).as_dict()} for i in indices],
        (4,),
    )
    pooled = wf.record("p", "bullish", 790, 4)
    contexts = [tagger.tag(i).as_dict() for i in indices]
    rare = next(
        (c for c in contexts if 0 < wf.raw("p", "bullish", 790, 4, {"session": c["session"]})[0].n < 30),
        None,
    )
    matched = wf.matched("p", "bullish", 790, 4, {"session": "does-not-exist"})
    assert matched["dims"] == [] and matched["count"] == pooled["count"]       # falls back to the pooled record
    if rare:
        narrowed = wf.matched("p", "bullish", 790, 4, rare)
        assert "session" not in narrowed["dims"]

    # the chart's pick: a split below the floor is ignored and the pooled record named
    stats = {"4": dict(pooled, context={"session": {"us": {"count": 12, "win_rate": 0.9, "t_stat": 3.0}}})}
    picked = pick_record(stats, {"session": "us"}, min_samples=30)
    assert picked["basis"] == "전체" and picked["stats"]["count"] == pooled["count"]
    stats["4"]["context"]["session"]["us"]["count"] = 45
    picked = pick_record(stats, {"session": "us"}, min_samples=30)
    assert picked["basis"] == "session=us" and picked["stats"]["count"] == 45


def test_walkforward_study_shape_and_the_old_study_stays_available():
    from goldlab.walkforward import run_walkforward_study

    series = _series(count=1500, seed=21)
    study = run_walkforward_study(series, horizons=(4, 12), now=FAR_FUTURE)
    assert study["method"] == "walk_forward_v1" and study["window"] == "expanding"
    assert study["legacy_patterns"] and study["fdr"]["tested"] >= 0
    row = study["patterns"][0]
    some = next(h for r in study["patterns"] for h in r["horizons"].values() if h.get("count"))
    assert {"count", "win_rate", "shrunk_win_rate", "confidence", "fdr_significant"} <= set(some)
    assert all(
        h.get("shrunk_win_rate") is None or abs(h["shrunk_win_rate"] - h["base_win_rate"]) <= abs(h["win_rate"] - h["base_win_rate"]) + 1e-4
        for r in study["patterns"] for h in r["horizons"].values() if h.get("count") and h.get("base_win_rate") is not None
    )
    assert row["pattern"] in PATTERN_REGISTRY


def test_chart_quotes_the_shrunk_record_and_still_reads_an_old_study():
    from goldlab.chart import build_frame
    from goldlab.walkforward import run_walkforward_study

    series = _series(count=1500, seed=21)
    study = run_walkforward_study(series, horizons=(4, 12), now=FAR_FUTURE)
    study["ledger_line"] = "최근 30일 실시간 기록: 신호 3건"
    frame = build_frame(series, study=study, max_bars=300)
    assert frame["record_method"] == "walk_forward_v1" and frame["ledger_line"]
    assert all("basis" in hit and hit["shrunk"] for hit in frame["hits"])
    old = {"patterns": study["legacy_patterns"]}
    legacy = build_frame(series, study=old, max_bars=300)
    assert legacy["record_method"] == "legacy" and all(hit["shrunk"] is False for hit in legacy["hits"])

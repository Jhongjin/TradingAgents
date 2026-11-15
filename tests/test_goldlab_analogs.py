"""Similar past charts: no look-ahead, distinct episodes, scale invariance, serving, honest wording."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from goldlab import analogs as A
from goldlab.data import bars_from_rows, write_cache

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
W, HMAX = A.WINDOW, max(A.HORIZONS)


def _arrays(n=4000, seed=7, scale=1.0, volume_scale=1.0, interval="5m", symbol="GC=F") -> A.Arrays:
    rng = np.random.default_rng(seed)
    drift = np.where((np.arange(n) // 180) % 2 == 0, 0.0004, -0.0004)
    r = rng.normal(0, 0.001, n) * (1 + 0.8 * np.sin(np.arange(n) / 400)) + drift
    close = 2400.0 * np.exp(np.cumsum(r)) * scale
    ts = (int(START.timestamp()) + 300 * np.arange(n)).astype(np.int64)
    return A.Arrays(symbol=symbol, interval=interval, ts=ts, close=close, volume=rng.uniform(100, 500, n) * volume_scale)


def _ends(arrays, query_end=None, **kwargs):
    feats = A.build_features(arrays)
    q = len(arrays) - 1 if query_end is None else query_end
    return [end for end, _ in A.search(feats, q, **kwargs)]


def test_no_look_ahead_and_no_overlap_with_the_query():
    arrays = _arrays()
    feats = A.build_features(arrays)
    for q in (900, 1500, 2500, 3999):
        found = A.search(feats, q)
        assert found, q
        for end, _ in found:
            assert end + HMAX < q - W          # the whole forward path ended before the query window began
            assert end >= W


def test_results_do_not_depend_on_anything_after_the_query():
    arrays = _arrays()
    q = 2500
    full = _ends(arrays, q)
    cut = A.Arrays(arrays.symbol, arrays.interval, arrays.ts[: q + 1], arrays.close[: q + 1], arrays.volume[: q + 1])
    assert _ends(cut) == full
    poisoned_close = arrays.close.copy()
    poisoned_close[q + 1 :] *= 7.3          # a different future must not move the answer
    poisoned = A.Arrays(arrays.symbol, arrays.interval, arrays.ts, poisoned_close, arrays.volume)
    assert _ends(poisoned, q) == full


def test_analogs_are_distinct_episodes():
    arrays = _arrays()
    ends = sorted(_ends(arrays))
    assert len(ends) == A.NEIGHBOURS
    assert all(b - a >= 2 * W for a, b in zip(ends, ends[1:]))
    tight = sorted(_ends(arrays, min_separation=W))
    assert all(b - a >= W for a, b in zip(tight, tight[1:]))


def test_search_is_deterministic():
    arrays = _arrays()
    first, second = A.current_analogs(arrays), A.current_analogs(arrays)
    for payload in (first, second):
        payload.pop("computed_at")
    assert first == second


def test_scale_invariance_price_and_volume():
    base = _ends(_arrays())
    assert _ends(_arrays(scale=37.5, volume_scale=1000)) == base
    assert _ends(_arrays(scale=0.02)) == base


def test_a_planted_repeat_is_found_first():
    arrays = _arrays()
    r = np.diff(np.log(arrays.close), prepend=np.log(arrays.close[0]))
    r[3000 - W + 1 : 3001] = r[700 - W + 1 : 701] * 2.0        # same shape, twice the volatility
    close = np.exp(np.cumsum(r)) * arrays.close[0]
    planted = A.Arrays(arrays.symbol, arrays.interval, arrays.ts, close, arrays.volume)
    feats = A.build_features(planted)
    found = A.search(feats, 3000)
    assert found[0][0] == 700
    assert A.similarity(found[0][1], float(feats.norm[3000])) > 0.99
    report = A.current_analogs(planted, query_end=3000)
    assert report["analogs"][0]["end_index"] == 700
    assert report["analogs"][0]["vol_ratio"] == pytest.approx(2.0, rel=0.05)


def test_report_shape_and_forward_paths():
    arrays = _arrays()
    report = A.current_analogs(arrays)
    assert len(report["analogs"]) == A.NEIGHBOURS and set(report["summary"]) == {"12", "24", "72"}
    first = report["analogs"][0]
    assert len(first["forward"]) == HMAX + 1 and first["forward"][0] == 0.0
    s = report["summary"]["24"]
    assert s["up"] + s["down"] <= s["n"] and s["q25"] <= s["median"] <= s["q75"]
    assert 0.0 <= first["similarity"] <= 1.0
    sims = [x["similarity"] for x in report["analogs"]]
    assert sims == sorted(sims, reverse=True)
    json.dumps(report)                      # plain JSON, storable


def test_a_market_break_is_not_read_as_a_shape():
    arrays = _arrays()
    ts = arrays.ts.copy()
    ts[2000:] += 3 * 86400                   # a weekend-sized hole
    close = arrays.close.copy()
    close[2000:] *= 1.05                     # and a gap across it
    gapped = A.Arrays(arrays.symbol, arrays.interval, ts, close, arrays.volume)
    feats = A.build_features(gapped)
    plain = A.build_features(_arrays())
    assert np.allclose(feats.matrix[2000 + W + 5], plain.matrix[2000 + W + 5], atol=1e-4)


def test_load_arrays_reads_the_file_store(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path))
    rows = [{"timestamp": START + timedelta(minutes=5 * i), "open": 10 + i, "high": 12 + i, "low": 9 + i, "close": 11 + i, "volume": 5} for i in range(300)]
    series = bars_from_rows(rows, symbol="GC=F", interval="5m")
    write_cache(series)
    loaded = A.load_arrays("GC=F", "5m")
    expected = A.arrays_from_series(series)
    assert np.array_equal(loaded.ts, expected.ts) and np.allclose(loaded.close, expected.close)


def test_binomial_and_wilson_basics():
    low, high = A.wilson(50, 100)
    assert low < 0.5 < high and high - low < 0.21
    assert A.binom_two_sided(50, 100, 0.5) == pytest.approx(1.0, abs=1e-9)
    assert A.binom_two_sided(70, 100, 0.5) < 0.001


def test_validation_scores_with_only_earlier_data_and_states_the_verdict():
    arrays = _arrays(n=6000, seed=3)
    result = A.validate(arrays, queries=60, burn_fraction=0.25)
    assert result["kind"] == "research_not_trading_performance"
    for h in ("12", "24", "72"):
        block = result["horizons"][h]
        assert block["spacing_bars"] >= int(h)                      # outcomes of one horizon never overlap
        s = block["all"]
        assert s["n"] > 20 and 0 <= s["hit_rate"] <= 1 and s["hit_ci95"][0] <= s["hit_rate"] <= s["hit_ci95"][1]
        assert s["always_majority_rate"] >= 0.5
    assert result["line"].startswith("검증:")
    # random-walk-with-regimes data: whatever the verdict, the wording must match it
    assert ("낫지 않음" in result["line"]) == (not result["beats_base"])


def test_the_card_says_so_when_analogs_do_not_beat_the_base():
    weak = {"12": {"all": {"p_vs_majority": 0.4, "edge_over_majority": 0.01}}, "24": {"all": {"p_vs_majority": 0.9, "edge_over_majority": -0.02}}}
    verdict = A.verdict_for(weak)
    assert verdict["beats_base"] is False and "기준보다 낫지 않음" in verdict["line"]
    strong = {"12": {"all": {"p_vs_majority": 1e-6, "edge_over_majority": 0.05}}}
    assert A.verdict_for(strong)["beats_base"] is True
    # a significant result in the wrong direction is not a win
    assert A.verdict_for({"12": {"all": {"p_vs_majority": 1e-6, "edge_over_majority": -0.05}}})["beats_base"] is False


def _repo():
    from tradingagents.storage import StorageRepository, create_storage_engine

    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def test_serving_round_trip_through_the_database_keeps_one_row():
    repo = _repo()
    arrays = _arrays()
    payload = A.current_analogs(arrays)
    A.store_analogs(repo, payload)
    again = A.current_analogs(arrays)
    again["computed_at"] = "2030-01-01T00:00:00+00:00"
    A.store_analogs(repo, again)
    stored = A.load_stored_analogs(repo, "GC=F", "5m")
    assert stored["computed_at"] == "2030-01-01T00:00:00+00:00" and stored["analogs"] == again["analogs"]
    assert A.load_stored_analogs(repo, "GC=F", "1h") is None and A.load_stored_analogs(repo, "NQ=F", "5m") is None
    from sqlalchemy import func, select

    from tradingagents.storage.tables import backtest_runs

    with repo.engine.begin() as conn:
        rows = conn.execute(select(func.count()).select_from(backtest_runs).where(backtest_runs.c.label == "gold:analogs:GC=F:5m")).scalar()
    assert rows == 1
    assert A.load_stored_analogs(None, "GC=F", "5m") is None


def test_refresh_embeds_the_stored_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path))
    arrays = _arrays(n=3000)
    assert "validation" not in A.refresh("GC=F", "5m", arrays=arrays)
    result = A.validate(arrays, queries=40, burn_fraction=0.3)
    A.validation_path("GC=F", "5m").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    repo = _repo()
    payload = A.refresh("GC=F", "5m", repo=repo, arrays=arrays)
    assert payload["validation"]["line"] == result["line"]
    assert A.load_stored_analogs(repo, "GC=F", "5m")["validation"]["line"] == result["line"]


def _frame():
    from goldlab.chart import build_frame

    rng = np.random.default_rng(1)
    price, rows = 2400.0, []
    for i in range(400):
        price *= 1 + rng.normal(0, 0.001)
        rows.append({"timestamp": START + timedelta(hours=i), "open": price, "high": price * 1.001, "low": price * 0.999, "close": price, "volume": 10})
    return build_frame(bars_from_rows(rows, symbol="GC=F", interval="1h"), study=None, max_bars=200)


def test_page_renders_with_and_without_analogs():
    from goldlab.chart import render_chart

    frame = _frame()
    frame["analogs"] = None
    bare = render_chart({"1h": frame}, symbol="GC=F", intervals=("1h",), data_url="/lab/gold/data", bars=200)
    assert 'id="abody"' in bare and "그 뒤 흐름의 분포가 여기에 표시됩니다" in bare and "function renderAnalogs" in bare
    frame["analogs"] = A.current_analogs(_arrays())
    frame["analogs"]["validation"] = {"line": "검증: 10년 순차 검증에서 기준보다 낫지 않음 (예측 도구가 아닙니다)", "horizons": {}}
    full = render_chart({"1h": frame}, symbol="GC=F", intervals=("1h",), data_url="/lab/gold/data", bars=200)
    assert '"analogs": {"version": 1' in full and "기준보다 낫지 않음" in full


def test_the_data_route_carries_analogs_only_when_stored(monkeypatch):
    from fastapi.testclient import TestClient

    import goldlab.data as data
    from tradingagents.site import create_app

    rng = np.random.default_rng(2)
    price, rows = 2400.0, []
    for i in range(400):
        price *= 1 + rng.normal(0, 0.001)
        rows.append({"timestamp": START + timedelta(hours=i), "open": price, "high": price * 1.001, "low": price * 0.999, "close": price, "volume": 10})
    monkeypatch.setattr(data, "fetch_bars", lambda symbol="GC=F", *, interval="1h", days=None: bars_from_rows(rows, symbol=symbol, interval=interval))

    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=False))
    assert client.get("/lab/gold/data?interval=1h&symbol=GC=F").json()["analogs"] is None
    A.store_analogs(repo, A.current_analogs(_arrays(interval="1h")))
    body = client.get("/lab/gold/data?interval=1h&symbol=GC=F").json()
    assert len(body["analogs"]["analogs"]) == 10
    assert client.get("/lab/gold/data?interval=1h&symbol=NQ=F").json()["analogs"] is None

"""Reading and rewriting only the end of the bar file gives the same store as the full path. No network."""

from datetime import datetime, timedelta, timezone

import pytest

from goldlab.barstore import load_recent, sync_bars
from goldlab.data import Bar, BarSeries, cache_path, read_cache, read_cache_tail, write_cache


def _bar(i, base=100.0, source="yahoo"):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5 * i)
    return Bar(timestamp=ts, open=base + i, high=base + i + 1, low=base + i - 1, close=base + i + 0.5, volume=10, source=source)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path / "store"))
    return tmp_path / "store"


def test_tail_by_rows_and_since_matches_the_full_read(store):
    bars = tuple(_bar(i) for i in range(20000))          # ~1.2 MB, several read blocks
    write_cache(BarSeries("GC=F", "5m", bars))
    full = read_cache("GC=F", "5m").bars
    tail, head = read_cache_tail("GC=F", "5m", rows=700)
    assert tail.bars == full[-700:]
    assert cache_path("GC=F", "5m").read_bytes()[head:].count(b"\n") == 700
    since = full[-3000].timestamp
    tail, _ = read_cache_tail("GC=F", "5m", since=since)
    assert tail.bars == full[-3000:]
    tail, _ = read_cache_tail("GC=F", "5m", since=since, rows=5000)   # whichever reaches further back
    assert tail.bars == full[-5000:]
    tail, head = read_cache_tail("GC=F", "5m", since=full[0].timestamp - timedelta(days=1))
    assert tail.bars == full and head == len(b"timestamp,open,high,low,close,volume,source\r\n")


def test_tail_after_a_gap_still_returns_the_last_bar(store):
    write_cache(BarSeries("GC=F", "5m", tuple(_bar(i) for i in range(100))))
    tail, _ = read_cache_tail("GC=F", "5m", since=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert tail.bars == (_bar(99),)


def test_tail_refuses_a_file_it_can_not_splice(store):
    write_cache(BarSeries("GC=F", "5m", tuple(_bar(i) for i in range(50))))
    path = cache_path("GC=F", "5m")
    path.write_bytes(path.read_bytes() + b"garbage line\r\n" + b"2026-01-01T09:00:00+00:00,1,2,0.5,1.5,1,yahoo\r\n")
    assert read_cache_tail("GC=F", "5m", rows=10) == (None, 0)
    assert read_cache_tail("nope", "5m", rows=10) == (None, 0)


def _sync_both_ways(tmp_path, monkeypatch, stored, fresh):
    results = []
    for name in ("full", "tail"):
        monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path / name))
        write_cache(BarSeries("GC=F", "5m", stored))
        if name == "full":
            monkeypatch.setattr("goldlab.barstore.read_cache_tail", lambda *a, **k: (None, 0))
        else:
            monkeypatch.undo()
            monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path / name))
        report = sync_bars("GC=F", "5m", fetch=lambda symbol, interval: BarSeries(symbol, interval, fresh))
        results.append((report, cache_path("GC=F", "5m").read_bytes()))
    return results


def test_routine_sync_tail_equals_full(tmp_path, monkeypatch):
    stored = tuple(_bar(i, source="databento") for i in range(6000)) + tuple(_bar(i) for i in range(6000, 9000))
    fresh = tuple(_bar(i, base=100.25 if i > 9010 else 100.0) for i in range(8000, 9050))
    (full_rep, full_bytes), (tail_rep, tail_bytes) = _sync_both_ways(tmp_path, monkeypatch, stored, fresh)
    assert tail_bytes == full_bytes
    assert tail_rep.tail_only and not full_rep.tail_only
    assert (tail_rep.added, tail_rep.refreshed) == (full_rep.added, full_rep.refreshed) == (50, 0)


def test_sync_that_fills_a_hole_inside_the_tail_splices_and_keeps_the_head(tmp_path, monkeypatch):
    stored = tuple(_bar(i, source="databento") for i in range(5000)) + tuple(_bar(i) for i in range(5000, 8000) if i % 97)
    fresh = tuple(_bar(i) for i in range(7000, 8010))                 # fills the holes in its window
    before = (tmp_path / "before")
    monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(before))
    write_cache(BarSeries("GC=F", "5m", stored))
    original = cache_path("GC=F", "5m").read_bytes()
    (full_rep, _full_bytes), (tail_rep, tail_bytes) = _sync_both_ways(tmp_path, monkeypatch, stored, fresh)
    # a full rewrite re-formats old rows (10 -> 10.0); the splice leaves them byte for byte
    for name in ("full", "tail"):
        monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path / name))
        if name == "full":
            full_bars = read_cache("GC=F", "5m").bars
        else:
            assert read_cache("GC=F", "5m").bars == full_bars
    cut = original.index(_bar(6000).timestamp.isoformat().encode())
    assert tail_bytes[:cut] == original[:cut]
    assert tail_rep.added == full_rep.added > 10
    assert not list((tmp_path / "tail").glob("*.tmp"))


def test_load_recent_merges_the_same_span_of_the_database(store):
    write_cache(BarSeries("GC=F", "5m", tuple(_bar(i) for i in range(3000))))
    asked = {}

    class Repo:
        def goldlab_load_bars(self, symbol, interval, *, since=None):
            asked["since"] = since
            b = _bar(2999, base=150.0, source="databento")
            return [{"ts": b.timestamp, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume, "source": b.source}]

    got = load_recent("GC=F", "5m", repo=Repo(), rows=400)
    assert len(got.bars) == 400 and asked["since"] == _bar(2600).timestamp
    assert got.bars[-1].source == "databento"

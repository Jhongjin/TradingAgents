"""Reliability of the unattended gold lab sync: bounded steps, a stale-run lock, an
append-only bar file, a review that fills missed days and retries a cut-off reply. No network."""

import json
import os
import subprocess
import sys
import textwrap
import time
from datetime import date, datetime, timedelta, timezone

import pytest

import goldlab.review as R
from goldlab.data import Bar, BarSeries, cache_path, read_cache, update_cache, write_cache

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "automation"))
import goldlab_sync as S  # noqa: E402


def _bar(i, base=100.0, source="yahoo"):
    ts = datetime(2026, 11, 20, tzinfo=timezone.utc) + timedelta(minutes=5 * i)
    return Bar(timestamp=ts, open=base + i, high=base + i + 1, low=base + i - 1, close=base + i + 0.5, volume=10, source=source)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path / "store"))
    return tmp_path / "store"


# ------------------------------------------------------------ the bar file
def test_update_cache_appends_and_rewrites_only_the_tail(store):
    first = BarSeries("GC=F", "5m", tuple(_bar(i) for i in range(100)))
    write_cache(first)
    path = cache_path("GC=F", "5m")
    head = path.read_bytes()[:2000]
    # three new bars, and the last stored bar was still forming
    changed = tuple(_bar(i) for i in range(99)) + (_bar(99, base=100.2),) + tuple(_bar(i) for i in range(100, 103))
    mode = update_cache(first.bars, BarSeries("GC=F", "5m", changed))
    assert mode == "append"
    assert path.read_bytes()[:2000] == head                       # the old rows were not touched
    assert read_cache("GC=F", "5m").bars == changed
    assert update_cache(changed, BarSeries("GC=F", "5m", changed)) == "noop"


def test_update_cache_falls_back_to_a_rewrite_when_history_changed(store):
    first = BarSeries("GC=F", "5m", tuple(_bar(i) for i in range(100)))
    write_cache(first)
    merged = tuple(_bar(3, source="databento") if i == 3 else b for i, b in enumerate(first.bars))
    assert update_cache(first.bars, BarSeries("GC=F", "5m", merged)) == "rewrite"
    assert read_cache("GC=F", "5m").bars == merged
    assert not list(store.glob("*.tmp"))


def test_sync_bars_appends_without_rewriting(store):
    from goldlab.barstore import sync_bars

    write_cache(BarSeries("GC=F", "5m", tuple(_bar(i) for i in range(60))))
    path = cache_path("GC=F", "5m")
    before = path.read_bytes()
    report = sync_bars("GC=F", "5m", fetch=lambda symbol, interval: BarSeries(symbol, interval, tuple(_bar(i) for i in range(55, 64))))
    after = path.read_bytes()
    assert report.added == 4 and after.startswith(before[:-1000])
    assert len(read_cache("GC=F", "5m").bars) == 64


# ------------------------------------------------------------ the process runner
def test_run_killing_tree_returns_in_time_even_if_a_grandchild_holds_the_pipes(tmp_path):
    script = tmp_path / "spawner.py"
    script.write_text(textwrap.dedent("""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        time.sleep(60)
    """), encoding="utf-8")
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        R._run_killing_tree([sys.executable, str(script)], timeout=2, cwd=str(tmp_path))
    assert time.monotonic() - started < 30


def test_a_step_that_never_ends_is_killed_and_the_run_goes_on(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", tmp_path)
    hang = tmp_path / "run.py"
    hang.write_text("import sys, time\nif sys.argv[1] == 'hang':\n    time.sleep(60)\nprint('fine')\n", encoding="utf-8")
    monkeypatch.setattr(S, "RUN", hang)
    started = time.monotonic()
    status, code, _ = S.run_step("GC=F", S.Step("hang", ("hang",), 3), timeout=2, env=dict(os.environ))
    assert status == "timeout" and code is None and time.monotonic() - started < 20
    status, code, _ = S.run_step("GC=F", S.Step("ok", ("fast",), 3), timeout=20, env=dict(os.environ))
    assert (status, code) == ("ok", 0)
    log = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("goldlab-sync-*.log"))
    assert "status=timeout" in log and "status=ok exit=0" in log and "fine" in log


def test_full_run_survives_a_failing_step_and_logs_every_step(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", tmp_path)
    monkeypatch.setattr(S, "LOCK", tmp_path / "x.lock")
    seen = []

    def fake(symbol, step, *, timeout, env):
        seen.append((symbol, step.name))
        return ("failed", 1, 0.1) if step.name == "ledger-scan" else ("ok", 0, 0.1)

    monkeypatch.setattr(S, "run_step", fake)
    assert S.main(["--symbols", "GC=F,NQ=F"]) == 0
    assert len(seen) == 2 * len(S.STEPS)                 # the failure did not stop anything
    text = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("goldlab-sync-*.log"))
    assert "이상 2건" in text and not (tmp_path / "x.lock").exists()


# ------------------------------------------------------------ the lock
def test_lock_blocks_a_young_live_run_but_replaces_a_stale_or_dead_one(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", tmp_path)
    monkeypatch.setattr(S, "LOCK", tmp_path / "x.lock")
    killed = []
    monkeypatch.setattr(S, "kill_tree", lambda pid: killed.append(pid))
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    me = os.getpid()
    mine = S.process_start_time(me)
    now = time.time()

    (tmp_path / "x.lock").write_text(json.dumps({"pid": me, "started": now - 10 * 60, "pid_started": mine}))
    assert S.acquire_lock(now) is False and killed == []        # a live run, 10 minutes old: leave it alone

    (tmp_path / "x.lock").write_text(json.dumps({"pid": me, "started": now - 100 * 60, "pid_started": mine}))
    assert S.acquire_lock(now) is True and killed == [me]       # a live run past 90 minutes: killed, replaced
    assert json.loads((tmp_path / "x.lock").read_text())["started"] == now
    S.release_lock()
    assert not (tmp_path / "x.lock").exists()

    (tmp_path / "x.lock").write_text(json.dumps({"pid": 999999, "started": now - 5 * 60}))
    assert S.acquire_lock(now) is True                           # its process is gone: the leftover lock is cleared
    S.release_lock()


# ------------------------------------------------------------ the review: cut-off reply and backfill
def _truncated_then_ok(good_text):
    calls = []

    def call(system, user):
        calls.append(user)
        if len(calls) == 1:
            return R.LLMReply('```json\n{"summary": [{"text": "잘린', 1000, 12000)
        return R.LLMReply(good_text, 1000, 3000)

    return call, calls


def test_a_cut_off_json_reply_is_asked_again_once_and_both_calls_are_charged():
    call, calls = _truncated_then_ok(json.dumps({"summary": []}))
    who = R.Participant("analyst", "anthropic", "claude-sonnet-5", call)
    budget = R.Budget(5.0)
    turn = R._turn("analyst_final", who, "sys", "user", budget, parse_retries=1)
    assert turn["ok"] and turn["parse_retries_used"] == 1 and len(calls) == 2
    assert "[재요청]" in calls[1] and "[재요청]" not in calls[0]
    assert turn["usage"]["output_tokens"] == 15000 and turn["usage"]["cost_usd"] > 0.18
    assert round(budget.spent, 6) == turn["usage"]["cost_usd"]


def test_a_second_unreadable_reply_still_fails_the_turn_and_keeps_the_raw_text():
    who = R.Participant("analyst", "anthropic", "claude-sonnet-5", lambda s, u: R.LLMReply("not json", 10, 5))
    turn = R._turn("analyst_final", who, "s", "u", R.Budget(5.0), parse_retries=1)
    assert turn["ok"] is False and turn["error"] == "JSON으로 읽을 수 없는 응답" and turn["raw"] == "not json"


def test_analyst_output_cap_is_well_above_the_longest_final_seen():
    assert R.ANALYST_MAX_TOKENS >= 16000


def _day_bars(day):
    start, _end = R.window_for(day)
    return [Bar(timestamp=start + timedelta(minutes=5 * i), open=3900 + i * 0.1, high=3901 + i * 0.1, low=3899 + i * 0.1, close=3900.5 + i * 0.1, volume=100) for i in range(288)]


def test_review_backfills_missed_days_newest_first_and_never_overwrites(monkeypatch):
    import test_goldlab_review as T

    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    monkeypatch.setattr("goldlab.events.macro_events", lambda *a, **k: [])
    days = [date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 14)]
    bars = [b for d in days for b in _day_bars(d)]
    repo = T._repo()
    order = []

    def people():
        pack = T._pack(events=[], upcoming=[])
        return T._people(pack, [])

    # the middle day already has a good note
    first = R.run_review("GC=F", repo=repo, people=people(), now=T.NOW, bars=bars, signals=[], day=days[1])
    assert first["status"] == "ok"
    kept = R.load_record(repo, "GC=F", days[1])["generated_at"]
    written = []
    real_save = R.save_record
    monkeypatch.setattr(R, "save_record", lambda r, rec: (written.append(rec["date"]), real_save(r, rec))[1])
    out = R.run_review("GC=F", repo=repo, people=people(), now=T.NOW, bars=bars, signals=[])
    assert out["date"] == "2026-11-14" and out["status"] == "ok"
    assert written == ["2026-11-14", "2026-11-12"]                # newest first, the 13th untouched
    assert "2026-11-13:exists" in out["backfill"] and "2026-11-12:ok" in out["backfill"]
    assert R.load_record(repo, "GC=F", days[1])["generated_at"] == kept
    assert out["total_cost_usd"] > 0
    again = R.run_review("GC=F", repo=repo, people=people(), now=T.NOW, bars=bars, signals=[])
    assert again["status"] == "exists" and written == ["2026-11-14", "2026-11-12"]


def test_backfill_stops_when_the_daily_budget_is_spent(monkeypatch):
    import test_goldlab_review as T

    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    monkeypatch.setattr("goldlab.events.macro_events", lambda *a, **k: [])
    days = [date(2026, 11, 13), date(2026, 11, 14)]
    bars = [b for d in days for b in _day_bars(d)]
    repo = T._repo()
    out = R.run_review("GC=F", repo=repo, people=T._people(T._pack(events=[], upcoming=[]), []), now=T.NOW, bars=bars, signals=[], max_usd=0.0)
    assert out["status"] == "budget" and out["date"] == "2026-11-14" and R.list_records(repo, "GC=F") == []


def test_trading_review_days_skips_weekends_and_caps_the_count():
    days = [date(2026, 11, 9) + timedelta(days=i) for i in range(6)]       # Mon..Sat review days
    bars = [b for d in days if d.weekday() < 5 or d.weekday() == 5 for b in _day_bars(d)]
    now = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)
    got = R.trading_review_days(bars, now, count=3)
    assert got == sorted(got) and len(got) == 3 and got[-1] == date(2026, 11, 14)

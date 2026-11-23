"""The personal trade journal: grading math, point-in-time context, write protection, the page, the review note. No network."""

import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest

import goldlab.journal as J
import goldlab.review as R
from goldlab.contracts import GOLD_FUTURES, NASDAQ_FUTURES
from goldlab.data import Bar, BarSeries, write_cache

T0 = datetime(2026, 11, 13, 2, 7, tzinfo=timezone.utc)          # inside the 02:05 bar
NOW = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)


def bar(i, o, h, l, c, base=datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc)):
    return Bar(timestamp=base + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c, volume=10)


def flat_bars(start=-60, end=400, price=2000.0, base=datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc)):
    return [bar(i, price, price + 0.5, price - 0.5, price, base) for i in range(start, end)]


def entry(**over):
    raw = {"symbol": "GC=F", "side": "long", "entry_ts": T0.isoformat(), "entry_price": 2000.0, "stop": 1995.0, "target": 2010.0, "contracts": 2, "tags": ["돌파"], "reason": "테스트"}
    raw.update(over)
    return J.clean_entry(raw, now=NOW)


def with_bar(bars, index, o, h, l, c):
    out = list(bars)
    pos = next(i for i, b in enumerate(out) if b.timestamp == bar(index, 0, 0, 0, 0).timestamp)
    out[pos] = bar(index, o, h, l, c)
    return out


# ----------------------------------------------------------------- grading math
def test_long_hits_target_and_money_is_net_of_slippage_and_commission():
    bars = with_bar(flat_bars(), 4, 2001, 2011, 2000, 2010)         # the 02:20 bar reaches 2010
    g = J.grade_entry(entry(), bars, now=NOW)
    assert g["status"] == "closed" and g["exit_reason"] == "target" and g["result"] == "win"
    expect = GOLD_FUTURES.pnl(2000.0, 2010.0, contracts=2, long=True)
    assert g["net_usd"] == round(expect, 2) == 1950.0                # 9.8 pt * $100 * 2 - $10 commission
    assert g["gross_usd"] == 2000.0 and g["cost_usd"] == 50.0
    assert g["risk_usd"] == 1000.0 and g["r_net"] == 1.95 and g["r_gross"] == 2.0
    assert g["mfe_points"] == 11.0 and g["mae_points"] == 0.5        # the bars before it dipped 0.5 under the entry
    assert g["plan_first"] == "target"


def test_the_entry_bar_itself_is_not_used_and_a_tie_goes_to_the_stop():
    wild = with_bar(flat_bars(), 1, 2000, 2050, 1950, 2000)          # the 02:05 bar holds the entry: ignored
    wild = with_bar(wild, 2, 2000, 2012, 1990, 2005)                 # the next bar touches both stop and target
    g = J.grade_entry(entry(), wild, now=NOW)
    assert g["exit_reason"] == "stop" and g["plan_ambiguous"] is True and g["result"] == "loss"
    assert g["exit_price"] == 1995.0 and g["r_net"] < -1.0           # costs make a full stop worse than -1R
    assert any("스톱으로 처리" in n for n in g["notes"])


def test_short_on_nq_uses_the_nq_multiplier_and_stop_above():
    e = entry(symbol="NQ=F", side="short", entry_price=25000.0, stop=25040.0, target=24900.0, contracts=1)
    bars = with_bar(flat_bars(price=25000.0), 3, 25000, 25045, 24999, 25020)
    g = J.grade_entry(e, bars, now=NOW)
    assert g["exit_reason"] == "stop" and g["exit_price"] == 25040.0
    assert g["net_usd"] == round(NASDAQ_FUTURES.pnl(25000.0, 25040.0, contracts=1, long=False), 2)
    assert g["risk_points"] == 40.0 and g["risk_usd"] == 800.0


def test_manual_exit_is_graded_at_the_users_price_and_flags_a_stop_he_ignored():
    bars = with_bar(flat_bars(), 3, 2000, 2001, 1990, 1996)          # 02:15 bar trades through the 1995 stop
    e = entry(exit_ts=(T0 + timedelta(minutes=40)).isoformat(), exit_price=1998.0)
    g = J.grade_entry(e, bars, now=NOW)
    assert g["exit_reason"] == "manual" and g["exit_price"] == 1998.0
    assert g["plan_first"] == "stop"
    assert g["net_usd"] == round(GOLD_FUTURES.pnl(2000.0, 1998.0, contracts=2, long=True), 2)
    assert any("먼저 닿은 뒤 직접 종료" in n for n in g["notes"])


def test_manual_exit_ignores_the_bar_the_exit_fell_in():
    bars = with_bar(flat_bars(), 4, 2000, 2030, 1999, 2020)          # 02:20 bar spikes, but the exit is at 02:22
    e = entry(exit_ts=(datetime(2026, 11, 13, 2, 22, tzinfo=timezone.utc)).isoformat(), exit_price=2001.0)
    g = J.grade_entry(e, bars, now=NOW)
    assert g["mfe_points"] == 1.0 and g["plan_first"] == "none"       # the 2030 high came after the exit


def test_open_trade_is_marked_to_the_last_close_and_closed_by_horizon_later():
    bars = flat_bars(end=10, price=2003.0)                            # only bars up to 02:45
    soon = J.grade_entry(entry(), bars, now=datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc))
    assert soon["status"] == "open" and soon["result"] == "open" and soon["last_price"] == 2003.0
    assert soon["net_usd"] == round(GOLD_FUTURES.pnl(2000.0, 2003.0, contracts=2, long=True), 2)
    later = J.grade_entry(entry(horizon_bars=12), flat_bars(price=2003.0), now=datetime(2026, 11, 13, 4, 0, tzinfo=timezone.utc))
    assert later["status"] == "closed" and later["exit_reason"] == "horizon" and later["exit_price"] == 2003.0


def test_watching_is_graded_by_what_the_market_did_not_by_money():
    bars = with_bar(flat_bars(), 6, 2000, 2020, 1990, 2012)
    g = J.grade_entry(entry(side="flat", stop=None, target=None, horizon_bars=12), bars, now=NOW)
    assert g["result"] == "watch" and g["status"] == "closed" and g["up_max_points"] >= 20.0 and "net_usd" not in g
    st = J.journal_stats([(entry(side="flat", stop=None, target=None), g)])
    assert st["total"]["watch"] == 1 and st["total"]["n"] == 0


def test_stats_count_wins_by_tag_and_mark_small_samples():
    win = J.grade_entry(entry(tags=["돌파", "뉴스"]), with_bar(flat_bars(), 4, 2001, 2011, 2000, 2010), now=NOW)
    loss = J.grade_entry(entry(tags=["돌파"]), with_bar(flat_bars(), 4, 2000, 2001, 1990, 1994), now=NOW)
    stats = J.journal_stats([(entry(tags=["돌파", "뉴스"]), win), (entry(tags=["돌파"]), loss)])
    assert stats["total"]["n"] == 2 and stats["total"]["wins"] == 1 and stats["total"]["hit_rate"] == 0.5 and stats["total"]["small_sample"]
    assert stats["by_tag"]["돌파"]["n"] == 2 and stats["by_tag"]["뉴스"]["n"] == 1
    assert stats["total"]["net_usd"] == round(win["net_usd"] + loss["net_usd"], 2)


# ----------------------------------------------------------------- validation
@pytest.mark.parametrize(
    "over,needle",
    [
        ({"stop": 2001.0}, "롱의 스톱"),
        ({"target": 1999.0}, "롱의 목표"),
        ({"side": "short", "stop": 1990.0, "target": 1990.0}, "숏의 스톱"),
        ({"entry_ts": (NOW + timedelta(hours=2)).isoformat()}, "미래"),
        ({"symbol": "ES=F"}, "종목"),
        ({"entry_price": -1}, "0보다"),
        ({"exit_ts": (T0 + timedelta(hours=1)).isoformat()}, "함께"),
        ({"side": "flat", "exit_ts": (T0 + timedelta(hours=1)).isoformat(), "exit_price": 2000.0}, "관망"),
        ({"contracts": 500}, "계약 수"),
    ],
)
def test_bad_entries_are_refused_with_a_korean_reason(over, needle):
    with pytest.raises(J.JournalError) as err:
        entry(**over)
    assert needle in str(err.value)


def test_a_typo_price_is_caught_against_the_bars():
    e = entry(entry_price=200.0, stop=190.0, target=210.0)
    with pytest.raises(J.JournalError):
        J.check_price_against_bars(e, flat_bars())
    J.check_price_against_bars(entry(), flat_bars())


def test_tags_are_trimmed_deduplicated_and_capped():
    assert J.clean_tags(["  돌파 ", "돌파", "x" * 40, "a", "b", "c", "d", "e"]) == ["돌파", "x" * 12, "a", "b", "c", "d"]


# ----------------------------------------------------------------- point in time
def _signal(minutes_from_open, direction="bullish"):
    ts = datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes_from_open)
    return {"id": f"s{minutes_from_open}", "ts": ts.isoformat(), "pattern": "doji", "label": "도지", "direction": direction, "claim": {"12": {"win_rate": 0.51}}}


def test_snapshot_uses_only_what_was_known_before_the_entry_bar():
    e = entry()
    spike = [b if b.timestamp < datetime(2026, 11, 13, 2, 5, tzinfo=timezone.utc) else bar(int((b.timestamp - datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc)).total_seconds() // 300), 3000, 3100, 2900, 3050) for b in flat_bars()]
    signals = [_signal(-10), _signal(-5, "bearish"), _signal(0), _signal(5), _signal(30)]        # 02:00 bar is the last one before the 02:05 entry bar
    analogs_late = {"analogs": [{}], "last_bar": "2026-11-13T02:05:00+00:00", "computed_at": "2026-11-13T03:00:00+00:00", "horizons": [4], "summary": {"4": {"n": 10, "up": 7, "down": 3, "share_up": 0.7, "median": 0.001}}}
    a = J.lab_snapshot(e, flat_bars(), signals, analogs_late, now=NOW)
    b = J.lab_snapshot(e, spike, signals, analogs_late, now=NOW)
    assert a["context"] == b["context"] and a["bar_before"] == "2026-11-13T02:00:00+00:00"          # the post-entry spike changed nothing
    assert [s["ts"][11:16] for s in a["signals"]] == ["02:00", "01:55", "01:50"] and a["signal_counts"] == {"bullish": 2, "bearish": 1}
    assert a["analogs"] is None and any("닮은 차트" in n for n in a["notes"])                        # computed after the entry: dropped
    early = dict(analogs_late, last_bar="2026-11-13T01:55:00+00:00", computed_at="2026-11-13T01:58:00+00:00")
    assert J.lab_snapshot(e, flat_bars(), signals, early, now=NOW)["analogs"]["summary"]["4"]["share_up"] == 0.7


def test_alignment_reads_trend_and_signals_against_the_side():
    lab = {"signal_counts": {"bullish": 3, "bearish": 1}, "context": {"trend": "down"}}
    al = J.alignment({"side": "long", "tags": ["추세추종"]}, lab)
    assert al["signals"] == "agree" and al["trend"] == "against" and al["tag_flags"]
    assert J.alignment({"side": "short", "tags": ["역추세"]}, {"signal_counts": {}, "context": {"trend": "down"}})["tag_flags"] == ["역추세라 적었지만 그 시각 추세 태그는 같은 방향"]


# ----------------------------------------------------------------- storage, auth, page
def _repo():
    from tradingagents.storage import StorageRepository, create_storage_engine

    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _bar_rows(bars):
    return [{"ts": b.timestamp, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume, "source": "yahoo"} for b in bars]


def test_entries_round_trip_in_the_private_table_and_a_snapshot_is_attached(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path))
    repo = _repo()
    repo.goldlab_upsert_bars("GC=F", "5m", _bar_rows(flat_bars(-400, 400)))
    made = J.create_entry(repo, {"symbol": "GC=F", "side": "long", "entry_ts": T0.isoformat(), "entry_price": 2000.2, "stop": 1995, "tags": ["추세추종"]}, now=NOW)
    assert made["lab"]["bar_before"] and made["lab"]["context"]["trend"] in ("up", "down", "range")
    again = repo.goldlab_journal_get(made["id"])
    assert again["entry_price"] == 2000.2 and again["lab"]["captured_at"] and again["tags"] == ["추세추종"]
    closed = J.update_entry(repo, made["id"], {"exit_ts": (T0 + timedelta(hours=1)).isoformat(), "exit_price": 2004.0}, now=NOW)
    assert closed["exit_price"] == 2004.0 and closed["lab"] == made["lab"]                # an edit does not redo the snapshot
    listed = J.graded_list(repo, "GC=F", now=NOW, with_fresh=False)
    assert listed["entries"][0]["grade"]["exit_reason"] == "manual" and listed["stats"]["total"]["n"] == 1
    assert repo.goldlab_journal_delete(made["id"]) is True and repo.goldlab_journal_list("GC=F") == []
    with pytest.raises(J.JournalError):
        J.create_entry(repo, {"symbol": "GC=F", "side": "long", "entry_ts": T0.isoformat(), "entry_price": 20.0}, now=NOW)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tradingagents.site import create_app

    monkeypatch.setenv("GOLDLAB_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret-token")
    monkeypatch.setattr(J, "fresh_bars", lambda symbol: [])
    repo = _repo()
    repo.goldlab_upsert_bars("GC=F", "5m", _bar_rows(flat_bars(-400, 400)))
    app = create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=False)
    return TestClient(app), repo


BODY = {"symbol": "GC=F", "side": "long", "entry_ts": T0.isoformat(), "entry_price": 2000.0, "stop": 1995, "target": 2010, "reason": "비밀 이유 XYZ"}


def test_writes_and_reads_need_the_operator_token(client):
    http, repo = client
    path = "/api/admin/lab/gold/journal"
    assert http.post(path, json=BODY).status_code == 401
    assert http.get(path).status_code == 401
    assert http.post(path, json=BODY, headers={"X-TradingAgents-Worker-Token": "wrong"}).status_code == 403
    assert http.delete(path + "/abc").status_code == 401
    assert http.patch(path + "/abc", json={"reason": "x"}).status_code == 401
    assert repo.goldlab_journal_list() == []
    good = {"X-TradingAgents-Worker-Token": "secret-token"}
    made = http.post(path, json=BODY, headers=good)
    assert made.status_code == 200, made.text
    entry_id = made.json()["entry"]["id"]
    listing = http.get(path, headers=good).json()
    assert listing["entries"][0]["id"] == entry_id and listing["entries"][0]["grade"]["status"] in ("open", "closed")
    assert http.patch(f"{path}/{entry_id}", json={"reason": "바꿈"}, headers=good).json()["entry"]["reason"] == "바꿈"
    assert http.post(path, json={**BODY, "stop": 2001}, headers=good).status_code == 400
    assert http.delete(f"{path}/{entry_id}", headers=good).status_code == 200
    assert http.delete(f"{path}/{entry_id}", headers=good).status_code == 404


def test_no_configured_token_means_the_journal_is_closed(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tradingagents.site import create_app

    for name in ("TRADINGAGENTS_WORKER_TOKEN", "DASHBOARD_ADMIN_TOKEN", "OPERATOR_ACCESS_CODE", "CRON_SECRET"):
        monkeypatch.delenv(name, raising=False)
    http = TestClient(create_app(repo=_repo(), load_repo_from_env=False, trust_member_user_header=False))
    assert http.post("/api/admin/lab/gold/journal", json=BODY).status_code in (401, 503)
    assert http.get("/api/admin/lab/gold/journal", headers={"X-TradingAgents-Worker-Token": "anything"}).status_code in (403, 503)


def test_page_renders_with_and_without_entries_and_never_inlines_them(client, monkeypatch):
    import goldlab.data as data

    http, repo = client
    series = BarSeries("GC=F", "1h", tuple(Bar(timestamp=datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(hours=i), open=2000 + i % 7, high=2003 + i % 7, low=1997 + i % 7, close=2001 + i % 5, volume=5) for i in range(400)))
    monkeypatch.setattr(data, "fetch_bars", lambda symbol="GC=F", *, interval="1h", days=None: series)
    empty = http.get("/lab/gold?symbol=GC=F&interval=1h")
    assert empty.status_code == 200 and 'id="jcard"' in empty.text and "내 판단 기록" in empty.text and 'id="jform"' in empty.text
    assert "X-TradingAgents-Worker-Token" in empty.text and "tradingagents.admin.worker_token" in empty.text
    good = {"X-TradingAgents-Worker-Token": "secret-token"}
    assert http.post("/api/admin/lab/gold/journal", json=BODY, headers=good).status_code == 200
    full = http.get("/lab/gold?symbol=GC=F&interval=1h")
    assert full.status_code == 200 and "비밀 이유 XYZ" not in full.text                 # the page is a shell; entries come only with the code
    from goldlab.chart import render_chart

    static = render_chart({"1h": http.get("/lab/gold/data?interval=1h").json()}, symbol="GC=F", default_interval="1h", intervals=["1h"], data_url=None, bars=300)
    assert 'id="jcard"' not in static                                                      # a static file has no API to write to


# ----------------------------------------------------------------- the review note
DAY = date(2026, 11, 13)
WIN_START, WIN_END = R.window_for(DAY)


def _day_rows(repo):
    base = WIN_START
    bars = [Bar(timestamp=base + timedelta(minutes=5 * i), open=2000 + (i % 5), high=2002 + (i % 5), low=1998 + (i % 5), close=2001 + (i % 5), volume=10) for i in range(288)]
    repo.goldlab_upsert_bars("GC=F", "5m", _bar_rows(bars))
    return bars


def _graded_rows(repo, bars):
    e = J.clean_entry({"symbol": "GC=F", "side": "long", "entry_ts": (WIN_START + timedelta(hours=4, minutes=2)).isoformat(), "entry_price": 2001.0, "stop": 1996.0, "target": 2020.0, "tags": ["돌파", "뉴스"], "reason": "발표 직후 돌파", "contracts": 1}, now=NOW)
    e["lab"] = J.lab_snapshot(e, bars, [], None, now=NOW)
    repo.goldlab_journal_save(e)
    return J.graded_list(repo, "GC=F", now=NOW, with_fresh=False)["entries"]


def test_the_evidence_pack_gets_the_days_calls_last_and_ids_of_the_rest_do_not_move(monkeypatch):
    import test_goldlab_review as T

    monkeypatch.setattr("goldlab.events.macro_events", lambda *a, **k: [])
    repo = _repo()
    bars = _day_rows(repo)
    rows = _graded_rows(repo, bars)
    base = R.build_evidence("GC=F", DAY, bars=bars, signals=[], events=[], upcoming=[], now=NOW)
    pack = R.build_evidence("GC=F", DAY, bars=bars, signals=[], events=[], upcoming=[], now=NOW, journal=rows, journal_recent={**J.journal_stats([(r, r["grade"]) for r in rows]), "days": 30})
    assert [i["text"] for i in pack["items"][: len(base["items"])]] == [i["text"] for i in base["items"]]
    keys = pack["keys"]
    assert "journal_summary" in keys and f"journal_{rows[0]['id']}" in keys and "journal_tags" in keys and pack["journal"] == 1
    text = {i["id"]: i["text"] for i in pack["items"]}[keys[f"journal_{rows[0]['id']}"]]
    assert "롱 기록" in text and "발표 직후 돌파" in text and "슬리피지" not in text
    assert not R._ADVICE.search(" ".join(i["text"] for i in pack["items"] if i["key"].startswith("journal")))     # wording avoids what the guard reads as advice
    assert "journal_summary" not in base["keys"]


class JournalFake:
    """Scripts the analyst's journal section; defers everything else to the review test's fake."""

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, system, user):
        reply = self.inner(system, user)
        if "[내 판단 기록이 있는 날]" not in user:
            return reply
        match = re.search(r"\[(E\d+)\] 내 판단 기록:", user)
        body = json.loads(reply.text)
        body["journal"] = [
            {"text": "롱 기록은 종료 전이고 비용 뺀 손익은 기록돼 있다", "evidence": [match.group(1)]},
            {"text": "고가는 9,999.9까지 갔다", "evidence": [match.group(1)]},
        ]
        return R.LLMReply(json.dumps(body, ensure_ascii=False), reply.input_tokens, reply.output_tokens)


def test_the_note_gets_a_journal_section_only_on_days_with_a_call(monkeypatch):
    import test_goldlab_review as T

    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    monkeypatch.setattr("goldlab.events.macro_events", lambda *a, **k: [])
    repo = _repo()
    bars = _day_rows(repo)
    seen = []

    def people():
        built = T._people(T._pack(events=[], upcoming=[]), [])
        analyst = built["analyst"]
        built["analyst"] = R.Participant("analyst", analyst.provider, analyst.model, lambda s, u: (seen.append(u), JournalFake(analyst.call)(s, u))[1])
        return built

    quiet = R.run_review("GC=F", repo=repo, people=people(), now=NOW, day=DAY, bars=bars, signals=[])
    assert quiet["status"] == "ok" and not any("[내 판단 기록이 있는 날]" in u for u in seen)
    plain = R.load_record(repo, "GC=F", DAY)
    assert "내 판단 복기" not in plain["text"] and plain["sections"].get("journal") == []

    _graded_rows(repo, bars)
    seen.clear()
    out = R.run_review("GC=F", repo=repo, people=people(), now=NOW, day=DAY, bars=bars, signals=[], force=True)
    assert out["status"] == "ok"
    note = R.load_record(repo, "GC=F", DAY)
    assert any("[내 판단 기록이 있는 날]" in u for u in seen)
    assert "내 판단 복기" in note["text"] and note["sections"]["journal"]
    kept = [i["text"] for i in note["sections"]["journal"]]
    assert kept == ["롱 기록은 종료 전이고 비용 뺀 손익은 기록돼 있다"]                       # the invented 9,999.9 was removed by the numeric guard
    assert any("9,999.9" in r["numbers"] for r in note["guard"]["removed"] if r.get("section") == "journal")
    ids = {i["key"]: i["id"] for i in note["evidence"]["items"]}
    assert note["sections"]["journal"][0]["evidence"] == [ids["journal_summary"]]
    page = R.page_payload(note)
    assert page["sections"]["journal"] and "journal_summary" in note["evidence"]["keys"]

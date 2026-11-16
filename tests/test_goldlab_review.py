"""The AI review note: a code-built evidence pack, a four-turn debate, a numeric guard. No network."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

import goldlab.review as R
from goldlab.data import Bar

DAY = date(2026, 11, 14)                       # KST day whose window is Fri 11-13 07:00 -> Sat 11-14 07:00 KST
START, END = R.window_for(DAY)
NOW = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)   # Monday 10:00 KST


def _bars(start=START, count=288, base=3900.0):
    rows = []
    for i in range(count):
        price = base + (i % 40) * 0.7 - (i // 40) * 0.2
        rows.append(Bar(timestamp=start + timedelta(minutes=5 * i), open=price, high=price + 1.2, low=price - 1.1, close=price + 0.3, volume=100))
    return rows


def _signal(i, pattern="inside_bar", direction="bullish", hit=True, hours=3, graded=(4, 12, 24), session="us", claim=0.5):
    ts = START + timedelta(hours=hours, minutes=5 * i)
    grades = {str(h): {"return": 0.001 if hit else -0.001, "hit": hit, "mfe": 0.002, "mae": -0.001} for h in graded}
    return {
        "id": f"GC=F|5m|{pattern}|{ts:%Y%m%dT%H%M%SZ}", "ts": ts.isoformat(), "pattern": pattern, "direction": direction, "label": "인사이드 바",
        "context": {"session": session, "trend": "range", "vol": "mid", "event": "far"}, "origin": "live",
        "claim": {"12": {"win_rate": claim, "count": 500}}, "grades": grades,
    }


def _study():
    return {
        "bars": 766182, "start": "2016-01-03T23:00:00+00:00", "end": "2026-11-13T14:30:00+00:00", "fdr": {"q": 0.1, "tested": 1110, "survivors": 17},
        "base_rate": {"12": {"long": {"win_rate": 0.4962}, "short": {"win_rate": 0.4800}}},
        "patterns": [{"pattern": "inside_bar", "label": "인사이드 바", "horizons": {"12": {"count": 5000, "win_rate": 0.5, "base_win_rate": 0.4962, "fdr_significant": False, "shrunk_edge_win_rate": 0.0003}}}],
    }


def _signals():
    out = [_signal(i, hit=i % 2 == 0) for i in range(8)]
    out += [_signal(20 + i, pattern="doji", direction="bearish", hit=False, graded=(4,), session="asia") for i in range(3)]
    return out


def _pack(**over):
    args = dict(bars=_bars(), signals=_signals(), study=_study(), study_1h=_study(), analogs=None, events=[], upcoming=[], now=NOW)
    args.update(over)
    return R.build_evidence("GC=F", DAY, **args)


@pytest.fixture(autouse=True)
def _no_retries(monkeypatch):
    monkeypatch.setattr(R, "RETRIES", 0)
    monkeypatch.setattr(R, "RETRY_DELAY", 0)


# ----------------------------------------------------------------- window / day
def test_review_day_window_is_the_kst_morning_to_morning():
    assert START == datetime(2026, 11, 12, 22, 0, tzinfo=timezone.utc) and END == datetime(2026, 11, 13, 22, 0, tzinfo=timezone.utc)
    assert R.latest_review_day(datetime(2026, 11, 16, 21, 59, tzinfo=timezone.utc)) == date(2026, 11, 16)
    assert R.latest_review_day(datetime(2026, 11, 16, 22, 0, tzinfo=timezone.utc)) == date(2026, 11, 17)
    assert R.latest_review_day(datetime(2026, 11, 16, 21, 0, tzinfo=timezone.utc)) == date(2026, 11, 16)


def test_a_weekend_review_day_falls_back_to_the_last_trading_day():
    assert R.pick_review_day(_bars(), NOW) == DAY                      # Monday morning: Sat/Sun windows have no bars
    assert R.pick_review_day([], NOW) is None


# ----------------------------------------------------------------- evidence
def test_evidence_ids_are_stable_and_unique():
    first, second = _pack(), _pack()
    assert first == second
    ids = [item["id"] for item in first["items"]]
    assert ids == [f"E{i}" for i in range(1, len(ids) + 1)]
    assert len(set(first["keys"])) == len(first["keys"])
    # different prices, same structure: the same facts keep the same ids
    other = _pack(bars=_bars(base=2100.0))
    assert other["keys"] == first["keys"] and other["items"][1]["text"] != first["items"][1]["text"]


def test_evidence_carries_prices_signals_drift_and_study():
    pack = _pack()
    keys, text = pack["keys"], {i["id"]: i["text"] for i in pack["items"]}
    assert {"meta", "price", "signals_total", "drift", "div_summary", "study_5분봉", "study_1시간봉"} <= set(keys)
    assert "하루 신호 11건" in text[keys["signals_total"]]
    assert "4봉 뒤 채점 11건 중 맞음 4건" in text[keys["signals_total"]]       # 4 even-index hits out of 8; the 3 doji missed
    assert "12봉 뒤 맞음 4/8" in text[keys["sig_inside_bar_bullish"]]
    assert "미국장 구간" in "".join(text[keys[k]] for k in keys if k.startswith("session_"))
    assert "1,110칸" in text[keys["study_5분봉"]]
    assert pack["bars"] == 288 and pack["signals"] == 11


def test_evidence_without_data_still_has_a_pack():
    pack = _pack(bars=[], signals=[], study=None, study_1h=None)
    assert "봉이 없습니다" in "".join(i["text"] for i in pack["items"])


def test_signals_outside_the_window_are_not_the_days():
    old = _signal(0, hours=-40)
    pack = _pack(signals=_signals() + [old])
    assert pack["signals"] == 11


# ----------------------------------------------------------------- numeric guard
def test_guard_strips_invented_numbers_and_keeps_formatting_variants():
    pack = _pack()
    allowed = R.pack_numbers(pack)
    price_text = {i["id"]: i["text"] for i in pack["items"]}[pack["keys"]["price"]]
    close = [t for t, _v, _d in R.extract_numbers(price_text)][3]            # a real number from the pack, e.g. 3,9xx.x
    text = f"종가는 {close}였다. 종가는 {close.replace(',', '')}였다. 고가는 4,321.0까지 갔다. 맞음 비율은 83%였다. 신호는 11건이었다 [E3]."
    kept, removed = R.guard_text(text, allowed)
    assert "4,321.0" not in kept and "83%" not in kept
    assert "신호는 11건" in kept and kept.count(close.replace(",", "")) >= 1 and close in kept
    assert [r["numbers"] for r in removed] == [["4,321.0"], ["83"]]


def test_guard_accepts_rounded_percent_and_rejects_small_invented_integers():
    allowed = [47.3, 0.5, 12.0, 3.0]
    assert R.number_allowed(47, 0, allowed) and R.number_allowed(0.47, 2, [47.3]) and R.number_allowed(47.3, 1, allowed)
    assert not R.number_allowed(7, 0, allowed) and not R.number_allowed(99.9, 1, allowed)
    assert R.number_allowed(12, 0, allowed)


def test_guard_ignores_evidence_tags_and_drops_trade_advice():
    kept, removed = R.guard_text("신호는 많았다 [E12]. 지금 매수하는 편이 좋다. 내일은 오를 것이다. 표본이 작다.", [])
    assert kept == "신호는 많았다 [E12]. 표본이 작다."
    assert [r["reason"] for r in removed] == ["거래 권유 또는 방향 단정으로 읽히는 표현"] * 2


def test_clean_statements_drop_unknown_evidence_ids():
    kept, dropped = R.clean_statements([{"text": "가", "evidence": ["E1", "E99"]}, {"text": "나", "evidence": ["E99"]}, "다"], {"E1"})
    assert kept == [{"text": "가", "evidence": ["E1"]}] and len(dropped) == 2


# ----------------------------------------------------------------- the debate
class Fake:
    """A scripted model. ``script`` maps a marker found in the prompt to the reply."""

    def __init__(self, role, provider, model, pack, log, fail=False, bad_json=False):
        self.pack, self.log, self.fail, self.bad_json = pack, log, fail, bad_json
        self.participant = R.Participant(role, provider, model, self.call)
        self.calls = 0

    def sec(self, text, *ids):
        return [{"text": text, "evidence": list(ids)}]

    def call(self, system, user):
        self.calls += 1
        self.log.append(self.participant.provider)
        if self.fail:
            raise RuntimeError("provider down")
        if self.bad_json:
            return R.LLMReply("이건 JSON이 아닙니다", 100, 10)
        k = self.pack["keys"]
        price, sig = k["price"], k["signals_total"]
        if "비판자입니다" in user or "당신은 비판자" in user:
            body = {
                "challenges": [{"type": "작은표본", "target": "신호", "text": "채점된 신호가 적다", "evidence": [sig]}],
                "hypotheses": [
                    {"text": "패턴 인사이드 바는 미국장에서 12봉 뒤 기준보다 높다", "pattern": "inside_bar", "context": {"session": "us"}, "horizon": 12},
                    {"text": "알 수 없는 패턴", "pattern": "nope", "horizon": 7},
                ],
            }
        elif "검증자입니다" in user or "당신은 검증자" in user:
            body = {"checked": 6, "problems": [{"source": "draft", "text": "고가는 4,321.0까지 갔다", "status": "unsupported", "reason": "팩에 없음", "evidence": [price]}], "overall": "대체로 맞음"}
        elif "초안을 쓴 분석가" in user:
            body = {
                "summary": self.sec("종가 흐름을 정리했다", price),
                "signals": self.sec(f"신호는 11건이었다", sig) + self.sec("고가는 4,321.0까지 갔다", price),
                "context": self.sec("표본이 작아 해석하기 어렵다", sig),
                "drift": self.sec("최근 기록과 10년 기록을 비교했다", k["drift"]),
                "watch": self.sec("내일은 예정된 지표가 있는지 본다", k["upcoming_none"]),
                "dissent": self.sec("비판자는 표본이 작다고 지적했다", sig),
            }
        else:
            body = {
                "summary": self.sec("종가 흐름을 정리했다", price),
                "signals": self.sec("신호는 11건이었다", sig) + self.sec("고가는 4,321.0까지 갔다", price),
                "context": self.sec("표본이 작다", sig),
                "drift": self.sec("기록을 비교했다", k["drift"]),
                "watch": self.sec("예정된 지표를 본다", k["upcoming_none"]),
            }
        return R.LLMReply(json.dumps(body, ensure_ascii=False), 3000, 800)


def _people(pack, log, **fail):
    return {
        "analyst": Fake("analyst", "anthropic", "claude-sonnet-5", pack, log, **fail.get("analyst", {})).participant,
        "critic": Fake("critic", "openai", "gpt-5.4", pack, log, **fail.get("critic", {})).participant,
        "verifier": Fake("verifier", "google", "gemini-3.5-flash", pack, log, **fail.get("verifier", {})).participant,
    }


def test_debate_runs_four_turns_in_order_and_the_guard_removes_the_invented_number():
    pack, log = _pack(), []
    debate = R.run_debate(pack, _people(pack, log), R.Budget(5.0))
    assert log == ["anthropic", "openai", "google", "anthropic"]
    assert [t["turn"] for t in debate["turns"]] == ["analyst_draft", "critic", "verifier", "analyst_final"]
    note = R.assemble_note("GC=F", str(DAY), pack, debate, people=_people(pack, []), now=NOW, run_day="2026-11-16")
    assert note["mode"] == "debate" and note["status"] == "ok"
    texts = [i["text"] for items in note["sections"].values() for i in items]
    assert not any("4,321.0" in t for t in texts) and "신호는 11건이었다" in texts
    assert any("4,321.0" in r["numbers"] for r in note["guard"]["removed"])
    assert note["text"].rstrip().endswith("과거 기록 복기이며 거래 권유가 아닙니다")
    assert [h["status"] for h in note["hypotheses"]] == ["미검증", "미검증"]
    assert [h["expressible"] for h in note["hypotheses"]] == [True, False]
    assert note["hypotheses"][0]["spec"] == {"pattern": "inside_bar", "horizon": 12, "context": {"session": "us"}, "direction": "higher"}
    assert note["usage"]["cost_usd"] > 0 and set(note["usage"]["by_model"]) == {"anthropic:claude-sonnet-5", "openai:gpt-5.4", "google:gemini-3.5-flash"}
    assert note["models"]["critic"] == "openai:gpt-5.4"


def test_critic_failure_publishes_a_solo_note():
    pack, log = _pack(), []
    debate = R.run_debate(pack, _people(pack, log, critic={"fail": True}), R.Budget(5.0))
    note = R.assemble_note("GC=F", str(DAY), pack, debate, people=_people(pack, []), now=NOW, run_day="d")
    assert note["mode"] == "solo" and "단독 작성" in note["mode_line"] and "비판 생략" in note["degraded"]
    assert note["hypotheses"] == [] and log == ["anthropic", "openai", "google", "anthropic"]


def test_verifier_and_final_failures_degrade_without_stopping():
    pack = _pack()
    debate = R.run_debate(pack, _people(pack, [], verifier={"bad_json": True}), R.Budget(5.0))
    assert "검증 생략" in debate["degraded"] and debate["turns"][-1]["ok"]
    # the analyst fails only on its second call (the final rewrite): the draft, minus what the verifier flagged, stands
    people = _people(pack, [])
    first = people["analyst"].call
    state = {"n": 0}

    def flaky(system, user):
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("down")
        return first(system, user)

    people["analyst"] = R.Participant("analyst", "anthropic", "claude-sonnet-5", flaky)
    debate = R.run_debate(pack, people, R.Budget(5.0))
    assert any("최종 재작성 실패" in d for d in debate["degraded"])
    assert not any("4,321.0" in i["text"] for items in debate["sections"].values() for i in items)


def test_a_transient_provider_error_is_retried_once(monkeypatch):
    monkeypatch.setattr(R, "RETRIES", 1)
    pack, log = _pack(), []
    people = _people(pack, log)
    inner, state = people["verifier"].call, {"n": 0}

    def flaky(system, user):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("503 UNAVAILABLE")
        return inner(system, user)

    people["verifier"] = R.Participant("verifier", "google", "gemini-3.5-flash", flaky)
    debate = R.run_debate(pack, people, R.Budget(5.0))
    assert debate["turns"][2]["ok"] and state["n"] == 2 and "검증 생략" not in debate["degraded"]


def test_analyst_failure_gives_no_note():
    pack = _pack()
    debate = R.run_debate(pack, _people(pack, [], analyst={"fail": True}), R.Budget(5.0))
    assert debate["ok"] is False and len(debate["turns"]) == 1


def test_budget_stops_the_debate_before_the_next_call():
    pack, log = _pack(), []
    # enough for the analyst draft only: its estimate plus a little
    draft_estimate = ((len(R.SYSTEM_COMMON) + len(R.ANALYST_DRAFT.format(pack=R.pack_text(pack)))) / 1.2 * 3.0 + 5500 * 15.0) / 1_000_000
    debate = R.run_debate(pack, _people(pack, log), R.Budget(draft_estimate + 0.005))
    assert log[0] == "anthropic" and len(log) < 4
    assert any(t.get("skipped") for t in debate["turns"])
    none = R.run_debate(pack, _people(pack, []), R.Budget(0.0))
    assert none["ok"] is False and none["turns"][0]["skipped"]


# ----------------------------------------------------------------- storage, idempotence, serving
def _repo():
    from tradingagents.storage import StorageRepository, create_storage_engine

    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _run(repo, people_log=None, **kw):
    bars, signals = _bars(), _signals()
    pack = _pack()
    log = people_log if people_log is not None else []
    return R.run_review("GC=F", repo=repo, people=_people(pack, log), now=NOW, bars=bars, signals=signals, **kw), log


def test_the_daily_run_is_idempotent_and_stores_one_row_per_day(monkeypatch):
    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    repo = _repo()
    first, log = _run(repo)
    assert first["status"] == "ok" and first["date"] == "2026-11-14" and len(log) == 4
    second, log2 = _run(repo)
    assert second["status"] == "exists" and log2 == []
    again, log3 = _run(repo, force=True)
    assert again["status"] == "ok" and len(log3) == 4
    assert len(R.list_records(repo, "GC=F")) == 1
    assert R.load_record(repo, "GC=F", "2026-11-14")["status"] == "ok"


def test_a_failing_provider_chain_is_retried_once_then_given_up(monkeypatch):
    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    repo = _repo()
    pack = _pack()

    def run():
        return R.run_review("GC=F", repo=repo, people=_people(pack, [], analyst={"fail": True}), now=NOW, bars=_bars(), signals=_signals())

    assert run()["status"] == "failed"
    assert run()["status"] == "failed"
    assert run()["status"] == "gave_up"
    assert R.load_stored_review(repo, "GC=F") is None            # a failed record is never shown


def test_the_daily_budget_is_shared_across_symbols_and_stops_the_run(monkeypatch):
    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    repo = _repo()
    result, _ = _run(repo, max_usd=5.0)
    spent = R.spent_on(repo, "2026-11-16")
    assert spent == result["cost_usd"] > 0
    pack = _pack()
    blocked = R.run_review("NQ=F", repo=repo, people=_people(pack, []), now=NOW, bars=_bars(), signals=[], max_usd=spent)
    assert blocked["status"] == "budget"


def test_no_trading_day_means_no_note(monkeypatch):
    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    out = R.run_review("GC=F", repo=_repo(), people={}, now=NOW, bars=[], signals=[])
    assert out["status"] == "no_data"


def test_serving_round_trip_and_the_data_route(monkeypatch):
    from fastapi.testclient import TestClient

    import goldlab.data as data
    from goldlab.data import bars_from_rows
    from tradingagents.site import create_app

    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    rows = [{"timestamp": START + timedelta(hours=i), "open": 2400.0 + i, "high": 2402.0 + i, "low": 2399.0 + i, "close": 2401.0 + i, "volume": 10} for i in range(400)]
    monkeypatch.setattr(data, "fetch_bars", lambda symbol="GC=F", *, interval="1h", days=None: bars_from_rows(rows, symbol=symbol, interval=interval))
    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=False))
    assert client.get("/lab/gold/data?interval=1h&symbol=GC=F").json()["review"] is None
    _run(repo)
    body = client.get("/lab/gold/data?interval=1h&symbol=GC=F").json()["review"]
    assert body["date"] == "2026-11-14" and body["mode"] == "debate" and len(body["turns"]) == 4
    assert [t["provider"] for t in body["turns"]] == ["anthropic", "openai", "google", "anthropic"]
    assert body["footer"] == "과거 기록 복기이며 거래 권유가 아닙니다" and body["evidence"]["E1"]
    assert "raw" not in json.dumps(body)
    assert client.get("/lab/gold/data?interval=1h&symbol=NQ=F").json()["review"] is None


def test_the_newest_note_wins_for_the_page(monkeypatch):
    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    repo = _repo()
    _run(repo)
    older = R.load_record(repo, "GC=F", "2026-11-14")
    older["date"] = "2026-11-13"
    R.save_record(repo, older)
    assert R.load_stored_review(repo, "GC=F")["date"] == "2026-11-14"


def test_page_renders_with_and_without_a_review(monkeypatch):
    from goldlab.chart import build_frame, render_chart
    from goldlab.data import bars_from_rows

    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    rows = [{"timestamp": START + timedelta(hours=i), "open": 2400.0, "high": 2401.0, "low": 2399.0, "close": 2400.5, "volume": 10} for i in range(300)]
    frame = build_frame(bars_from_rows(rows, symbol="GC=F", interval="1h"), study=None, max_bars=200)
    frame["review"] = None
    bare = render_chart({"1h": frame}, symbol="GC=F", intervals=("1h",), data_url="/lab/gold/data", bars=200)
    assert 'id="rbody"' in bare and "function renderReview" in bare and "세 AI가 토론해 쓴 복기 노트가 여기에 표시됩니다" in bare
    repo = _repo()
    _run(repo)
    frame["review"] = R.load_stored_review(repo, "GC=F")
    full = render_chart({"1h": frame}, symbol="GC=F", intervals=("1h",), data_url="/lab/gold/data", bars=200)
    assert "과거 기록 복기이며 거래 권유가 아닙니다" in full and "분석가 최종" in full and "openai" in full and '"mode": "debate"' in full
    assert "var(--up)" in full and "var(--down)" in full


# ----------------------------------------------------------------- hypotheses
def test_hypothesis_specs_are_normalised_or_flagged():
    h = R.normalize_hypothesis({"text": "t", "pattern": "인사이드 바", "session": "미국장", "horizon": "12"}, 1)
    assert h["expressible"] and h["spec"] == {"pattern": "inside_bar", "horizon": 12, "context": {"session": "us"}, "direction": "higher"} and h["status"] == "미검증"
    two = R.normalize_hypothesis({"pattern": "doji", "horizon": 12, "context": {"session": "us", "trend": "up"}}, 2)
    assert not two["expressible"] and "둘 이상" in two["why_not"]
    assert not R.normalize_hypothesis({"pattern": "doji", "horizon": 5}, 3)["expressible"]
    assert R.normalize_hypothesis({"pattern": "doji", "horizon": 12}, 4)["text"].startswith("패턴")


def test_hypothesis_text_shows_korean_labels_not_code_names():
    h = R.normalize_hypothesis({"text": "doji(도지)는 asia에서 12봉 뒤 기준보다 높다. inside_bar도 본다", "pattern": "doji", "context": {"session": "asia"}, "horizon": 12}, 1)
    assert h["text"] == "도지는 아시아장에서 12봉 뒤 기준보다 높다. inside_bar도 본다"
    j = R.normalize_hypothesis({"text": "bearish_harami는 12봉 뒤 기준보다 높다", "pattern": "bearish_harami", "context": {"volatility": "high"}, "horizon": 24}, 2)
    assert j["text"].startswith("하락 잉태형은") and j["expressible"] and j["spec"]["context"] == {"vol": "high"}


def _fake_study(p_value=0.0000001, edge=0.02, n=400):
    def run(series, *, horizons, patterns, with_legacy):
        cell = {"count": n, "win_rate": 0.55, "base_win_rate": 0.5, "shrunk_edge_win_rate": edge, "p_value": p_value, "independent_count": n // 2,
                "context": {"session": {"us": {"count": n, "win_rate": 0.56, "base_win_rate": 0.5, "shrunk_edge_win_rate": edge, "p_value": p_value}}}}
        return {"end": "2026-11-13T14:30:00+00:00", "patterns": [{"pattern": p, "horizons": {str(h): cell for h in horizons}} for p in patterns]}
    return run


def test_expressible_hypotheses_are_tested_and_recorded_with_numbers():
    expressible = R.normalize_hypothesis({"pattern": "inside_bar", "session": "us", "horizon": 12}, 1)
    other = R.normalize_hypothesis({"pattern": "nope", "horizon": 12}, 2)
    changed = R.evaluate_hypotheses([expressible, other], object(), family=1110, run_study=_fake_study())
    assert [h["id"] for h in changed] == ["H1"] and expressible["status"] == "통과" and other["status"] == "미검증"
    assert expressible["result"]["n"] == 400 and expressible["result"]["alpha"] == pytest.approx(0.05 / 1110) and expressible["result"]["p_value"] == 1e-07
    weak = R.normalize_hypothesis({"pattern": "inside_bar", "horizon": 12}, 1)
    R.evaluate_hypotheses([weak], object(), family=1110, run_study=_fake_study(p_value=0.01))
    assert weak["status"] == "기각"
    thin = R.normalize_hypothesis({"pattern": "inside_bar", "horizon": 12}, 1)
    R.evaluate_hypotheses([thin], object(), run_study=_fake_study(p_value=None, n=0))
    assert thin["status"] == "표본 부족"


def test_a_lower_than_base_hypothesis_passes_when_the_rate_is_lower():
    h = R.normalize_hypothesis({"text": "인사이드 바는 12봉 뒤 기준보다 낮다", "pattern": "inside_bar", "horizon": 12}, 1)
    assert h["spec"]["direction"] == "lower"

    def run(series, *, horizons, patterns, with_legacy):
        cell = {"count": 900, "win_rate": 0.45, "base_win_rate": 0.50, "shrunk_edge_win_rate": -0.04, "p_value": 1e-9}
        return {"patterns": [{"pattern": "inside_bar", "horizons": {"12": cell}}]}

    R.evaluate_hypotheses([h], object(), family=100, run_study=run)
    assert h["status"] == "통과"


def test_the_weekly_job_updates_stored_notes_and_runs_at_most_weekly(monkeypatch):
    monkeypatch.setattr("goldlab.analogs.load_stored_analogs", lambda repo, s, i: None)
    repo = _repo()
    _run(repo)
    out = R.run_weekly_hypotheses("GC=F", repo=repo, series=object(), run_study=_fake_study(), now=NOW)
    assert out["status"] == "ok" and out["tested"] == 1
    stored = R.load_record(repo, "GC=F", "2026-11-14")
    assert [h["status"] for h in stored["hypotheses"]] == ["통과", "미검증"]
    assert R.run_weekly_hypotheses("GC=F", repo=repo, series=object(), run_study=_fake_study(), now=NOW + timedelta(days=2))["status"] == "not_due"
    assert R.run_weekly_hypotheses("GC=F", repo=repo, series=object(), run_study=_fake_study(), now=NOW + timedelta(days=8))["status"] == "nothing_to_test"
    assert R.load_stored_review(repo, "GC=F")["hypotheses"][0]["status"] == "통과"


def test_model_defaults_and_prices_can_be_set_from_the_environment(monkeypatch):
    monkeypatch.setenv("GOLDLAB_REVIEW_CRITIC", "openai:gpt-5.4-mini")
    monkeypatch.setenv("GOLDLAB_REVIEW_MAX_USD", "0.25")
    monkeypatch.setenv("GOLDLAB_REVIEW_PRICES", json.dumps({"gpt-5.4-mini": [1, 2]}))
    people = R.build_participants()
    assert people["analyst"].name == "anthropic:claude-sonnet-5" and people["critic"].name == "openai:gpt-5.4-mini" and people["verifier"].name == "google:gemini-3.5-flash"
    assert R.default_budget_usd() == 0.25 and R.cost_of("gpt-5.4-mini", 1_000_000, 1_000_000) == 3.0

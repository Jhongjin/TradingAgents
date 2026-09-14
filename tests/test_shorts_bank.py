"""Which story the channel tells today, and why it does not repeat itself."""

import json
from datetime import date, datetime, timezone

import pytest

from tradingagents.shorts.bank import (
    BY_KEY,
    STORIES,
    evaluate,
    plan,
    read_ledger,
    record_published,
)

FRIDAY = datetime(2026, 9, 11, 2, 0, tzinfo=timezone.utc)     # 11:00 KST, a Friday
MONDAY = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)     # and the Monday after


def _payload(*, exits: tuple = (), closed_before: int = 0, entered_today: int = 0, today: str = "2026-09-14") -> dict:
    closed = [
        {"ticker_name": f"과거{index}", "realized_return": -0.02, "exit_reason": "stop_loss",
         "exit_date": "2026-09-01", "entry_date": "2026-08-28"}
        for index in range(closed_before)
    ]
    for name, value, reason in exits:
        closed.append({"ticker_name": name, "realized_return": value, "exit_reason": reason,
                       "exit_date": today, "entry_date": "2026-09-10"})
    return {
        "summary": {"initial_cash": 1.5e8, "total_return": -0.0117, "closed_count": len(closed), "win_count": 0},
        "accounts": [
            {"key": "paper", "label": "AI 확인", "summary": {"total_return": -0.0147, "open_count": 3, "closed_count": 3}},
            {"key": "rules", "label": "규칙 전용", "summary": {"total_return": -0.0205, "open_count": 6, "closed_count": 2}},
        ],
        "positions": [{"ticker_name": f"보유{index}", "account": "paper", "entry_date": today}
                      for index in range(entered_today)],
        "closed": closed,
    }


def test_a_day_where_stops_fired_beats_a_day_where_nothing_did():
    quiet = plan(_payload(closed_before=4, entered_today=3), now=MONDAY, ledger=[])
    loud = plan(_payload(closed_before=4, entered_today=3, exits=(("티에스이", -0.156, "stop_loss"),)), now=MONDAY, ledger=[])

    assert quiet["story"] in {"record", "picks"}
    assert loud["story"] == "stop_worked"
    # the same account, one event, and the whole running order changes
    assert loud["candidates"][0]["score"] > quiet["candidates"][0]["score"]
    assert "손절선에서 1건" in loud["reason"]


def test_a_bigger_loss_scores_higher_than_a_smaller_one():
    small = evaluate(_payload(exits=(("가", -0.03, "stop_loss"),)), now=MONDAY, ledger=[])
    large = evaluate(_payload(exits=(("나", -0.16, "stop_loss"),)), now=MONDAY, ledger=[])
    by_key = lambda rows: {row.story.key: row.score for row in rows}
    assert by_key(large)["stop_worked"] > by_key(small)["stop_worked"]


def test_a_story_told_yesterday_is_no_longer_new():
    payload = _payload(closed_before=4, exits=(("티에스이", -0.156, "stop_loss"),))
    fresh = plan(payload, now=MONDAY, ledger=[])
    assert fresh["story"] == "stop_worked"

    repeated = plan(payload, now=MONDAY, ledger=[{"story": "stop_worked", "date": "2026-09-13"}])
    assert repeated["story"] != "stop_worked"           # it ran yesterday, so something else goes out
    scores = {item["key"]: item["novelty"] for item in repeated["candidates"]}
    assert scores["stop_worked"] < 1.0

    # and once the cooldown has passed it is new again
    rested = plan(payload, now=MONDAY, ledger=[{"story": "stop_worked", "date": "2026-09-01"}])
    assert rested["story"] == "stop_worked"


def test_standby_material_is_always_in_the_running_and_never_wins_a_loud_day():
    rows = {item.story.key: item for item in evaluate(_payload(), now=MONDAY, ledger=[])}
    assert {"explain_stop", "explain_debate", "explain_open"} <= set(rows)
    assert all(rows[key].story.tier == "standby" for key in ("explain_stop", "explain_debate", "explain_open"))

    loud = evaluate(_payload(closed_before=4, exits=(("가", -0.16, "stop_loss"),)), now=MONDAY, ledger=[])
    assert loud[0].story.tier != "standby"


def test_friday_puts_the_weekly_report_in_the_running():
    friday = {item["key"] for item in plan(_payload(), now=FRIDAY, ledger=[])["candidates"]}
    monday = {item["key"] for item in plan(_payload(), now=MONDAY, ledger=[])["candidates"]}
    assert "weekly" in friday and "weekly" not in monday


def test_a_milestone_fires_only_on_the_round_number():
    fired = lambda count: {item.story.key for item in evaluate(_payload(closed_before=count), now=MONDAY, ledger=[])}
    assert "milestone" in fired(10) and "milestone" in fired(25)
    assert "milestone" not in fired(11) and "milestone" not in fired(9)


def test_only_a_story_that_can_actually_be_drawn_is_chosen():
    decision = plan(_payload(closed_before=4, exits=(("가", -0.02, "take_profit"),)), now=MONDAY, ledger=[])
    chosen = BY_KEY[decision["story"]]
    assert chosen.renderable and decision["renderer"] in {"record", "picks"}
    # take_profit fired and scored well, but nothing draws it yet, so it waits
    assert "take_profit" in {item["key"] for item in decision["candidates"]}
    assert "take_profit" in decision["waiting"]


def test_an_empty_account_still_yields_a_decision():
    decision = plan({"summary": {}, "accounts": [], "closed": [], "positions": []}, now=MONDAY, ledger=[])
    assert decision["candidates"]                        # the shelf is never empty
    assert decision["story"] is None                     # but nothing renderable fired
    assert "만들 수 있는 것이 없습니다" in decision["reason"]


def test_the_ledger_remembers_what_went_out(tmp_path):
    path = tmp_path / "published.json"
    assert read_ledger(path) == []

    row = record_published("record", video_id="abc123", when=date(2026, 9, 14), path=path)
    assert row["story"] == "record" and row["video_id"] == "abc123"
    record_published("picks", when=date(2026, 9, 15), path=path)

    rows = read_ledger(path)
    assert [item["story"] for item in rows] == ["record", "picks"]
    assert json.loads(path.read_text(encoding="utf-8"))[0]["date"] == "2026-09-14"

    path.write_text("not json", encoding="utf-8")
    assert read_ledger(path) == []                       # a damaged ledger is not a crash


def test_every_story_declares_what_it_needs():
    assert len({story.key for story in STORIES}) == len(STORIES)
    for story in STORIES:
        assert story.tier in {"daily", "event", "periodic", "standby"}
        assert 0 < story.completeness <= 1 and story.cooldown_days >= 1
        assert story.renderer in {None, "record", "picks"}
    assert any(story.renderable for story in STORIES)
    assert any(not story.renderable for story in STORIES)   # the plan is honest about what is unbuilt

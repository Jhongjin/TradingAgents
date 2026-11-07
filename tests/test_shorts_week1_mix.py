"""2026-11-09 week-1 story-mix test (bank.py `WEEK1_MIX_TEST_*`).

One variable changed: which story wins a day when more than one candidate
fires. These tests cover the weekly quotas, the identical-title rerun block,
the no-empty-day fallback, and a dry run over the week of 2026-11-09 against
the real publish ledger.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradingagents.shorts.bank import (
    KST,
    WEEK1_MIX_TEST_RECORD_TARGET,
    WEEK1_MIX_TEST_WEEKLY_CAPS,
    plan,
    read_ledger,
)

MONDAY = datetime(2026, 11, 9, 2, 0, tzinfo=ZoneInfo("UTC"))  # 11:00 KST


def _payload(*, closed_before: int = 0, entered_today: int = 0, funnel=None, today: str = "2026-11-09") -> dict:
    closed = [
        {"ticker_name": f"과거{index}", "realized_return": -0.02, "exit_reason": "stop_loss",
         "exit_date": "2026-10-20", "entry_date": "2026-10-10"}
        for index in range(closed_before)
    ]
    payload = {
        "summary": {"initial_cash": 1.5e8, "total_return": -0.03, "closed_count": len(closed), "win_count": 0},
        "accounts": [
            {"key": "paper", "label": "AI 확인", "summary": {"total_return": -0.03, "open_count": 3, "closed_count": 3}},
            {"key": "rules", "label": "규칙 전용", "summary": {"total_return": -0.04, "open_count": 6, "closed_count": 2}},
        ],
        "positions": [{"ticker_name": f"보유{index}", "account": "paper", "entry_date": today,
                       "average_price": 10000, "target_price": 11500, "stop_price": 9200}
                      for index in range(entered_today)],
        "closed": closed,
    }
    if funnel is not None:
        payload["funnel"] = funnel
    return payload


def _funnel(universe=349, survived=4, as_of="2026-11-09"):
    return {
        "universe": universe,
        "as_of_date": as_of,
        "stages": [
            {"label": "1차 선별", "from": universe, "to": 30},
            {"label": "AI 토론 탈락", "from": 30, "to": survived},
        ],
        "picks": [{"name": "티에스이", "sub": "비중 확대", "value": "0.62"}],
    }


def test_funnel_quota_blocks_a_second_use_in_the_same_iso_week():
    cap = WEEK1_MIX_TEST_WEEKLY_CAPS["funnel"]
    assert cap == 1

    payload = _payload(closed_before=4, funnel=_funnel())
    ledger = [{"story": "funnel", "date": "2026-11-09", "title": "349종목에서 4종목 | AI가 거른 과정 전부 공개"}]

    # same ISO week (2026-11-10 is still week 46), funnel already used once
    decision = plan(payload, now=MONDAY + timedelta(days=1), ledger=ledger)
    assert decision["story"] != "funnel"
    assert any(key == "funnel" for key, _ in decision["mix"].get("blocked", []))

    # a week later (week 47) the quota has reset — use different funnel
    # numbers so this isn't also caught by the separate title-rerun block
    fresh_payload = _payload(closed_before=4, funnel=_funnel(universe=349, survived=9))
    decision_next_week = plan(fresh_payload, now=MONDAY + timedelta(days=7), ledger=ledger)
    assert "funnel" not in [key for key, _ in decision_next_week["mix"].get("blocked", [])]


def test_picks_and_debate_quota_is_one_per_week_each():
    for key in ("picks", "debate"):
        assert WEEK1_MIX_TEST_WEEKLY_CAPS[key] == 1

    payload = _payload(closed_before=4, entered_today=3)
    ledger = [{"story": "picks", "date": "2026-11-09", "title": "AI가 지금 담고 있는 2종목 | 목표가·손절가 공개"}]
    decision = plan(payload, now=MONDAY + timedelta(days=1), ledger=ledger)
    assert decision["story"] != "picks"


def test_identical_title_rerun_is_blocked_within_the_30_day_window():
    """explain_stop's title never changes, so a rerun inside 30 days is the
    exact case the content review flagged (753->48->2, 41->26->25)."""

    from tradingagents.shorts.topics import BY_TOPIC

    explain_stop_title = BY_TOPIC["explain_stop"].title
    payload = {"summary": {}, "accounts": [], "closed": [], "positions": [],
               "backtests": {"rules:현행 5%/10%": {"total_return": 0.5033, "max_drawdown": -0.2887,
                                                     "sharpe_ratio": 0.620116, "hit_rate": 0.3915},
                             "rules:변동성 제외 + 손절 8%": {"total_return": 1.2646, "max_drawdown": -0.2402,
                                                            "sharpe_ratio": 1.156081, "hit_rate": 0.4912,
                                                            "benchmark_return": 1.684, "start_date": "2023-09-19",
                                                            "end_date": "2026-09-18"}}}

    # published 20 days before this plan() call: inside the 30-day window
    ledger = [{"story": "explain_stop", "date": "2026-10-20", "title": explain_stop_title}]
    decision = plan(payload, now=MONDAY, ledger=ledger)
    # explain_stop is the only renderable candidate on an empty account, so
    # this is the fallback case: it still gets chosen (never an empty day),
    # but the mix machinery must say so rather than silently reusing it.
    assert decision["story"] == "explain_stop"
    assert decision["mix"]["fallback"] is True
    assert "동일 제목" in decision["mix"]["reason"]

    # the same ledger entry 40 days before now is outside the window and does
    # not block it, and nothing else is eligible either way on this payload
    far_ledger = [{"story": "explain_stop", "date": "2026-09-30", "title": explain_stop_title}]
    far_decision = plan(payload, now=MONDAY, ledger=far_ledger)
    assert far_decision["story"] == "explain_stop"
    assert far_decision["mix"]["fallback"] is False


def test_identical_title_rerun_falls_through_to_an_eligible_alternative():
    """When blocking the rerun still leaves another candidate, that one runs
    instead of falling all the way back to the blocked one."""

    from tradingagents.shorts.topics import BY_TOPIC

    explain_stop_title = BY_TOPIC["explain_stop"].title
    payload = _payload(closed_before=4)  # record is also on the shelf here
    ledger = [{"story": "explain_stop", "date": "2026-11-01", "title": explain_stop_title}]
    decision = plan(payload, now=MONDAY, ledger=ledger)
    assert decision["story"] != "explain_stop"
    assert decision["mix"]["fallback"] is False


def test_a_title_with_new_numbers_is_never_blocked():
    """Only an unchanged title is a rerun; new numbers make it a new video."""

    # a record row old enough that its own cooldown/novelty has fully rested,
    # so the only thing under test is the title comparison, not the score
    payload = _payload(closed_before=6)
    ledger = [{"story": "record", "date": "2026-09-01",
               "title": "AI 모의계좌 성적 전부 공개 | 정리한 3건과 -1.00%"}]
    decision = plan(payload, now=MONDAY, ledger=ledger)
    # closed_before=6 produces a different closed_count/return, so the title
    # differs from the ledger row above and record is never in the blocked list
    assert "record" not in [key for key, _ in decision["mix"].get("blocked", [])]


def test_record_is_nudged_ahead_while_under_its_weekly_target():
    assert WEEK1_MIX_TEST_RECORD_TARGET == 2

    payload = _payload(closed_before=4, funnel=_funnel(universe=60, survived=55))  # a thin, low-severity funnel
    decision = plan(payload, now=MONDAY, ledger=[])
    assert decision["mix"]["record_boosted"] is True
    assert decision["story"] == "record"

    # once record has already run twice this week, the nudge turns off
    ledger = [
        {"story": "record", "date": "2026-11-09"},
        {"story": "record", "date": "2026-11-10"},
    ]
    decision_after_target = plan(payload, now=MONDAY + timedelta(days=2), ledger=ledger)
    assert decision_after_target["mix"]["record_boosted"] is False


def test_a_sharp_funnel_or_real_event_still_wins_over_a_boosted_record():
    """The nudge is additive, not an override: the screen outranking the
    scoreboard (an existing invariant of this module) must survive the test."""

    payload = _payload(closed_before=6, funnel=_funnel(universe=349, survived=3))
    decision = plan(payload, now=MONDAY, ledger=[])
    assert decision["story"] == "funnel"


def test_quotas_never_leave_a_weekday_with_no_story():
    """Even with every quota exhausted, something still goes out.

    A single account, no closed trades and no backtests keeps record and all
    three explainers off the shelf, so picks and funnel are the only
    candidates — and both are quota-blocked this week.
    """

    payload = {
        "summary": {"initial_cash": 1.5e8, "total_return": 0.0, "closed_count": 0, "win_count": 0},
        "accounts": [{"key": "paper", "label": "AI 확인", "summary": {"total_return": 0.0, "open_count": 2, "closed_count": 0}}],
        "positions": [{"ticker_name": f"보유{i}", "account": "paper", "entry_date": "2026-11-10"} for i in range(2)],
        "closed": [],
        "funnel": _funnel(as_of="2026-11-10"),
    }
    ledger = [
        {"story": "funnel", "date": "2026-11-09", "title": "x"},
        {"story": "picks", "date": "2026-11-09", "title": "y"},
    ]
    decision = plan(payload, now=MONDAY + timedelta(days=1), ledger=ledger)
    assert decision["story"] is not None
    assert decision["mix"]["fallback"] is True


def test_a_normal_day_with_an_empty_ledger_still_picks_something():
    decision = plan(_payload(closed_before=4), now=MONDAY, ledger=[])
    assert decision["story"] is not None
    assert decision["mix"]["applied"] is True


def test_dry_run_the_week_of_2026_11_09_against_the_real_ledger():
    """Not a prediction of real market data — this repo keeps no cached
    account payload offline, and the task asked not to hit the network or
    the broker for this check. It replays the publicly-visible real ledger
    (shorts-out/published.json) against the same synthetic account fixture
    used by test_shorts_bank.py, once per weekday, so the mix rule's
    behaviour against the actual recent history is visible without a live
    payload. Treat the "candidates" as representative, not the exact pick a
    live run would make with real account data that day.
    """

    ledger = read_ledger()  # the real shorts-out/published.json
    week_start = date(2026, 11, 9)
    results = []
    for offset in range(5):  # Mon-Fri
        day = week_start + timedelta(days=offset)
        now = datetime(day.year, day.month, day.day, 11, 0, tzinfo=KST)
        payload = _payload(closed_before=60 + offset, entered_today=2,
                            funnel=_funnel(survived=3 + offset, as_of=day.isoformat()),
                            today=day.isoformat())
        decision = plan(payload, now=now, ledger=ledger)
        results.append((day.isoformat(), decision["story"], decision["mix"]))
        # the ledger grows exactly the way shorts-daily would record it, so
        # day two's quotas see day one's pick
        ledger = [*ledger, {"story": decision["story"], "date": day.isoformat(),
                             "title": (decision["chosen"] or {}).get("label", "")}]

    print("\nWEEK1_MIX_TEST dry run, week of 2026-11-09 (synthetic account, real ledger):")
    for day_iso, story, mix in results:
        print(f"  {day_iso} -> {story}  (fallback={mix.get('fallback')})")

    assert len(results) == 5
    assert all(story is not None for _, story, _ in results)
    # the funnel quota holds even across this synthetic week
    assert len([1 for _, story, _ in results if story == "funnel"]) <= WEEK1_MIX_TEST_WEEKLY_CAPS["funnel"]

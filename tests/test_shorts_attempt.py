"""The daily video has to survive an attempt that fails.

Six weekday attempts between 09-14 and 09-21 produced one confirmed video id.
Every failure had a different cause — a console that could not write an em
dash, n8n answering with uploadId, a machine still booting, npx refused with
WinError 5 — and each was fixed afterwards. The next one will be new too.

So the job runs more than once a day and the causes stop mattering. What makes
that safe is a claim: the story is chosen once and written down, so a second
attempt continues the same video instead of publishing a different one.
"""

import json

import pytest

from tradingagents.shorts.attempt import (
    Claim,
    clear_claim,
    published_today,
    read_claim,
    start_attempt,
    write_claim,
)


def _rows(*entries):
    return [dict(entry) for entry in entries]


def test_a_day_that_reached_youtube_is_finished():
    rows = _rows({"date": "2026-09-17", "story": "funnel", "video_id": "63THZa"})
    assert published_today(rows, day="2026-09-17")["video_id"] == "63THZa"


def test_an_attempt_that_never_got_an_id_is_not_finished():
    """This is the bug: five of seven ledger rows carry no id, and each of
    those days ended with no video and no retry."""

    for empty in (None, "", "   "):
        rows = _rows({"date": "2026-09-15", "story": "record", "video_id": empty})
        assert published_today(rows, day="2026-09-15") is None


def test_another_day_does_not_count_as_today():
    rows = _rows({"date": "2026-09-17", "story": "funnel", "video_id": "63THZa"})
    assert published_today(rows, day="2026-09-18") is None


def test_the_latest_row_for_a_day_wins():
    rows = _rows(
        {"date": "2026-09-21", "story": "sweep", "video_id": ""},
        {"date": "2026-09-21", "story": "sweep", "video_id": "abc123"},
    )
    assert published_today(rows, day="2026-09-21")["video_id"] == "abc123"


def test_a_second_attempt_keeps_the_first_attempts_story(tmp_path):
    """Otherwise a retry publishes a second, different short — worse than none."""

    path = tmp_path / "claim.json"
    first = start_attempt(day="2026-09-21", story="sweep", reason="규칙 비교", path=path)
    second = start_attempt(day="2026-09-21", story="debate", reason="다른 이야기", path=path)

    assert first.story == "sweep" and first.attempts == 1
    assert second.story == "sweep"          # not "debate"
    assert second.reason == "규칙 비교"
    assert second.attempts == 2


def test_a_new_day_starts_a_new_claim(tmp_path):
    path = tmp_path / "claim.json"
    start_attempt(day="2026-09-21", story="sweep", reason="어제", path=path)
    today = start_attempt(day="2026-09-22", story="debate", reason="오늘", path=path)

    assert today.story == "debate" and today.attempts == 1
    assert read_claim(day="2026-09-21", path=path) is None


def test_a_finished_day_drops_its_claim(tmp_path):
    path = tmp_path / "claim.json"
    start_attempt(day="2026-09-21", story="sweep", reason="x", path=path)
    clear_claim(path=path)

    assert read_claim(day="2026-09-21", path=path) is None
    clear_claim(path=path)                  # and again is not an error


def test_a_corrupt_claim_is_a_missing_claim(tmp_path):
    path = tmp_path / "claim.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_claim(day="2026-09-21", path=path) is None

    path.write_text(json.dumps({"day": "2026-09-21"}), encoding="utf-8")
    assert read_claim(day="2026-09-21", path=path) is None   # no story named


def test_the_command_skips_a_day_that_is_already_published():
    import inspect

    import cli.main as main

    source = inspect.getsource(main.shorts_daily_command)
    assert "published_today" in source
    assert "이미 올라갔습니다" in source
    # and the claim is taken before any building happens
    assert source.index("start_attempt(") < source.index("_shorts_build(")


def test_spawning_the_renderer_is_retried_but_a_real_failure_is_not():
    """WinError 5 clears on its own; a command that ran and failed has a reason."""

    import inspect

    from tradingagents.shorts import hyperframes

    source = inspect.getsource(hyperframes.run)
    assert "except (PermissionError, OSError)" in source
    assert hyperframes.SPAWN_ATTEMPTS >= 2
    # a non-zero return code still raises on the first try
    assert source.index("if result.returncode != 0:") > source.index("except (PermissionError, OSError)")

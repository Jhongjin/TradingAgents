"""Five storyboard-driven layouts beside each story's own template, and a closing line that turns over."""

from datetime import date, datetime, timedelta, timezone

import pytest

from tests.test_shorts import NOW, _payload
from tradingagents.shorts import build
from tradingagents.shorts.hyperframes import TIMELINE_HANDOFF, with_motion
from tradingagents.shorts.layouts import LAYOUTS, ROTATION, can_lay_out, compose_layout, layout_for
from tradingagents.shorts.scenes import Statement
from tradingagents.shorts.stories import CLOSERS


def test_there_are_at_least_five_layouts_besides_the_template():
    assert len(LAYOUTS) >= 5 and ROTATION[0] == "base" and set(LAYOUTS) <= set(ROTATION)
    weekdays = [date(2026, 10, 5) + timedelta(days=i) for i in range(14)]
    weekdays = [d for d in weekdays if d.weekday() < 5][: len(ROTATION)]
    days = [layout_for(d) for d in weekdays]
    assert sorted(days) == sorted(ROTATION)                                  # each comes round once in six publishing days
    assert all(a != b for a, b in zip(days, days[1:]))
    assert layout_for(date(2026, 10, 10)) == layout_for(date(2026, 10, 12))  # a weekend takes Monday's


def test_the_base_template_does_not_wear_the_same_look_every_time(monkeypatch):
    from tradingagents.shorts.hyperframes import LOOKS, look_for

    monkeypatch.delenv("TRADINGAGENTS_SHORTS_LOOK", raising=False)
    start = date(2026, 10, 5)
    base_days = [start + timedelta(days=i) for i in range(120)]
    base_days = [d for d in base_days if d.weekday() < 5 and layout_for(d) == "base"][: len(LOOKS)]
    assert sorted(look_for(d) for d in base_days) == sorted(LOOKS)
    assert layout_for(override="Cards") == "cards"


@pytest.mark.parametrize("name", LAYOUTS)
def test_every_layout_carries_the_whole_board_on_one_timeline(name):
    board = build("record", _payload(), now=NOW)
    assert can_lay_out(board)
    html, seconds = compose_layout(name, board)
    assert seconds == pytest.approx(board.seconds, abs=0.05)
    assert html.count('class="clip"') == len(board.scenes)
    assert f'data-layout="{name}"' in html and 'data-composition-id="main"' in html
    assert html.count(TIMELINE_HANDOFF) == 1 and "paused: true" in html
    assert "Math.random" not in html and "Date.now" not in html
    assert 'id="s0-fig"' in html                                            # the hero the motion layer reaches for
    for scene in board.scenes:
        for line in getattr(scene, "lines", ()) or ():
            if line:
                assert line.replace("&", "&amp;") in html
    moving = with_motion(html, "bold", "grid")
    assert "hf-progress" in moving and "rotating look" not in moving          # a layout is its own look


def test_a_board_that_leaves_its_words_to_the_template_keeps_the_template():
    board = build("record", _payload(), now=NOW)
    empty = type(board)(**{**board.__dict__, "scenes": (Statement(eyebrow="양쪽 주장"),) + tuple(board.scenes[1:])})
    assert not can_lay_out(empty)
    with pytest.raises(ValueError, match="unknown layout"):
        compose_layout("nope", board)


def test_the_closing_line_turns_over_by_day_and_holds_within_a_day():
    seen = []
    for day in range(len(CLOSERS)):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc) + timedelta(days=day)
        outro = build("record", _payload(), now=now).scenes[-1]
        again = build("record", _payload(), now=now).scenes[-1]
        assert outro.headline == again.headline and outro.narration == again.narration
        seen.append(outro.headline)
    assert all(a != b for a, b in zip(seen, seen[1:]))
    assert len(set(seen)) == len(seen)                                       # a full week without a repeat

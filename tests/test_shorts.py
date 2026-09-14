"""The generated short: what the cut says, and that a frame can be painted.

The storyboard is plain data and is checked everywhere. The painting needs a
font that can draw Hangul, which a bare CI image may not have, so those checks
stand aside rather than fail when there is none.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradingagents.shorts import build
from tradingagents.shorts.design import DOWN, UP, font_pair
from tradingagents.shorts.render import FfmpegMissingError, paint, scene_at, write_caption
from tradingagents.shorts.scenes import Bars, Hook, Outro, Rows, Statement
from tradingagents.shorts.stories import build_picks, build_record, short_date

NOW = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)  # 11:00 KST
needs_font = pytest.mark.skipif(font_pair() is None, reason="한글 글꼴이 없는 환경")


def _payload() -> dict:
    return {
        "summary": {
            "initial_cash": 150_000_000.0,
            "equity": 148_237_852.34,
            "realized_pnl": -1_750_034.43,
            "total_return": -0.011748,
            "closed_count": 3,
            "win_count": 0,
        },
        "accounts": [
            {"key": "paper", "label": "AI 확인", "summary": {"total_return": -0.014659, "open_count": 3, "closed_count": 3}},
            {"key": "rules", "label": "규칙 전용", "summary": {"total_return": -0.020528, "open_count": 6, "closed_count": 2}},
            {"key": "kis", "label": "KIS 모의투자", "summary": {"total_return": None, "open_count": 3, "closed_count": 0}},
        ],
        "positions": [
            {"ticker_name": "신한지주", "ticker_code": "055550", "account": "paper", "entry_date": "2026-09-14",
             "average_price": 113400.0, "target_price": 122472.0, "stop_price": 108297.0, "decision_rating": "Overweight"},
            {"ticker_name": "삼성SDI", "ticker_code": "006400", "account": "paper", "entry_date": "2026-09-11",
             "average_price": 556000.0, "target_price": 617160.0, "stop_price": 514300.0, "decision_rating": "Overweight"},
            {"ticker_name": "ISC", "ticker_code": "095340", "account": "rules", "entry_date": "2026-09-10",
             "average_price": 190600.0, "target_price": 209660.0, "stop_price": 181070.0, "decision_rating": None},
        ],
        "closed": [
            {"ticker_name": "SK이노베이션", "account_label": "AI 확인", "entry_date": "2026-09-10", "exit_date": "2026-09-14",
             "realized_return": -0.065292, "exit_reason": "stop_loss"},
            {"ticker_name": "티에스이", "account_label": "AI 확인", "entry_date": "2026-09-10", "exit_date": "2026-09-11",
             "realized_return": -0.156, "exit_reason": "stop_loss"},
            {"ticker_name": "제이앤티씨", "account_label": "규칙 전용", "entry_date": "2026-09-09", "exit_date": "2026-09-12",
             "realized_return": 0.031, "exit_reason": "take_profit"},
        ],
    }


def test_the_record_cut_opens_with_the_loss_and_lists_every_trade():
    board = build_record(_payload(), now=NOW)
    hook, rows, statement, bars, outro = board.scenes
    assert isinstance(hook, Hook) and isinstance(rows, Rows) and isinstance(statement, Statement)
    assert isinstance(bars, Bars) and isinstance(outro, Outro)

    assert hook.value_to == pytest.approx(-0.011748)
    assert hook.value_colour == DOWN                       # a loss is blue, as a Korean chart reads
    assert hook.lines == ("지금까지 정리한 3건,", "전부 손실이었습니다.")
    assert "1.5억원" in hook.caption

    # worst first, so the number that stops a scroll is the one on screen soonest
    assert [row["label"] for row in rows.rows] == ["티에스이", "SK이노베이션", "제이앤티씨"]
    assert [row["badge"] for row in rows.rows] == ["손절", "손절", "익절"]
    assert rows.rows[0]["value"] == "-15.60%" and rows.rows[0]["colour"] == DOWN
    assert rows.rows[-1]["colour"] == UP
    assert rows.rows[0]["sub"] == "AI 확인 · 9/10 매수 → 9/11 정리"
    assert "-1,750,034원" in rows.note

    assert statement.highlight == "-1.17%" and "2건 모두 손절선" in statement.caption
    # an account with nothing measured yet is left out rather than drawn as zero
    assert [item["label"] for item in bars.items] == ["AI 확인", "규칙 전용"]
    assert bars.signed is True

    assert "정리한 3건과 -1.17%" in board.title
    assert 18 <= board.seconds <= 40                        # long enough to read, short enough to finish


def test_a_winning_record_changes_the_verdict_not_the_shape():
    payload = _payload()
    payload["summary"].update({"total_return": 0.0234, "win_count": 2})
    board = build_record(payload, now=NOW)
    hook = board.scenes[0]
    assert hook.lines[1] == "2건이 이익이었습니다."
    assert hook.value_colour == UP
    assert "+2.34%" in board.title


def test_an_empty_account_still_produces_a_cut():
    board = build_record({"summary": {}, "accounts": [], "closed": [], "positions": []}, now=NOW)
    assert [type(scene).__name__ for scene in board.scenes] == ["Hook", "Rows", "Outro"]
    assert board.seconds > 0


def test_the_picks_cut_shows_the_ai_book_with_both_levels():
    board = build_picks(_payload(), now=NOW)
    hook, targets, stops, outro = board.scenes
    assert hook.value == "2종목"                             # only the AI book, not the rules one
    assert [row["label"] for row in targets.rows] == ["신한지주", "삼성SDI"]   # newest entry first
    assert targets.rows[0]["value"] == "122,472원" and targets.rows[0]["badge"] == "비중 확대"
    assert stops.rows[0]["value"] == "108,297원" and stops.rows[0]["colour"] == DOWN
    assert "-4.5%" in stops.rows[0]["sub"]
    assert isinstance(outro, Outro)


def test_every_cut_carries_the_disclaimer_and_a_tagged_link():
    for name in ("record", "picks"):
        board = build(name, _payload(), now=NOW)
        assert "매매 권유가 아닙니다" in board.description
        assert "utm_source=youtube" in board.description and "utm_content=20260914" in board.description
        assert board.slug.endswith("20260914") and board.tags
        outro = board.scenes[-1]
        assert "매매 권유가 아닙니다" in outro.disclaimer


def test_an_unknown_story_says_which_ones_exist():
    with pytest.raises(ValueError, match="record"):
        build("nope", _payload())


def test_short_date_is_month_slash_day():
    assert short_date("2026-09-10") == "9/10"
    assert short_date(None) == ""


def test_the_timeline_maps_a_second_to_the_scene_playing_then():
    board = build_record(_payload(), now=NOW)
    assert scene_at(board.scenes, 0.0)[0] is board.scenes[0]
    assert scene_at(board.scenes, board.scenes[0].seconds - 0.01)[0] is board.scenes[0]
    assert scene_at(board.scenes, board.scenes[0].seconds + 0.01)[0] is board.scenes[1]
    scene, local = scene_at(board.scenes, board.seconds + 5)    # past the end holds the last frame
    assert scene is board.scenes[-1] and local == pytest.approx(scene.seconds)
    assert scene_at((), 1.0) is None


def test_the_caption_file_is_ready_to_paste(tmp_path):
    board = build_record(_payload(), now=NOW)
    target = write_caption(board, tmp_path / "cut.txt")
    text = target.read_text(encoding="utf-8")
    assert text.startswith(board.title)
    assert "https://" in text and "태그: " in text and "1080x1920" in text


@needs_font
def test_a_frame_is_painted_at_the_size_a_short_is_watched_at():
    board = build_record(_payload(), now=NOW)
    frame = paint(board, 2.0)
    assert frame.size == (1080, 1920)
    # the hook has ink on it, and the progress line has started
    assert len(frame.getcolors(maxcolors=1 << 20) or []) > 40
    assert frame.getpixel((90, 187)) != frame.getpixel((990, 187))


@needs_font
def test_the_poster_and_the_last_frame_differ(tmp_path):
    board = build_record(_payload(), now=NOW)
    assert paint(board, 2.0).tobytes() != paint(board, board.seconds - 0.2).tobytes()


def test_encoding_without_ffmpeg_says_so(monkeypatch, tmp_path):
    import shutil

    from tradingagents.shorts import render as encode

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(FfmpegMissingError, match="ffmpeg"):
        encode(build_record(_payload(), now=NOW), Path(tmp_path / "out.mp4"))

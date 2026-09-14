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


def test_every_scene_carries_a_line_short_enough_to_fit_it():
    """Spoken Korean runs about six characters a second; a line must fit its shot."""

    for name in ("record", "picks"):
        board = build(name, _payload(), now=NOW)
        for index, scene in enumerate(board.scenes):
            assert scene.narration.strip(), f"{name} s{index} 내레이션 없음"
            assert len(scene.narration) <= 70, f"{name} s{index} 너무 김: {len(scene.narration)}자"
        spoken = " ".join(scene.narration for scene in board.scenes)
        assert "%" not in spoken and "→" not in spoken     # a narrator reads words, not glyphs
        assert "원" not in spoken or "만원" in spoken       # and amounts in units, not digit strings
    # the record cut states the figure out loud, spelled the way it is said
    assert "퍼센트" in build("record", _payload(), now=NOW).scenes[0].narration


def test_the_outro_points_at_a_channel_only_once_one_exists(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_TELEGRAM_CHANNEL", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_USERNAME", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "TradingAgentsKRBot")

    outro = build("record", _payload(), now=NOW).scenes[-1]
    assert outro.telegram.endswith("/start")            # the bot is not something a viewer can follow
    assert "가입하고 텔레그램을 연결하면" in outro.telegram_line
    assert "@TradingAgentsKRBot" not in outro.telegram

    monkeypatch.setenv("TRADINGAGENTS_TELEGRAM_CHANNEL", "agenttrust_kr")
    board = build("record", _payload(), now=NOW)
    assert board.scenes[-1].telegram == "@agenttrust_kr"
    assert "t.me/agenttrust_kr" in board.description


def test_narration_stretches_a_scene_to_hold_its_line_and_never_shrinks_it():
    from tradingagents.shorts.voice import LEAD_SECONDS, TAIL_SECONDS, fit

    board = build_record(_payload(), now=NOW)
    authored = [scene.seconds for scene in board.scenes]
    manifest = {
        "lines": [
            {"id": "s0", "path": "a.wav", "seconds": 20.0},    # far longer than the shot
            {"id": "s2", "path": "b.wav", "seconds": 0.5},     # far shorter
        ]
    }
    fitted, placed = fit(board, manifest)
    seconds = [scene.seconds for scene in fitted.scenes]
    assert seconds[0] == pytest.approx(LEAD_SECONDS + 20.0 + TAIL_SECONDS)
    assert seconds[2] == authored[2]                            # a short line does not shorten the shot
    assert seconds[1] == authored[1] and seconds[3] == authored[3]
    assert [item["path"] for item in placed] == ["a.wav", "b.wav"]
    assert placed[0]["start"] == pytest.approx(LEAD_SECONDS)
    assert placed[1]["start"] == pytest.approx(seconds[0] + seconds[1] + LEAD_SECONDS)
    assert fitted.seconds > board.seconds


def test_a_machine_without_voxcpm_says_so(monkeypatch, tmp_path):
    from tradingagents.shorts import voice

    monkeypatch.setenv(voice.VOXCPM_HOME_ENV, str(tmp_path / "nowhere"))
    monkeypatch.setenv(voice.VOXCPM_PYTHON_ENV, str(tmp_path / "nopython.exe"))
    assert voice.available() is False
    with pytest.raises(voice.VoiceUnavailableError, match="VoxCPM"):
        voice.speak([{"id": "s0", "text": "안녕하세요"}], tmp_path)


@needs_font
def test_the_page_is_ruled_rather_than_filled():
    """The design's premise: hairlines and a margin rail, not stacked cards."""

    from tradingagents.shorts.design import ACCENT, RAIL_X

    board = build_record(_payload(), now=NOW)
    early, late = paint(board, 0.4), paint(board, board.seconds - 0.3)
    # the rail fills as the cut runs, so the same pixel differs early and late
    low = (RAIL_X + 1, 1400)
    assert early.getpixel(low) != late.getpixel(low)
    assert late.getpixel(low)[1] > late.getpixel(low)[2]        # green-dominant: the accent
    assert early.getpixel((RAIL_X + 1, 260))[1] >= early.getpixel((RAIL_X + 1, 1400))[1]

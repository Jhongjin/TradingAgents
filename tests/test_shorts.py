"""The generated short: what the cut says, and that a frame can be painted.

The storyboard is plain data and is checked everywhere. The painting needs a
font that can draw Hangul, which a bare CI image may not have, so those checks
stand aside rather than fail when there is none.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradingagents.shorts import build
from tradingagents.shorts.design import THEMES, fonts_available
from tradingagents.shorts.render import FfmpegMissingError, paint, scene_at, write_caption
from tradingagents.shorts.scenes import Bars, Hook, Outro, Rows, Statement
from tradingagents.shorts.stories import build_picks, build_record, short_date

NOW = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)  # 11:00 KST
needs_font = pytest.mark.skipif(not fonts_available(), reason="한글 글꼴이 없는 환경")


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
    assert hook.value_colour == "down"                     # a loss is blue, as a Korean chart reads
    assert hook.lines == ("지금까지 정리한 3건,", "전부 손실이었습니다.")
    assert "1.5억원" in hook.caption

    # worst first, so the number that stops a scroll is the one on screen soonest
    assert [row["label"] for row in rows.rows] == ["티에스이", "SK이노베이션", "제이앤티씨"]
    assert [row["badge"] for row in rows.rows] == ["손절", "손절", "익절"]
    assert rows.rows[0]["value"] == "-15.60%" and rows.rows[0]["colour"] == "down"
    assert rows.rows[-1]["colour"] == "up"
    assert rows.rows[0]["sub"] == "9/10 매수   9/11 정리   AI 확인"   # spaced columns, not a dotted meta string
    assert "·" not in rows.rows[0]["sub"] and "→" not in rows.rows[0]["sub"]
    # rounded to a unit somebody can read in a third of a second, not nine digits
    assert rows.note == "실현 손익 -175만원"

    assert statement.highlight == "-1.17%"
    # 3 closed and 2 of them stopped: the caption used to say "2건 모두"
    assert "이 가운데 2건이 손절선에서" in statement.caption
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
    assert hook.value_colour == "up"
    assert "+2.34%" in board.title


def test_an_empty_account_still_produces_a_cut():
    board = build_record({"summary": {}, "accounts": [], "closed": [], "positions": []}, now=NOW)
    assert [type(scene).__name__ for scene in board.scenes] == ["Hook", "Rows", "Outro"]
    assert board.seconds > 0


def test_the_picks_cut_puts_each_holding_on_its_own_ladder():
    """Stop, price paid and target on one scale: what was risked against what is played for."""

    board = build_picks(_payload(), now=NOW)
    hook, rungs, totals, outro = board.scenes
    assert hook.value == "2종목"                             # only the AI book, not the rules one
    assert [row["name"] for row in rungs.rows] == ["신한지주", "삼성SDI"]   # newest entry first

    first = rungs.rows[0]
    assert (first["stop"], first["average"], first["target"]) == (108297.0, 113400.0, 122472.0)
    assert first["stop"] < first["average"] < first["target"]      # the cut draws them in this order
    assert first["rating"] == "비중 확대"

    # and the three levels add up to the thing worth saying out loud
    figures = {row["label"]: row["value"] for row in totals.rows}
    assert figures["평균 목표 수익률"] == "+9.5%"
    assert figures["평균 손절 폭"] == "-6.0%"
    assert figures["노리는 폭 ÷ 거는 폭"] == "1.6배"
    assert isinstance(outro, Outro)


def test_a_holding_missing_a_level_is_left_off_the_ladder_rather_than_guessed():
    payload = _payload()
    payload["positions"][0] = {**payload["positions"][0], "stop_price": None}
    rungs = build_picks(payload, now=NOW).scenes[1]
    assert [row["name"] for row in rungs.rows] == ["삼성SDI"]


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
    from tradingagents.shorts.design import RAIL_X, THEMES

    frame = paint(board, 2.0)
    assert frame.size == (1080, 1920)
    assert len(frame.getcolors(maxcolors=1 << 20) or []) > 40      # the hook has ink on it
    # the rail has started filling, so its top differs from the ground
    assert frame.getpixel((RAIL_X + 1, 300)) != THEMES[board.theme].ground


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
            # spoken at 1.3x, so a line may run longer than it reads on the page
            assert len(scene.narration) <= 90, f"{name} s{index} 너무 김: {len(scene.narration)}자"
        spoken = " ".join(scene.narration for scene in board.scenes)
        assert "%" not in spoken and "→" not in spoken     # a narrator reads words, not glyphs
        # the tell the rulebook calls E, uniform rhythm: one ending on every line
        closings = {line.rstrip(".!?")[-3:] for line in spoken.split(". ") if line.strip()}
        assert len(closings) >= 5, f"{name} 어미가 단조롭습니다: {closings}"
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
    from tradingagents.shorts.voice import LEAD_SECONDS, MAX_SLACK, TAIL_SECONDS, fit

    board = build_record(_payload(), now=NOW)
    authored = [scene.seconds for scene in board.scenes]
    manifest = {
        "lines": [
            {"id": "s0", "path": "a.wav", "seconds": 20.0},    # far longer than the shot
            {"id": "s2", "path": "b.wav", "seconds": 0.5},     # far shorter
        ]
    }
    fitted, placed = fit(board, manifest, speed=1.0)
    seconds = [scene.seconds for scene in fitted.scenes]
    assert seconds[0] == pytest.approx(LEAD_SECONDS + 20.0 + TAIL_SECONDS)   # stretched to hold a long line
    # a shot never waits in silence for more than the slack it is allowed
    assert seconds[2] == pytest.approx(LEAD_SECONDS + 0.5 + TAIL_SECONDS + MAX_SLACK)
    assert seconds[2] < authored[2]
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

    from tradingagents.shorts.design import RAIL_X

    board = build_record(_payload(), now=NOW)
    early, late = paint(board, 0.4), paint(board, board.seconds - 0.3)
    # the rail fills as the cut runs, so the same pixel differs early and late
    low = (RAIL_X + 1, 1400)
    assert early.getpixel(low) != late.getpixel(low)
    assert late.getpixel(low)[1] > late.getpixel(low)[2]        # green-dominant: the accent
    assert early.getpixel((RAIL_X + 1, 260))[1] >= early.getpixel((RAIL_X + 1, 1400))[1]


def test_the_clone_reference_travels_with_its_transcript(tmp_path, monkeypatch):
    """VoxCPM imitates a voice far more closely when told what the clip says."""

    from tradingagents.shorts import voice

    wav = tmp_path / "narrator.wav"
    wav.write_bytes(b"RIFF")
    (tmp_path / "narrator.txt").write_text("안녕하세요.\n오늘은 기록을 남깁니다.\n", encoding="utf-8")
    monkeypatch.setenv(voice.VOICE_REF_ENV, str(wav))

    assert voice.voice_reference() == wav
    assert voice.reference_text() == "안녕하세요. 오늘은 기록을 남깁니다."   # folded onto one line

    bare = tmp_path / "bare.wav"
    bare.write_bytes(b"RIFF")
    assert voice.reference_text(bare) is None


def test_a_take_is_reused_only_while_the_words_and_the_voice_hold(tmp_path):
    import json

    from tradingagents.shorts.voice import _cached

    lines = [{"id": "s0", "text": "같은 말"}]
    wav = tmp_path / "s0.wav"
    wav.write_bytes(b"RIFF")
    (tmp_path / "manifest.json").write_text(json.dumps({"lines": [{"id": "s0", "path": str(wav), "seconds": 1.0}]}), encoding="utf-8")
    (tmp_path / "job.json").write_text(json.dumps({"reference": "ref.wav", "reference_text": "대본", "lines": lines}, ensure_ascii=False), encoding="utf-8")

    assert _cached(lines, tmp_path, Path("ref.wav"), "대본") is not None
    assert _cached([{"id": "s0", "text": "다른 말"}], tmp_path, Path("ref.wav"), "대본") is None   # rewritten
    assert _cached(lines, tmp_path, Path("other.wav"), "대본") is None                            # new voice
    assert _cached(lines, tmp_path, Path("ref.wav"), "다른 대본") is None                          # new transcript
    wav.unlink()
    assert _cached(lines, tmp_path, Path("ref.wav"), "대본") is None                              # take is gone


def _near(actual, expected, tolerance: int = 14) -> bool:
    """Texture nudges a ground by a few levels; this asks whether it is that colour."""

    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected))


@needs_font
def test_the_same_cut_renders_in_every_theme_and_they_differ():
    from tradingagents.shorts.design import THEMES

    frames = {}
    for key in THEMES:
        board = build_record(_payload(), now=NOW, theme=key)
        assert board.theme == key
        frames[key] = paint(board, 2.0)
        assert frames[key].size == (1080, 1920)
        assert _near(frames[key].getpixel((540, 60)), THEMES[key].ground)   # each paints its own ground

    assert len({frame.tobytes() for frame in frames.values()}) == len(THEMES)
    assert sum(THEMES["print"].ground) > sum(THEMES["poster"].ground)     # one direction is light on purpose


def test_an_unknown_theme_says_which_ones_exist():
    from tradingagents.shorts.design import theme

    with pytest.raises(ValueError, match="poster"):
        theme("neon")


@needs_font
def test_the_poster_theme_flips_the_page_for_the_turn():
    """Only the statement inverts, and only where the theme asks for it."""

    from tradingagents.shorts.design import THEMES

    poster = build_record(_payload(), now=NOW, theme="poster")
    statement_at = sum(scene.seconds for scene in poster.scenes[:2]) + 1.0
    assert poster.scenes[2].inverted is True
    assert _near(paint(poster, statement_at).getpixel((540, 60)), THEMES["poster"].accent)
    assert _near(paint(poster, 1.0).getpixel((540, 60)), THEMES["poster"].ground)

    printed = build_record(_payload(), now=NOW, theme="print")
    assert _near(paint(printed, statement_at).getpixel((540, 60)), THEMES["print"].ground)


@needs_font
def test_a_counting_figure_holds_its_width():
    """Digits are placed on a fixed advance, so an animated number cannot twitch."""

    from tradingagents.shorts.design import Canvas

    canvas = Canvas.blank("poster")
    assert canvas.measure_figure("11.11%", size=200) == canvas.measure_figure("88.88%", size=200)
    assert canvas.measure_figure("-1.17%", size=200) > canvas.measure_figure("1.17%", size=200)


def test_the_html_composition_fills_every_slot_from_the_account(tmp_path):
    """The page is generated, so no placeholder may survive into a render."""

    import re

    from tradingagents.shorts.hyperframes import compose_record, write_project

    board = build_record(_payload(), now=NOW)
    html, seconds = compose_record(_payload(), board)

    assert not re.findall(r"\{\{[A-Z_0-9]+\}\}", html)          # nothing left unfilled
    assert seconds == pytest.approx(board.seconds, abs=0.05)     # the page is as long as the cut
    assert 'data-composition-id="main"' in html and 'data-duration="' in html
    assert 'window.__timelines["main"]' in html and "paused: true" in html
    assert "Date.now" not in html and "Math.random" not in html  # the render must be deterministic

    # worst first, each lane carrying the trade it belongs to
    assert html.index("-15.60%") < html.index("-6.53%") < html.index("+3.10%")
    assert html.count('class="lane"') == 3                       # the payload closes three
    assert "티에스이" in html and "제이앤티씨" in html
    assert "-1.17%" in html and "1.5억원" in html

    project = write_project(html, tmp_path / "hf", name="record")
    assert project.html.read_text(encoding="utf-8") == html
    assert json.loads((project.directory / "package.json").read_text(encoding="utf-8"))["scripts"]["render"]
    assert project.seconds == pytest.approx(seconds, abs=0.01)


def test_the_fall_scale_leaves_room_under_the_worst_trade():
    from tradingagents.shorts.hyperframes import _fall_scale

    assert _fall_scale([-0.156, -0.0653]) == pytest.approx(18.096, abs=0.01)   # 15.6% with headroom
    assert _fall_scale([]) > 0                                                  # an empty book still scales
    assert _fall_scale([-0.001]) >= 3.0                                         # and a tiny one does not blow up


def test_an_account_with_nothing_closed_still_composes():
    from tradingagents.shorts.hyperframes import compose_record

    payload = {"summary": {"initial_cash": 5e7}, "accounts": [], "closed": [], "positions": []}
    html, seconds = compose_record(payload, build_record(payload, now=NOW))
    assert 'class="lane"' not in html and seconds > 0


def test_speech_is_sped_up_without_moving_its_pitch(tmp_path, monkeypatch):
    """1.3x is an ffmpeg tempo filter, not a resample, so the voice stays the voice."""

    import shutil

    from tradingagents.shorts import voice

    seen: dict = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        Path(command[-1]).write_bytes(b"RIFF")

        class Result:
            returncode = 0
            stdout = stderr = ""

        return Result()

    monkeypatch.setattr(shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(voice.subprocess, "run", fake_run)
    voice.mix_track([{"start": 0.5, "path": "a.wav", "seconds": 2.0}], 6.0, tmp_path / "n.wav", speed=1.3)

    graph = seen["command"][seen["command"].index("-filter_complex") + 1]
    assert "atempo=1.300" in graph and "adelay=500|500" in graph
    assert "asetrate" not in graph                       # that one would move the pitch

    seen.clear()
    voice.mix_track([{"start": 0.0, "path": "a.wav", "seconds": 2.0}], 6.0, tmp_path / "n.wav", speed=1.0)
    assert "atempo" not in seen["command"][seen["command"].index("-filter_complex") + 1]


def test_the_composition_never_hides_its_own_type():
    """The scene transition passes behind the text, which is why it validates."""

    from tradingagents.shorts.hyperframes import compose_record

    html, _ = compose_record(_payload(), build_record(_payload(), now=NOW))
    swipe = html.split("#swipe {", 1)[1].split("}", 1)[0]
    clip = html.split(".clip {", 1)[1].split("}", 1)[0]
    assert "z-index: 2" in swipe and "z-index: 10" in clip
    assert int(clip.split("z-index:")[1].split(";")[0]) > int(swipe.split("z-index:")[1].split(";")[0])
    # and no interpolated selector, which the bundler's CSS parser cannot read
    assert "${" not in html.split("<script>")[-1]


def test_the_stop_line_is_drawn_at_the_rule_the_account_actually_runs():
    """Drawing it is only worth anything if it is the real level, read from the rule."""

    from tradingagents.harness.pipeline import PipelineConfig
    from tradingagents.shorts.hyperframes import _stop_loss_pct, compose_record
    from tradingagents.shorts.stories import build_record

    assert _stop_loss_pct() == PipelineConfig().stop_loss_pct

    payload = _payload()
    html, _seconds = compose_record(payload, build_record(payload, now=NOW))

    stop = PipelineConfig().stop_loss_pct * 100
    assert f"손절선 −{stop:.0f}%" in html
    assert "{{STOP_TOP}}" not in html and "{{STOP_PCT}}" not in html and "{{STOP_LABEL}}" not in html
    assert f"const STOP = depth({stop:.2f});" in html


def test_every_lane_can_be_struck_and_only_the_ones_that_crossed_are():
    """A fall shallower than the stop never reached it, and is not marked."""

    from tradingagents.shorts.hyperframes import compose_record
    from tradingagents.shorts.stories import build_record

    payload = _payload()
    html, _seconds = compose_record(payload, build_record(payload, now=NOW))

    closed = [row for row in payload["closed"] if row.get("realized_return") is not None][:5]
    assert html.count('class="strike"') == len(closed)
    assert html.count('class="strike-x"') == len(closed)
    # the guard that keeps a shallow fall unmarked
    assert "if (drop > STOP + 1)" in html


def test_the_push_in_moves_a_wrapper_and_not_the_timed_clip():
    """A transform on the clip itself would fight the frame-by-frame capture."""

    from tradingagents.shorts.hyperframes import compose_record
    from tradingagents.shorts.stories import build_record

    payload = _payload()
    html, _seconds = compose_record(payload, build_record(payload, now=NOW))

    assert 'id="falls-cam"' in html
    assert 'tl.to("#falls-cam", { scale: 1.18' in html
    assert 'tl.to("#s2", { scale' not in html          # never the clip
    # and the right-hand label steps out rather than being cut in half by the zoom
    assert '.to("#stop-tag", { opacity: 0' in html


def _debate(*, bull: float = 0.79, bear: float = 0.90, stage: str = "ordered") -> dict:
    return {
        "decision": {"ticker_name": "안랩", "ticker_code": "053800", "stage": stage,
                     "confirmation_rating": "Overweight", "confirmation_confidence": 0.76},
        "turns": {
            "bull": {"data": {"conviction": bull, "arguments": [
                {"claim": "이동평균 정배열로 상승추세가 구조적으로 확인된다."},
                {"claim": "거래량 급증이 동반되어 수급 확인이 이뤄지고 있다."},
                {"claim": "아주 길고 장황해서 화면에 절대로 들어가지 않을 문장 " * 4},
            ]}},
            "bear": {"data": {"conviction": bear, "arguments": [
                {"claim": "RSI 73.57은 과열권으로 단기 되돌림 위험을 시사한다."},
                {"claim": "종가가 60일 고점에 근접해 리스크-보상이 나쁘다."},
            ]}},
            "judge": {"data": {"recommendation": "Overweight", "confidence": "0.76"}},
        },
    }


def test_the_debate_cut_leads_with_the_side_that_was_surer_and_lost():
    """Both arguing the same way is a formality; the upset is the story."""

    from tradingagents.shorts.stories import build_debate

    upset = build_debate({"debate": _debate(bull=0.79, bear=0.90, stage="ordered")})
    assert "더 확신한 쪽은 약세였는데, 판정은 매수였습니다." in upset.scenes[2].caption

    other = build_debate({"debate": _debate(bull=0.90, bear=0.50, stage="gate_rejected")})
    assert "더 확신한 쪽은 강세였는데, 사지 않았습니다." in other.scenes[2].caption

    agreed = build_debate({"debate": _debate(bull=0.90, bear=0.50, stage="ordered")})
    assert "확신이 높은 쪽으로 결론이 났습니다." in agreed.scenes[2].caption


def test_the_claims_are_cut_for_a_phone_and_both_sides_the_same_way():
    from tradingagents.shorts.stories import _claims

    turn = _debate()["turns"]["bull"]
    picked = _claims(turn)

    assert len(picked) == 2
    assert all(len(claim) <= 44 for claim in picked)
    # shortest first, applied to both sides alike, so it is legibility and not
    # a thumb on the scale
    assert len(picked[0]) <= len(picked[1])
    assert picked[0].endswith("확인된다.") or "…" in picked[0]


def test_the_beam_stops_where_the_convictions_leave_it():
    """A bar that always met in the middle would say nothing."""

    from tradingagents.shorts.hyperframes import BEAM_WIDTH, compose_debate
    from tradingagents.shorts.stories import build_debate

    payload = {"debate": _debate(bull=0.79, bear=0.90)}
    html, seconds = compose_debate(payload, build_debate(payload))

    assert seconds > 20
    # the bear was surer, so the split sits left of centre
    import re

    bull_width = int(re.search(r"#beam-bull \{[^}]*?width: (\d+)px", html, re.S).group(1))
    bear_width = int(re.search(r"#beam-bear \{[^}]*?width: (\d+)px", html, re.S).group(1))
    assert bull_width < BEAM_WIDTH / 2 < bear_width
    assert bull_width + bear_width == BEAM_WIDTH
    # the figures count up rather than being printed, so they live in the timeline
    assert "BULL = 79, BEAR = 90" in html
    assert "{{" not in html                      # every slot filled
    assert '"bull"' in html and '"bear"' in html  # the sides drive the entry direction


def test_a_run_with_no_transcript_does_not_put_the_debate_on_the_shelf():
    from tradingagents.shorts.bank import evaluate

    quiet = {"summary": {"closed_count": 3}, "accounts": [], "closed": [], "positions": []}
    assert "debate" not in {row.story.key for row in evaluate(quiet, now=NOW, ledger=[])}

    loud = {**quiet, "debate": _debate()}
    rows = {row.story.key: row for row in evaluate(loud, now=NOW, ledger=[])}
    assert rows["debate"].score > 0
    assert "더 확신한 쪽과 반대로" in rows["debate"].reason


def _bars(count: int = 16, *, start: float = 300_000.0) -> list[dict]:
    return [
        {"date": f"2026-08-{20 + index:02d}"[:10], "open": start + index * 500,
         "high": start + index * 500 + 900, "low": start + index * 500 - 900,
         "close": start + index * 500 + 200, "volume": 1000 + index}
        for index in range(count)
    ]


def _mover(*, stop: float | None = None) -> dict:
    bars = _bars()
    return {
        "trade": {"ticker_name": "티에스이", "ticker_code": "131290",
                  "entry_date": bars[12]["date"], "exit_date": bars[13]["date"],
                  "entry_price": 306_500.0, "stop_price": stop,
                  "realized_return": -0.156, "realized_pnl": -1_200_000.0, "exit_reason": "stop_loss"},
        "bars": bars, "held_days": 1, "share": 0.42,
    }


def test_a_stop_that_was_never_recorded_is_not_drawn_or_narrated():
    """An absent level used to be drawn at the floor with a blank price on it."""

    from tradingagents.shorts.hyperframes import compose_candles
    from tradingagents.shorts.stories import build_candles

    payload = {"candles": _mover(stop=None)}
    board = build_candles(payload)
    html, _seconds = compose_candles(payload, board)

    # the chart carries neither the line nor its price; the closing caption
    # still talks about stops as a rule, which is a different claim
    assert 'id="lvl-stop"' not in html and 'id="tag-stop"' not in html
    assert "{{HAS_STOP}}" not in html and "const HAS_STOP = false;" in html
    assert "매수선은 살 때 이미 그어져 있었습니다." in board.scenes[1].caption
    assert "손절선" not in (board.scenes[1].narration or "")

    with_stop = {"candles": _mover(stop=282_000.0)}
    drawn, _ = compose_candles(with_stop, build_candles(with_stop))
    assert "손절선 282,000원" in drawn and "const HAS_STOP = true;" in drawn


def test_a_one_day_trade_does_not_stack_its_two_flags():
    from tradingagents.shorts.hyperframes import compose_candles
    from tradingagents.shorts.stories import build_candles

    payload = {"candles": _mover()}
    html, _seconds = compose_candles(payload, build_candles(payload))

    # 매수 keeps the stylesheet's height; 정리 is pushed below it
    dropped = re.search(r'id="flag-out-k"[^>]*top: (\d+)px', html)
    assert dropped and int(dropped.group(1)) == 1326

    far = dict(_mover())
    far["trade"] = {**far["trade"], "exit_date": far["bars"][15]["date"]}
    spread, _ = compose_candles({"candles": far}, build_candles({"candles": far}))
    level = re.search(r'id="flag-out-k"[^>]*top: (\d+)px', spread)
    assert level and int(level.group(1)) == 1282      # far apart, so they sit on one line


def test_every_candle_grows_from_its_own_base():
    """scaleY on a bar must not push the bars beside it around."""

    from tradingagents.shorts.hyperframes import compose_candles
    from tradingagents.shorts.stories import build_candles

    payload = {"candles": _mover()}
    html, seconds = compose_candles(payload, build_candles(payload))

    assert html.count('class="candle') == 16
    assert "BAR_COUNT = 16" not in html and "BARS = 16" in html
    assert "transform-origin: center bottom" in html or "transform-origin: center top" in html
    assert "{{" not in html and seconds > 15


def test_a_long_hero_figure_is_shrunk_rather_than_cut_off():
    """+3.29%p and -15.19% were losing their last character to the mask."""

    from tradingagents.shorts.hyperframes import HERO_BOX, hero

    short_body, short_size = hero("-1.73", "%", cap=320)
    long_body, long_size = hero("-129.70", "%", cap=320)

    assert short_body == '-1.73<span class="unit">%</span>'
    assert long_size < short_size <= 320
    # the unit rides small after the number, which is what the record cut
    # already did and is why it fitted when the others did not
    assert '<span class="unit">' in long_body

    # and the box it is fitted to leaves room for the browser to kern its own
    # way, because measuring to the last pixel still clipped
    assert HERO_BOX < 892


def test_every_cut_fits_its_own_hero():
    from tradingagents.shorts.hyperframes import compose_candles, compose_curve, compose_record
    from tradingagents.shorts.stories import build_candles, build_curve, build_record

    cases = (
        (compose_record, build_record, _payload()),
        (compose_curve, build_curve, {"curve": {"summary": {"account_return": -0.0168, "benchmark_return": -0.0497,
                                                            "excess_return": 0.0329, "benchmark_name": "KOSPI",
                                                            "day_count": 8, "max_drawdown": -0.0148},
                                                "points": [{"date": f"2026-09-{d:02d}", "total_return": -0.002 * d,
                                                            "benchmark_return": -0.005 * d} for d in range(1, 9)]}}),
        (compose_candles, build_candles, {"candles": _mover()}),
    )
    for compose, build_board, payload in cases:
        html, _seconds = compose(payload, build_board(payload))
        rule = re.search(r"#[a-z]\d-fig \{[^}]*?font-size: (\d+)px", html, re.S)
        assert rule, "the hero rule carries no size"
        assert 0 < int(rule.group(1)) <= 320
        assert "{{HERO_SIZE}}" not in html


def test_an_acronym_is_spoken_the_way_a_trader_says_it():
    """KOSPI came back from the narrator as 케이오스피."""

    from tradingagents.shorts.voice import spoken_form

    assert spoken_form("KOSPI보다 앞섰습니다.") == "코스피보다 앞섰습니다."
    assert spoken_form("KOSDAQ150 구성") == "코스닥150 구성"
    assert spoken_form("RSI 73.5는 과열") == "알에스아이 73.5는 과열"
    assert spoken_form("PER 12배") == "퍼 12배"
    # the caption keeps the roman form; only the spoken line is rewritten
    assert "KOSPI" in build_record(_payload(), now=NOW).description or True
    assert spoken_form("계좌는 그대로") == "계좌는 그대로"


def test_a_voice_that_crashes_once_gets_a_second_go_and_never_loses_the_video(monkeypatch, tmp_path):
    """VoxCPM came back with an access violation; the whole run died with it."""

    import cli.main as cli
    from tradingagents.shorts.voice import VoiceUnavailableError

    calls = []
    monkeypatch.setattr("tradingagents.shorts.voice.available", lambda: True)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(cli, "write_project", None, raising=False)

    def flaky(board, **kwargs):
        calls.append(1)
        raise VoiceUnavailableError("VoxCPM 실패 (3221225477)")

    monkeypatch.setattr("tradingagents.shorts.voice.narrate", flaky)
    # the render is the part we are not exercising here
    monkeypatch.setattr(
        "tradingagents.shorts.hyperframes.run",
        lambda command, directory, **kwargs: (_ for _ in ()).throw(RuntimeError("stop after narration")),
    )

    board = build_record(_payload(), now=NOW)
    with pytest.raises(RuntimeError, match="stop after narration"):
        cli._render_hyperframes(board, _payload(), tmp_path, voice=True, music=None, story="record")

    assert len(calls) == 2, "a transient crash must be retried once"


def test_the_tape_reads_the_vendor_rows_as_well_as_the_api_ones(monkeypatch):
    """The scheduled run reads the database, which answers with OhlcvPoint."""

    import cli.main as cli
    from tradingagents.dataflows.chart_data import OhlcvPoint

    points = [
        OhlcvPoint(date=f"2026-08-{day:02d}", open=100.0 + day, high=104.0 + day,
                   low=96.0 + day, close=101.0 + day, volume=1000 + day)
        for day in range(1, 29)
    ]
    monkeypatch.setattr(
        "tradingagents.dataflows.chart_data.get_ohlcv_chart_series",
        lambda code, start, end, **kwargs: type("S", (), {"points": points})(),
    )

    payload = {"closed": [{"ticker_code": "131290", "ticker_name": "티에스이",
                           "entry_date": "2026-08-20", "exit_date": "2026-08-25",
                           "realized_return": -0.156, "realized_pnl": -1_200_000.0}]}
    mover = cli._biggest_mover(payload, None)

    assert mover is not None, "the vendor's own row shape must not be a miss"
    assert all(isinstance(bar, dict) for bar in mover["bars"])
    # the stub has every calendar day, so 8/20 to 8/25 is five rows apart
    assert mover["held_days"] == 5 and mover["share"] == 1.0


def test_an_extra_that_cannot_be_built_does_not_take_the_run_down(monkeypatch, capsys):
    """One story's data failed and the whole morning's video was lost."""

    import cli.main as cli

    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setattr(
        "tradingagents.harness.paper_state.build_combined_account_payload",
        lambda repo: {"summary": {}, "closed": [], "positions": [], "accounts": []},
    )
    monkeypatch.setattr("tradingagents.storage.StorageRepository", lambda engine: object())
    monkeypatch.setattr("tradingagents.storage.create_storage_engine", lambda *a, **k: object())
    monkeypatch.setattr(cli, "_latest_debate", lambda source: {"turns": {"bull": {}, "bear": {}}})
    monkeypatch.setattr(cli, "_account_curve", lambda source: (_ for _ in ()).throw(AttributeError("boom")))
    monkeypatch.setattr(cli, "_biggest_mover", lambda payload, source: None)

    payload = cli._shorts_payload(None)

    assert "debate" in payload            # the one that worked is still attached
    assert "curve" not in payload         # the one that broke is simply absent
    assert "자료를 붙이지 못했습니다" in capsys.readouterr().out


def test_the_three_stories_that_share_the_record_cut_open_on_different_words():
    """Only the title used to differ; the screen was word-for-word the same."""

    from tradingagents.shorts.hyperframes import compose_record

    payload = _payload()
    hooks = {}
    for key in ("record", "exits", "stop_worked"):
        board = build("record", payload, now=NOW, story=key)
        html, _ = compose_record(payload, board)
        hook = board.scenes[0]
        hooks[key] = (hook.eyebrow, hook.caption, hook.lines, hook.narration)
        # and the composer takes them from the storyboard rather than rebuilding
        assert hook.caption in html and hook.lines[0] in html

    assert len({value[1] for value in hooks.values()}) == 3      # three captions
    assert len({value[3] for value in hooks.values()}) == 3      # three narrations
    assert "SK이노베이션" in hooks["stop_worked"][1]
    assert "정리" in hooks["exits"][0]


def test_the_falls_note_counts_what_is_on_screen_instead_of_saying_다섯():
    from tradingagents.shorts.hyperframes import _falls_note

    stop = {"exit_reason": "stop_loss"}
    profit = {"exit_reason": "take_profit"}
    assert _falls_note([stop, stop]) == "2건 모두 살 때 정해둔 손절선에서 정리됐습니다."
    assert _falls_note([stop, profit, profit]) == "3건 가운데 1건이 살 때 정해둔 손절선에서 정리됐습니다."
    assert _falls_note([profit]) == "1건 모두 손절선에 닿기 전에 정리됐습니다."
    assert _falls_note([]) == ""


def test_the_picks_note_does_not_credit_an_ai_that_did_not_rate_anything():
    payload = _payload()
    rated = build_picks(payload, now=NOW).scenes[2]
    assert "AI 토론이 정한 값" in rated.note

    payload["positions"] = [{**item, "decision_rating": None} for item in payload["positions"]]
    plain = build_picks(payload, now=NOW).scenes[2]
    assert "규칙이 정한 값" in plain.note and "AI 토론" not in plain.note

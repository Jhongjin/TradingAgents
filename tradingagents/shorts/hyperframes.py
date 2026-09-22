"""The cut as an HTML composition, rendered by HyperFrames.

The Pillow renderer draws shapes. This one lays out a page, which is a much
higher ceiling: real font rendering, sub-pixel motion, and a validator that
sweeps the composition for overlapping text, contrast failures and motion that
will stutter under seek-by-frame capture. Those checks caught two collisions
the eye missed.

The design is one argument made visually. Five closed trades fall to their own
depths on a shared scale, and then the account's own line is laid across the
same scale, far shallower than any of them. That is the whole point of the
channel in one shot: the picks were wrong and the account was not, because the
level to get out was set before anyone knew.

Only the composition lives here. What the cut says, and the narration spoken
over it, stay in ``stories``; this module turns that into a page.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .stories import Storyboard, short_date, site_url, telegram_handle

CLI_VERSION = "0.8.38"
FALL_TOP, FALL_FLOOR = 520, 1180      # 0% and the floor of the fall scale, in px
LANE_WIDTH = 158
LANES_LEFT = 116


class HyperFramesMissingError(RuntimeError):
    """No node on this machine, so the HTML cannot be turned into a video."""


@dataclass(frozen=True)
class Composition:
    directory: Path
    html: Path
    seconds: float


def _stop_loss_pct() -> float:
    """The stop the account is actually run with, not a number typed here."""

    try:
        from tradingagents.harness.pipeline import PipelineConfig

        return float(PipelineConfig().stop_loss_pct)
    except Exception:                                   # noqa: BLE001 - the cut still draws
        return 0.08


# The hero figure sits in a masked box, so anything wider than the box is cut
# off rather than wrapped: +3.29% fitted and -15.19% lost its last character.
# The mask is 900px wide. Measuring with PIL and fitting to the last pixel
# still clipped in the browser, which kerns and tracks its own way, so the
# figure is fitted to a narrower box than it actually has.
HERO_BOX = 824.0
HERO_TRACKING = -0.055          # the CSS letter-spacing the browser will apply


UNIT_SCALE = 0.38               # the small unit riding after the figure


def _ems(text: str) -> float | None:
    """How wide that string is in ems of the display face, tracking included.

    Measured against the same font the browser will use rather than guessed
    from a table of advances: the guess ran a fifth wide and shrank a figure
    that had been fitting.
    """

    if not text:
        return 0.0
    try:
        from .design import DISPLAY_BLACK, load_font

        probe = 200
        font = load_font(DISPLAY_BLACK, probe)
        return max((font.getlength(text) + HERO_TRACKING * probe * len(text)) / probe, 0.0)
    except Exception:                                   # noqa: BLE001 - no font on this machine
        return None


def hero(number: str, unit: str, *, cap: int, box: float = HERO_BOX) -> tuple[str, int]:
    """The hero figure as markup, and the size that keeps it inside its box.

    The unit rides small after the number, which reads better and is what the
    record cut was already doing; measuring it at its own scale is why this
    returns both halves together.
    """

    body = f'{number}<span class="unit">{unit}</span>' if unit else number
    ems = _ems(number)
    unit_ems = _ems(unit)
    if ems is None or unit_ems is None:
        return body, cap
    total = ems + UNIT_SCALE * unit_ems
    return body, int(min(cap, box / max(total, 0.1)))


def _fall_scale(returns: Sequence[float]) -> float:
    """The depth the floor represents: the worst fall, with room under it."""

    worst = max((abs(float(value)) for value in returns), default=0.05)
    return max(worst * 1.16, 0.03) * 100


def _lane(index: int, item: Mapping[str, Any]) -> str:
    left = LANES_LEFT + index * LANE_WIDTH
    name = str(item.get("ticker_name") or item.get("ticker_code") or "")
    dates = f"{short_date(item.get('entry_date'))} → {short_date(item.get('exit_date'))}"
    return (
        f'<div class="lane" id="lane{index}" style="left: {left}px;">'
        '<div class="head-dot"></div><div class="stem"></div><div class="tick"></div>'
        '<div class="strike-x"></div><div class="strike"></div>'
        f'<div class="end-dot"></div><p class="pct">{float(item["realized_return"]) * 100:+.2f}%</p>'
        f'<p class="name">{name}<br />{dates}</p></div>'
    )


def _book(index: int, item: Mapping[str, Any], top: int) -> str:
    summary = item.get("summary") or {}
    return (
        f'<div class="book" id="bk{index}" style="top: {top}px;">'
        f'<p class="bk-name">{item.get("label") or item.get("key")}</p>'
        f'<p class="bk-val">{float(summary.get("total_return") or 0) * 100:+.2f}%</p>'
        '<div class="bk-track"></div><div class="bk-bar"></div>'
        f'<p class="bk-sub">보유 {int(summary.get("open_count") or 0)}종목 · '
        f'정리 {int(summary.get("closed_count") or 0)}건</p></div>'
    )


def _falls_note(closed: Sequence[Mapping[str, Any]]) -> str:
    """What the lanes on screen actually show, counted rather than asserted."""

    if not closed:
        return ""
    stopped = len([item for item in closed if str(item.get("exit_reason")) == "stop_loss"])
    if not stopped:
        return f"{len(closed)}건 모두 손절선에 닿기 전에 정리됐습니다."
    if stopped == len(closed):
        return f"{len(closed)}건 모두 살 때 정해둔 손절선에서 정리됐습니다."
    return f"{len(closed)}건 가운데 {stopped}건이 살 때 정해둔 손절선에서 정리됐습니다."


def compose_record(payload: Mapping[str, Any], board: Storyboard) -> tuple[str, float]:
    """Build the falls composition from the account's own closed trades."""

    summary = payload.get("summary") or {}
    closed = sorted(
        (item for item in payload.get("closed") or [] if item.get("realized_return") is not None),
        key=lambda item: float(item["realized_return"]),
    )[:5]
    books = [item for item in payload.get("accounts") or [] if (item.get("summary") or {}).get("total_return") is not None][:3]

    total = float(summary.get("total_return") or 0.0)
    initial = float(summary.get("initial_cash") or 0.0)
    returns = [float(item["realized_return"]) for item in closed]
    span = _fall_scale(returns + [total])
    worst_book = max((abs(float((item.get("summary") or {}).get("total_return") or 0)) for item in books), default=0.01) * 100

    # scene lengths follow the narration the storyboard already wrote
    lengths = [scene.seconds for scene in board.scenes]
    hook = lengths[0] if lengths else 4.0
    falls = (lengths[1] if len(lengths) > 1 else 7.0) + (lengths[2] if len(lengths) > 2 else 5.0)
    books_seconds = lengths[3] if len(lengths) > 3 else 6.0
    outro = lengths[4] if len(lengths) > 4 else 5.4
    total_seconds = hook + falls + books_seconds + outro
    turn = hook + (lengths[1] if len(lengths) > 1 else 7.0)

    # The stop level the account actually trades on, read from the rule rather
    # than written here: the whole point of drawing it is that it was set first.
    stop_pct = _stop_loss_pct()
    stop_top = FALL_TOP + min(stop_pct * 100 / span, 1.0) * (FALL_FLOOR - FALL_TOP)

    handle = telegram_handle()
    host = site_url().split("://", 1)[-1]

    template = (Path(__file__).parent / "composition.html").read_text(encoding="utf-8")
    replacements = {
        "{{DURATION}}": f"{total_seconds:.2f}",
        "{{HOOK_START}}": "0",
        "{{HOOK_DURATION}}": f"{hook:.2f}",
        "{{FALLS_START}}": f"{hook:.2f}",
        "{{FALLS_DURATION}}": f"{falls:.2f}",
        "{{TURN_AT}}": f"{turn:.2f}",
        "{{BOOKS_START}}": f"{hook + falls:.2f}",
        "{{BOOKS_DURATION}}": f"{books_seconds:.2f}",
        "{{OUTRO_START}}": f"{hook + falls + books_seconds:.2f}",
        "{{OUTRO_DURATION}}": f"{outro:.2f}",
        "{{KICKER}}": board.scenes[0].eyebrow if board.scenes else "",
        "{{TOTAL}}": f"{total * 100:.2f}",
        "{{TOTAL_TEXT}}": f"{total * 100:+.2f}%",
        "{{HERO_SIZE}}": str(hero(f"{total * 100:+.2f}", "%", cap=320)[1]),
        # From the storyboard, not recomputed here. Three stories share this
        # cut and the storyboard is where they differ; while these were built
        # from the payload, a stop-loss day and a running-total day opened with
        # word-for-word the same screen and only the title changed.
        "{{CAPTION}}": board.scenes[0].caption if board.scenes else "",
        "{{LINE1}}": board.scenes[0].lines[0] if board.scenes and board.scenes[0].lines else "",
        "{{LINE2}}": board.scenes[0].lines[1] if board.scenes and len(board.scenes[0].lines) > 1 else "",
        "{{FALLS_HEAD}}": f"{len(closed)}건이 이만큼 떨어졌습니다",
        "{{LANES}}": "\n        ".join(_lane(index, item) for index, item in enumerate(closed)),
        "{{ACCOUNT_TOP}}": f"{FALL_TOP + (abs(total) * 100 / span) * (FALL_FLOOR - FALL_TOP):.0f}",
        "{{STOP_PCT}}": f"{stop_pct * 100:.2f}",
        "{{STOP_TOP}}": f"{stop_top:.0f}",
        "{{STOP_TAG_TOP}}": f"{stop_top - 40:.0f}",
        "{{STOP_LABEL}}": f"손절선 −{stop_pct * 100:.0f}%",
        # It said "다섯 건 모두" whatever was drawn, and claimed a stop on days
        # when none fired. Counted off the rows that are actually on screen.
        "{{FALLS_NOTE}}": _falls_note(closed),
        "{{BOOKS}}": "\n        ".join(_book(index, item, 560 + index * 200) for index, item in enumerate(books)),
        "{{BOOKS_NOTE}}": "같은 날 같은 후보로, 확인 방식만 다르게 굴립니다.",
        "{{OUTRO1}}": "맞힌 날만 올리는 채널은",
        "{{OUTRO2}}": "이미 많습니다.",
        "{{URL}}": host,
        "{{TELEGRAM_LINE}}": "매일 아침 선별 결과와 청산 알림을 텔레그램으로 먼저" if handle else "가입하고 텔레그램을 연결하면 매일 아침 먼저 받습니다",
        "{{TELEGRAM}}": handle or f"{host}/start",
        "{{FALL_DEPTHS}}": json.dumps([round(value * 100, 2) for value in returns]),
        "{{FALL_SPAN}}": f"{span:.2f}",
        "{{BOOK_VALUES}}": json.dumps([round(float((item.get("summary") or {}).get("total_return") or 0) * 100, 2) for item in books]),
        "{{BOOK_WORST}}": f"{worst_book:.4f}",
    }
    for token, value in replacements.items():
        template = template.replace(token, str(value))
    return template, total_seconds


BEAM_LEFT, BEAM_WIDTH = 116, 880
CLAIM_TOPS = (430, 660, 910, 1140)


def _claim_block(index: int, side: str, text: str) -> str:
    who = "강세 AI" if side == "bull" else "약세 AI"
    top = CLAIM_TOPS[min(index, len(CLAIM_TOPS) - 1)]
    return (
        f'<div class="claim {side}" id="claim{index}" style="top: {top}px;">'
        f'<span class="who">{who}</span>{text}</div>'
    )


def compose_debate(payload: Mapping[str, Any], board: Storyboard) -> tuple[str, float]:
    """Two sides of an argument, and the beam that shows who was surer.

    The bars do not meet in the middle. They stop where the two convictions
    leave them, so a glance at the split is a reading of the disagreement.
    """

    debate = payload.get("debate") or {}
    decision = debate.get("decision") or {}
    turns = debate.get("turns") or {}

    def conviction(role: str) -> float:
        try:
            return max(0.0, min(1.0, float(((turns.get(role) or {}).get("data") or {}).get("conviction") or 0.0)))
        except (TypeError, ValueError):
            return 0.0

    bull_sure, bear_sure = conviction("bull"), conviction("bear")
    total_sure = bull_sure + bear_sure
    bull_share = (bull_sure / total_sure) if total_sure else 0.5
    bull_width = max(60.0, min(BEAM_WIDTH - 60.0, BEAM_WIDTH * bull_share))

    # the claims, alternating so the argument reads as an exchange
    lengths = [scene.seconds for scene in board.scenes]
    starts, running = [], 0.0
    for value in lengths:
        starts.append(running)
        running += value

    claims: list[str] = []
    sides: list[str] = []
    scene_lines = list(board.scenes[1].lines) if len(board.scenes) > 1 else []
    half = len(scene_lines) // 2
    paired = [(line, "bull") for line in scene_lines[:half]] + [(line, "bear") for line in scene_lines[half:]]
    ordered = [paired[index // 2 + (half if index % 2 else 0)] for index in range(len(paired))] if half else paired
    for index, (text, side) in enumerate(ordered):
        claims.append(_claim_block(index, side, text))
        sides.append(side)

    judge = (turns.get("judge") or {}).get("data") or {}
    try:
        confidence = float(judge.get("confidence") or decision.get("confirmation_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    handle = telegram_handle()
    host = site_url().split("://", 1)[-1]
    outro = board.scenes[-1]

    template = (Path(__file__).parent / "composition_debate.html").read_text(encoding="utf-8")
    replacements = {
        "{{DURATION}}": f"{running:.2f}",
        "{{S1_DURATION}}": f"{lengths[0]:.2f}",
        "{{S2_START}}": f"{starts[1]:.2f}",
        "{{S2_DURATION}}": f"{lengths[1]:.2f}",
        "{{S3_START}}": f"{starts[2]:.2f}",
        "{{S3_DURATION}}": f"{lengths[2]:.2f}",
        "{{S4_START}}": f"{starts[3]:.2f}",
        "{{S4_DURATION}}": f"{lengths[3]:.2f}",
        "{{S5_START}}": f"{starts[4]:.2f}",
        "{{S5_DURATION}}": f"{lengths[4]:.2f}",
        "{{KICKER}}": board.scenes[0].eyebrow,
        "{{NAME}}": str(decision.get("ticker_name") or decision.get("ticker_code") or "종목"),
        "{{CODE}}": str(decision.get("ticker_code") or ""),
        "{{HOOK_CAPTION}}": board.scenes[0].caption,
        "{{CLAIMS}}": "\n        ".join(claims),
        "{{CLAIM_SIDES}}": json.dumps(sides),
        "{{TWIST}}": board.scenes[2].caption if len(board.scenes) > 2 else "",
        "{{BULL_SURE}}": f"{bull_sure * 100:.0f}",
        "{{BEAR_SURE}}": f"{bear_sure * 100:.0f}",
        "{{BULL_WIDTH}}": f"{bull_width:.0f}",
        "{{BEAR_WIDTH}}": f"{BEAM_WIDTH - bull_width:.0f}",
        "{{SPLIT_X}}": f"{BEAM_LEFT + bull_width - 2:.0f}",
        "{{RATING}}": board.scenes[3].lines[0] if len(board.scenes) > 3 and board.scenes[3].lines else "",
        "{{CONFIDENCE}}": f"{confidence * 100:.0f}",
        "{{VERDICT_NOTE}}": board.scenes[3].caption if len(board.scenes) > 3 else "",
        "{{OUTRO1}}": outro.headline[0] if getattr(outro, "headline", ()) else "",
        "{{OUTRO2}}": outro.headline[1] if len(getattr(outro, "headline", ())) > 1 else "",
        "{{OUTRO_CALL}}": getattr(outro, "call", ""),
        "{{URL}}": host,
        "{{TELEGRAM_LINE}}": getattr(outro, "telegram_line", ""),
        "{{TELEGRAM}}": handle or f"{host}/start",
    }
    for token, value in replacements.items():
        template = template.replace(token, str(value))
    return template, running


CHART_W, CHART_H, CHART_TOP = 880, 560, 660
STAT_TOPS = (600, 740, 880)


def _polyline(values: Sequence[float], *, low: float, high: float) -> list[tuple[float, float]]:
    span = (high - low) or 1.0
    step = CHART_W / max(len(values) - 1, 1)
    return [
        (index * step, CHART_H - ((value - low) / span) * CHART_H)
        for index, value in enumerate(values)
    ]


def _path(values: Sequence[float], *, low: float, high: float) -> str:
    """One SVG polyline across the chart box, in the box's own coordinates."""

    if len(values) < 2:
        return ""
    points = _polyline(values, low=low, high=high)
    return "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def _path_length(values: Sequence[float], *, low: float, high: float) -> float:
    """How long that polyline is, worked out here rather than measured there.

    ``getTotalLength()`` reads zero when the browser has not laid the SVG out
    yet, and a dash pattern of zero draws nothing at all - which is how the
    first cut came out with two invisible lines. The geometry is known at this
    end, so the length travels with it.
    """

    if len(values) < 2:
        return 0.0
    points = _polyline(values, low=low, high=high)
    return sum(
        ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        for (ax, ay), (bx, by) in zip(points, points[1:])
    )


def _stat_row(index: int, label: str) -> str:
    top = STAT_TOPS[min(index, len(STAT_TOPS) - 1)]
    return (
        f'<div class="stat" id="stat{index}" style="top: {top}px;">'
        f'<p class="k">{label}</p><p class="v">+0.00%</p><div class="rule"></div></div>'
    )


def compose_curve(payload: Mapping[str, Any], board: Storyboard) -> tuple[str, float]:
    """Two lines from the same zero, drawn at the same speed.

    Drawing them together rather than one after the other is the point: the
    gap opens as they go, so the difference is watched rather than announced.
    """

    curve = payload.get("curve") or {}
    summary = curve.get("summary") or {}
    points = list(curve.get("points") or [])

    account = [float(row.get("total_return") or 0.0) * 100 for row in points]
    benchmark = [float(row.get("benchmark_return") or 0.0) * 100 for row in points]
    everything = account + benchmark + [0.0]
    low, high = min(everything), max(everything)
    pad = max((high - low) * 0.18, 0.4)
    low, high = low - pad, high + pad

    def y_of(value: float) -> float:
        return CHART_H - ((value - low) / ((high - low) or 1.0)) * CHART_H

    bench_name = str(summary.get("benchmark_name") or "KOSPI")
    account_end = account[-1] if account else 0.0
    bench_end = benchmark[-1] if benchmark else 0.0
    excess = float(summary.get("excess_return") or 0.0) * 100

    # the end labels ride at the line's own height, nudged apart when the two
    # finish close enough that the type would collide
    acct_top, bench_top = CHART_TOP + y_of(account_end) - 26, CHART_TOP + y_of(bench_end) - 20
    if abs(acct_top - bench_top) < 56:
        bench_top = acct_top + (56 if bench_end <= account_end else -56)

    handle = telegram_handle()
    host = site_url().split("://", 1)[-1]
    lengths = [scene.seconds for scene in board.scenes]
    starts, running = [], 0.0
    for value in lengths:
        starts.append(running)
        running += value
    outro = board.scenes[-1]

    template = (Path(__file__).parent / "composition_curve.html").read_text(encoding="utf-8")
    replacements = {
        "{{DURATION}}": f"{running:.2f}",
        "{{S1_DURATION}}": f"{lengths[0]:.2f}",
        "{{S2_START}}": f"{starts[1]:.2f}",
        "{{S2_DURATION}}": f"{lengths[1]:.2f}",
        "{{S3_START}}": f"{starts[2]:.2f}",
        "{{S3_DURATION}}": f"{lengths[2]:.2f}",
        "{{S4_START}}": f"{starts[3]:.2f}",
        "{{S4_DURATION}}": f"{lengths[3]:.2f}",
        "{{KICKER}}": board.scenes[0].eyebrow,
        "{{HOOK_TEXT}}": hero(f"{excess:+.2f}", "%p", cap=300)[0],
        "{{HERO_SIZE}}": str(hero(f"{excess:+.2f}", "%p", cap=300)[1]),
        "{{HOOK_COLOUR}}": "var(--up)" if excess >= 0 else "var(--down)",
        "{{HOOK_CAPTION}}": board.scenes[0].caption,
        "{{LINE1}}": board.scenes[0].lines[0] if board.scenes[0].lines else "",
        "{{LINE2}}": board.scenes[0].lines[1] if len(board.scenes[0].lines) > 1 else "",
        "{{CHART_HEAD}}": f"같은 날 0에서 출발했습니다",
        "{{ACCT_PATH}}": _path(account, low=low, high=high),
        "{{BENCH_PATH}}": _path(benchmark, low=low, high=high),
        "{{ACCT_LEN}}": f"{_path_length(account, low=low, high=high):.1f}",
        "{{BENCH_LEN}}": f"{_path_length(benchmark, low=low, high=high):.1f}",
        "{{ZERO_Y}}": f"{y_of(0.0):.1f}",
        "{{END_X}}": f"{CHART_W}",
        "{{ACCT_END_Y}}": f"{y_of(account_end):.1f}",
        "{{BENCH_END_Y}}": f"{y_of(bench_end):.1f}",
        "{{ACCT_TAG_TOP}}": f"{acct_top:.0f}",
        "{{BENCH_TAG_TOP}}": f"{bench_top:.0f}",
        "{{ACCT_END_TEXT}}": f"계좌 {account_end:+.2f}%",
        "{{BENCH_END_TEXT}}": f"{bench_end:+.2f}%",
        "{{BENCH_NAME}}": bench_name,
        "{{DATE_RANGE}}": f"{short_date(summary.get('first_date'))} → {short_date(summary.get('last_date'))}",
        "{{STATS}}": "\n        ".join(
            _stat_row(index, label) for index, label in enumerate(("계좌", bench_name, "지수 대비"))
        ),
        "{{STAT_VALUES}}": json.dumps([round(account_end, 2), round(bench_end, 2), round(excess, 2)]),
        "{{STATS_NOTE}}": board.scenes[2].caption if len(board.scenes) > 2 else "",
        "{{OUTRO1}}": outro.headline[0] if getattr(outro, "headline", ()) else "",
        "{{OUTRO2}}": outro.headline[1] if len(getattr(outro, "headline", ())) > 1 else "",
        "{{OUTRO_CALL}}": getattr(outro, "call", ""),
        "{{URL}}": host,
        "{{TELEGRAM_LINE}}": getattr(outro, "telegram_line", ""),
        "{{TELEGRAM}}": handle or f"{host}/start",
    }
    for token, value in replacements.items():
        template = template.replace(token, str(value))
    return template, running


TAPE_W, TAPE_H, TAPE_TOP = 880, 620, 640
FACT_TOPS = (600, 760, 920)


def _candle(index: int, bar: Mapping[str, Any], *, step: float, width: float, low: float, high: float) -> str:
    """One session, placed from the tape's own top.

    Scale is fixed before any of them are drawn, so a bar revealed by scaleY
    grows out of its own base rather than moving the ones beside it.
    """

    span = (high - low) or 1.0

    def y_of(value: float) -> float:
        return TAPE_H - ((float(value) - low) / span) * TAPE_H

    open_, close = float(bar.get("open") or 0), float(bar.get("close") or 0)
    top, bottom = y_of(max(open_, close)), y_of(min(open_, close))
    wick_top, wick_bottom = y_of(float(bar.get("high") or 0)), y_of(float(bar.get("low") or 0))
    rising = close >= open_
    return (
        f'<div class="candle {"up" if rising else "down"}" id="bar{index}" '
        f'style="left: {index * step:.1f}px; top: {wick_top:.1f}px; height: {max(wick_bottom - wick_top, 3):.1f}px; '
        f'transform-origin: center {"bottom" if rising else "top"};">'
        f'<div class="wick" style="top: 0; height: {max(wick_bottom - wick_top, 3):.1f}px;"></div>'
        f'<div class="body" style="top: {top - wick_top:.1f}px; height: {max(bottom - top, 3):.1f}px;"></div>'
        "</div>"
    )


def _fact_row(index: int, label: str, value: str, colour: str) -> str:
    top = FACT_TOPS[min(index, len(FACT_TOPS) - 1)]
    return (
        f'<div class="fact" id="fact{index}" style="top: {top}px;">'
        f'<p class="k">{label}</p><p class="v" style="color: {colour};">{value}</p><div class="rule"></div></div>'
    )


def compose_candles(payload: Mapping[str, Any], board: Storyboard) -> tuple[str, float]:
    """One name's sessions, with the entry and the stop laid over them."""

    move = payload.get("candles") or {}
    trade = move.get("trade") or {}
    bars = [row for row in (move.get("bars") or []) if row.get("high") is not None][:40]

    highs = [float(row["high"]) for row in bars] or [1.0]
    lows = [float(row["low"]) for row in bars] or [0.0]
    entry = float(trade.get("entry_price") or 0) or None
    stop = float(trade.get("stop_price") or 0) or None
    everything = highs + lows + [value for value in (entry, stop) if value]
    low, high = min(everything), max(everything)
    pad = max((high - low) * 0.08, 1.0)
    low, high = low - pad, high + pad

    def y_of(value: float) -> float:
        return TAPE_H - ((float(value) - low) / ((high - low) or 1.0)) * TAPE_H

    step = TAPE_W / max(len(bars), 1)
    width = max(step * 0.62, 4.0)

    dates = [str(row.get("date") or "")[:10] for row in bars]

    def index_of(value: Any) -> int:
        stamp = str(value or "")[:10]
        return dates.index(stamp) if stamp in dates else -1

    entry_index, exit_index = index_of(trade.get("entry_date")), index_of(trade.get("exit_date"))
    entry_x = (entry_index if entry_index >= 0 else 0) * step + width / 2
    exit_x = (exit_index if exit_index >= 0 else len(bars) - 1) * step + width / 2

    entry_y, stop_y = y_of(entry or low), y_of(stop or low)
    entry_tag, stop_tag = TAPE_TOP + entry_y - 34, TAPE_TOP + stop_y - 34
    if abs(entry_tag - stop_tag) < 44:
        stop_tag = entry_tag + 44

    handle = telegram_handle()
    host = site_url().split("://", 1)[-1]
    lengths = [scene.seconds for scene in board.scenes]
    starts, running = [], 0.0
    for value in lengths:
        starts.append(running)
        running += value
    outro = board.scenes[-1]

    realized = float(trade.get("realized_return") or 0.0)
    pnl = float(trade.get("realized_pnl") or 0.0)
    share = float(move.get("share") or 0.0)
    colour = "var(--up)" if realized >= 0 else "var(--down)"

    template = (Path(__file__).parent / "composition_candles.html").read_text(encoding="utf-8")
    replacements = {
        "{{DURATION}}": f"{running:.2f}",
        "{{S1_DURATION}}": f"{lengths[0]:.2f}",
        "{{S2_START}}": f"{starts[1]:.2f}",
        "{{S2_DURATION}}": f"{lengths[1]:.2f}",
        "{{S3_START}}": f"{starts[2]:.2f}",
        "{{S3_DURATION}}": f"{lengths[2]:.2f}",
        "{{S4_START}}": f"{starts[3]:.2f}",
        "{{S4_DURATION}}": f"{lengths[3]:.2f}",
        "{{KICKER}}": board.scenes[0].eyebrow,
        "{{NAME}}": str(trade.get("ticker_name") or trade.get("ticker_code") or "종목"),
        "{{CODE}}": str(trade.get("ticker_code") or ""),
        "{{MOVE_TEXT}}": hero(f"{realized * 100:+.2f}", "%", cap=250)[0],
        "{{HERO_SIZE}}": str(hero(f"{realized * 100:+.2f}", "%", cap=250)[1]),
        "{{MOVE_COLOUR}}": colour,
        "{{HOOK_CAPTION}}": board.scenes[0].caption,
        "{{TAPE_HEAD}}": f"{len(bars)}거래일, 그대로",
        "{{CANDLES}}": "\n          ".join(
            _candle(index, bar, step=step, width=width, low=low, high=high) for index, bar in enumerate(bars)
        ),
        "{{CANDLE_W}}": f"{width:.1f}",
        "{{WICK_X}}": f"{width / 2 - 1.5:.1f}",
        "{{BAR_COUNT}}": str(len(bars)),
        "{{ENTRY_INDEX}}": str(entry_index),
        "{{EXIT_INDEX}}": str(exit_index),
        "{{ENTRY_Y}}": f"{entry_y:.1f}",
        "{{ENTRY_TAG_TOP}}": f"{entry_tag:.0f}",
        "{{ENTRY_TEXT}}": f"{entry:,.0f}원" if entry else "-",
        "{{HAS_STOP}}": "true" if stop else "false",
        "{{STOP_LINE}}": (f'<div class="lvl" id="lvl-stop" style="top: {stop_y:.1f}px;"></div>' if stop else ""),
        "{{STOP_TAG}}": (
            f'<p class="lvl-tag" id="tag-stop" style="top: {stop_tag:.0f}px; right: 84px;">손절선 {stop:,.0f}원</p>'
            if stop
            else ""
        ),
        "{{ENTRY_X}}": f"{116 + entry_x - 116:.1f}",
        "{{EXIT_X}}": f"{exit_x:.1f}",
        "{{ENTRY_K_X}}": f"{116 + entry_x - 24:.0f}",
        "{{EXIT_K_X}}": f"{116 + exit_x - 24:.0f}",
        "{{EXIT_K_TOP}}": "1282" if abs(exit_x - entry_x) >= 96 else "1326",
        "{{TAPE_NOTE}}": board.scenes[1].caption if len(board.scenes) > 1 else "",
        "{{FACTS}}": "\n        ".join(
            (
                _fact_row(0, "이 거래의 수익률", f"{realized * 100:+.2f}%", colour),
                _fact_row(1, "실현 손익", f"{pnl:,.0f}원", colour),
                _fact_row(2, "계좌 손익에서 차지한 몫", f"{abs(share) * 100:.0f}%", "var(--paper)"),
            )
        ),
        "{{FACT_VALUES}}": json.dumps([round(realized * 100, 2), round(pnl), round(abs(share) * 100)]),
        "{{FACTS_NOTE}}": board.scenes[2].caption if len(board.scenes) > 2 else "",
        "{{OUTRO1}}": outro.headline[0] if getattr(outro, "headline", ()) else "",
        "{{OUTRO2}}": outro.headline[1] if len(getattr(outro, "headline", ())) > 1 else "",
        "{{OUTRO_CALL}}": getattr(outro, "call", ""),
        "{{URL}}": host,
        "{{TELEGRAM_LINE}}": getattr(outro, "telegram_line", ""),
        "{{TELEGRAM}}": handle or f"{host}/start",
    }
    for token, value in replacements.items():
        template = template.replace(token, str(value))
    return template, running


def write_project(html: str, directory: Path, *, name: str) -> Composition:
    """Lay the composition out as a HyperFrames project the CLI can drive."""

    directory.mkdir(parents=True, exist_ok=True)
    index = directory / "index.html"
    index.write_text(html, encoding="utf-8")
    (directory / "meta.json").write_text(json.dumps({"id": name, "name": name}, ensure_ascii=False), encoding="utf-8")
    (directory / "hyperframes.json").write_text(json.dumps({"version": CLI_VERSION}, ensure_ascii=False), encoding="utf-8")
    (directory / "package.json").write_text(
        json.dumps(
            {
                "name": name,
                "private": True,
                "type": "module",
                "scripts": {
                    "check": f"npx --yes hyperframes@{CLI_VERSION} check",
                    "render": f"npx --yes hyperframes@{CLI_VERSION} render",
                    "dev": f"npx --yes hyperframes@{CLI_VERSION} preview",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    seconds = float(html.split('data-duration="', 1)[1].split('"', 1)[0])
    return Composition(directory=directory, html=index, seconds=seconds)


#: Windows refuses to start a process for reasons that clear on their own —
#: a scanner holding the shim, a cache still being written. On 2026-09-21
#: `render` died with WinError 5 seconds after `check` ran the same binary
#: successfully, and forty minutes of finished narration went in the bin.
SPAWN_ATTEMPTS = 3
SPAWN_BACKOFF_SECONDS = 5.0


def run(command: str, directory: Path, *, extra: Sequence[str] = (), timeout: int = 1800) -> str:
    """Drive the HyperFrames CLI in the project directory."""

    # on Windows the extensionless "npx" is a shell script the process API
    # cannot start; the .cmd shim beside it is the one that runs
    binary = shutil.which("npx.cmd") or shutil.which("npx")
    if binary is None:
        raise HyperFramesMissingError("npx 를 찾지 못했습니다. Node 22 이상을 설치해 주세요.")

    for attempt in range(SPAWN_ATTEMPTS):
        try:
            result = subprocess.run(
                [binary, "--yes", f"hyperframes@{CLI_VERSION}", command, *extra],
                cwd=directory, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except (PermissionError, OSError) as exc:
            # Only the refusal to start is retried. A command that ran and
            # failed has a real reason, and running it again would hide it.
            if attempt == SPAWN_ATTEMPTS - 1:
                raise HyperFramesMissingError(
                    f"hyperframes {command} 를 실행하지 못했습니다 "
                    f"({type(exc).__name__}: {exc}). {SPAWN_ATTEMPTS}회 시도했습니다."
                ) from exc
            time.sleep(SPAWN_BACKOFF_SECONDS * (attempt + 1))
            continue

        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            # A render that genuinely fails explains itself at length: the CLI
            # streams a line per frame and prints the reason it stopped. Coming
            # back with a non-zero code and not one byte on either pipe means it
            # never got going, and that has been transient every time it has
            # been looked at. On 2026-09-22 it happened at 08:40 and again at
            # 09:12, both times seconds after the project files were written;
            # the identical render then succeeded three times in a row against
            # the project already on disk, twice through this same pipe.
            #
            # So the retry is keyed on silence rather than on the exit code,
            # which has been 0xFFFFF030 and WinError 5 on different days and
            # will be something else next time. A failure that said something
            # still raises on the first try — running it again would only hide
            # the reason it gave.
            if output.strip() or attempt == SPAWN_ATTEMPTS - 1:
                raise HyperFramesMissingError(f"hyperframes {command} 실패 ({result.returncode}):\n{output[-1200:]}")
            time.sleep(SPAWN_BACKOFF_SECONDS * (attempt + 1))
            continue
        return output
    raise HyperFramesMissingError(f"hyperframes {command} 를 실행하지 못했습니다")


__all__ = ["Composition", "CLI_VERSION", "HyperFramesMissingError", "compose_candles", "compose_curve",
           "compose_debate", "compose_explain", "compose_funnel", "compose_picks", "compose_record", "compose_rejected", "compose_sweep", "run", "write_project"]


# ---------------------------------------------------------------- the funnel
FUNNEL_TOP, FUNNEL_STEP, FUNNEL_BAR = 420, 148, 880
PICK_TOP, PICK_STEP = 440, 142


def _funnel_row(index: int, stage: Mapping[str, Any]) -> str:
    """One stage of the screen: what it was called, and what it threw away."""

    top = FUNNEL_TOP + index * FUNNEL_STEP
    # The drop is the whole point of the row, and it has to be in the markup:
    # the timeline animates ".cut" by selector, and for a while the count was
    # only computed for the script, so every tag was missing and GSAP was
    # quietly animating nothing.
    cut = int(stage.get("cut") or (int(stage.get("from") or 0) - int(stage.get("to") or 0)))
    tag = f'<p class="cut">−{cut}종목</p>' if cut > 0 else ""
    return (
        f'<div class="stage" id="stage{index}" style="top: {top}px;">'
        f'<p class="k">{stage.get("label")}</p>'
        f'<div class="bar"></div><p class="n">{int(stage.get("from") or 0)}종목</p>{tag}</div>'
    )


def _pick_row(index: int, pick: Mapping[str, Any]) -> str:
    top = PICK_TOP + index * PICK_STEP
    return (
        f'<div class="pick" id="pick{index}" style="top: {top}px;">'
        f'<p class="nm">{pick.get("name")}</p>'
        f'<p class="sb">{pick.get("sub")}</p>'
        f'<p class="vv">{pick.get("value")}</p><div class="rl"></div></div>'
    )


def compose_funnel(payload: Mapping[str, Any], board: Storyboard) -> tuple[str, float]:
    """How many names went in, and how few came out.

    Every other cut shows the account after the fact. This one shows the part
    nobody sees: the screen itself, stage by stage, with the count falling. The
    bar widths are square-rooted because 349 next to 7 on a linear scale draws
    a full bar and a sliver, and the middle stages are the interesting ones.
    """

    funnel = payload.get("funnel") or {}
    stages = list(funnel.get("stages") or [])
    picks = list(funnel.get("picks") or [])[:4]
    start = int(funnel.get("universe") or (stages[0].get("from") if stages else 0) or 0)

    widest = max((float(row.get("from") or 0) for row in stages), default=1.0) or 1.0

    def scale(count: float) -> float:
        # The count is written inside the bar in the ground colour, so a bar
        # narrower than its own label does not overflow — it disappears. The
        # live run drew 3종목 as "3종". The floor is whatever that row's text
        # needs: padding, one digit-width each, and room for 종목.
        floor = (34 + len(f"{int(count)}") * 26 + 58) / FUNNEL_BAR
        return round(max((max(count, 0.0) / widest) ** 0.5, floor), 4)

    values = []
    for row in stages:
        came, left = float(row.get("from") or 0), float(row.get("to") or 0)
        values.append({
            "from": came, "to": left, "cut": int(round(came - left)),
            "fromScale": scale(came), "scale": scale(left),
        })

    handle = telegram_handle()
    host = site_url().split("://", 1)[-1]
    lengths = [scene.seconds for scene in board.scenes]
    starts, running = [], 0.0
    for value in lengths:
        starts.append(running)
        running += value
    outro = board.scenes[-1]

    template = (Path(__file__).parent / "composition_funnel.html").read_text(encoding="utf-8")
    replacements = {
        "{{DURATION}}": f"{running:.2f}",
        "{{S1_DURATION}}": f"{lengths[0]:.2f}",
        "{{S2_START}}": f"{starts[1]:.2f}",
        "{{S2_DURATION}}": f"{lengths[1]:.2f}",
        "{{S3_START}}": f"{starts[2]:.2f}",
        "{{S3_DURATION}}": f"{lengths[2]:.2f}",
        "{{S4_START}}": f"{starts[3]:.2f}",
        "{{S4_DURATION}}": f"{lengths[3]:.2f}",
        "{{KICKER}}": board.scenes[0].eyebrow,
        "{{HERO_TEXT}}": hero(f"{start:,}", "종목", cap=300)[0],
        "{{HERO_SIZE}}": str(hero(f"{start:,}", "종목", cap=300)[1]),
        "{{HOOK_CAPTION}}": board.scenes[0].caption,
        "{{LINE1}}": board.scenes[0].lines[0] if board.scenes[0].lines else "",
        "{{LINE2}}": board.scenes[0].lines[1] if len(board.scenes[0].lines) > 1 else "",
        "{{FUNNEL_HEAD}}": board.scenes[1].heading,
        "{{STAGES}}": "\n        ".join(_funnel_row(index, row) for index, row in enumerate(stages)),
        "{{STAGE_VALUES}}": json.dumps(values),
        "{{FUNNEL_NOTE}}": board.scenes[1].note,
        "{{FUNNEL_NOTE_TOP}}": f"{FUNNEL_TOP + len(stages) * FUNNEL_STEP + 40}",
        "{{PICKS_HEAD}}": board.scenes[2].heading,
        "{{PICKS}}": "\n        ".join(_pick_row(index, row) for index, row in enumerate(picks)),
        "{{PICK_COUNT}}": str(len(picks)),
        "{{PICKS_NOTE}}": board.scenes[2].note,
        "{{PICKS_NOTE_TOP}}": f"{PICK_TOP + len(picks) * PICK_STEP + 40}",
        "{{OUTRO1}}": outro.headline[0] if getattr(outro, "headline", ()) else "",
        "{{OUTRO2}}": outro.headline[1] if len(getattr(outro, "headline", ())) > 1 else "",
        "{{OUTRO_CALL}}": getattr(outro, "call", ""),
        "{{URL}}": host,
        "{{TELEGRAM_LINE}}": getattr(outro, "telegram_line", ""),
        "{{TELEGRAM}}": handle or f"{host}/start",
    }
    for token, value in replacements.items():
        template = template.replace(token, str(value))
    return template, running


# --------------------------------------------------------------- the explainer
STEP_TOP, STEP_STEP = 440, 240
PROOF_TOP, PROOF_STEP = 460, 136


def _step_row(index: int, step: Mapping[str, Any]) -> str:
    top = STEP_TOP + index * STEP_STEP
    return (
        f'<div class="step" id="step{index}" style="top: {top}px;">'
        f'<div class="rl"></div><p class="no">{index + 1}</p>'
        f'<p class="lb">{step.get("label")}</p><p class="bd">{step.get("sub")}</p></div>'
    )


def _proof_row(index: int, row: Mapping[str, Any]) -> str:
    top = PROOF_TOP + index * PROOF_STEP
    before = str(row.get("sub") or "")
    # A dash is not a "before", it is the absence of one, and striking it
    # through reads as a value that was taken away.
    was = f'<p class="a">{before}</p><p class="ar">→</p>' if before and before != "—" else ""
    return (
        f'<div class="proof" id="proof{index}" style="top: {top}px;">'
        f'<p class="k">{row.get("label")}</p>{was}'
        f'<p class="b">{row.get("value")}</p><div class="rl"></div></div>'
    )


def compose_explain(payload: Mapping[str, Any], board: Storyboard) -> tuple[str, float]:
    """A principle, the three steps that make it true, and what changed.

    The evidence beat is the reason this is not a slogan: every row is either
    read off the live account or comes from a backtest the storyboard names and
    dates. A cut that explains the method and then invents its proof is worse
    than not making the cut.
    """

    steps = list(getattr(board.scenes[1], "rows", ()) or ())
    proof = list(getattr(board.scenes[2], "rows", ()) or ())

    handle = telegram_handle()
    host = site_url().split("://", 1)[-1]
    lengths = [scene.seconds for scene in board.scenes]
    starts, running = [], 0.0
    for value in lengths:
        starts.append(running)
        running += value
    outro = board.scenes[-1]

    hero_text, hero_size = hero(
        str(getattr(board.scenes[0], "value", "") or "").rstrip("%단계"),
        "%" if str(getattr(board.scenes[0], "value", "")).endswith("%") else
        ("단계" if str(getattr(board.scenes[0], "value", "")).endswith("단계") else ""),
        cap=300,
    )

    template = (Path(__file__).parent / "composition_explain.html").read_text(encoding="utf-8")
    replacements = {
        "{{DURATION}}": f"{running:.2f}",
        "{{S1_DURATION}}": f"{lengths[0]:.2f}",
        "{{S2_START}}": f"{starts[1]:.2f}",
        "{{S2_DURATION}}": f"{lengths[1]:.2f}",
        "{{S3_START}}": f"{starts[2]:.2f}",
        "{{S3_DURATION}}": f"{lengths[2]:.2f}",
        "{{S4_START}}": f"{starts[3]:.2f}",
        "{{S4_DURATION}}": f"{lengths[3]:.2f}",
        "{{KICKER}}": board.scenes[0].eyebrow,
        "{{HERO_TEXT}}": hero_text,
        "{{HERO_SIZE}}": str(hero_size),
        "{{HOOK_CAPTION}}": board.scenes[0].caption,
        "{{LINE1}}": board.scenes[0].lines[0] if board.scenes[0].lines else "",
        "{{LINE2}}": board.scenes[0].lines[1] if len(board.scenes[0].lines) > 1 else "",
        "{{STEPS_HEAD}}": board.scenes[1].heading,
        "{{STEPS}}": "\n        ".join(_step_row(index, row) for index, row in enumerate(steps)),
        "{{STEP_COUNT}}": str(len(steps)),
        "{{STEPS_NOTE}}": board.scenes[1].note,
        "{{STEPS_NOTE_TOP}}": f"{STEP_TOP + len(steps) * STEP_STEP + 20}",
        "{{PROOF_HEAD}}": board.scenes[2].heading,
        "{{PROOF}}": "\n        ".join(_proof_row(index, row) for index, row in enumerate(proof)),
        "{{PROOF_COUNT}}": str(len(proof)),
        "{{PROOF_NOTE}}": board.scenes[2].note,
        "{{PROOF_NOTE_TOP}}": f"{PROOF_TOP + len(proof) * PROOF_STEP + 40}",
        "{{OUTRO1}}": outro.headline[0] if getattr(outro, "headline", ()) else "",
        "{{OUTRO2}}": outro.headline[1] if len(getattr(outro, "headline", ())) > 1 else "",
        "{{OUTRO_CALL}}": getattr(outro, "call", ""),
        "{{URL}}": host,
        "{{TELEGRAM_LINE}}": getattr(outro, "telegram_line", ""),
        "{{TELEGRAM}}": handle or f"{host}/start",
    }
    for token, value in replacements.items():
        template = template.replace(token, str(value))
    return template, running


# ------------------------------------------------------------------ the picks
RUNG_TOP, RUNG_STEP, RUNG_W = 442, 226, 880
TOTAL_TOP, TOTAL_STEP = 480, 150


def _rung(index: int, item: Mapping[str, Any]) -> str:
    """One holding on its own price scale: stop, average paid, target.

    The two lengths leave the same pin, so which is longer — what was risked
    or what is being played for — is read off the picture rather than worked
    out from a pair of numbers.
    """

    top = RUNG_TOP + index * RUNG_STEP
    stop = float(item.get("stop") or 0.0)
    average = float(item.get("average") or 0.0)
    target = float(item.get("target") or 0.0)
    span = max(target - stop, 1e-9)
    pin = max(min((average - stop) / span, 0.96), 0.04) * RUNG_W

    name = str(item.get("name") or "")
    rating = str(item.get("rating") or "")
    return (
        f'<div class="rung" id="rung{index}" style="top: {top}px;">'
        f'<p class="nm">{name}</p><p class="rt">{rating}</p><div class="track"></div>'
        f'<div class="risk" style="left: 0; width: {pin:.0f}px;"></div>'
        f'<div class="reward" style="left: {pin:.0f}px; width: {RUNG_W - pin:.0f}px;"></div>'
        f'<div class="pin" style="left: {pin - 2:.0f}px;"></div>'
        f'<p class="lo" style="left: 0;">손절 {stop:,.0f}원</p>'
        f'<p class="av" style="left: {max(pin - 90, 120):.0f}px;">평단 {average:,.0f}원</p>'
        f'<p class="hi" style="right: 0;">목표 {target:,.0f}원</p></div>'
    )


def _total_row(index: int, row: Mapping[str, Any]) -> str:
    top = TOTAL_TOP + index * TOTAL_STEP
    return (
        f'<div class="tot" id="tot{index}" style="top: {top}px;">'
        f'<p class="k">{row.get("label")}</p>'
        f'<p class="v" style="color: var(--{row.get("colour") or "ink"});">{row.get("value")}</p>'
        '<div class="rl"></div></div>'
    )


def compose_picks(payload: Mapping[str, Any], board: Storyboard) -> tuple[str, float]:
    """What the book is holding, and the two levels set on the way in.

    For a while there was no composer here at all, so a picks day fell through
    to compose_record and went out as the loss-record video under a picks
    title. The cut and the words have to be about the same thing.
    """

    rungs = list(getattr(board.scenes[1], "rows", ()) or ())[:4]
    totals = list(getattr(board.scenes[2], "rows", ()) or ())

    handle = telegram_handle()
    host = site_url().split("://", 1)[-1]
    lengths = [scene.seconds for scene in board.scenes]
    starts, running = [], 0.0
    for value in lengths:
        starts.append(running)
        running += value
    outro = board.scenes[-1]

    count = str(getattr(board.scenes[0], "value", "") or "")
    hero_text, hero_size = hero(count.rstrip("종목"), "종목" if count.endswith("종목") else "", cap=300)

    template = (Path(__file__).parent / "composition_picks.html").read_text(encoding="utf-8")
    replacements = {
        "{{DURATION}}": f"{running:.2f}",
        "{{S1_DURATION}}": f"{lengths[0]:.2f}",
        "{{S2_START}}": f"{starts[1]:.2f}",
        "{{S2_DURATION}}": f"{lengths[1]:.2f}",
        "{{S3_START}}": f"{starts[2]:.2f}",
        "{{S3_DURATION}}": f"{lengths[2]:.2f}",
        "{{S4_START}}": f"{starts[3]:.2f}",
        "{{S4_DURATION}}": f"{lengths[3]:.2f}",
        "{{KICKER}}": board.scenes[0].eyebrow,
        "{{HERO_TEXT}}": hero_text,
        "{{HERO_SIZE}}": str(hero_size),
        "{{HOOK_CAPTION}}": board.scenes[0].caption,
        "{{LINE1}}": board.scenes[0].lines[0] if board.scenes[0].lines else "",
        "{{LINE2}}": board.scenes[0].lines[1] if len(board.scenes[0].lines) > 1 else "",
        "{{RUNGS_HEAD}}": board.scenes[1].heading,
        "{{RUNGS}}": "\n        ".join(_rung(index, row) for index, row in enumerate(rungs)),
        "{{RUNG_COUNT}}": str(len(rungs)),
        "{{RUNGS_NOTE}}": board.scenes[1].note,
        "{{RUNGS_NOTE_TOP}}": f"{RUNG_TOP + len(rungs) * RUNG_STEP + 20}",
        "{{TOTALS_HEAD}}": board.scenes[2].heading,
        "{{TOTALS}}": "\n        ".join(_total_row(index, row) for index, row in enumerate(totals)),
        "{{TOTALS_COUNT}}": str(len(totals)),
        "{{TOTALS_NOTE}}": board.scenes[2].note,
        "{{TOTALS_NOTE_TOP}}": f"{TOTAL_TOP + len(totals) * TOTAL_STEP + 40}",
        "{{OUTRO1}}": outro.headline[0] if getattr(outro, "headline", ()) else "",
        "{{OUTRO2}}": outro.headline[1] if len(getattr(outro, "headline", ())) > 1 else "",
        "{{OUTRO_CALL}}": getattr(outro, "call", ""),
        "{{URL}}": host,
        "{{TELEGRAM_LINE}}": getattr(outro, "telegram_line", ""),
        "{{TELEGRAM}}": handle or f"{host}/start",
    }
    for token, value in replacements.items():
        template = template.replace(token, str(value))
    return template, running


# --------------------------------------------------------------- the passed-on
PLOT_W, PLOT_MID = 880.0, 235.0
DOT_ROWS = (0, -44, 44, -88, 88, -110, 110)     # stacked off the axis, alternating


def _dot(index: int, row: Mapping[str, Any], *, x: float, lane: int) -> str:
    top = PLOT_MID + DOT_ROWS[lane % len(DOT_ROWS)]
    kind = "took" if row.get("bought") else "passed"
    return f'<div class="dot {kind}" id="dot{index}" style="left: {x:.0f}px; top: {top:.0f}px;"></div>'


def compose_rejected(payload: Mapping[str, Any], board: Storyboard) -> tuple[str, float]:
    """The whole shortlist on one axis, with the ones we bought filled in.

    The screener narrows the market to twenty and the book takes a handful.
    Nobody looks at the other fifteen again, so the one number that says
    whether the picking works — did the names we passed on do better? — is the
    number nobody has. This is that number, drawn so it cannot be softened:
    every name is a dot, ours are solid, and the two group averages cut
    vertically through the lot of them.
    """

    data = payload.get("rejected") or {}
    rows = list(data.get("rows") or [])
    took_alpha = float(data.get("bought_alpha") or 0.0) * 100
    passed_alpha = float(data.get("passed_alpha") or 0.0) * 100

    values = [float(row["alpha"]) * 100 for row in rows] + [took_alpha, passed_alpha, 0.0]
    low, high = min(values), max(values)
    pad = max((high - low) * 0.10, 0.6)
    low, high = low - pad, high + pad

    def x_of(value: float) -> float:
        return (value - low) / ((high - low) or 1.0) * PLOT_W

    # Names close together would sit on top of each other, so each dot drops to
    # the next lane whenever it would collide with the one before it.
    placed: list[str] = []
    last_x, lane = -999.0, 0
    for index, row in enumerate(sorted(rows, key=lambda item: float(item["alpha"]))):
        x = x_of(float(row["alpha"]) * 100)
        lane = lane + 1 if x - last_x < 30 else 0
        placed.append(_dot(index, row, x=x, lane=lane))
        last_x = x

    took_x, passed_x = x_of(took_alpha), x_of(passed_alpha)
    took_text, passed_text = f"{took_alpha:+.2f}%p", f"{passed_alpha:+.2f}%p"
    best = data.get("best") or {}

    handle = telegram_handle()
    host = site_url().split("://", 1)[-1]
    lengths = [scene.seconds for scene in board.scenes]
    starts, running = [], 0.0
    for value in lengths:
        starts.append(running)
        running += value
    outro = board.scenes[-1]

    gap = passed_alpha - took_alpha
    hero_text, hero_size = hero(f"{abs(gap):.1f}", "%p", cap=300)

    template = (Path(__file__).parent / "composition_rejected.html").read_text(encoding="utf-8")
    replacements = {
        "{{DURATION}}": f"{running:.2f}",
        "{{S1_DURATION}}": f"{lengths[0]:.2f}",
        "{{S2_START}}": f"{starts[1]:.2f}",
        "{{S2_DURATION}}": f"{lengths[1]:.2f}",
        "{{S3_START}}": f"{starts[2]:.2f}",
        "{{S3_DURATION}}": f"{lengths[2]:.2f}",
        "{{S4_START}}": f"{starts[3]:.2f}",
        "{{S4_DURATION}}": f"{lengths[3]:.2f}",
        "{{KICKER}}": board.scenes[0].eyebrow,
        "{{HERO_TEXT}}": hero_text,
        "{{HERO_SIZE}}": str(hero_size),
        "{{HERO_COLOUR}}": "var(--passed)" if gap >= 0 else "var(--took)",
        "{{HOOK_CAPTION}}": board.scenes[0].caption,
        "{{LINE1}}": board.scenes[0].lines[0] if board.scenes[0].lines else "",
        "{{LINE2}}": board.scenes[0].lines[1] if len(board.scenes[0].lines) > 1 else "",
        "{{PLOT_HEAD}}": board.scenes[1].heading,
        "{{DOTS}}": "\n          ".join(placed),
        "{{DOT_COUNT}}": str(len(placed)),
        "{{ZERO_X}}": f"{x_of(0.0):.0f}",
        "{{ZERO_TAG_X}}": f"{max(x_of(0.0) - 60, 0):.0f}",
        "{{TOOK_X}}": f"{took_x:.0f}",
        "{{PASSED_X}}": f"{passed_x:.0f}",
        "{{TOOK_TAG_X}}": f"{max(min(took_x - 110, PLOT_W - 250), 0):.0f}",
        "{{PASSED_TAG_X}}": f"{max(min(passed_x - 120, PLOT_W - 270), 0):.0f}",
        "{{TOOK_TEXT}}": took_text,
        "{{PASSED_TEXT}}": passed_text,
        "{{TOOK_COUNT}}": str(int(data.get("bought_count") or 0)),
        "{{PASSED_COUNT}}": str(int(data.get("passed_count") or 0)),
        "{{PLOT_NOTE}}": board.scenes[1].note,
        "{{TOTALS_HEAD}}": board.scenes[2].heading,
        "{{MISS_LABEL}}": f"가장 많이 오른 {best.get('name', '')}" + ("" if best.get("bought") else ", 우리는 넘겼습니다"),
        "{{MISS_TEXT}}": f"{float(best.get('alpha') or 0.0) * 100:+.2f}%p",
        "{{MISS_COLOUR}}": "var(--took)" if best.get("bought") else "var(--passed)",
        "{{TOTALS_NOTE}}": board.scenes[2].note,
        "{{OUTRO1}}": outro.headline[0] if getattr(outro, "headline", ()) else "",
        "{{OUTRO2}}": outro.headline[1] if len(getattr(outro, "headline", ())) > 1 else "",
        "{{OUTRO_CALL}}": getattr(outro, "call", ""),
        "{{URL}}": host,
        "{{TELEGRAM_LINE}}": getattr(outro, "telegram_line", ""),
        "{{TELEGRAM}}": handle or f"{host}/start",
    }
    for token, value in replacements.items():
        template = template.replace(token, str(value))
    return template, running


# ---------------------------------------------------------------- the sweep
# The bars and the index share 740px; the value labels keep the rest of
# the row, or the index line draws straight through them.
BOARD_W, BOARD_STEP = 740.0, 118


def _sweep_row(index: int, item: Mapping[str, Any], *, scale: float) -> str:
    top = index * BOARD_STEP
    width = max(float(item.get("total_return") or 0.0) * scale, 4.0)
    tag = '<p class="tag">현행</p>' if item.get("live") else ""
    return (
        f'<div class="row{" on" if item.get("live") else ""}" id="row{index}" style="top: {top}px;">'
        f'<p class="nm">{item.get("name")}</p><div class="track"></div>'
        f'<div class="fill" style="width: {width:.0f}px;"></div>'
        f'<p class="val">{float(item.get("total_return") or 0.0) * 100:+.1f}%</p>{tag}</div>'
    )


def compose_sweep(payload: Mapping[str, Any], board: Storyboard) -> tuple[str, float]:
    """Seven replays of the same three years, ranked, with the index across them.

    The bars are our own settings measured against each other, which on its own
    says nothing about whether any of them was worth running. The index arrives
    last, on the same scale, cutting through the lot — that is the comparison
    that decides it, and the one the stop-loss cut used to leave out.
    """

    data = payload.get("sweep") or {}
    variants = list(data.get("variants") or [])
    benchmark = data.get("benchmark")

    ceiling = max([float(item.get("total_return") or 0.0) for item in variants]
                  + ([float(benchmark)] if benchmark is not None else []) + [0.01])
    scale = BOARD_W / (ceiling * 1.06)

    rows = "\n          ".join(_sweep_row(index, item, scale=scale) for index, item in enumerate(variants))
    board_height = max(len(variants) * BOARD_STEP, BOARD_STEP)
    index_x = min(float(benchmark) * scale, BOARD_W - 4) if benchmark is not None else BOARD_W - 4

    handle = telegram_handle()
    host = site_url().split("://", 1)[-1]
    lengths = [scene.seconds for scene in board.scenes]
    starts, running = [], 0.0
    for value in lengths:
        starts.append(running)
        running += value
    outro = board.scenes[-1]

    hero_text, hero_size = hero(str(len(variants)), "가지", cap=300)
    beat = board.scenes[2]
    count = str(getattr(beat, "value", "") or "0")
    count_text, count_size = hero(count, "개", cap=250)

    template = (Path(__file__).parent / "composition_sweep.html").read_text(encoding="utf-8")
    replacements = {
        "{{DURATION}}": f"{running:.2f}",
        "{{S1_DURATION}}": f"{lengths[0]:.2f}",
        "{{S2_START}}": f"{starts[1]:.2f}",
        "{{S2_DURATION}}": f"{lengths[1]:.2f}",
        "{{S3_START}}": f"{starts[2]:.2f}",
        "{{S3_DURATION}}": f"{lengths[2]:.2f}",
        "{{S4_START}}": f"{starts[3]:.2f}",
        "{{S4_DURATION}}": f"{lengths[3]:.2f}",
        "{{KICKER}}": board.scenes[0].eyebrow,
        "{{HERO_TEXT}}": hero_text,
        "{{HERO_SIZE}}": str(hero_size),
        "{{HOOK_CAPTION}}": board.scenes[0].caption,
        "{{LINE1}}": board.scenes[0].lines[0] if board.scenes[0].lines else "",
        "{{LINE2}}": board.scenes[0].lines[1] if len(board.scenes[0].lines) > 1 else "",
        "{{BOARD_HEAD}}": board.scenes[1].heading,
        "{{ROWS}}": rows,
        "{{ROW_COUNT}}": str(len(variants)),
        "{{BOARD_H}}": f"{board_height}",
        "{{INDEX_X}}": f"{index_x:.0f}",
        "{{INDEX_H}}": f"{board_height - 24}",
        "{{INDEX_TAG_X}}": f"{116 + max(min(index_x - 170, BOARD_W - 300), 0):.0f}",
        "{{INDEX_TAG_TOP}}": f"{400 + board_height + 6}",
        "{{INDEX_TEXT}}": f"{float(benchmark) * 100:+.1f}%" if benchmark is not None else "기록 없음",
        "{{BOARD_NOTE}}": board.scenes[1].note,
        "{{BOARD_NOTE_TOP}}": f"{400 + board_height + 72}",
        "{{COUNT_KICKER}}": beat.eyebrow,
        "{{COUNT_TEXT}}": count_text,
        "{{COUNT_SIZE}}": str(count_size),
        "{{COUNT_COLOUR}}": "var(--live)" if count != "0" else "var(--index)",
        "{{COUNT_CAPTION}}": getattr(beat, "caption", "") or beat.heading,
        "{{LIVE_LABEL}}": (beat.rows[0]["label"] if beat.rows else ""),
        "{{LIVE_TEXT}}": (beat.rows[0]["value"] if beat.rows else ""),
        "{{BEST_LABEL}}": (beat.rows[1]["label"] if len(beat.rows) > 1 else ""),
        "{{BEST_TEXT}}": (beat.rows[1]["value"] if len(beat.rows) > 1 else ""),
        "{{COUNT_NOTE}}": beat.note,
        "{{OUTRO1}}": outro.headline[0] if getattr(outro, "headline", ()) else "",
        "{{OUTRO2}}": outro.headline[1] if len(getattr(outro, "headline", ())) > 1 else "",
        "{{OUTRO_CALL}}": getattr(outro, "call", ""),
        "{{URL}}": host,
        "{{TELEGRAM_LINE}}": getattr(outro, "telegram_line", ""),
        "{{TELEGRAM}}": handle or f"{host}/start",
    }
    for token, value in replacements.items():
        template = template.replace(token, str(value))
    return template, running

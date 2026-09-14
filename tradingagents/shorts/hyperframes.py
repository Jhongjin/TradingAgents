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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .stories import Storyboard, short_date, site_url, telegram_handle

CLI_VERSION = "0.8.38"
FALL_TOP, FALL_FLOOR = 520, 1180      # 0% and the floor of the fall scale, in px
LANE_WIDTH = 176
LANES_LEFT = 116


class HyperFramesMissingError(RuntimeError):
    """No node on this machine, so the HTML cannot be turned into a video."""


@dataclass(frozen=True)
class Composition:
    directory: Path
    html: Path
    seconds: float


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
        '<div class="head-dot"></div><div class="stem"></div>'
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
        "{{CAPTION}}": f"{initial / 100_000_000:.1f}억원으로 시작한 계좌의 지금 성적",
        "{{LINE1}}": f"지금까지 정리한 {int(summary.get('closed_count') or len(closed))}건,",
        "{{LINE2}}": "전부 손실이었습니다." if not int(summary.get("win_count") or 0) else f"{int(summary['win_count'])}건이 이익이었습니다.",
        "{{FALLS_HEAD}}": f"{len(closed)}건이 이만큼 떨어졌습니다",
        "{{LANES}}": "\n        ".join(_lane(index, item) for index, item in enumerate(closed)),
        "{{ACCOUNT_TOP}}": f"{FALL_TOP + (abs(total) * 100 / span) * (FALL_FLOOR - FALL_TOP):.0f}",
        "{{FALLS_NOTE}}": "다섯 건 모두 살 때 정해둔 손절선에서 정리됐습니다." if closed else "",
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


def run(command: str, directory: Path, *, extra: Sequence[str] = (), timeout: int = 1800) -> str:
    """Drive the HyperFrames CLI in the project directory."""

    # on Windows the extensionless "npx" is a shell script the process API
    # cannot start; the .cmd shim beside it is the one that runs
    binary = shutil.which("npx.cmd") or shutil.which("npx")
    if binary is None:
        raise HyperFramesMissingError("npx 를 찾지 못했습니다. Node 22 이상을 설치해 주세요.")
    result = subprocess.run(
        [binary, "--yes", f"hyperframes@{CLI_VERSION}", command, *extra],
        cwd=directory, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise HyperFramesMissingError(f"hyperframes {command} 실패 ({result.returncode}):\n{output[-1200:]}")
    return output


__all__ = ["Composition", "CLI_VERSION", "HyperFramesMissingError", "compose_record", "run", "write_project"]

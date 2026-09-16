"""Draw the channel's avatar and banner from the same design the videos use.

The cuts already have a palette, a face and a way of setting a figure. A
channel picture drawn somewhere else would look like a different product, so
this reuses the shorts design system rather than inventing a second one.

    python scripts/channel_art.py [output-dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

from tradingagents.shorts.design import DISPLAY_BLACK, KR_LIGHT, load_font

INK = (234, 239, 247)
PAPER = (243, 236, 223)
MUTED = (95, 113, 137)
UP = (255, 92, 96)
DOWN = (77, 155, 255)
RULE = (240, 180, 41)


def _ground(size: tuple[int, int]) -> Image.Image:
    """The same cool ground the cuts sit on, as a vertical wash."""

    width, height = size
    image = Image.new("RGB", size, (11, 19, 32))
    draw = ImageDraw.Draw(image)
    top, bottom = (13, 23, 38), (8, 15, 26)
    for row in range(height):
        share = row / max(height - 1, 1)
        draw.line(
            [(0, row), (width, row)],
            fill=tuple(int(a + (b - a) * share) for a, b in zip(top, bottom)),
        )
    return image


def _centre(draw: ImageDraw.ImageDraw, text: str, font, *, cy: int, width: int, fill) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2] - box[0])) / 2 - box[0], cy - (box[3] - box[1]) / 2 - box[1]), text, font=font, fill=fill)
    return box[3] - box[1]


def avatar(path: Path, size: int = 800) -> Path:
    """A square mark: the account's line holding while a pick falls away.

    Two strokes and the wordmark. At the size a comment avatar is actually
    seen, anything more is mud.
    """

    image = _ground((size, size))
    draw = ImageDraw.Draw(image)
    unit = size / 800

    # the falling pick, and the line that did not follow it down
    draw.line([(250 * unit, 250 * unit), (250 * unit, 560 * unit)], fill=DOWN, width=int(16 * unit))
    draw.ellipse(
        [(232 * unit, 232 * unit), (268 * unit, 268 * unit)],
        fill=PAPER,
    )
    draw.ellipse(
        [(226 * unit, 536 * unit), (274 * unit, 584 * unit)],
        fill=DOWN,
    )
    draw.line([(170 * unit, 372 * unit), (630 * unit, 372 * unit)], fill=RULE, width=int(7 * unit))
    draw.line([(330 * unit, 330 * unit), (630 * unit, 330 * unit)], fill=PAPER, width=int(18 * unit))

    mark = load_font(DISPLAY_BLACK, int(104 * unit))
    _centre(draw, "agenttrust", mark, cy=int(668 * unit), width=size, fill=PAPER)
    image.save(path, "PNG")
    return path


def banner(path: Path, width: int = 2560, height: int = 1440) -> Path:
    """The banner, with everything that matters inside the safe 1546x423 middle."""

    image = _ground((width, height))
    draw = ImageDraw.Draw(image)
    cx, cy = width // 2, height // 2

    title = load_font(DISPLAY_BLACK, 132)
    line = load_font(KR_LIGHT, 52)
    small = load_font(KR_LIGHT, 40)

    _centre(draw, "에이전트트러스트", title, cy=cy - 126, width=width, fill=INK)
    _centre(draw, "AI가 고른 종목을 모의 계좌가 담고, 결과를 하나도 빼지 않고 공개합니다", line, cy=cy + 6, width=width, fill=(148, 166, 189))

    draw.line([(cx - 420, cy + 86), (cx + 420, cy + 86)], fill=(31, 45, 68), width=3)
    _centre(draw, "평일 아침 · agenttrust.kr", small, cy=cy + 148, width=width, fill=MUTED)

    # the stop line from the avatar, carried through as two rules that flank
    # the name. The falling stem is left out: at this width it lands on the
    # subtitle rather than beside it.
    draw.line([(cx - 780, cy - 126), (cx - 560, cy - 126)], fill=RULE, width=5)
    draw.line([(cx + 560, cy - 126), (cx + 780, cy - 126)], fill=RULE, width=5)
    image.save(path, "PNG")
    return path


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "shorts-out/brand")
    out.mkdir(parents=True, exist_ok=True)
    for made in (avatar(out / "avatar.png"), banner(out / "banner.png")):
        print(made, f"{made.stat().st_size / 1024:,.0f}KB")

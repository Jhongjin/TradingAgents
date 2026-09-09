"""Open Graph images (1200x630 PNG) rendered on demand with Pillow and Pretendard.

Layout: slate ground, teal accent bar on the left, kicker badge, wrapped title,
subtitle, up to four stat tiles, and a footer with the brand mark and domain.
Results are memoised per (title, subtitle, kicker, stats) for the process.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Sequence

WIDTH, HEIGHT = 1200, 630
FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
BOLD = FONT_DIR / "Pretendard-Bold.otf"
MEDIUM = FONT_DIR / "Pretendard-Medium.otf"

BG = (243, 245, 249)
PANEL = (255, 255, 255)
INK = (15, 23, 42)
INK2 = (71, 85, 105)
MUTED = (100, 116, 139)
LINE = (226, 231, 238)
TEAL = (15, 118, 110)
TEAL_SOFT = (204, 251, 241)
TEAL_INK = (17, 94, 89)


def _font(path: Path, size: int):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    """Greedy wrap by words, falling back to characters for long Korean runs."""

    lines: list[str] = []
    current = ""
    tokens = text.split(" ")
    for token in tokens:
        candidate = f"{current} {token}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        # token alone too wide: split by characters
        piece = ""
        for ch in token:
            if draw.textlength(piece + ch, font=font) <= max_width:
                piece += ch
            else:
                lines.append(piece)
                piece = ch
        current = piece
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


@lru_cache(maxsize=128)
def render_og_image(title: str, subtitle: str = "", kicker: str = "TradingAgents Korea", stats: tuple[tuple[str, str], ...] = (), footer: str = "trading-agents-seven.vercel.app") -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    # soft teal glow top-left
    glow = Image.new("RGB", (WIDTH, HEIGHT), BG)
    glow_draw = ImageDraw.Draw(glow)
    for i in range(18, 0, -1):
        alpha = int(6 * i / 18)
        color = tuple(int(BG[c] + (TEAL_SOFT[c] - BG[c]) * (i / 18) * 0.9) for c in range(3))
        glow_draw.ellipse([-320 + i * 6, -360 + i * 6, 620 - i * 6, 300 - i * 6], fill=color)
        del alpha
    img = Image.blend(img, glow, 0.9)
    draw = ImageDraw.Draw(img)
    # accent bar
    draw.rounded_rectangle([0, 0, 18, HEIGHT], radius=0, fill=TEAL)

    # kicker badge
    kicker_font = _font(MEDIUM, 26)
    kw = draw.textlength(kicker, font=kicker_font)
    draw.rounded_rectangle([72, 64, 72 + kw + 40, 64 + 46], radius=23, fill=TEAL_SOFT)
    draw.text((92, 72), kicker, font=kicker_font, fill=TEAL_INK)

    # title
    title_font = _font(BOLD, 64)
    lines = _wrap(draw, title, title_font, WIDTH - 72 - 80, 3)
    y = 140
    for line in lines:
        draw.text((72, y), line, font=title_font, fill=INK)
        y += 78
    # subtitle
    if subtitle:
        sub_font = _font(MEDIUM, 30)
        for line in _wrap(draw, subtitle, sub_font, WIDTH - 72 - 80, 2):
            draw.text((72, y + 6), line, font=sub_font, fill=INK2)
            y += 42
    # stats
    if stats:
        y = max(y + 28, 400)
        tile_w = min(250, (WIDTH - 72 - 80 - 16 * (len(stats) - 1)) // max(1, len(stats)))
        label_font = _font(MEDIUM, 22)
        value_font = _font(BOLD, 40)
        x = 72
        for label, value in stats[:4]:
            draw.rounded_rectangle([x, y, x + tile_w, y + 108], radius=16, fill=PANEL, outline=LINE)
            draw.text((x + 20, y + 16), label, font=label_font, fill=MUTED)
            draw.text((x + 20, y + 48), value, font=value_font, fill=INK)
            x += tile_w + 16
    # footer
    foot_font = _font(MEDIUM, 24)
    draw.line([(72, HEIGHT - 78), (WIDTH - 80, HEIGHT - 78)], fill=LINE, width=2)
    _draw_mark(draw, 72, HEIGHT - 58, 36)
    draw.text((120, HEIGHT - 56), "TradingAgents Korea", font=_font(BOLD, 26), fill=INK)
    fw = draw.textlength(footer, font=foot_font)
    draw.text((WIDTH - 80 - fw, HEIGHT - 55), footer, font=foot_font, fill=MUTED)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _draw_mark(draw, x: int, y: int, size: int) -> None:
    unit = size / 64
    draw.rounded_rectangle([x, y, x + size, y + size], radius=int(size * 0.25), fill=TEAL)
    pts = [(x + px * unit, y + py * unit) for px, py in ((12, 44), (24, 32), (32, 38), (52, 18))]
    draw.line(pts, fill=(255, 255, 255), width=max(2, int(7 * unit)), joint="curve")
    ex, ey = pts[-1]
    r = 6 * unit
    draw.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(255, 255, 255))


def og_stats(pairs: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    return tuple((str(k), str(v)) for k, v in pairs)

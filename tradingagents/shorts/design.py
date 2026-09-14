"""How a short looks: the palette, the type, and the canvas that draws it.

The direction is a ledger, because that is what the channel is. A ledger has
ruled lines rather than cards, tabular figures rather than prose numbers, a
margin rail down the left, and a stamp when an entry is closed. Filled cards
in a scrolling list is what every generated finance video already looks like;
this is meant to look like a record being kept.

Two typefaces do two jobs. Korean is set in Malgun Gothic, and every numeral is
set in Consolas, which is monospaced, so a figure counting up on screen does
not jitter as its digits change width.

Practical constraints the design answers: it is watched on a phone, in a feed,
usually with the sound off, and the player covers the top and bottom of the
frame. So the type is large, contrast is high, and nothing that must be read
sits outside the safe band.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1080, 1920
FPS = 30

# The player's chrome covers the top ~190px and the bottom ~360px, and the
# action buttons sit over the right edge below the middle.
SAFE_TOP = 230
SAFE_BOTTOM = 1540
RAIL_X = 56
MARGIN = 116
CONTENT_WIDTH = WIDTH - MARGIN - 84

# Ground and ink. Every value below clears 4.5:1 against BG.
BG = (11, 15, 18)
GRID = (20, 27, 32)
HAIRLINE = (34, 44, 52)
LINE = (46, 59, 69)
INK = (237, 239, 243)
INK2 = (167, 178, 188)
MUTED = (120, 132, 143)
ACCENT = (53, 208, 180)
UP = (255, 90, 107)
DOWN = (91, 156, 255)
AMBER = (240, 179, 87)

# kept so callers that still name the old surfaces keep working
PANEL = GRID
PANEL_HI = HAIRLINE

FONT_ENV = "TRADINGAGENTS_SHORTS_FONT"
NUMERAL_ENV = "TRADINGAGENTS_SHORTS_NUMERAL_FONT"
FONT_CANDIDATES: tuple[tuple[str, str], ...] = (
    (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", "/System/Library/Fonts/AppleSDGothicNeo.ttc"),
)
NUMERAL_CANDIDATES: tuple[tuple[str, str], ...] = (
    (r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\consolab.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
    ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Menlo.ttc"),
)


def _first_pair(candidates: Sequence[tuple[str, str]], env: str) -> tuple[str, str] | None:
    override = (os.getenv(env) or "").strip()
    if override:
        parts = [item.strip() for item in override.split(os.pathsep) if item.strip()]
        if parts and Path(parts[0]).exists():
            return parts[0], (parts[1] if len(parts) > 1 and Path(parts[1]).exists() else parts[0])
    for regular, bold in candidates:
        if Path(regular).exists():
            return regular, (bold if Path(bold).exists() else regular)
    return None


def font_pair() -> tuple[str, str] | None:
    """The first regular/bold pair on this machine that can draw Hangul."""

    return _first_pair(FONT_CANDIDATES, FONT_ENV)


def numeral_pair() -> tuple[str, str] | None:
    """A monospaced pair for figures, so a counting number holds its width."""

    return _first_pair(NUMERAL_CANDIDATES, NUMERAL_ENV) or font_pair()


class MissingFontError(RuntimeError):
    """No installed font can draw Korean, so nothing legible can be rendered."""


@lru_cache(maxsize=96)
def load_font(size: int, *, bold: bool = False, numeral: bool = False) -> ImageFont.FreeTypeFont:
    pair = numeral_pair() if numeral else font_pair()
    if pair is None:
        raise MissingFontError(f"한글 글꼴을 찾지 못했습니다. {FONT_ENV} 환경변수에 TTF 경로를 지정하세요.")
    return ImageFont.truetype(pair[1] if bold else pair[0], size)


@lru_cache(maxsize=1)
def background() -> Image.Image:
    """The sheet: near-black, faintly ruled, with one soft bloom behind the rail."""

    base = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(base)
    for y in range(SAFE_TOP - 120, HEIGHT, 96):       # the ledger's own ruling, barely there
        draw.rectangle((0, y, WIDTH, y), fill=GRID)
    for x in range(MARGIN, WIDTH, 192):
        draw.rectangle((x, 0, x, HEIGHT), fill=GRID)

    glow = Image.new("L", (WIDTH // 4, HEIGHT // 4), 0)
    ImageDraw.Draw(glow).ellipse((-70, 40, 150, 300), fill=52)
    glow = glow.filter(ImageFilter.GaussianBlur(30)).resize((WIDTH, HEIGHT))
    return Image.composite(Image.new("RGB", (WIDTH, HEIGHT), (12, 46, 43)), base, glow)


def ease_out(x: float) -> float:
    """Fast then settling: how a thing arriving on screen should move."""

    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def appear(local: float, delay: float, duration: float = 0.45) -> float:
    """Progress of an element that starts at ``delay`` and takes ``duration``."""

    if duration <= 0:
        return 1.0
    return ease_out((local - delay) / duration)


def mix(a: Sequence[int], b: Sequence[int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def fade(colour: Sequence[int], alpha: float) -> tuple[int, int, int]:
    """A colour dimmed toward the ground, which is how fading in is drawn."""

    return mix(BG, colour, alpha)


def tone(value: float | None) -> tuple[int, int, int]:
    """Red for a gain, blue for a loss, as a Korean chart reads."""

    if value is None:
        return INK2
    return UP if value > 0 else (DOWN if value < 0 else INK2)


@dataclass
class Canvas:
    """A single frame, with the handful of drawing moves the scenes need."""

    image: Image.Image

    @classmethod
    def blank(cls) -> "Canvas":
        return cls(background().copy())

    @property
    def draw(self) -> ImageDraw.ImageDraw:
        return ImageDraw.Draw(self.image, "RGBA")

    # ---------------------------------------------------------------- text
    def text(
        self,
        xy: tuple[int, int],
        value: str,
        *,
        size: int = 44,
        bold: bool = False,
        numeral: bool = False,
        fill: Sequence[int] = INK,
        anchor: str = "la",
        alpha: float = 1.0,
        spacing: int = 14,
        tracking: int = 0,
    ) -> None:
        if alpha <= 0.01 or not value:
            return
        font = load_font(size, bold=bold, numeral=numeral)
        colour = fade(fill, alpha)
        if not tracking:
            self.draw.text(xy, value, font=font, fill=colour, anchor=anchor, spacing=spacing)
            return
        # letter-spaced runs are only used for small labels, so the slow path is fine
        x, y = xy
        for character in value:
            self.draw.text((x, y), character, font=font, fill=colour, anchor=anchor)
            x += self.draw.textlength(character, font=font) + tracking

    def measure(self, value: str, *, size: int = 44, bold: bool = False, numeral: bool = False, tracking: int = 0) -> tuple[int, int]:
        font = load_font(size, bold=bold, numeral=numeral)
        box = self.draw.textbbox((0, 0), value, font=font)
        return box[2] - box[0] + tracking * max(len(value) - 1, 0), box[3] - box[1]

    def fit(self, value: str, width: int, *, size: int = 44, bold: bool = False) -> str:
        """Trim to the width available, so a long name never overruns its column."""

        if self.measure(value, size=size, bold=bold)[0] <= width:
            return value
        trimmed = value
        while trimmed and self.measure(trimmed + "…", size=size, bold=bold)[0] > width:
            trimmed = trimmed[:-1]
        return (trimmed + "…") if trimmed else ""

    # --------------------------------------------------------------- rules
    def rule(
        self,
        y: int,
        *,
        x0: int = MARGIN,
        x1: int = WIDTH - 84,
        alpha: float = 1.0,
        colour: Sequence[int] = HAIRLINE,
        weight: int = 2,
        progress: float = 1.0,
    ) -> None:
        """A ruled line, optionally drawn part way: rules wipe in from the left."""

        if alpha <= 0.01 or progress <= 0:
            return
        end = x0 + (x1 - x0) * max(0.0, min(1.0, progress))
        self.draw.rectangle((x0, y, end, y + weight - 1), fill=fade(colour, alpha))

    def rail(self, progress: float, *, alpha: float = 1.0) -> None:
        """The margin rail: the whole video's position, drawn as part of the page."""

        top, bottom = SAFE_TOP - 40, SAFE_BOTTOM + 40
        self.draw.rectangle((RAIL_X, top, RAIL_X + 3, bottom), fill=fade(HAIRLINE, alpha))
        filled = top + (bottom - top) * max(0.0, min(1.0, progress))
        if filled > top:
            self.draw.rectangle((RAIL_X, top, RAIL_X + 3, filled), fill=fade(ACCENT, alpha))

    def label(self, xy: tuple[int, int], value: str, *, colour: Sequence[int] = ACCENT, alpha: float = 1.0, size: int = 30) -> None:
        """A small tracked label with a short accent tick, used as a section head."""

        if alpha <= 0.01:
            return
        x, y = xy
        self.draw.rectangle((x, y + size // 2 - 1, x + 28, y + size // 2 + 1), fill=fade(colour, alpha))
        self.text((x + 44, y + size // 2), value, size=size, bold=True, fill=colour, anchor="lm", alpha=alpha, tracking=2)

    def tag(self, xy: tuple[int, int], value: str, *, colour: Sequence[int] = MUTED, alpha: float = 1.0, size: int = 26) -> int:
        """An outlined marker beside a row, the ledger's note in the margin."""

        if alpha <= 0.01:
            return 0
        pad = 14
        width = self.measure(value, size=size, bold=True)[0] + pad * 2
        height = size + 16
        self.draw.rounded_rectangle((xy[0], xy[1], xy[0] + width, xy[1] + height), radius=6, outline=fade(colour, alpha * 0.8), width=2)
        self.text((xy[0] + pad, xy[1] + height // 2), value, size=size, bold=True, fill=colour, anchor="lm", alpha=alpha)
        return width

    def stamp(self, centre: tuple[int, int], value: str, *, colour: Sequence[int] = AMBER, alpha: float = 1.0, size: int = 76, angle: float = -8.0, scale: float = 1.0) -> None:
        """The closed-entry stamp: a boxed word set at an angle, pressed on.

        Drawn on its own layer and rotated, which is the one flourish this
        design spends, so it has to land rather than fade.
        """

        if alpha <= 0.01:
            return
        pad_x, pad_y = 40, 22
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        font = load_font(size, bold=True)
        box = probe.textbbox((0, 0), value, font=font)
        width, height = box[2] - box[0] + pad_x * 2, box[3] - box[1] + pad_y * 2
        layer = Image.new("RGBA", (width + 16, height + 16), (0, 0, 0, 0))
        pen = ImageDraw.Draw(layer)
        ink = (*colour, int(255 * min(1.0, alpha)))
        pen.rounded_rectangle((8, 8, width + 8, height + 8), radius=10, outline=ink, width=5)
        pen.text((width // 2 + 8, height // 2 + 8), value, font=font, fill=ink, anchor="mm")
        if scale != 1.0:
            layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.LANCZOS)
        layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
        self.image.paste(layer, (centre[0] - layer.width // 2, centre[1] - layer.height // 2), layer)

    def bar(self, box: tuple[float, float, float, float], *, colour: Sequence[int] = ACCENT, alpha: float = 1.0, radius: int = 4) -> None:
        """A thin mark with rounded ends, anchored to the baseline it grows from."""

        x0, y0, x1, y1 = box
        if abs(x1 - x0) < 2 or alpha <= 0.01:
            return
        self.draw.rounded_rectangle((min(x0, x1), y0, max(x0, x1), y1), radius=radius, fill=fade(colour, alpha))


def money(value: float | None, *, unit: str = "원") -> str:
    if value is None:
        return "–"
    return f"{value:+,.0f}{unit}" if value else f"0{unit}"


def percent(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return "–"
    return f"{value * 100:+.{digits}f}%"


def korean_date(value: str | None) -> str:
    if not value:
        return ""
    parts = str(value)[:10].split("-")
    if len(parts) != 3:
        return str(value)
    return f"{int(parts[1])}월 {int(parts[2])}일"


__all__ = [
    "ACCENT", "AMBER", "BG", "Canvas", "CONTENT_WIDTH", "DOWN", "FPS", "GRID", "HAIRLINE", "HEIGHT",
    "INK", "INK2", "LINE", "MARGIN", "MUTED", "MissingFontError", "PANEL", "PANEL_HI", "RAIL_X",
    "SAFE_BOTTOM", "SAFE_TOP", "UP", "WIDTH", "appear", "background", "ease_out", "fade",
    "font_pair", "korean_date", "load_font", "mix", "money", "numeral_pair", "percent", "tone",
]

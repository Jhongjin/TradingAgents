"""How a short looks: the palette, the type, and the canvas that draws it.

A vertical video is watched on a phone, in a feed, with the sound off, and the
player covers the top and bottom of the frame with its own controls. So the
type is large, the contrast is high, every number is legible at a glance, and
nothing that matters is drawn outside the safe band in the middle.

The colours are the site's dark theme, and rising is red and falling is blue,
which is what a Korean reader expects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1080, 1920
FPS = 30

# The player's own chrome sits over the top ~180px and the bottom ~360px, and
# the action buttons cover the right edge below the middle. Everything that
# must be read lives inside this band.
SAFE_TOP = 210
SAFE_BOTTOM = 1560
MARGIN = 76
CONTENT_WIDTH = WIDTH - MARGIN * 2

BG = (11, 18, 32)
BG2 = (16, 25, 42)
PANEL = (23, 32, 49)
PANEL_HI = (30, 41, 61)
LINE = (46, 59, 81)
INK = (233, 238, 246)
INK2 = (160, 173, 192)
MUTED = (117, 131, 151)
ACCENT = (45, 212, 191)
ACCENT_DIM = (16, 78, 74)
UP = (255, 77, 94)
DOWN = (77, 141, 255)
AMBER = (245, 172, 60)

FONT_ENV = "TRADINGAGENTS_SHORTS_FONT"
FONT_CANDIDATES: tuple[tuple[str, str], ...] = (
    # (regular, bold) pairs, in the order they are worth trying
    (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", "/System/Library/Fonts/AppleSDGothicNeo.ttc"),
)


def font_pair() -> tuple[str, str] | None:
    """The first regular/bold pair on this machine that can draw Hangul."""

    override = (os.getenv(FONT_ENV) or "").strip()
    if override:
        parts = [item.strip() for item in override.split(os.pathsep) if item.strip()]
        if parts and Path(parts[0]).exists():
            return parts[0], (parts[1] if len(parts) > 1 and Path(parts[1]).exists() else parts[0])
    for regular, bold in FONT_CANDIDATES:
        if Path(regular).exists():
            return regular, (bold if Path(bold).exists() else regular)
    return None


class MissingFontError(RuntimeError):
    """No installed font can draw Korean, so nothing legible can be rendered."""


@lru_cache(maxsize=64)
def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    pair = font_pair()
    if pair is None:
        raise MissingFontError(
            f"한글 글꼴을 찾지 못했습니다. {FONT_ENV} 환경변수에 TTF 경로를 지정하세요."
        )
    return ImageFont.truetype(pair[1] if bold else pair[0], size)


@lru_cache(maxsize=1)
def background() -> Image.Image:
    """One painted backdrop, reused by every frame: two soft glows on deep navy."""

    base = Image.new("RGB", (WIDTH, HEIGHT), BG)
    # a vertical lift, so the frame is not a flat block of colour
    gradient = Image.new("L", (1, HEIGHT))
    for y in range(HEIGHT):
        gradient.putpixel((0, y), int(26 * (1 - y / HEIGHT) ** 1.4))
    base = Image.composite(Image.new("RGB", (WIDTH, HEIGHT), BG2), base, gradient.resize((WIDTH, HEIGHT)))

    glow = Image.new("L", (WIDTH // 4, HEIGHT // 4), 0)
    draw = ImageDraw.Draw(glow)
    draw.ellipse((-40, -70, 190, 160), fill=70)          # top left, accent
    glow = glow.filter(ImageFilter.GaussianBlur(28)).resize((WIDTH, HEIGHT))
    base = Image.composite(Image.new("RGB", (WIDTH, HEIGHT), ACCENT_DIM), base, glow)

    glow2 = Image.new("L", (WIDTH // 4, HEIGHT // 4), 0)
    ImageDraw.Draw(glow2).ellipse((150, 330, 330, 500), fill=44)   # lower right, cool
    glow2 = glow2.filter(ImageFilter.GaussianBlur(30)).resize((WIDTH, HEIGHT))
    return Image.composite(Image.new("RGB", (WIDTH, HEIGHT), (24, 39, 66)), base, glow2)


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
    """A colour dimmed toward the background, which is how fading in is drawn."""

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

    def text(
        self,
        xy: tuple[int, int],
        value: str,
        *,
        size: int = 48,
        bold: bool = False,
        fill: Sequence[int] = INK,
        anchor: str = "la",
        alpha: float = 1.0,
        spacing: int = 12,
    ) -> None:
        if alpha <= 0.01:
            return
        self.draw.text(xy, value, font=load_font(size, bold=bold), fill=fade(fill, alpha), anchor=anchor, spacing=spacing)

    def measure(self, value: str, *, size: int = 48, bold: bool = False) -> tuple[int, int]:
        box = self.draw.textbbox((0, 0), value, font=load_font(size, bold=bold))
        return box[2] - box[0], box[3] - box[1]

    def fit(self, value: str, width: int, *, size: int = 48, bold: bool = False) -> str:
        """Trim to the width available, with an ellipsis, so a long name never overruns."""

        if self.measure(value, size=size, bold=bold)[0] <= width:
            return value
        trimmed = value
        while trimmed and self.measure(trimmed + "…", size=size, bold=bold)[0] > width:
            trimmed = trimmed[:-1]
        return (trimmed + "…") if trimmed else ""

    def panel(
        self,
        box: tuple[int, int, int, int],
        *,
        radius: int = 28,
        fill: Sequence[int] = PANEL,
        outline: Sequence[int] | None = LINE,
        alpha: float = 1.0,
    ) -> None:
        if alpha <= 0.01:
            return
        self.draw.rounded_rectangle(
            box,
            radius=radius,
            fill=fade(fill, alpha),
            outline=fade(outline, alpha) if outline else None,
            width=2 if outline else 0,
        )

    def chip(self, xy: tuple[int, int], label: str, *, colour: Sequence[int] = ACCENT, size: int = 34, alpha: float = 1.0) -> int:
        """A small pill, returning the width it took."""

        pad_x, pad_y = 22, 12
        text_w, text_h = self.measure(label, size=size, bold=True)
        width = text_w + pad_x * 2
        height = text_h + pad_y * 2 + 6
        self.panel((xy[0], xy[1], xy[0] + width, xy[1] + height), radius=height // 2, fill=mix(BG, colour, 0.16), outline=mix(BG, colour, 0.45), alpha=alpha)
        self.text((xy[0] + pad_x, xy[1] + height // 2), label, size=size, bold=True, fill=colour, anchor="lm", alpha=alpha)
        return width

    def rule(self, y: int, *, x0: int = MARGIN, x1: int = WIDTH - MARGIN, alpha: float = 1.0, colour: Sequence[int] = LINE) -> None:
        if alpha <= 0.01:
            return
        self.draw.rectangle((x0, y, x1, y + 2), fill=fade(colour, alpha))

    def bar(
        self,
        box: tuple[int, int, int, int],
        progress: float,
        *,
        colour: Sequence[int] = ACCENT,
        track: Sequence[int] = PANEL_HI,
        radius: int | None = None,
        alpha: float = 1.0,
    ) -> None:
        x0, y0, x1, y1 = box
        r = radius if radius is not None else (y1 - y0) // 2
        self.panel((x0, y0, x1, y1), radius=r, fill=track, outline=None, alpha=alpha)
        filled = x0 + max(0.0, min(1.0, progress)) * (x1 - x0)
        if filled - x0 > 2:
            self.panel((x0, y0, filled, y1), radius=r, fill=colour, outline=None, alpha=alpha)


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
    "ACCENT", "AMBER", "BG", "Canvas", "CONTENT_WIDTH", "DOWN", "FPS", "HEIGHT", "INK", "INK2",
    "LINE", "MARGIN", "MUTED", "MissingFontError", "PANEL", "PANEL_HI", "SAFE_BOTTOM", "SAFE_TOP",
    "UP", "WIDTH", "appear", "background", "ease_out", "fade", "font_pair", "korean_date",
    "load_font", "mix", "money", "percent", "tone",
]

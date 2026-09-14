"""How a short looks: the themes, the type, and the canvas that draws them.

Three directions are kept side by side rather than one, because the right
answer for a feed is decided by watching, not by arguing. Each theme sets its
own ground, ink, accent, typefaces and texture; every scene is written once
against semantic colour names and renders in whichever theme is chosen.

Type is the biggest lever here and it is spent deliberately. Headlines are set
in Noto Sans KR at Black, which is the heaviest Korean weight on this machine
and the only one that holds a phone screen at arm's length. Running text is
Pretendard, the same face the website sets, so the channel and the site read as
one thing. Figures are drawn on a fixed digit advance, so a number counting up
never jitters, whatever the typeface.

Practical constraints the design answers: it is watched on a phone, in a feed,
usually with the sound off, and the player covers the top and bottom of the
frame.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence

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

Colour = tuple[int, int, int]

# ------------------------------------------------------------------- fonts
FONT_DIRS = (
    Path(r"C:\Windows\Fonts"),
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts")),
    Path("/usr/share/fonts/truetype/noto"),
    Path("/usr/share/fonts/opentype/noto"),
    Path("/usr/share/fonts/truetype/nanum"),
    Path("/usr/share/fonts"),
    Path("assets/fonts"),
)
FONT_ENV = "TRADINGAGENTS_SHORTS_FONT"


@dataclass(frozen=True)
class FontSpec:
    """A file plus, for a variable font, the named instance to set on it."""

    files: tuple[str, ...]
    variation: str | None = None

    def resolve(self) -> Path | None:
        for name in self.files:
            direct = Path(name)
            if direct.is_absolute() and direct.exists():
                return direct
            for folder in FONT_DIRS:
                candidate = folder / name
                if candidate.exists():
                    return candidate
        return None


DISPLAY_BLACK = FontSpec(("NotoSansKR-VF.ttf", "NotoSansKR-Black.ttf", "malgunbd.ttf"), "Black")
DISPLAY_BOLD = FontSpec(("NotoSansKR-VF.ttf", "NotoSansKR-Bold.ttf", "malgunbd.ttf"), "Bold")
SERIF_BLACK = FontSpec(("NotoSerifKR-VF.ttf", "malgunbd.ttf"), "Black")
SERIF_BOLD = FontSpec(("NotoSerifKR-VF.ttf", "malgunbd.ttf"), "SemiBold")
BODY = FontSpec(("Pretendard-Regular.ttf", "NotoSansKR-Regular.ttf", "malgun.ttf"))
BODY_STRONG = FontSpec(("Pretendard-SemiBold.ttf", "NotoSansKR-Medium.ttf", "malgunbd.ttf"))
MONO = FontSpec(("consola.ttf", "DejaVuSansMono.ttf"))
MONO_BOLD = FontSpec(("consolab.ttf", "DejaVuSansMono-Bold.ttf"))
ROUND_BOLD = FontSpec(("NanumSquareRoundB.ttf", "NotoSansKR-VF.ttf", "malgunbd.ttf"), "Bold")
KR = ("NotoSansKR-VF.ttf", "malgun.ttf")
KR_THIN = FontSpec(KR, "Light")
KR_LIGHT = FontSpec(KR, "DemiLight")
KR_REGULAR = FontSpec(KR, "Regular")
KR_MEDIUM = FontSpec(KR, "Medium")
KR_BOLD = FontSpec(KR, "Bold")
KR_BLACK = FontSpec(KR, "Black")


class MissingFontError(RuntimeError):
    """No installed font can draw Korean, so nothing legible can be rendered."""


@lru_cache(maxsize=256)
def _font(files: tuple[str, ...], variation: str | None, size: int) -> ImageFont.FreeTypeFont:
    override = (os.getenv(FONT_ENV) or "").strip()
    path = Path(override) if override and Path(override).exists() else FontSpec(files, variation).resolve()
    if path is None:
        raise MissingFontError(f"한글 글꼴을 찾지 못했습니다. {FONT_ENV} 환경변수에 TTF 경로를 지정하세요.")
    font = ImageFont.truetype(str(path), size)
    if variation:
        try:
            font.set_variation_by_name(variation)
        except (OSError, AttributeError, ValueError):
            pass  # a static file already carries its weight
    return font


def load_font(spec: FontSpec, size: int) -> ImageFont.FreeTypeFont:
    return _font(spec.files, spec.variation, size)


def fonts_available() -> bool:
    return BODY.resolve() is not None or DISPLAY_BLACK.resolve() is not None


# ------------------------------------------------------------------ themes
@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    note: str
    ground: Colour
    ink: Colour
    ink2: Colour
    muted: Colour
    accent: Colour
    on_accent: Colour
    up: Colour
    down: Colour
    warn: Colour
    hairline: Colour
    grid: Colour
    display: FontSpec = DISPLAY_BLACK
    heading: FontSpec = DISPLAY_BOLD
    body: FontSpec = BODY
    body_strong: FontSpec = BODY_STRONG
    figure: FontSpec = DISPLAY_BLACK
    label_font: FontSpec = BODY_STRONG
    texture: str = "grid"
    invert_statement: bool = False
    eyebrows: bool = True        # a label above every heading is a generated-page tell
    paths: bool = False          # draw each trade as the move it actually made
    label_tracking: int = 3
    rule_weight: int = 2

    def colour(self, name: str | Sequence[int] | None) -> Colour:
        if name is None:
            return self.ink
        if not isinstance(name, str):
            return tuple(name)  # type: ignore[return-value]
        return {
            "ink": self.ink, "ink2": self.ink2, "muted": self.muted, "accent": self.accent,
            "up": self.up, "down": self.down, "warn": self.warn, "hairline": self.hairline,
            "ground": self.ground, "on_accent": self.on_accent,
        }.get(name, self.ink)


POSTER = Theme(
    key="poster",
    label="대문",
    note="검은 바탕에 아주 큰 숫자, 한 장면만 강조색으로 뒤집습니다.",
    ground=(10, 12, 16), ink=(244, 246, 249), ink2=(168, 178, 190), muted=(118, 128, 140),
    accent=(45, 212, 191), on_accent=(8, 22, 22),
    up=(255, 86, 102), down=(88, 152, 255), warn=(245, 176, 66),
    hairline=(38, 44, 54), grid=(20, 24, 31),
    texture="none", invert_statement=True,
)

TERMINAL = Theme(
    key="terminal",
    label="전광판",
    note="시세 단말기처럼 고정폭 표와 인광 녹색, 주사선 질감.",
    ground=(6, 10, 11), ink=(224, 238, 232), ink2=(140, 166, 158), muted=(96, 120, 114),
    accent=(53, 240, 160), on_accent=(4, 20, 14),
    up=(255, 99, 110), down=(96, 168, 255), warn=(245, 196, 84),
    hairline=(28, 48, 42), grid=(12, 24, 21),
    display=DISPLAY_BLACK, heading=DISPLAY_BOLD, figure=MONO_BOLD, label_font=BODY_STRONG,
    body=BODY, body_strong=BODY_STRONG, texture="scanline", label_tracking=4,
)

PRINT = Theme(
    key="print",
    label="지면",
    note="밝은 종이 바탕에 명조 제목과 붉은 도장. 어두운 피드에서 튑니다.",
    ground=(238, 235, 228), ink=(22, 24, 27), ink2=(78, 82, 88), muted=(128, 130, 132),
    accent=(178, 44, 38), on_accent=(247, 244, 238),
    up=(196, 42, 46), down=(34, 78, 168), warn=(178, 44, 38),
    hairline=(206, 201, 190), grid=(228, 224, 215),
    display=SERIF_BLACK, heading=SERIF_BOLD, figure=SERIF_BLACK,
    texture="paper", label_tracking=4, rule_weight=3,
)

STATEMENT = Theme(
    key="statement",
    label="명세",
    note="증권 계좌 명세서에서 온 화면. 색은 상승·하락 두 가지뿐이고, 강조는 색이 아니라 굵기와 밝기로 합니다.",
    # a deep navy taken from the colour a Korean screen already uses for a fall,
    # rather than a near-black with a bright accent dropped on top of it
    ground=(13, 21, 33), ink=(230, 236, 244), ink2=(154, 170, 190), muted=(104, 121, 142),
    accent=(245, 238, 223), on_accent=(13, 21, 33),
    up=(255, 92, 96), down=(77, 155, 255), warn=(245, 238, 223),
    hairline=(35, 49, 68), grid=(17, 27, 41),
    display=KR_BLACK, heading=KR_BOLD, body=KR_LIGHT, body_strong=KR_MEDIUM,
    figure=KR_BLACK, label_font=KR_MEDIUM,
    texture="none", eyebrows=False, paths=True, label_tracking=0, rule_weight=2,
)

THEMES: dict[str, Theme] = {theme.key: theme for theme in (STATEMENT, POSTER, TERMINAL, PRINT)}
DEFAULT_THEME = "statement"


def theme(name: str | Theme | None = None) -> Theme:
    if isinstance(name, Theme):
        return name
    key = (name or os.getenv("TRADINGAGENTS_SHORTS_THEME") or DEFAULT_THEME).strip().lower()
    if key not in THEMES:
        raise ValueError(f"알 수 없는 테마 {key!r}. 가능한 값: {', '.join(THEMES)}")
    return THEMES[key]


# --------------------------------------------------------------- movement
def ease_out(x: float) -> float:
    """Fast then settling: how a thing arriving on screen should move."""

    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def appear(local: float, delay: float, duration: float = 0.45) -> float:
    """Progress of an element that starts at ``delay`` and takes ``duration``."""

    if duration <= 0:
        return 1.0
    return ease_out((local - delay) / duration)


def mix(a: Sequence[int], b: Sequence[int], t: float) -> Colour:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def tone(value: float | None) -> str:
    """Red for a gain, blue for a loss, named rather than fixed to one theme."""

    if value is None:
        return "ink2"
    return "up" if value > 0 else ("down" if value < 0 else "ink2")


# ---------------------------------------------------------------- surface
@lru_cache(maxsize=8)
def background(theme_key: str, inverted: bool = False) -> Image.Image:
    """The painted ground, made once per theme and reused by every frame."""

    active = THEMES[theme_key]
    ground = active.accent if inverted else active.ground
    base = Image.new("RGB", (WIDTH, HEIGHT), ground)
    if inverted:
        return base
    draw = ImageDraw.Draw(base)

    if active.texture == "grid":
        for y in range(SAFE_TOP - 120, HEIGHT, 96):
            draw.rectangle((0, y, WIDTH, y), fill=active.grid)
        for x in range(MARGIN, WIDTH, 192):
            draw.rectangle((x, 0, x, HEIGHT), fill=active.grid)
    elif active.texture == "scanline":
        for y in range(0, HEIGHT, 4):
            draw.rectangle((0, y, WIDTH, y), fill=active.grid)
    elif active.texture == "paper":
        # a soft vignette and one warm bloom, so the page is not a flat swatch
        shade = Image.new("L", (WIDTH // 4, HEIGHT // 4), 0)
        ImageDraw.Draw(shade).ellipse((-120, -160, 390, 340), fill=34)
        shade = shade.filter(ImageFilter.GaussianBlur(40)).resize((WIDTH, HEIGHT))
        base = Image.composite(Image.new("RGB", (WIDTH, HEIGHT), (246, 243, 236)), base, shade)

    if active.texture in {"grid", "scanline"}:
        glow = Image.new("L", (WIDTH // 4, HEIGHT // 4), 0)
        ImageDraw.Draw(glow).ellipse((-80, 30, 160, 310), fill=48)
        glow = glow.filter(ImageFilter.GaussianBlur(32)).resize((WIDTH, HEIGHT))
        base = Image.composite(Image.new("RGB", (WIDTH, HEIGHT), mix(active.ground, active.accent, 0.22)), base, glow)
    return base


@dataclass
class Canvas:
    """A single frame, with the handful of drawing moves the scenes need."""

    image: Image.Image
    theme: Theme
    inverted: bool = False

    @classmethod
    def blank(cls, active: Theme | str | None = None, *, inverted: bool = False) -> "Canvas":
        resolved = theme(active)
        return cls(background(resolved.key, inverted).copy(), resolved, inverted)

    @property
    def draw(self) -> ImageDraw.ImageDraw:
        return ImageDraw.Draw(self.image, "RGBA")

    @property
    def ground(self) -> Colour:
        return self.theme.accent if self.inverted else self.theme.ground

    def colour(self, name: str | Sequence[int] | None, alpha: float = 1.0) -> Colour:
        """Resolve a semantic name in the active theme, faded toward the ground."""

        if self.inverted and isinstance(name, str) and name in {"ink", "accent"}:
            name = "on_accent"
        return mix(self.ground, self.theme.colour(name), max(0.0, min(1.0, alpha)))

    # ------------------------------------------------------------- typography
    def _spec(self, role: str) -> FontSpec:
        return {
            "display": self.theme.display, "heading": self.theme.heading, "body": self.theme.body,
            "strong": self.theme.body_strong, "figure": self.theme.figure, "label": self.theme.label_font,
            "mono": MONO, "mono_bold": MONO_BOLD,
        }.get(role, self.theme.body)

    def text(
        self,
        xy: tuple[int, int],
        value: str,
        *,
        size: int = 44,
        role: str = "body",
        fill: str | Sequence[int] = "ink",
        anchor: str = "la",
        alpha: float = 1.0,
        spacing: int = 14,
        tracking: int = 0,
    ) -> None:
        if alpha <= 0.01 or not value:
            return
        font = load_font(self._spec(role), size)
        colour = self.colour(fill, alpha)
        if not tracking:
            self.draw.text(xy, value, font=font, fill=colour, anchor=anchor, spacing=spacing)
            return
        x, y = xy
        for character in value:
            self.draw.text((x, y), character, font=font, fill=colour, anchor=anchor)
            x += self.draw.textlength(character, font=font) + tracking

    def figure(
        self,
        xy: tuple[int, int],
        value: str,
        *,
        size: int = 120,
        fill: str | Sequence[int] = "ink",
        anchor: str = "la",
        alpha: float = 1.0,
        role: str = "figure",
    ) -> int:
        """Draw a number on a fixed digit advance, so a counting value cannot jitter.

        Proportional faces set 1 narrower than 8, which makes an animated
        figure twitch as its digits change. Every digit is placed in a cell the
        width of a zero instead; the sign, point and unit keep their own width.
        """

        if alpha <= 0.01 or not value:
            return 0
        font = load_font(self._spec(role), size)
        cell = self.draw.textlength("0", font=font)
        widths = [cell if character.isdigit() else self.draw.textlength(character, font=font) for character in value]
        total = int(sum(widths))
        x = xy[0] - (total if anchor.startswith("r") else (total // 2 if anchor.startswith("m") else 0))
        colour = self.colour(fill, alpha)
        vertical = "m" if anchor.endswith("m") else ("s" if anchor.endswith("s") else "a")
        for character, width in zip(value, widths):
            self.draw.text((x + width / 2, xy[1]), character, font=font, fill=colour, anchor=f"m{vertical}")
            x += width
        return total

    def hero(
        self,
        xy: tuple[int, int],
        value: str,
        *,
        size: int = 300,
        fill: str | Sequence[int] = "ink",
        alpha: float = 1.0,
        limit: int | None = None,
    ) -> int:
        """The one figure a shot is built around, with its unit set smaller.

        A percent sign at the same size as the number eats a sixth of the
        column and reads as loudly as the value, which it should not. Setting
        it at a little under half buys the number the width back.
        """

        head = value.rstrip("%원건종목 ")
        tail = value[len(head):]
        room = (limit or (WIDTH - MARGIN - 40))
        unit = max(int(size * 0.42), 28)
        while self.measure_figure(head, size=size) + (self.measure(tail, size=unit, role="figure")[0] if tail else 0) > room and size > 110:
            size -= 10
            unit = max(int(size * 0.42), 28)
        width = self.figure(xy, head, size=size, fill=fill, alpha=alpha, anchor="lm")
        if tail:
            self.text((xy[0] + width + int(size * 0.04), xy[1] + int(size * 0.22)), tail, size=unit, role="figure", fill=fill, alpha=alpha, anchor="lm")
            width += self.measure(tail, size=unit, role="figure")[0]
        return width

    def measure(self, value: str, *, size: int = 44, role: str = "body", tracking: int = 0) -> tuple[int, int]:
        font = load_font(self._spec(role), size)
        box = self.draw.textbbox((0, 0), value, font=font)
        return box[2] - box[0] + tracking * max(len(value) - 1, 0), box[3] - box[1]

    def measure_figure(self, value: str, *, size: int = 120, role: str = "figure") -> int:
        font = load_font(self._spec(role), size)
        cell = self.draw.textlength("0", font=font)
        return int(sum(cell if character.isdigit() else self.draw.textlength(character, font=font) for character in value))

    def fit(self, value: str, width: int, *, size: int = 44, role: str = "body") -> str:
        """Trim to the width available, so a long name never overruns its column."""

        if self.measure(value, size=size, role=role)[0] <= width:
            return value
        trimmed = value
        while trimmed and self.measure(trimmed + "…", size=size, role=role)[0] > width:
            trimmed = trimmed[:-1]
        return (trimmed + "…") if trimmed else ""

    # ------------------------------------------------------------------ marks
    def rule(
        self,
        y: int,
        *,
        x0: int = MARGIN,
        x1: int = WIDTH - 84,
        alpha: float = 1.0,
        fill: str | Sequence[int] = "hairline",
        weight: int | None = None,
        progress: float = 1.0,
    ) -> None:
        """A ruled line, optionally drawn part way: rules wipe in from the left."""

        if alpha <= 0.01 or progress <= 0:
            return
        end = x0 + (x1 - x0) * max(0.0, min(1.0, progress))
        thickness = weight if weight is not None else self.theme.rule_weight
        self.draw.rectangle((x0, y, end, y + thickness - 1), fill=self.colour(fill, alpha))

    def rail(self, progress: float, *, alpha: float = 1.0) -> None:
        """The margin rail: the whole cut's position, drawn as part of the page."""

        top, bottom = SAFE_TOP - 40, SAFE_BOTTOM + 40
        self.draw.rectangle((RAIL_X, top, RAIL_X + 3, bottom), fill=self.colour("hairline", alpha))
        filled = top + (bottom - top) * max(0.0, min(1.0, progress))
        if filled > top:
            self.draw.rectangle((RAIL_X, top, RAIL_X + 3, filled), fill=self.colour("accent", alpha))

    def label(self, xy: tuple[int, int], value: str, *, fill: str | Sequence[int] = "accent", alpha: float = 1.0, size: int = 28) -> None:
        """A small tracked label with a short tick, used as a section head."""

        if alpha <= 0.01 or not value:
            return
        x, y = xy
        self.draw.rectangle((x, y + size // 2 - 1, x + 26, y + size // 2 + 1), fill=self.colour(fill, alpha))
        self.text((x + 42, y + size // 2), value, size=size, role="label", fill=fill, anchor="lm", alpha=alpha, tracking=self.theme.label_tracking)

    def tag(self, xy: tuple[int, int], value: str, *, fill: str | Sequence[int] = "warn", alpha: float = 1.0, size: int = 25) -> int:
        """An outlined marker beside a row, the ledger's note in the margin."""

        if alpha <= 0.01 or not value:
            return 0
        pad = 14
        width = self.measure(value, size=size, role="strong")[0] + pad * 2
        height = size + 16
        self.draw.rounded_rectangle((xy[0], xy[1], xy[0] + width, xy[1] + height), radius=5, outline=self.colour(fill, alpha * 0.85), width=2)
        self.text((xy[0] + pad, xy[1] + height // 2), value, size=size, role="strong", fill=fill, anchor="lm", alpha=alpha)
        return width

    def stamp(self, centre: tuple[int, int], value: str, *, fill: str | Sequence[int] = "warn", alpha: float = 1.0, size: int = 78, angle: float = -8.0, scale: float = 1.0) -> None:
        """The closed-entry stamp: a boxed word set at an angle, pressed on."""

        if alpha <= 0.01 or not value:
            return
        pad_x, pad_y = 42, 24
        font = load_font(self._spec("heading"), size)
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        box = probe.textbbox((0, 0), value, font=font)
        width, height = box[2] - box[0] + pad_x * 2, box[3] - box[1] + pad_y * 2
        layer = Image.new("RGBA", (width + 18, height + 18), (0, 0, 0, 0))
        pen = ImageDraw.Draw(layer)
        ink = (*self.theme.colour(fill), int(255 * min(1.0, alpha)))
        pen.rounded_rectangle((9, 9, width + 9, height + 9), radius=8, outline=ink, width=6)
        pen.text((width // 2 + 9, height // 2 + 9), value, font=font, fill=ink, anchor="mm")
        if scale != 1.0:
            layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.LANCZOS)
        layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
        self.image.paste(layer, (centre[0] - layer.width // 2, centre[1] - layer.height // 2), layer)

    def bar(self, box: tuple[float, float, float, float], *, fill: str | Sequence[int] = "accent", alpha: float = 1.0, radius: int = 4) -> None:
        """A thin mark with rounded ends, anchored to the baseline it grows from."""

        x0, y0, x1, y1 = box
        if abs(x1 - x0) < 2 or alpha <= 0.01:
            return
        self.draw.rounded_rectangle((min(x0, x1), y0, max(x0, x1), y1), radius=radius, fill=self.colour(fill, alpha))

    def trade_path(
        self,
        box: tuple[int, int, int, int],
        *,
        entry: float,
        exit_price: float,
        stop: float | None = None,
        fill: str | Sequence[int] = "ink",
        alpha: float = 1.0,
        progress: float = 1.0,
    ) -> None:
        """Entry to exit as one segment, with the level it was meant to stop at.

        Two prices that really happened and one that was set in advance. It is
        a diagram, not an invented chart: no path is drawn between them that
        the data does not contain.
        """

        if alpha <= 0.01:
            return
        x0, y0, x1, y1 = box
        span = max(abs(exit_price - entry), abs((stop if stop else entry) - entry), entry * 0.001) * 1.35
        def place(price: float) -> float:
            return y0 + (y1 - y0) * (0.5 - (price - entry) / (2 * span))

        if stop:
            level = place(stop)
            if y0 <= level <= y1:
                for dash in range(int(x0), int(x1), 12):
                    self.draw.rectangle((dash, level, dash + 6, level + 1), fill=self.colour("muted", alpha * 0.8))
        end_x = x0 + (x1 - x0) * max(0.0, min(1.0, progress))
        end_y = place(entry) + (place(exit_price) - place(entry)) * max(0.0, min(1.0, progress))
        self.draw.line((x0, place(entry), end_x, end_y), fill=self.colour(fill, alpha), width=3)
        self.draw.ellipse((end_x - 5, end_y - 5, end_x + 5, end_y + 5), fill=self.colour(fill, alpha))

    def block(self, box: tuple[int, int, int, int], *, fill: str | Sequence[int] = "accent", alpha: float = 1.0) -> None:
        if alpha <= 0.01:
            return
        self.draw.rectangle(box, fill=self.colour(fill, alpha))


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
    "BODY", "BODY_STRONG", "CONTENT_WIDTH", "Canvas", "DEFAULT_THEME", "DISPLAY_BLACK", "FPS", "STATEMENT",
    "FontSpec", "HEIGHT", "MARGIN", "MONO", "MONO_BOLD", "MissingFontError", "POSTER", "PRINT",
    "RAIL_X", "SAFE_BOTTOM", "SAFE_TOP", "TERMINAL", "THEMES", "Theme", "WIDTH", "appear",
    "background", "ease_out", "fonts_available", "korean_date", "load_font", "mix", "money",
    "percent", "theme", "tone",
]

"""The shots a short is cut from.

Each scene knows how long it lasts, what the narrator says over it, and how to
paint itself at any moment inside that span, so the renderer can ask for any
frame without replaying what came before.

Everything arrives on a stagger and rules wipe in from the left, which is what
makes a generated cut read as written rather than as a slideshow. No scene
fills a card: the page is ruled, and at most one thing per screen is filled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .design import (
    ACCENT,
    AMBER,
    Canvas,
    CONTENT_WIDTH,
    HAIRLINE,
    INK,
    INK2,
    MARGIN,
    MUTED,
    SAFE_TOP,
    WIDTH,
    appear,
    ease_out,
    fade,
    percent,
    tone,
)

RIGHT = WIDTH - 84


@dataclass
class Scene:
    seconds: float = 3.0
    narration: str = ""

    def draw(self, canvas: Canvas, local: float) -> None:  # pragma: no cover - base
        raise NotImplementedError


def _head(canvas: Canvas, label: str, heading: str, local: float) -> None:
    """Every body scene opens the same way: a tracked label, a rule, a heading."""

    canvas.label((MARGIN, SAFE_TOP), label, alpha=appear(local, 0.0, 0.3))
    canvas.rule(SAFE_TOP + 62, progress=appear(local, 0.05, 0.5))
    canvas.text((MARGIN, SAFE_TOP + 96), heading, size=64, bold=True, alpha=appear(local, 0.14, 0.4))


@dataclass
class Hook(Scene):
    """The first two seconds: one figure, and why it is worth staying for."""

    eyebrow: str = ""
    value: str = ""
    value_from: float | None = None
    value_to: float | None = None
    value_digits: int = 2
    value_colour: Sequence[int] = INK
    caption: str = ""
    lines: tuple[str, ...] = ()
    seconds: float = 3.4

    def draw(self, canvas: Canvas, local: float) -> None:
        canvas.label((MARGIN, SAFE_TOP), self.eyebrow, alpha=appear(local, 0.0, 0.35))

        shown = self.value
        if self.value_to is not None:
            start = self.value_from if self.value_from is not None else 0.0
            progress = ease_out((local - 0.25) / 1.1)
            shown = percent(start + (self.value_to - start) * progress, digits=self.value_digits)
        alpha = appear(local, 0.18, 0.4)
        size = 180 if len(shown) <= 8 else 148
        canvas.text((MARGIN - 8, 470), shown, size=size, bold=True, numeral=True, fill=self.value_colour, alpha=alpha)
        canvas.text((MARGIN, 700), self.caption, size=40, fill=INK2, alpha=appear(local, 0.5, 0.4))

        canvas.rule(820, progress=appear(local, 0.66, 0.55), colour=ACCENT, alpha=0.55)
        for index, line in enumerate(self.lines):
            canvas.text((MARGIN, 880 + index * 92), line, size=66, bold=True, alpha=appear(local, 0.85 + index * 0.18, 0.45))


@dataclass
class Rows(Scene):
    """A ruled list where each line lands on its own beat."""

    eyebrow: str = ""
    heading: str = ""
    rows: tuple[dict, ...] = ()
    note: str = ""
    stagger: float = 0.26
    seconds: float = 7.0

    def draw(self, canvas: Canvas, local: float) -> None:
        _head(canvas, self.eyebrow, self.heading, local)

        count = min(len(self.rows), 6)
        pitch = 152
        top = max(SAFE_TOP + 230, 950 - (count * pitch) // 2)
        for index, row in enumerate(self.rows[:6]):
            progress = appear(local, 0.4 + index * self.stagger, 0.42)
            if progress <= 0.01:
                continue
            y = top + index * pitch
            shift = int((1 - progress) * 34)

            value = str(row.get("value") or "")
            value_w = canvas.measure(value, size=56, bold=True, numeral=True)[0] if value else 0
            room = CONTENT_WIDTH - value_w - 48

            canvas.text((MARGIN - shift, y + 42), canvas.fit(str(row.get("label") or ""), room, size=48, bold=True), size=48, bold=True, alpha=progress, anchor="lm")
            if value:
                canvas.text((RIGHT + shift, y + 42), value, size=56, bold=True, numeral=True, fill=row.get("colour") or INK, alpha=progress, anchor="rm")

            sub = str(row.get("sub") or "")
            tag = str(row.get("badge") or "")
            tag_w = (canvas.measure(tag, size=26, bold=True)[0] + 28) if tag else 0
            if sub:
                canvas.text((MARGIN - shift, y + 98), canvas.fit(sub, room - tag_w - 40, size=31), size=31, fill=MUTED, alpha=progress, anchor="lm")
            if tag:
                # the note sits in the margin, under the figure it explains
                canvas.tag((RIGHT - tag_w + shift, y + 78), tag, colour=row.get("badge_colour") or AMBER, alpha=progress * 0.9)
            canvas.rule(y + pitch - 22, progress=progress, alpha=0.9)

        if self.note:
            canvas.text((MARGIN, top + count * pitch + 16), self.note, size=33, fill=MUTED, alpha=appear(local, 0.4 + count * self.stagger, 0.5))


@dataclass
class Bars(Scene):
    """Signed quantities against one zero line: left is a loss, right is a gain."""

    eyebrow: str = ""
    heading: str = ""
    items: tuple[dict, ...] = ()
    note: str = ""
    signed: bool = True
    seconds: float = 6.0

    def draw(self, canvas: Canvas, local: float) -> None:
        _head(canvas, self.eyebrow, self.heading, local)

        values = [abs(float(item.get("value") or 0.0)) for item in self.items] or [1.0]
        scale = max(values) or 1.0
        count = min(len(self.items), 4)
        block = 190
        top = max(SAFE_TOP + 250, 920 - (count * block) // 2)
        centre = (MARGIN + RIGHT) // 2
        half = (RIGHT - MARGIN) // 2

        if self.signed and count:
            zero = appear(local, 0.3, 0.4)
            if zero > 0.01:
                bottom = top + (count - 1) * block + 132
                canvas.draw.rectangle((centre - 1, top + 54, centre + 1, top + 54 + (bottom - top - 54) * zero), fill=fade(HAIRLINE, zero))

        for index, item in enumerate(self.items[:4]):
            progress = appear(local, 0.42 + index * 0.26, 0.55)
            if progress <= 0.01:
                continue
            y = top + index * block
            value = float(item.get("value") or 0.0)
            colour = item.get("colour") or tone(value)
            canvas.text((MARGIN, y), str(item.get("label") or ""), size=44, bold=True, alpha=progress)
            canvas.text((RIGHT, y - 4), str(item.get("text") or percent(value)), size=50, bold=True, numeral=True, fill=colour, anchor="ra", alpha=progress)
            reach = (abs(value) / scale) * (half - 12) * progress
            if self.signed:
                box = (centre - reach, y + 76, centre - 2, y + 112) if value < 0 else (centre + 2, y + 76, centre + reach, y + 112)
            else:
                box = (MARGIN, y + 76, MARGIN + (abs(value) / scale) * (RIGHT - MARGIN) * progress, y + 112)
            canvas.bar(box, colour=colour, alpha=progress)
            if item.get("sub"):
                canvas.text((MARGIN, y + 126), str(item["sub"]), size=30, fill=MUTED, alpha=progress)

        if self.note:
            canvas.text((MARGIN, top + count * block + 6), self.note, size=33, fill=MUTED, alpha=appear(local, 0.42 + count * 0.26, 0.5))


@dataclass
class Statement(Scene):
    """One idea, held long enough to read twice, with the stamp that names it."""

    eyebrow: str = ""
    lines: tuple[str, ...] = ()
    highlight: str = ""
    highlight_colour: Sequence[int] = ACCENT
    stamp: str = ""
    caption: str = ""
    seconds: float = 4.6

    def draw(self, canvas: Canvas, local: float) -> None:
        canvas.label((MARGIN, SAFE_TOP), self.eyebrow, alpha=appear(local, 0.0, 0.3))
        y = 500
        for index, line in enumerate(self.lines):
            canvas.text((MARGIN, y + index * 94), line, size=68, bold=True, alpha=appear(local, 0.12 + index * 0.2, 0.45))

        after = y + len(self.lines) * 94
        if self.highlight:
            alpha = appear(local, 0.12 + len(self.lines) * 0.2 + 0.18, 0.45)
            canvas.rule(after + 26, progress=alpha, colour=self.highlight_colour, alpha=0.5)
            canvas.text((MARGIN - 6, after + 56), self.highlight, size=132, bold=True, numeral=True, fill=self.highlight_colour, alpha=alpha)
            after += 56 + 160

        if self.stamp:
            # lands rather than fades: over-scaled for a beat, then settles
            progress = appear(local, 0.95, 0.42)
            if progress > 0.01:
                canvas.stamp((WIDTH - 290, 700), self.stamp, alpha=min(1.0, progress * 1.2), scale=1.0 + (1 - progress) * 0.45)

        if self.caption:
            canvas.text((MARGIN, max(after + 34, 1150)), self.caption, size=38, fill=INK2, alpha=appear(local, 1.05, 0.5), spacing=16)


@dataclass
class Outro(Scene):
    """Where to go next, and the line that has to be on every one of these."""

    headline: tuple[str, ...] = ()
    url: str = "agenttrust.kr"
    call: str = ""
    telegram: str = ""
    telegram_line: str = "매일 아침 선별 결과와 청산 알림을 텔레그램으로 먼저"
    disclaimer: str = "AI 실험 기록이며 매매 권유가 아닙니다 · 모의 계좌 · 실계좌 주문 없음"
    seconds: float = 5.2

    def draw(self, canvas: Canvas, local: float) -> None:
        for index, line in enumerate(self.headline):
            canvas.text((MARGIN, 440 + index * 92), line, size=66, bold=True, alpha=appear(local, 0.05 + index * 0.18, 0.45))

        alpha = appear(local, 0.42, 0.5)
        canvas.rule(720, progress=alpha, colour=ACCENT, alpha=0.55)
        if self.call:
            canvas.text((MARGIN, 766), self.call, size=38, fill=INK2, alpha=alpha)
        canvas.text((MARGIN - 4, 826), self.url, size=72, bold=True, fill=ACCENT, alpha=appear(local, 0.55, 0.5))

        if self.telegram:
            block = appear(local, 0.95, 0.5)
            canvas.rule(1000, progress=block, alpha=0.9)
            canvas.label((MARGIN, 1040), "텔레그램", colour=INK2, alpha=block, size=27)
            canvas.text((MARGIN, 1104), self.telegram_line, size=36, fill=INK, alpha=block, spacing=14)
            canvas.text((MARGIN - 4, 1168), self.telegram, size=54, bold=True, numeral=True, fill=ACCENT, alpha=appear(local, 1.15, 0.5))

        canvas.text((MARGIN, 1430), self.disclaimer, size=28, fill=MUTED, alpha=appear(local, 1.3, 0.6))


__all__ = ["Bars", "Hook", "Outro", "Rows", "Scene", "Statement"]

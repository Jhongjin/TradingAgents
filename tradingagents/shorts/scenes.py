"""The shots a short is cut from.

Each scene knows how long it lasts and how to paint itself at any moment
inside that span, so the renderer can ask for any frame without replaying what
came before. Elements arrive on a stagger rather than all at once, which is
what makes a generated video read as edited instead of as a slideshow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .design import (
    ACCENT,
    AMBER,
    Canvas,
    CONTENT_WIDTH,
    INK,
    INK2,
    LINE,
    MARGIN,
    MUTED,
    PANEL,
    PANEL_HI,
    SAFE_TOP,
    WIDTH,
    appear,
    ease_out,
    fade,
    mix,
    percent,
    tone,
)


@dataclass
class Scene:
    seconds: float = 3.0

    def draw(self, canvas: Canvas, local: float) -> None:  # pragma: no cover - base
        raise NotImplementedError


def _eyebrow(canvas: Canvas, text: str, *, alpha: float, y: int = SAFE_TOP + 40) -> None:
    canvas.chip((MARGIN, y), text, alpha=alpha)


def _title(canvas: Canvas, lines: Sequence[str], *, alpha: float, y: int, size: int = 72) -> int:
    for index, line in enumerate(lines):
        canvas.text((MARGIN, y + index * int(size * 1.28)), line, size=size, bold=True, alpha=alpha)
    return y + len(lines) * int(size * 1.28)


@dataclass
class Hook(Scene):
    """The first two seconds: one number, and why it is worth staying for."""

    eyebrow: str = ""
    value: str = ""
    value_from: float | None = None
    value_to: float | None = None
    value_digits: int = 2
    value_colour: Sequence[int] = INK
    caption: str = ""
    lines: tuple[str, ...] = ()
    seconds: float = 3.2

    def draw(self, canvas: Canvas, local: float) -> None:
        _eyebrow(canvas, self.eyebrow, alpha=appear(local, 0.0, 0.35))

        shown = self.value
        if self.value_to is not None:
            start = self.value_from if self.value_from is not None else 0.0
            progress = ease_out((local - 0.25) / 1.1)
            shown = percent(start + (self.value_to - start) * progress, digits=self.value_digits)
        alpha = appear(local, 0.2, 0.4)
        size = 176 if len(shown) <= 8 else 140
        canvas.text((MARGIN, 560), shown, size=size, bold=True, fill=self.value_colour, alpha=alpha)
        canvas.text((MARGIN, 790), self.caption, size=44, fill=INK2, alpha=appear(local, 0.5, 0.4))

        canvas.rule(900, alpha=appear(local, 0.7, 0.4))
        _title(canvas, self.lines, alpha=appear(local, 0.85, 0.45), y=970, size=68)


@dataclass
class Rows(Scene):
    """A list where each line lands on its own beat: the body of most cuts."""

    eyebrow: str = ""
    heading: str = ""
    rows: tuple[dict, ...] = ()
    note: str = ""
    stagger: float = 0.28
    seconds: float = 7.0

    def draw(self, canvas: Canvas, local: float) -> None:
        _eyebrow(canvas, self.eyebrow, alpha=appear(local, 0.0, 0.3))
        canvas.text((MARGIN, SAFE_TOP + 150), self.heading, size=66, bold=True, alpha=appear(local, 0.1, 0.4))

        # the list is centred in the band, so three rows do not float at the top
        count = min(len(self.rows), 6)
        height = 148
        gap = 16
        top = max(SAFE_TOP + 290, 940 - (count * (height + gap)) // 2)
        for index, row in enumerate(self.rows[:6]):
            progress = appear(local, 0.35 + index * self.stagger, 0.42)
            if progress <= 0.01:
                continue
            y = top + index * (height + gap)
            slide = int((1 - progress) * 60)
            box = (MARGIN + slide, y, WIDTH - MARGIN + slide, y + height)
            canvas.panel(box, alpha=progress, fill=PANEL)

            label = str(row.get("label") or "")
            sub = str(row.get("sub") or "")
            value = str(row.get("value") or "")
            value_colour = row.get("colour") or INK
            badge = str(row.get("badge") or "")

            value_w = canvas.measure(value, size=58, bold=True)[0] if value else 0
            text_room = CONTENT_WIDTH - value_w - 70
            canvas.text((MARGIN + 34 + slide, y + 46), canvas.fit(label, text_room, size=50, bold=True), size=50, bold=True, alpha=progress, anchor="lm")
            if sub:
                canvas.text((MARGIN + 34 + slide, y + 102), canvas.fit(sub, text_room, size=34), size=34, fill=MUTED, alpha=progress, anchor="lm")
            if value:
                canvas.text((WIDTH - MARGIN - 34 + slide, y + (62 if badge else 74)), value, size=58, bold=True, fill=value_colour, alpha=progress, anchor="rm")
            if badge:
                badge_w = canvas.measure(badge, size=30, bold=True)[0] + 34
                canvas.chip((WIDTH - MARGIN - 34 - badge_w + slide, y + 92), badge, colour=row.get("badge_colour") or AMBER, size=30, alpha=progress)

        if self.note:
            canvas.text((MARGIN, top + count * (height + gap) + 34), self.note, size=36, fill=MUTED, alpha=appear(local, 0.35 + count * self.stagger, 0.5))


@dataclass
class Bars(Scene):
    """Two or three quantities side by side, growing from nothing."""

    eyebrow: str = ""
    heading: str = ""
    items: tuple[dict, ...] = ()
    note: str = ""
    signed: bool = True
    seconds: float = 6.0

    def draw(self, canvas: Canvas, local: float) -> None:
        _eyebrow(canvas, self.eyebrow, alpha=appear(local, 0.0, 0.3))
        canvas.text((MARGIN, SAFE_TOP + 150), self.heading, size=66, bold=True, alpha=appear(local, 0.1, 0.4))

        values = [abs(float(item.get("value") or 0.0)) for item in self.items] or [1.0]
        scale = max(values) or 1.0
        block = 196
        count = min(len(self.items), 4)
        top = max(SAFE_TOP + 300, 900 - (count * block) // 2)
        centre = WIDTH // 2
        half = (WIDTH - MARGIN * 2) // 2

        if self.signed and count:
            # one zero line behind every bar, so a longer bar to the left reads
            # as a bigger loss rather than as a bigger number
            zero_alpha = appear(local, 0.35, 0.4)
            canvas.draw.rectangle((centre - 1, top + 68, centre + 1, top + (count - 1) * block + 140), fill=fade(LINE, zero_alpha))

        for index, item in enumerate(self.items[:4]):
            progress = appear(local, 0.4 + index * 0.26, 0.55)
            if progress <= 0.01:
                continue
            y = top + index * block
            value = float(item.get("value") or 0.0)
            colour = item.get("colour") or tone(value)
            canvas.text((MARGIN, y), str(item.get("label") or ""), size=46, bold=True, alpha=progress)
            canvas.text((WIDTH - MARGIN, y), str(item.get("text") or percent(value)), size=52, bold=True, fill=colour, anchor="ra", alpha=progress)
            if self.signed:
                reach = (abs(value) / scale) * half * progress
                if reach >= 3:
                    box = (centre - reach, y + 80, centre, y + 128) if value < 0 else (centre, y + 80, centre + reach, y + 128)
                    canvas.panel(box, radius=10, fill=colour, outline=None, alpha=progress)
            else:
                canvas.bar((MARGIN, y + 80, WIDTH - MARGIN, y + 128), (abs(value) / scale) * progress, colour=colour, track=PANEL_HI, alpha=progress)
            if item.get("sub"):
                canvas.text((MARGIN, y + 140), str(item["sub"]), size=32, fill=MUTED, alpha=progress)

        if self.note:
            canvas.text((MARGIN, top + count * block + 20), self.note, size=36, fill=MUTED, alpha=appear(local, 0.4 + count * 0.26, 0.5))


@dataclass
class Statement(Scene):
    """One idea, held long enough to read twice."""

    eyebrow: str = ""
    lines: tuple[str, ...] = ()
    highlight: str = ""
    caption: str = ""
    seconds: float = 4.2

    def draw(self, canvas: Canvas, local: float) -> None:
        _eyebrow(canvas, self.eyebrow, alpha=appear(local, 0.0, 0.3))
        y = 600
        for index, line in enumerate(self.lines):
            canvas.text((MARGIN, y + index * 96), line, size=72, bold=True, alpha=appear(local, 0.15 + index * 0.22, 0.45))
        if self.highlight:
            hy = y + len(self.lines) * 96 + 40
            alpha = appear(local, 0.15 + len(self.lines) * 0.22 + 0.2, 0.45)
            width = canvas.measure(self.highlight, size=72, bold=True)[0]
            canvas.panel((MARGIN - 18, hy - 8, MARGIN + width + 34, hy + 104), radius=20, fill=mix((11, 18, 32), ACCENT, 0.18), outline=None, alpha=alpha)
            canvas.text((MARGIN + 8, hy + 6), self.highlight, size=72, bold=True, fill=ACCENT, alpha=alpha)
        if self.caption:
            canvas.text((MARGIN, 1090), self.caption, size=40, fill=INK2, alpha=appear(local, 0.9, 0.5), spacing=18)


@dataclass
class Outro(Scene):
    """Where to go, and the line that has to be on every one of these."""

    headline: tuple[str, ...] = ()
    url: str = "agenttrust.kr"
    call: str = ""
    disclaimer: str = "AI 실험 기록이며 매매 권유가 아닙니다 · 모의 계좌 · 실계좌 주문 없음"
    seconds: float = 3.6

    def draw(self, canvas: Canvas, local: float) -> None:
        for index, line in enumerate(self.headline):
            canvas.text((MARGIN, 620 + index * 96), line, size=70, bold=True, alpha=appear(local, 0.05 + index * 0.2, 0.45))

        alpha = appear(local, 0.45, 0.5)
        canvas.rule(960, alpha=alpha)
        if self.call:
            canvas.text((MARGIN, 1010), self.call, size=42, fill=INK2, alpha=alpha)
        canvas.text((MARGIN, 1090), self.url, size=76, bold=True, fill=ACCENT, alpha=appear(local, 0.6, 0.5))
        canvas.text((MARGIN, 1440), self.disclaimer, size=30, fill=MUTED, alpha=appear(local, 0.9, 0.6))


__all__ = ["Bars", "Hook", "Outro", "Rows", "Scene", "Statement"]

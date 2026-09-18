"""The shots a short is cut from.

Each scene knows how long it lasts, what the narrator says over it, and how to
paint itself at any moment inside that span, so the renderer can ask for any
frame without replaying what came before.

Scenes name colours rather than fix them, so the same cut renders in any theme.
Elements arrive on a stagger and rules wipe in from the left, which is what
makes a generated cut read as written rather than as a slideshow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .design import (
    CONTENT_WIDTH,
    MARGIN,
    SAFE_TOP,
    WIDTH,
    Canvas,
    appear,
    ease_out,
    percent,
)

RIGHT = WIDTH - 84
CENTRE_Y = 880          # where the eye sits once the player has covered the rest


@dataclass
class Scene:
    seconds: float = 3.0
    narration: str = ""
    inverted: bool = False

    def draw(self, canvas: Canvas, local: float) -> None:  # pragma: no cover - base
        raise NotImplementedError


def _head(canvas: Canvas, label: str, heading: str, local: float) -> None:
    """The heading, and above it a label only where the theme asks for one.

    A tracked label over every heading is one of the surest tells of a
    generated page, so the themes that do without it let the heading and the
    rule carry the section on their own.
    """

    if canvas.theme.eyebrows:
        canvas.label((MARGIN, SAFE_TOP), label, alpha=appear(local, 0.0, 0.3))
        canvas.rule(SAFE_TOP + 60, progress=appear(local, 0.05, 0.5))
        canvas.text((MARGIN, SAFE_TOP + 94), heading, size=62, role="heading", alpha=appear(local, 0.14, 0.4))
        return
    canvas.text((MARGIN, SAFE_TOP + 10), heading, size=64, role="heading", alpha=appear(local, 0.0, 0.35))
    canvas.rule(SAFE_TOP + 118, progress=appear(local, 0.1, 0.5))


@dataclass
class Hook(Scene):
    """The first two seconds: one figure, big enough to stop a thumb."""

    eyebrow: str = ""
    value: str = ""
    value_from: float | None = None
    value_to: float | None = None
    value_digits: int = 2
    value_colour: str | Sequence[int] = "ink"
    caption: str = ""
    lines: tuple[str, ...] = ()
    seconds: float = 3.4

    def draw(self, canvas: Canvas, local: float) -> None:
        if canvas.theme.eyebrows:
            canvas.label((MARGIN, SAFE_TOP), self.eyebrow, alpha=appear(local, 0.0, 0.35))
        else:
            # the same fact without the label device: a plain quiet line
            canvas.text((MARGIN, SAFE_TOP + 4), self.eyebrow, size=32, fill="muted", alpha=appear(local, 0.0, 0.35))

        shown = self.value
        if self.value_to is not None:
            start = self.value_from if self.value_from is not None else 0.0
            progress = ease_out((local - 0.22) / 1.05)
            shown = percent(start + (self.value_to - start) * progress, digits=self.value_digits)

        # the figure is the whole shot: sized to fill the column, and set hard
        # against the left margin rather than floating in the middle
        alpha = appear(local, 0.16, 0.4)
        canvas.hero((MARGIN - 10, 556), shown, size=340, fill=self.value_colour, alpha=alpha)

        canvas.text((MARGIN, 706), self.caption, size=38, fill="ink2", alpha=appear(local, 0.5, 0.4))
        canvas.rule(800, progress=appear(local, 0.62, 0.55), fill="accent", weight=4)
        for index, line in enumerate(self.lines):
            canvas.text((MARGIN, 866 + index * 94), line, size=68, role="display", alpha=appear(local, 0.8 + index * 0.16, 0.45))


@dataclass
class Rows(Scene):
    """A ruled list where each line lands on its own beat."""

    eyebrow: str = ""
    heading: str = ""
    rows: tuple[dict, ...] = ()
    note: str = ""
    # A figure and a line under it, for the cuts whose list beat leads with a
    # count rather than a heading. Unset everywhere else, and the Pillow
    # renderer ignores both.
    value: str = ""
    caption: str = ""
    stagger: float = 0.26
    seconds: float = 7.0

    def draw(self, canvas: Canvas, local: float) -> None:
        _head(canvas, self.eyebrow, self.heading, local)

        count = min(len(self.rows), 6)
        pitch = 152
        top = max(SAFE_TOP + 230, CENTRE_Y + 70 - (count * pitch) // 2)
        for index, row in enumerate(self.rows[:6]):
            progress = appear(local, 0.4 + index * self.stagger, 0.42)
            if progress <= 0.01:
                continue
            y = top + index * pitch
            # a slide on every row is the generic entrance; the theme that
            # draws paths lets rows simply arrive instead
            shift = 0 if canvas.theme.paths else int((1 - progress) * 34)

            value = str(row.get("value") or "")
            value_w = canvas.measure_figure(value, size=54) if value else 0
            room = CONTENT_WIDTH - value_w - 48

            canvas.text((MARGIN - shift, y + 42), canvas.fit(str(row.get("label") or ""), room, size=46, role="strong"),
                        size=46, role="strong", alpha=progress, anchor="lm")
            if value:
                canvas.figure((RIGHT + shift, y + 42), value, size=54, fill=row.get("colour") or "ink", alpha=progress, anchor="rm")

            entry, exit_price = row.get("entry"), row.get("exit")
            if canvas.theme.paths and entry and exit_price:
                width = 170
                canvas.trade_path((RIGHT - value_w - width - 44, y + 8, RIGHT - value_w - 44, y + 76),
                                  entry=float(entry), exit_price=float(exit_price),
                                  stop=float(row["stop"]) if row.get("stop") else None,
                                  fill=row.get("colour") or "ink", alpha=progress, progress=progress)

            sub = str(row.get("sub") or "")
            tag = str(row.get("badge") or "")
            tag_w = (canvas.measure(tag, size=25, role="strong")[0] + 28) if tag else 0
            if sub:
                canvas.text((MARGIN - shift, y + 98), canvas.fit(sub, room - tag_w - 40, size=30), size=30, fill="muted", alpha=progress, anchor="lm")
            if tag:
                canvas.tag((RIGHT - tag_w + shift, y + 78), tag, fill=row.get("badge_colour") or "warn", alpha=progress * 0.9)
            canvas.rule(y + pitch - 22, progress=progress, alpha=0.9)

        if self.note:
            canvas.text((MARGIN, top + count * pitch + 16), self.note, size=32, fill="muted", alpha=appear(local, 0.4 + count * self.stagger, 0.5))


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
        top = max(SAFE_TOP + 250, CENTRE_Y + 40 - (count * block) // 2)
        centre = (MARGIN + RIGHT) // 2
        half = (RIGHT - MARGIN) // 2

        if self.signed and count:
            zero = appear(local, 0.3, 0.4)
            if zero > 0.01:
                bottom = top + (count - 1) * block + 132
                canvas.draw.rectangle((centre - 1, top + 54, centre + 1, top + 54 + (bottom - top - 54) * zero),
                                      fill=canvas.colour("hairline", zero))

        for index, item in enumerate(self.items[:4]):
            progress = appear(local, 0.42 + index * 0.26, 0.55)
            if progress <= 0.01:
                continue
            y = top + index * block
            value = float(item.get("value") or 0.0)
            colour = item.get("colour") or ("up" if value > 0 else "down" if value < 0 else "ink2")
            canvas.text((MARGIN, y), str(item.get("label") or ""), size=42, role="strong", alpha=progress)
            canvas.figure((RIGHT, y + 22), str(item.get("text") or percent(value)), size=48, fill=colour, anchor="rm", alpha=progress)
            reach = (abs(value) / scale) * (half - 12) * progress
            if self.signed:
                box = (centre - reach, y + 76, centre - 2, y + 112) if value < 0 else (centre + 2, y + 76, centre + reach, y + 112)
            else:
                box = (MARGIN, y + 76, MARGIN + (abs(value) / scale) * (RIGHT - MARGIN) * progress, y + 112)
            canvas.bar(box, fill=colour, alpha=progress)
            if item.get("sub"):
                canvas.text((MARGIN, y + 126), str(item["sub"]), size=29, fill="muted", alpha=progress)

        if self.note:
            canvas.text((MARGIN, top + count * block + 6), self.note, size=32, fill="muted", alpha=appear(local, 0.42 + count * 0.26, 0.5))


@dataclass
class Statement(Scene):
    """The turn of the video: one idea, and where the theme allows, a page flip.

    Inverting the ground for a single shot is the one structural flourish the
    design spends. A hard cut to a full accent frame in the middle of a feed
    reads as a beat rather than as decoration.
    """

    eyebrow: str = ""
    lines: tuple[str, ...] = ()
    highlight: str = ""
    highlight_colour: str | Sequence[int] = "accent"
    stamp: str = ""
    caption: str = ""
    seconds: float = 4.6

    def draw(self, canvas: Canvas, local: float) -> None:
        flipped = canvas.inverted
        if canvas.theme.eyebrows:
            canvas.label((MARGIN, SAFE_TOP), self.eyebrow, fill="ink" if flipped else "accent", alpha=appear(local, 0.0, 0.3))

        y = 470
        for index, line in enumerate(self.lines):
            canvas.text((MARGIN, y + index * 92), line, size=66, role="display", alpha=appear(local, 0.12 + index * 0.2, 0.45))

        after = y + len(self.lines) * 92
        if self.highlight:
            alpha = appear(local, 0.12 + len(self.lines) * 0.2 + 0.18, 0.45)
            tint = "ink" if flipped else self.highlight_colour
            canvas.rule(after + 24, progress=alpha, fill=tint, weight=4)
            canvas.hero((MARGIN - 8, after + 170), self.highlight, size=240, fill=tint, alpha=alpha)
            after += 300

        if self.stamp:
            progress = appear(local, 0.95, 0.42)
            if progress > 0.01:
                canvas.stamp((WIDTH - 270, 690), self.stamp, fill="ink" if flipped else "warn",
                             alpha=min(1.0, progress * 1.2), scale=1.0 + (1 - progress) * 0.45)

        if self.caption:
            canvas.text((MARGIN, max(after + 40, 1180)), self.caption, size=36,
                        fill="ink" if flipped else "ink2", alpha=appear(local, 1.05, 0.5), spacing=16)


@dataclass
class Outro(Scene):
    """Where to go next, and the line that has to be on every one of these."""

    headline: tuple[str, ...] = ()
    url: str = "agenttrust.kr"
    call: str = ""
    telegram: str = ""
    telegram_line: str = "매일 아침 선별 결과와 청산 알림을 텔레그램으로 먼저"
    disclaimer: str = "AI 실험 기록이며 매매 권유가 아닙니다. 모의 계좌 기록이고 실계좌 주문은 없습니다."
    seconds: float = 5.4

    def draw(self, canvas: Canvas, local: float) -> None:
        for index, line in enumerate(self.headline):
            canvas.text((MARGIN, 420 + index * 92), line, size=64, role="display", alpha=appear(local, 0.05 + index * 0.18, 0.45))

        alpha = appear(local, 0.42, 0.5)
        canvas.rule(700, progress=alpha, fill="accent", weight=4)
        if self.call:
            canvas.text((MARGIN, 744), self.call, size=36, fill="ink2", alpha=alpha)
        canvas.text((MARGIN - 2, 800), self.url, size=70, role="display", fill="accent", alpha=appear(local, 0.55, 0.5))

        if self.telegram:
            block = appear(local, 0.95, 0.5)
            canvas.rule(984, progress=block, alpha=0.9)
            canvas.label((MARGIN, 1024), "텔레그램", fill="ink2", alpha=block, size=26)
            canvas.text((MARGIN, 1086), self.telegram_line, size=34, alpha=block, spacing=14)
            canvas.text((MARGIN - 2, 1148), self.telegram, size=52, role="heading", fill="accent", alpha=appear(local, 1.15, 0.5))

        canvas.text((MARGIN, 1424), self.disclaimer, size=27, fill="muted", alpha=appear(local, 1.3, 0.6))


__all__ = ["Bars", "CENTRE_Y", "Hook", "Outro", "Rows", "Scene", "Statement"]

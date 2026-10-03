"""Five more ways to lay a short out, drawn from the storyboard itself.

Every story already had its own template, and every template had the same
shape: a kicker, a hero figure at the left, a ruled list, the same outro. On
10-03 the channel owner asked for the current form to stay as one template and
for at least five genuinely different layouts beside it.

These read only the storyboard (Hook, Rows, Bars, Statement, Outro), so one
layout serves every story whose scenes carry their own words. A story whose
picture lives in its template rather than its scenes (debate leaves its
Statements empty and draws the argument from the payload) is not laid out
here; it keeps its own template, which is the "base" layout.

Text flows (flex columns, keep-all wrapping, clamped lines) rather than
sitting at fixed pixels, so a long name wraps instead of colliding. The
shared motion layer in hyperframes.py still applies: headlines are ``.head``
and the hero figure is ``s0-fig``.
"""

from __future__ import annotations

import html as _html
import re
from datetime import date
from typing import Any, Callable, Mapping, Sequence

from .scenes import Bars, Hook, Outro, Rows, Statement
from .stories import Storyboard

LAYOUTS = ("center", "news", "field", "terminal", "cards")
ROTATION = ("base",) + LAYOUTS

GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"

FONTS = """
      @font-face { font-family: "Noto Sans KR"; font-weight: 300; src: local("Noto Sans KR Light"), local("Noto Sans KR"); }
      @font-face { font-family: "Noto Sans KR"; font-weight: 500; src: local("Noto Sans KR Medium"), local("Noto Sans KR"); }
      @font-face { font-family: "Noto Sans KR"; font-weight: 700; src: local("Noto Sans KR Bold"), local("Noto Sans KR"); }
      @font-face { font-family: "Noto Sans KR"; font-weight: 900; src: local("Noto Sans KR Black"), local("Noto Sans KR"); }
"""

# what the storyboard calls a colour, per layout palette
TONES = ("up", "down", "accent", "ink", "ink2", "muted", "reward", "risk", "took", "passed", "warn", "keep", "drop")


def weekday_index(day: date) -> int:
    """How many weekdays have passed up to ``day``; a weekend shares the next Monday's.

    Shorts go out on weekdays only. Counting calendar days put a six-way
    rotation out of step with a five-day week, so some layouts landed on
    Saturdays for weeks at a time.
    """

    weeks, weekday = divmod(day.toordinal() - 1, 7)          # ordinal 1 is a Monday
    return weeks * 5 + min(weekday, 5)


def layout_for(day: date | None = None, *, override: str | None = None) -> str:
    """The layout for a day: an override if given, else one per publishing day in turn, base included."""

    if override:
        return override.strip().lower()
    return ROTATION[weekday_index(day or date.today()) % len(ROTATION)]


def can_lay_out(board: Storyboard) -> bool:
    """True when every scene carries the words a layout needs to draw it."""

    if not board.scenes or not isinstance(board.scenes[-1], Outro):
        return False
    for scene in board.scenes:
        if isinstance(scene, Hook) and not (_hook_value(scene) or scene.caption):
            return False
        if isinstance(scene, Statement) and not ([line for line in scene.lines if line.strip()] or scene.highlight):
            return False
        if isinstance(scene, Rows) and not (scene.rows or scene.value):
            return False
        if isinstance(scene, Bars) and not scene.items:
            return False
        if not isinstance(scene, (Hook, Statement, Rows, Bars, Outro)):
            return False
    return True


# ------------------------------------------------------------------ markup
def _e(text: Any) -> str:
    return _html.escape(str(text or ""), quote=True)


def _tone(value: Any) -> str:
    name = str(value or "ink")
    return name if name in TONES else "ink"


def _hook_value(scene: Hook) -> str:
    if scene.value:
        return scene.value
    if scene.value_to is not None:
        return f"{float(scene.value_to) * 100:+.{scene.value_digits}f}%"
    return ""


_UNIT = re.compile(r"^([+\-−]?[\d.,]+)\s*(%p|%|[가-힣A-Za-z]+)?$")


def _figure(text: str, *, box: int, cap: int) -> str:
    """A hero figure, number large and unit small, sized to stay inside ``box`` pixels."""

    from .hyperframes import hero

    match = _UNIT.match(text.strip())
    if match:
        markup, size = hero(match.group(1), match.group(2) or "", cap=cap, box=box)
    else:
        markup, size = _e(text), min(cap, int(box / max(len(text) * 0.95, 1)))
    return f'<span class="fig-in" style="font-size:{size}px">{markup}</span>'


def _hook(index: int, scene: Hook) -> str:
    value = _hook_value(scene)
    lines = "".join(f'<p class="head enter">{_e(line)}</p>' for line in scene.lines if line)
    figure = (f'<div class="fig enter tone-{_tone(scene.value_colour)}" id="s{index}-fig">'
              f'{_figure(value, box=880, cap=300)}</div>') if value else ""
    return (f'<p class="eyebrow enter">{_e(scene.eyebrow)}</p>{figure}'
            f'<p class="cap enter">{_e(scene.caption)}</p><div class="lines">{lines}</div>')


def _rows(index: int, scene: Rows) -> str:
    rows = []
    for row in list(scene.rows)[:6]:
        badge = f'<span class="badge">{_e(row.get("badge"))}</span>' if row.get("badge") else ""
        sub = f'<span class="sub">{_e(row.get("sub"))}</span>' if row.get("sub") else ""
        rows.append(
            f'<div class="row enter"><div class="lbl"><span class="name">{_e(row.get("label"))}</span>{sub}</div>'
            f'<div class="val tone-{_tone(row.get("colour"))}">{_e(row.get("value"))}{badge}</div></div>'
        )
    count = (f'<div class="count enter"><span class="count-v">{_e(scene.value)}</span>'
             f'<span class="count-c">{_e(scene.caption)}</span></div>') if scene.value else ""
    note = f'<p class="note enter">{_e(scene.note)}</p>' if scene.note else ""
    return (f'<p class="eyebrow enter">{_e(scene.eyebrow)}</p><p class="head enter">{_e(scene.heading)}</p>'
            f'{count}<div class="rows">{"".join(rows)}</div>{note}')


def _bars(index: int, scene: Bars) -> str:
    items = list(scene.items)[:4]
    scale = max((abs(float(item.get("value") or 0.0)) for item in items), default=0.0) or 1.0
    bars = []
    for item in items:
        value = float(item.get("value") or 0.0)
        tone = _tone(item.get("colour") or ("up" if value > 0 else "down" if value < 0 else "ink2"))
        width = max(abs(value) / scale * 100, 3)
        text = item.get("text") or f"{value * 100:+.2f}%"
        sub = f'<span class="sub">{_e(item.get("sub"))}</span>' if item.get("sub") else ""
        bars.append(
            f'<div class="bar enter"><div class="bar-top"><span class="name">{_e(item.get("label"))}</span>'
            f'<span class="val tone-{tone}">{_e(text)}</span></div>'
            f'<div class="track"><div class="fill tone-bg-{tone}" style="width:{width:.1f}%"></div></div>{sub}</div>'
        )
    note = f'<p class="note enter">{_e(scene.note)}</p>' if scene.note else ""
    return (f'<p class="eyebrow enter">{_e(scene.eyebrow)}</p><p class="head enter">{_e(scene.heading)}</p>'
            f'<div class="bars">{"".join(bars)}</div>{note}')


def _statement(index: int, scene: Statement) -> str:
    lines = "".join(f'<p class="say enter">{_e(line)}</p>' for line in scene.lines if line.strip())
    highlight = (f'<div class="hl enter tone-{_tone(scene.highlight_colour)}" id="s{index}-fig">'
                 f'{_figure(scene.highlight, box=880, cap=240)}</div>') if scene.highlight else ""
    stamp = f'<span class="stamp enter">{_e(scene.stamp)}</span>' if scene.stamp else ""
    caption = "".join(f'<p class="cap enter">{_e(part)}</p>' for part in (scene.caption or "").split("\n") if part)
    return (f'<p class="eyebrow enter">{_e(scene.eyebrow)}</p><div class="says">{lines}</div>'
            f'{highlight}{stamp}{caption}')


def _outro(index: int, scene: Outro) -> str:
    head = "".join(f'<p class="head enter">{_e(line)}</p>' for line in scene.headline if line)
    return (f'<div class="ohead">{head}</div><p class="call enter">{_e(scene.call)}</p>'
            f'<p class="url enter">{_e(scene.url)}</p>'
            f'<div class="tg enter"><p class="tg-line">{_e(scene.telegram_line)}</p><p class="tg-url">{_e(scene.telegram)}</p></div>'
            f'<p class="fine enter">{_e(scene.disclaimer)}</p>')


MARKUP: Mapping[type, Callable[[int, Any], str]] = {
    Hook: _hook, Rows: _rows, Bars: _bars, Statement: _statement, Outro: _outro,
}


# ------------------------------------------------------------------ layouts
#: Shared bones: every layout lays each scene out as a padded flex column.
BASE_CSS = """
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1080px; height: 1920px; overflow: hidden; background: var(--ground); }
      #root { width: 1080px; height: 1920px; position: relative; overflow: hidden; color: var(--ink);
              font-family: "Noto Sans KR", sans-serif; font-variant-numeric: tabular-nums; background: var(--ground); }
      .clip { position: absolute; inset: 0; z-index: 10; }
      .scene { position: absolute; left: 96px; right: 96px; top: 260px; bottom: 420px;
               display: flex; flex-direction: column; justify-content: center; gap: 26px; }
      .eyebrow { font-weight: 500; font-size: 32px; color: var(--muted); }
      .head { font-weight: 900; font-size: 64px; line-height: 1.18; letter-spacing: -0.04em; word-break: keep-all; }
      .cap, .note { font-weight: 300; font-size: 34px; line-height: 1.5; color: var(--ink2); word-break: keep-all; }
      .note { font-size: 29px; }
      .fig, .hl { font-weight: 900; letter-spacing: -0.055em; line-height: 1.05; white-space: nowrap; }
      /* Noto Sans KR spans ~1.45em top to bottom; a tighter line box let the
         figure overlap the line above it (content_overlap) */
      .fig-in { display: block; line-height: 1.45; }
      .unit { font-size: 0.38em; font-weight: 700; letter-spacing: -0.02em; }
      .rows, .bars, .lines, .says, .ohead { display: flex; flex-direction: column; }
      .rows { gap: 18px; } .bars { gap: 34px; }
      .row { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
      .lbl { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
      /* no line clamp: a clamped box cut 4px off every Korean glyph (clipped_text) */
      .name { font-weight: 700; font-size: 40px; line-height: 1.35; word-break: keep-all; }
      .sub { font-weight: 300; font-size: 27px; color: var(--muted); line-height: 1.4; word-break: keep-all; }
      .val { font-weight: 900; font-size: 50px; letter-spacing: -0.03em; white-space: nowrap; display: flex; align-items: center; gap: 12px; }
      .badge { font-weight: 700; font-size: 24px; padding: 4px 12px; border-radius: 8px; background: var(--warn); color: var(--ground); }
      .count { display: flex; align-items: baseline; gap: 22px; }
      .count-v { font-weight: 900; font-size: 150px; letter-spacing: -0.05em; line-height: 1; }
      .count-c { font-weight: 500; font-size: 34px; color: var(--ink2); }
      .bar-top { display: flex; justify-content: space-between; align-items: baseline; gap: 20px; }
      .track { height: 22px; border-radius: 11px; background: var(--hair); margin-top: 12px; overflow: hidden; }
      .fill { height: 100%; border-radius: 11px; transform-origin: left center; }
      .say { font-weight: 900; font-size: 70px; line-height: 1.2; letter-spacing: -0.04em; word-break: keep-all; }
      .stamp { align-self: flex-start; font-weight: 900; font-size: 34px; padding: 8px 22px; border: 4px solid var(--accent);
               color: var(--accent); border-radius: 10px; transform: rotate(-4deg); }
      .call { font-weight: 500; font-size: 34px; color: var(--ink2); }
      .url { font-weight: 900; font-size: 80px; letter-spacing: -0.04em; color: var(--accent); }
      .tg-line { font-weight: 300; font-size: 28px; color: var(--ink2); }
      .tg-url { font-weight: 900; font-size: 50px; letter-spacing: -0.03em; }
      .fine { font-weight: 300; font-size: 25px; color: var(--muted); line-height: 1.5; }
      .mark { position: absolute; right: 96px; bottom: 360px; font-size: 26px; color: var(--muted); z-index: 12; }
""" + "".join(f"      .tone-{t} {{ color: var(--{t}); }} .tone-bg-{t} {{ background: var(--{t}); }}\n" for t in TONES)


def _palette(ground: str, ink: str, ink2: str, muted: str, hair: str, accent: str,
             up: str, down: str, warn: str) -> str:
    return (f"      :root {{ --ground: {ground}; --ink: {ink}; --ink2: {ink2}; --muted: {muted}; --hair: {hair};"
            f" --accent: {accent}; --up: {up}; --down: {down}; --warn: {warn};"
            f" --reward: {up}; --risk: {down}; --took: {accent}; --passed: {ink2}; --keep: {accent}; --drop: {muted}; }}\n")


LAYOUT_CSS = {
    # everything on the centre line, the figure as large as the frame allows
    "center": _palette("#0c1230", "#f5efe0", "#c2bfd6", "#8a88a8", "#232a52", "#f0b84b",
                       "#ff6b6b", "#6ea8ff", "#f0b84b") + """
      #root { background: radial-gradient(900px 900px at 50% 38%, #1d2760 0%, #0c1230 62%, #070a1d 100%); }
      .scene { align-items: center; text-align: center; }
      .eyebrow { letter-spacing: 0.12em; color: var(--accent); }
      .head { font-size: 70px; }
      .lines, .says, .ohead { align-items: center; }
      .rows { width: 100%; } .row { padding: 18px 28px; border-radius: 18px; background: rgba(255,255,255,0.05); text-align: left; }
      .bars { width: 100%; text-align: left; }
      .count { justify-content: center; }
      .stamp { align-self: center; }
""",
    # a news desk: a red strip with the eyebrow, lower thirds for every row
    "news": _palette("#0b0b0d", "#ffffff", "#d6d6db", "#9a9aa3", "#2a2a30", "#e32b22",
                     "#ff4d43", "#4f9bff", "#ffcc00") + """
      .clip::before { content: ""; position: absolute; left: 0; right: 0; top: 196px; height: 92px; background: var(--accent); }
      .eyebrow { position: absolute; top: -134px; left: -96px; right: -96px; height: 92px; padding: 0 96px;
                 display: flex; align-items: center; color: #fff; font-weight: 900; font-size: 38px; letter-spacing: -0.01em; }
      .eyebrow::before { content: "LIVE"; font-size: 24px; padding: 4px 12px; margin-right: 20px; border: 3px solid #fff; border-radius: 6px; }
      .scene { justify-content: flex-start; top: 330px; }
      .head { font-size: 66px; padding-left: 26px; border-left: 12px solid var(--accent); }
      .row { background: #fff; color: #0b0b0d; padding: 18px 24px; border-radius: 4px; }
      .row .sub { color: #55555f; }
      .row .val { background: var(--accent); color: #fff; padding: 6px 16px; border-radius: 4px; font-size: 44px; }
      .fig { border-bottom: 10px solid var(--accent); padding-bottom: 18px; align-self: flex-start; }
      .url { color: #fff; background: var(--accent); align-self: flex-start; padding: 4px 22px; }
""",
    # a colour field: every scene on its own flat pastel ground, dark type. A
    # fixed coloured block over the top half was tried first and failed check
    # on contrast wherever a heading ran long enough to cross its edge.
    "field": _palette("#f6d365", "#10151c", "#232c38", "#3a4552", "rgba(16,21,28,0.16)", "#10151c",
                      "#a3121a", "#123c9c", "#7a3d00") + """
      #root, .clip { background: var(--block, #f6d365); }
      .scene { justify-content: center; }
      .eyebrow { font-weight: 900; font-size: 30px; letter-spacing: 0.08em; }
      .head { font-size: 72px; }
      .row { border-top: 4px solid var(--ink); padding-top: 14px; }
      .fig, .hl { font-size: inherit; }
      .url { color: var(--ink); text-decoration: underline; text-decoration-thickness: 8px; text-underline-offset: 12px; }
      .badge { background: var(--ink); color: #ffffff; }
""",
    # a terminal: monospace figures, rows as receipt lines with dotted leaders
    "terminal": _palette("#050a06", "#c8f7d2", "#8fd6a0", "#4f8a5e", "#163a20", "#5cf28a",
                         "#ff7a6e", "#7ab8ff", "#f2d35c") + """
      #root { font-family: "Consolas", "Noto Sans KR", monospace; }
      #root::after { content: ""; position: absolute; inset: 0; z-index: 70; pointer-events: none;
                     background: repeating-linear-gradient(0deg, rgba(0,0,0,0.18) 0 2px, transparent 2px 5px); }
      .scene { justify-content: flex-start; top: 230px; }
      .eyebrow { color: var(--accent); font-family: "Consolas", monospace; }
      .eyebrow::before { content: "$ "; }
      .head { font-weight: 700; font-size: 58px; letter-spacing: -0.02em; }
      .head::before { content: "> "; color: var(--accent); }
      .row { border-bottom: 3px dotted var(--hair); padding-bottom: 14px; }
      .name { font-weight: 500; }
      .fig::after, .hl::after { content: "_"; color: var(--accent); }
      .url { color: var(--accent); }
""",
    # paper and cards: the one light layout
    "cards": _palette("#f1ece2", "#16181d", "#3d414b", "#6b6559", "#ddd5c6", "#c43a1c",
                      "#e5392f", "#2f6fe0", "#ff9f1a") + """
      .scene { justify-content: center; }
      .row, .bar, .fig, .hl, .count { background: #ffffff; border-radius: 26px; padding: 26px 30px;
             box-shadow: 0 18px 40px rgba(40, 30, 10, 0.12); }
      .fig, .hl { align-self: flex-start; padding: 30px 40px 36px; }
      .row:nth-child(odd) { transform: rotate(-0.8deg); } .row:nth-child(even) { transform: rotate(0.8deg); }
      .stamp { background: var(--accent); color: #fff; border: none; }
      .url { color: var(--accent); }
      .eyebrow { font-weight: 700; color: var(--accent); }
""",
}

#: how the pieces of a scene arrive, per layout
ENTER = {
    "center": "{ from: { opacity: 0, scale: 0.86 }, to: { opacity: 1, scale: 1, duration: 0.55, ease: 'back.out(1.6)' }, gap: 0.12 }",
    "news": "{ from: { opacity: 0, x: -1080 }, to: { opacity: 1, x: 0, duration: 0.45, ease: 'power3.out' }, gap: 0.14 }",
    "field": "{ from: { opacity: 0, y: 60 }, to: { opacity: 1, y: 0, duration: 0.5, ease: 'power3.out' }, gap: 0.1 }",
    "terminal": "{ from: { opacity: 0 }, to: { opacity: 1, duration: 0.05, ease: 'none' }, gap: 0.16, type: true }",
    "cards": "{ from: { opacity: 0, y: 520, rotation: 6 }, to: { opacity: 1, y: 0, rotation: 0, duration: 0.7, ease: 'expo.out' }, gap: 0.16 }",
}

BLOCKS = ("#f6d365", "#9be3d8", "#ffc4b0", "#cdbfff", "#b9e48a")

SCRIPT = """
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
      (function () {
        var ENTER = __ENTER__;
        var LAYOUT = "__LAYOUT__";
        var clips = document.querySelectorAll("#root > .clip");
        Array.prototype.forEach.call(clips, function (clip) {
          var start = parseFloat(clip.getAttribute("data-start")) || 0;
          var parts = clip.querySelectorAll(".enter");
          Array.prototype.forEach.call(parts, function (part, i) {
            var at = start + 0.15 + i * ENTER.gap;
            if (ENTER.type && part.children.length === 0 && part.textContent.length < 60) {
              // typed: each character lands in turn
              var text = part.textContent;
              part.textContent = "";
              var chars = [];
              for (var c = 0; c < text.length; c++) {
                var s = document.createElement("span");
                s.textContent = text.charAt(c);
                part.appendChild(s);
                chars.push(s);
              }
              tl.fromTo(chars, { opacity: 0 }, { opacity: 1, duration: 0.01, ease: "none", stagger: 0.025 }, at);
              return;
            }
            tl.fromTo(part, ENTER.from, Object.assign({}, ENTER.to), at);
          });
          Array.prototype.forEach.call(clip.querySelectorAll(".fill"), function (fill) {
            tl.fromTo(fill, { scaleX: 0 }, { scaleX: 1, duration: 0.8, ease: "power2.out" }, start + 0.5);
          });
        });
      })();
      window.__timelines["main"] = tl;
"""


def compose_layout(name: str, board: Storyboard) -> tuple[str, float]:
    """The storyboard laid out in ``name``. Returns the composition HTML and its length."""

    if name not in LAYOUTS:
        raise ValueError(f"unknown layout {name!r}; known: {', '.join(LAYOUTS)}")
    clips, running = [], 0.0
    for index, scene in enumerate(board.scenes):
        markup = MARKUP[type(scene)](index, scene)
        block = f' style="--block:{BLOCKS[index % len(BLOCKS)]}"' if name == "field" else ""
        clips.append(
            f'      <div class="clip" id="s{index}" data-start="{running:.2f}" data-duration="{scene.seconds:.2f}"'
            f' data-track-index="0"{block}>\n        <div class="scene">{markup}</div>\n      </div>'
        )
        running += scene.seconds
    from .stories import site_url

    host = _e(site_url().split("://", 1)[-1])
    script = SCRIPT.replace("__ENTER__", ENTER[name]).replace("__LAYOUT__", name)
    page = f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="{GSAP}"></script>
    <style>{FONTS}{BASE_CSS}{LAYOUT_CSS[name]}    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{running:.2f}"
         data-width="1080" data-height="1920" data-layout="{name}">
{chr(10).join(clips)}
      <p class="mark">{host}</p>
    </div>
    <script>{script}    </script>
  </body>
</html>
"""
    return page, running


__all__ = ["LAYOUTS", "ROTATION", "can_lay_out", "compose_layout", "layout_for", "weekday_index"]

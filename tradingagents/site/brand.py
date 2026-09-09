"""Brand mark, favicon, and app icons for TradingAgents Korea.

The mark is a rounded teal square with a rising white trend line and a small
node at the end (the same glyph the header uses). SVG is the source of truth;
PNG/ICO sizes are rasterised with Pillow on demand and memoised.
"""

from __future__ import annotations

import io
from functools import lru_cache

BRAND_TEAL = (15, 118, 110)
BRAND_TEAL_DEEP = (19, 78, 74)
BRAND_INK = (15, 23, 42)

# Trend line inside a 64x64 box (ends with a node), tuned to read at 16px.
_TREND_POINTS = ((12, 44), (24, 32), (32, 38), (52, 18))


def logo_svg(size: int = 28, *, title: str = "TradingAgents Korea") -> str:
    """Inline SVG mark for the header (currentColor-free, gradient fill)."""

    points = " ".join(f"{x},{y}" for x, y in _TREND_POINTS)
    end_x, end_y = _TREND_POINTS[-1]
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 64 64" role="img" aria-label="{title}">'
        '<defs><linearGradient id="ta-mark" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f766e"/><stop offset="1" stop-color="#134e4a"/></linearGradient></defs>'
        '<rect width="64" height="64" rx="16" fill="url(#ta-mark)"/>'
        f'<polyline points="{points}" fill="none" stroke="#ffffff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{end_x}" cy="{end_y}" r="6" fill="#ffffff"/>'
        f'<polyline points="{end_x - 12},{end_y} {end_x},{end_y} {end_x},{end_y + 12}" fill="none" stroke="#0f766e" stroke-width="0" />'
        "</svg>"
    )


def favicon_svg() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>' + logo_svg(64, title="TradingAgents Korea 아이콘")


@lru_cache(maxsize=16)
def icon_png(size: int) -> bytes:
    """Rasterised app icon (PNG) at ``size`` px, supersampled for crisp edges."""

    from PIL import Image, ImageDraw

    scale = 4
    canvas = size * scale
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # vertical gradient between the two teals
    gradient = Image.new("RGBA", (canvas, canvas), BRAND_TEAL + (255,))
    grad_draw = ImageDraw.Draw(gradient)
    for y in range(canvas):
        t = y / max(1, canvas - 1)
        color = tuple(int(BRAND_TEAL[i] + (BRAND_TEAL_DEEP[i] - BRAND_TEAL[i]) * t) for i in range(3)) + (255,)
        grad_draw.line([(0, y), (canvas, y)], fill=color)
    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=int(canvas * 0.25), fill=255)
    img.paste(gradient, (0, 0), mask)
    unit = canvas / 64
    pts = [(x * unit, y * unit) for x, y in _TREND_POINTS]
    draw = ImageDraw.Draw(img)
    draw.line(pts, fill=(255, 255, 255, 255), width=max(2, int(7 * unit)), joint="curve")
    for x, y in pts:  # round caps
        r = 3.5 * unit
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 255))
    ex, ey = pts[-1]
    r = 6 * unit
    draw.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(255, 255, 255, 255))
    img = img.resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


@lru_cache(maxsize=1)
def favicon_ico() -> bytes:
    from PIL import Image

    frames = []
    for size in (16, 32, 48):
        frames.append(Image.open(io.BytesIO(icon_png(size))).convert("RGBA"))
    out = io.BytesIO()
    frames[0].save(out, format="ICO", sizes=[(f.width, f.height) for f in frames], append_images=frames[1:])
    return out.getvalue()


def web_manifest(*, site_base_url: str | None = None) -> dict:
    return {
        "name": "TradingAgents Korea",
        "short_name": "TradingAgents",
        "description": "코스피200·코스닥150 종목 선별과 AI 토론, 모의투자 검증",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f3f5f9",
        "theme_color": "#0f766e",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }


ICON_HEAD_LINKS = (
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
    '<link rel="icon" href="/favicon.ico" sizes="32x32">'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
    '<link rel="manifest" href="/site.webmanifest">'
    '<meta name="theme-color" content="#0f766e">'
)

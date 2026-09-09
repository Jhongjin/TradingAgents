"""Shared design system for the public site (v3 "slate" system).

One font (Pretendard), one accent, semantic colors for stages, IDE-style
selectable themes, and a component vocabulary (card, badge, tile, table, tabs,
bar, switch). Pages call :func:`render_shell` for the common header/footer and
compose bodies from the CSS classes below. Charts are tiny inline SVGs from
:func:`sparkline_svg`.
"""

from __future__ import annotations

import html
import json
import random
from typing import Any, Iterable, Mapping, Sequence

from .seo import canonical_url

FONT_STYLESHEET = "https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard-dynamic-subset.min.css"

# Theme ids follow IDE conventions; "light"/"dark" are the OS defaults.
THEMES: tuple[str, ...] = ("light", "dark", "paper", "nord", "solar")
THEME_LABELS: dict[str, str] = {"light": "슬레이트 라이트", "dark": "슬레이트 다크", "paper": "페이퍼", "nord": "노르드", "solar": "솔라라이즈드"}
DEFAULT_THEME = "light"

_TOKEN_KEYS = ("bg", "bg2", "panel", "ink", "ink2", "muted", "line", "line-strong", "accent", "accent-ink", "accent-soft", "blue", "blue-soft", "violet", "violet-soft", "amber", "amber-soft", "orange", "orange-soft", "navy", "navy-soft", "gain", "gain-soft", "loss", "loss-soft", "on-accent", "shadow", "glow-a", "glow-b")

THEME_TOKENS: dict[str, dict[str, str]] = {
    "light": dict(zip(_TOKEN_KEYS, ("#f3f5f9", "#e9edf3", "#ffffff", "#0f172a", "#475569", "#64748b", "#e2e7ee", "#c9d2dd", "#0f766e", "#115e59", "#ccfbf1", "#2563eb", "#dbeafe", "#7c3aed", "#ede9fe", "#b45309", "#fef3c7", "#c2410c", "#ffedd5", "#1e3a8a", "#e0e7ff", "#dc2626", "#fee2e2", "#2563eb", "#dbeafe", "#ffffff", "0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.08)", "rgba(15,118,110,.14)", "rgba(124,58,237,.10)"))),
    "dark": dict(zip(_TOKEN_KEYS, ("#0b0f16", "#10161f", "#151c26", "#eef2f7", "#b4bfcd", "#8593a5", "#222b38", "#334155", "#2dd4bf", "#5eead4", "#113b36", "#93c5fd", "#1e2b47", "#c4b5fd", "#2a2447", "#fcd34d", "#3a2c10", "#fdba74", "#3b2214", "#a5b4fc", "#1f2547", "#f87171", "#3b1a1a", "#60a5fa", "#172a4a", "#0b0f16", "0 1px 2px rgba(0,0,0,.4)", "rgba(45,212,191,.16)", "rgba(196,181,253,.12)"))),
    "paper": dict(zip(_TOKEN_KEYS, ("#f6f2ea", "#ece6da", "#fffdf8", "#2a2419", "#5b5245", "#7d7364", "#e4dccd", "#cfc4b0", "#8a5a1e", "#6f4716", "#f2e4c8", "#2b5fb3", "#dfe8f7", "#6b46c1", "#e9e1f7", "#a05a12", "#f7e6c6", "#b8471a", "#f8e2d2", "#2d3f7a", "#e2e6f4", "#c0392b", "#f7dcd8", "#2b5fb3", "#dfe8f7", "#fffdf8", "0 1px 2px rgba(60,40,10,.07), 0 1px 3px rgba(60,40,10,.08)", "rgba(138,90,30,.14)", "rgba(107,70,193,.08)"))),
    "nord": dict(zip(_TOKEN_KEYS, ("#2e3440", "#3b4252", "#353c4a", "#eceff4", "#d8dee9", "#a3adc2", "#434c5e", "#4c566a", "#88c0d0", "#8fbcbb", "#2f4a55", "#81a1c1", "#2f3f55", "#b48ead", "#43384a", "#ebcb8b", "#4a4030", "#d08770", "#4a3a33", "#5e81ac", "#33405a", "#bf616a", "#4a3238", "#5e81ac", "#33405a", "#2e3440", "0 1px 2px rgba(0,0,0,.35)", "rgba(136,192,208,.18)", "rgba(180,142,173,.14)"))),
    "solar": dict(zip(_TOKEN_KEYS, ("#fdf6e3", "#eee8d5", "#fffbf0", "#073642", "#586e75", "#839496", "#e6dfc8", "#d3ccb4", "#2aa198", "#1f7f78", "#d8efe6", "#268bd2", "#dbe9f5", "#6c71c4", "#e4e4f4", "#b58900", "#f6ebc4", "#cb4b16", "#f7dfd0", "#268bd2", "#dbe9f5", "#dc322f", "#f6d9d6", "#268bd2", "#dbe9f5", "#fdf6e3", "0 1px 2px rgba(60,50,20,.08)", "rgba(42,161,152,.16)", "rgba(108,113,196,.10)"))),
}


def _tokens_block(theme: str) -> str:
    return " ".join(f"--{key}: {value};" for key, value in THEME_TOKENS[theme].items())


def theme_css() -> str:
    """Token declarations: light on bare :root, dark by OS preference, explicit themes win."""

    parts = [f":root {{ {_tokens_block('light')} color-scheme: light; }}"]
    parts.append(f"@media (prefers-color-scheme: dark) {{ :root:not([data-theme]) {{ {_tokens_block('dark')} color-scheme: dark; }} }}")
    for theme in THEMES:
        scheme = "dark" if theme in {"dark", "nord"} else "light"
        parts.append(f":root[data-theme=\"{theme}\"] {{ {_tokens_block(theme)} color-scheme: {scheme}; }}")
    return "\n".join(parts)


DS_COMPONENT_CSS = """
.ds, .ds body { margin: 0; }
.ds { font-family: "Pretendard Variable", Pretendard, "Apple SD Gothic Neo", "Malgun Gothic", "Segoe UI", sans-serif; font-size: 14px; line-height: 1.55; color: var(--ink); background: var(--bg); -webkit-font-smoothing: antialiased; min-height: 100vh; display: flex; flex-direction: column; }
.ds *, .ds *::before, .ds *::after { box-sizing: border-box; }
.ds h1, .ds h2, .ds h3 { margin: 0; font-weight: 700; line-height: 1.25; letter-spacing: -0.02em; color: var(--ink); text-wrap: balance; }
.ds h1 { font-size: 30px; } .ds h2 { font-size: 16px; } .ds h3 { font-size: 14px; }
.ds p { margin: 0; }
.ds a { color: inherit; text-decoration: none; }
.ds a:hover { text-decoration: underline; text-underline-offset: 3px; }
.ds svg { display: block; }
.ds :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }
.ds [hidden] { display: none !important; }
.ds .skip-link { position: absolute; left: -9999px; top: 8px; background: var(--panel); color: var(--ink); padding: 8px 12px; border-radius: 8px; z-index: 100; }
.ds .skip-link:focus { left: 8px; }
.ds .num { font-variant-numeric: tabular-nums; }
.ds .up { color: var(--gain); } .ds .down { color: var(--loss); } .ds .flat { color: var(--muted); }
.ds .muted { color: var(--muted); } .ds .ink2 { color: var(--ink2); }
.ds .small { font-size: 13px; } .ds .tiny { font-size: 12px; }
.ds .label { font-size: 12px; font-weight: 500; color: var(--muted); }
.ds .link { color: var(--accent-ink); font-weight: 600; }
.ds .shell { width: min(1200px, 100% - 48px); margin: 0 auto; }
.ds .card { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow); }
.ds .card-h { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 18px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.ds .card-h h2 { display: flex; align-items: center; gap: 8px; }
.ds .card-b { padding: 16px 18px; }
.ds .card-f { padding: 10px 18px; background: var(--bg); border-top: 1px solid var(--line); border-radius: 0 0 14px 14px; font-size: 12px; color: var(--muted); display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.ds .soft { background: var(--bg2); border-radius: 12px; }
.ds .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 38px; padding: 0 16px; border-radius: 9px; font-size: 14px; font-weight: 600; border: 1px solid var(--line-strong); color: var(--ink); background: var(--panel); white-space: nowrap; box-shadow: var(--shadow); cursor: pointer; font-family: inherit; text-decoration: none; }
.ds .btn:hover { text-decoration: none; border-color: var(--accent); }
.ds .btn.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.ds .btn.primary:hover { filter: brightness(1.05); }
.ds .btn.ghost { background: transparent; border-color: transparent; box-shadow: none; color: var(--ink2); }
.ds .btn.sm { height: 32px; padding: 0 12px; font-size: 13px; }
.ds .btn:disabled, .ds .btn[aria-disabled="true"] { opacity: .55; cursor: not-allowed; }
.ds .badge { display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 9px; border-radius: 999px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.ds .badge.xs { height: 18px; font-size: 11px; padding: 0 6px; }
.ds .b-teal { background: var(--accent-soft); color: var(--accent-ink); } .ds .b-blue { background: var(--blue-soft); color: var(--blue); } .ds .b-violet { background: var(--violet-soft); color: var(--violet); } .ds .b-amber { background: var(--amber-soft); color: var(--amber); } .ds .b-orange { background: var(--orange-soft); color: var(--orange); } .ds .b-navy { background: var(--navy-soft); color: var(--navy); } .ds .b-grey { background: var(--bg2); color: var(--ink2); } .ds .b-gain { background: var(--gain-soft); color: var(--gain); } .ds .b-loss { background: var(--loss-soft); color: var(--loss); }
.ds .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; display: inline-block; }
.ds .ico { width: 36px; height: 36px; border-radius: 10px; display: inline-flex; align-items: center; justify-content: center; flex: none; }
.ds .ico svg { width: 18px; height: 18px; }
.ds .ico.sm { width: 28px; height: 28px; border-radius: 8px; } .ds .ico.sm svg { width: 15px; height: 15px; }
.ds .ico.grad { background: linear-gradient(135deg, #0f766e 0%, #115e59 60%, #134e4a 100%); color: #fff; }
.ds .avatar { width: 32px; height: 32px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: 12px; flex: none; }
.ds table { border-collapse: collapse; width: 100%; font-size: 14px; }
.ds th { text-align: left; font-size: 12px; font-weight: 500; color: var(--muted); padding: 10px 14px; background: var(--bg); border-bottom: 1px solid var(--line); white-space: nowrap; }
.ds td { padding: 12px 14px; border-bottom: 1px solid var(--line); vertical-align: middle; }
.ds tbody tr:last-child td { border-bottom: 0; }
.ds .r { text-align: right; }
.ds .table-wrap { overflow-x: auto; }
.ds .bar { height: 6px; background: var(--line); border-radius: 999px; overflow: hidden; }
.ds .bar i { display: block; height: 100%; border-radius: 999px; background: var(--accent); }
.ds .kv { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); font-size: 14px; }
.ds .kv:last-child { border-bottom: 0; }
.ds .row { display: flex; align-items: center; gap: 8px; } .ds .between { justify-content: space-between; } .ds .wrap { flex-wrap: wrap; }
.ds .stack { display: grid; gap: 16px; }
.ds .field { height: 42px; border: 1px solid var(--line-strong); border-radius: 9px; background: var(--panel); padding: 0 12px; display: flex; align-items: center; gap: 8px; color: var(--ink); font-size: 14px; width: 100%; font-family: inherit; }
.ds input.field, .ds select.field { appearance: none; }
.ds input.field::placeholder { color: var(--muted); }
.ds .tabs { display: flex; gap: 4px; padding: 4px; background: var(--bg2); border-radius: 10px; overflow-x: auto; }
.ds .tabs > * { padding: 7px 14px; font-size: 13px; font-weight: 500; color: var(--ink2); border-radius: 8px; display: inline-flex; gap: 6px; align-items: center; white-space: nowrap; border: 0; background: transparent; cursor: pointer; font-family: inherit; }
.ds .tabs > .on, .ds .tabs > [aria-selected="true"] { color: var(--ink); background: var(--panel); font-weight: 600; box-shadow: var(--shadow); }
.ds .switch { width: 36px; height: 20px; border-radius: 999px; background: var(--accent); position: relative; display: inline-block; flex: none; }
.ds .switch::after { content: ""; position: absolute; top: 2px; right: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; }
.ds .switch.off { background: var(--line-strong); } .ds .switch.off::after { right: auto; left: 2px; }
.ds .grad { background: linear-gradient(135deg, #0f766e 0%, #115e59 60%, #134e4a 100%); color: #fff; border: 0; }
.ds .grad .muted, .ds .grad .label { color: rgba(255,255,255,.72); }
.ds .grad .bar { background: rgba(255,255,255,.22); } .ds .grad .bar i { background: #fff; }
.ds .hero { background: radial-gradient(820px 300px at 10% -10%, var(--glow-a), transparent 62%), radial-gradient(640px 280px at 88% 0%, var(--glow-b), transparent 60%), linear-gradient(180deg, var(--panel) 0%, var(--bg) 100%); border-bottom: 1px solid var(--line); }
.ds .tile { display: flex; gap: 12px; align-items: center; padding: 14px 16px; }
.ds .tile .v { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.2; }
.ds .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.ds .grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.ds .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.ds .grid-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 20px; align-items: start; }
.ds .msg { font-size: 13px; color: var(--ink2); min-height: 18px; }
.ds .msg.error { color: var(--gain); }
.ds .note { font-size: 12px; color: var(--muted); }
/* header */
.ds .topbar { background: var(--panel); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 30; }
.ds .topbar .shell { height: 60px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.ds .brand { display: inline-flex; align-items: center; gap: 9px; font-weight: 800; font-size: 16px; letter-spacing: -0.02em; white-space: nowrap; }
.ds .brand em { font-style: normal; color: var(--accent); }
.ds .nav { display: flex; gap: 2px; }
.ds .nav a { color: var(--ink2); font-size: 14px; font-weight: 500; padding: 6px 10px; border-radius: 8px; }
.ds .nav a:hover { background: var(--bg2); text-decoration: none; }
.ds .nav a[aria-current="page"] { color: var(--accent-ink); background: var(--accent-soft); font-weight: 600; }
.ds .top-right { display: flex; align-items: center; gap: 10px; }
.ds .top-search { height: 34px; width: 220px; font-size: 13px; }
.ds .theme-pick { position: relative; }
.ds .theme-pick button { height: 34px; width: 34px; border-radius: 999px; border: 1px solid var(--line); background: var(--bg2); color: var(--ink2); display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
.ds .theme-menu { position: absolute; right: 0; top: 40px; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,.14); padding: 6px; min-width: 190px; display: grid; gap: 2px; z-index: 40; }
.ds .theme-menu button { width: 100%; height: 34px; border-radius: 8px; border: 0; background: transparent; color: var(--ink); display: flex; align-items: center; gap: 10px; padding: 0 10px; font: inherit; font-size: 13px; cursor: pointer; text-align: left; }
.ds .theme-menu button:hover { background: var(--bg2); }
.ds .theme-menu button[aria-checked="true"] { background: var(--accent-soft); color: var(--accent-ink); font-weight: 600; }
.ds .swatch { width: 16px; height: 16px; border-radius: 50%; border: 1px solid rgba(0,0,0,.15); display: inline-block; flex: none; }
.ds .plan-badge { cursor: pointer; }
/* footer */
.ds footer.site { margin-top: auto; border-top: 1px solid var(--line); padding: 22px 0 28px; font-size: 13px; color: var(--ink2); }
.ds footer.site .trust { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.ds footer.site .trust > div { display: flex; gap: 12px; align-items: flex-start; }
.ds footer.site .trust b { color: var(--ink); display: block; }
.ds footer.site .links { margin-top: 18px; display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--muted); }
.ds main { flex: 1; }
.ds section.block { padding: 20px 0 0; }
@media (max-width: 960px) {
  .ds .grid-main { grid-template-columns: 1fr; }
  .ds .grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ds .grid-3 { grid-template-columns: 1fr; }
  .ds .nav { display: none; }
  .ds .top-search { display: none; }
  .ds footer.site .trust { grid-template-columns: 1fr; }
  .ds .shell { width: min(1200px, 100% - 32px); }
  .ds h1 { font-size: 24px; }
}
@media (prefers-reduced-motion: no-preference) { .ds .btn, .ds .nav a { transition: background .15s, border-color .15s; } }
"""


def _ic(path: str) -> str:
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{path}</svg>'


ICONS: dict[str, str] = {
    "trend": _ic('<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>'),
    "filter": _ic('<polygon points="22 3 2 3 10 12.5 10 19 14 21 14 12.5 22 3"/>'),
    "brain": _ic('<path d="M12 5a3 3 0 1 0-5.9 1A4 4 0 0 0 4 12a4 4 0 0 0 2 3.5V17a3 3 0 0 0 6 0"/><path d="M12 5a3 3 0 1 1 5.9 1A4 4 0 0 1 20 12a4 4 0 0 1-2 3.5V17a3 3 0 0 1-6 0"/><path d="M12 5v12"/>'),
    "check": _ic('<path d="M20 6 9 17l-5-5"/>'),
    "clock": _ic('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
    "layers": _ic('<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>'),
    "shield": _ic('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'),
    "bell": _ic('<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>'),
    "zap": _ic('<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'),
    "search": _ic('<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>'),
    "wallet": _ic('<rect x="2" y="6" width="20" height="14" rx="2"/><path d="M16 12h.01"/><path d="M2 10h20"/>'),
    "target": _ic('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>'),
    "book": _ic('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'),
    "star": _ic('<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>'),
    "send": _ic('<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>'),
    "users": _ic('<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
    "chevron": _ic('<polyline points="9 18 15 12 9 6"/>'),
    "mail": _ic('<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 7L2 7"/>'),
    "lock": _ic('<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'),
    "palette": _ic('<circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 1.7-.7 1.7-1.7 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.7 1.7-1.7H16c3.3 0 6-2.7 6-6 0-4.9-4.5-8.4-10-8.4z"/>'),
    "card": _ic('<rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/>'),
    "logout": _ic('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>'),
    "settings": _ic('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
}


def icon(name: str, size: int | None = None) -> str:
    svg = ICONS[name]
    if size:
        svg = svg.replace("<svg", f'<svg width="{size}" height="{size}"', 1)
    return svg


def icon_tile(name: str, tone: str, *, small: bool = False) -> str:
    return f'<span class="ico {"sm" if small else ""} {tone}">{icon(name)}</span>'


def h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def sparkline_svg(values: Sequence[float], *, width: int = 104, height: int = 32, color: str | None = None, area: bool = True, stroke_width: float = 1.6, css_class: str = "") -> str:
    """Inline SVG line for a short series. Color defaults to gain/loss by first→last change."""

    pts_src = [float(v) for v in values if v is not None]
    if len(pts_src) < 2:
        return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" class="{css_class}" aria-hidden="true"></svg>'
    if color is None:
        color = "var(--gain)" if pts_src[-1] >= pts_src[0] else "var(--loss)"
    lo, hi = min(pts_src), max(pts_src)
    span = (hi - lo) or 1.0
    n = len(pts_src)
    pts = []
    for i, y in enumerate(pts_src):
        x = i / (n - 1) * (width - 2) + 1
        yy = height - 2 - (y - lo) / span * (height - 4)
        pts.append((round(x, 1), round(yy, 1)))
    line = " ".join(f"{x},{y}" for x, y in pts)
    fill = ""
    if area:
        path = " L".join(f"{x},{y}" for x, y in pts)
        fill = f'<path d="M{pts[0][0]},{height} L{path} L{pts[-1][0]},{height} Z" fill="{color}" opacity="0.12"/>'
    lx, ly = pts[-1]
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" class="{css_class}" aria-hidden="true">{fill}<polyline points="{line}" fill="none" stroke="{color}" stroke-width="{stroke_width}" stroke-linejoin="round"/><circle cx="{lx}" cy="{ly}" r="2.2" fill="{color}"/></svg>'


def placeholder_series(seed: int, n: int = 40) -> list[float]:
    """Deterministic pseudo series for previews/tests (never for real data)."""

    rnd = random.Random(seed)
    v, out = 100.0, []
    for _ in range(n):
        v *= 1 + rnd.gauss(0.002, 0.015)
        out.append(round(v, 2))
    return out


NAV_ITEMS: tuple[tuple[str, str], ...] = (("/", "오늘"), ("/harness", "하네스"), ("/outcomes", "검증 성과"), ("/analyses", "AI 리포트"), ("/pricing", "요금제"))

TOKEN_STORAGE_KEY = "tradingagents.member.access_token"

DS_JS = r"""
(function(){
  var THEMES = __THEMES__;
  var KEY = 'ta-theme';
  var root = document.documentElement;
  function current(){ return root.getAttribute('data-theme') || ''; }
  function apply(name){
    if(name && THEMES.indexOf(name) >= 0){ root.setAttribute('data-theme', name); try{ localStorage.setItem(KEY, name); }catch(e){} }
    else { root.removeAttribute('data-theme'); try{ localStorage.removeItem(KEY); }catch(e){} }
    document.querySelectorAll('.theme-menu button').forEach(function(b){ b.setAttribute('aria-checked', String((b.getAttribute('data-theme') || '') === (name || ''))); });
  }
  var pick = document.querySelector('.theme-pick');
  if(pick){
    var trigger = pick.querySelector('[data-theme-trigger]');
    var menu = pick.querySelector('.theme-menu');
    trigger.addEventListener('click', function(){ var open = !menu.hidden; menu.hidden = open; trigger.setAttribute('aria-expanded', String(!open)); });
    document.addEventListener('click', function(ev){ if(!pick.contains(ev.target)){ menu.hidden = true; trigger.setAttribute('aria-expanded', 'false'); } });
    menu.querySelectorAll('button').forEach(function(b){ b.addEventListener('click', function(){ apply(b.getAttribute('data-theme') || ''); menu.hidden = true; trigger.setAttribute('aria-expanded', 'false'); }); });
    apply(current());
  }
  // auth-aware header: plan badge + avatar when a member session exists
  var token = '';
  try { token = localStorage.getItem('__TOKEN_KEY__') || sessionStorage.getItem('__TOKEN_KEY__') || ''; } catch(e) {}
  var out = document.querySelector('[data-auth="signed-out"]');
  var inn = document.querySelector('[data-auth="signed-in"]');
  if(!out || !inn) return;
  if(!token){ out.hidden = false; inn.hidden = true; return; }
  out.hidden = true; inn.hidden = false;
  fetch('/api/billing/me', { headers: { 'Authorization': 'Bearer ' + token } }).then(function(r){ return r.ok ? r.json() : null; }).then(function(d){
    var badge = inn.querySelector('[data-plan-badge]');
    if(!d || !d.access){ if(badge){ badge.textContent = '무료'; } return; }
    var s = d.access.status, name = d.access.plan.name;
    if(badge){ badge.textContent = s === 'trialing' ? name + ' 체험' : (s === 'active' && d.access.plan.id !== 'free' ? name : '무료'); badge.className = 'badge plan-badge ' + (s === 'trialing' ? 'b-amber' : (s === 'active' && d.access.plan.id !== 'free' ? 'b-teal' : 'b-grey')); }
    if(d.is_admin){ document.querySelectorAll('[data-admin-only]').forEach(function(n){ n.hidden = false; }); }
    var email = (d.access && d.access.email) || '';
    var av = inn.querySelector('[data-avatar]'); if(av && email){ av.textContent = email.slice(0,1).toUpperCase(); av.title = email; }
  }).catch(function(){ out.hidden = true; inn.hidden = false; });
})();
"""


def theme_init_script() -> str:
    """Tiny inline script applying the stored theme before first paint (no flash)."""

    themes = json.dumps(list(THEMES), ensure_ascii=False)
    return f"<script>(function(){{try{{var t=localStorage.getItem('ta-theme');if(t&&{themes}.indexOf(t)>=0){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>"


def _theme_menu() -> str:
    swatches = {"light": "#f3f5f9", "dark": "#0b0f16", "paper": "#f6f2ea", "nord": "#2e3440", "solar": "#fdf6e3"}
    rows = [f'<button type="button" role="menuitemradio" data-theme="" aria-checked="false"><span class="swatch" style="background: linear-gradient(90deg, #f3f5f9 50%, #0b0f16 50%);"></span>시스템 설정 따르기</button>']
    for name in THEMES:
        rows.append(f'<button type="button" role="menuitemradio" data-theme="{name}" aria-checked="false"><span class="swatch" style="background: {swatches[name]};"></span>{h(THEME_LABELS[name])}</button>')
    return f'<div class="theme-pick"><button type="button" data-theme-trigger aria-haspopup="menu" aria-expanded="false" aria-label="테마 선택" title="테마">{icon("palette", 16)}</button><div class="theme-menu" role="menu" hidden>{"".join(rows)}</div></div>'


def render_header(*, active: str | None = None, search: bool = True) -> str:
    nav = "".join(f'<a href="{href}"{" aria-current=\"page\"" if href == active else ""}>{h(text)}</a>' for href, text in NAV_ITEMS)
    search_html = (
        f'<form class="top-search-form" action="/stocks" method="get" role="search"><label class="field top-search"><span class="muted">{icon("search", 14)}</span><input name="ticker" type="search" placeholder="종목명 또는 코드" aria-label="종목 검색" style="border: 0; background: transparent; outline: none; width: 100%; font: inherit; color: var(--ink);"></label></form>'
        if search
        else ""
    )
    return f"""<header class="topbar">
  <div class="shell">
    <div class="row" style="gap: 24px;">
      <a class="brand" href="/" aria-label="TradingAgents Korea 홈"><span class="ico sm grad">{icon("trend")}</span><span>TradingAgents <em>Korea</em></span></a>
      <nav class="nav" aria-label="주요 메뉴">{nav}</nav>
    </div>
    <div class="top-right">
      {search_html}
      {_theme_menu()}
      <span data-auth="signed-out" hidden><a class="btn ghost sm" href="/member">로그인</a> <a class="btn primary sm" href="/member?mode=signup">무료로 시작</a></span>
      <span data-auth="signed-in" hidden class="row"><a class="badge plan-badge b-grey" href="/billing" data-plan-badge title="구독 관리">플랜 확인 중</a><a class="avatar" href="/mypage" data-avatar style="background: var(--accent); color: var(--on-accent);" aria-label="내 공간">M</a></span>
    </div>
  </div>
</header>"""


def render_footer() -> str:
    return f"""<footer class="site">
  <div class="shell">
    <div class="trust">
      <div>{icon_tile("shield", "b-teal", small=True)}<div><b>실계좌 주문은 이 사이트에서 일어나지 않습니다.</b>공개 페이지와 API는 조회 전용입니다.</div></div>
      <div>{icon_tile("layers", "b-blue", small=True)}<div><b>모든 숫자는 출처와 시각을 답니다.</b>pykrx · Naver · DART · KIS 중 어느 데이터인지 표시합니다.</div></div>
      <div>{icon_tile("brain", "b-violet", small=True)}<div><b>AI 의견은 연구 자료입니다.</b>투자 판단과 책임은 이용자에게 있으며 수익을 보장하지 않습니다.</div></div>
    </div>
    <div class="links"><span>© 2026 TradingAgents Korea</span><a href="/features">분석 기준</a><a href="/pricing">요금제</a><a href="/terms">이용약관</a><a href="/privacy">개인정보 처리방침</a><a href="/admin" data-admin-only hidden>운영 콘솔</a><a href="/admin/members" data-admin-only hidden>회원 관리</a></div>
  </div>
</footer>"""


def render_shell(
    *,
    title: str,
    body: str,
    description: str = "",
    active: str | None = None,
    canonical_path: str = "/",
    site_base_url: str | None = None,
    extra_head: str = "",
    extra_css: str = "",
    extra_js: str = "",
    noindex: bool = False,
    search: bool = True,
    body_class: str = "",
) -> str:
    robots = '<meta name="robots" content="noindex, nofollow">' if noindex else ""
    desc = f'<meta name="description" content="{h(description)}">' if description else ""
    js = DS_JS.replace("__THEMES__", json.dumps(list(THEMES), ensure_ascii=False)).replace("__TOKEN_KEY__", TOKEN_STORAGE_KEY)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h(title)}</title>
{desc}
{robots}
<link rel="canonical" href="{h(canonical_url(canonical_path, site_base_url=site_base_url))}">
<link rel="stylesheet" href="{FONT_STYLESHEET}">
{theme_init_script()}
<style>{theme_css()}{DS_COMPONENT_CSS}{extra_css}</style>
{extra_head}
</head>
<body class="ds {h(body_class)}">
<a class="skip-link" href="#main-content">본문 바로가기</a>
{render_header(active=active, search=search)}
<main id="main-content">
{body}
</main>
{render_footer()}
<script>{js}</script>
{f"<script>{extra_js}</script>" if extra_js else ""}
</body>
</html>"""


# --- small composite helpers used by several pages ------------------------------------
def stat_tile(icon_name: str, tone: str, label: str, value: str, sub: str = "", *, value_class: str = "") -> str:
    return f'<div class="card tile">{icon_tile(icon_name, tone)}<div><p class="label">{h(label)}</p><p class="v num {value_class}">{value}</p><p class="tiny muted">{h(sub)}</p></div></div>'


def badge(text: str, tone: str = "b-grey", *, icon_name: str | None = None, xs: bool = False) -> str:
    ic = icon(icon_name, 13) if icon_name else ""
    return f'<span class="badge {tone}{" xs" if xs else ""}">{ic}{h(text)}</span>'


def pct(value: float | None, *, digits: int = 2, sign: bool = True) -> str:
    if value is None:
        return '<span class="muted">–</span>'
    v = float(value) * 100
    cls = "up" if v > 0 else ("down" if v < 0 else "flat")
    txt = f"{v:+.{digits}f}%" if sign else f"{v:.{digits}f}%"
    return f'<span class="num {cls}">{txt}</span>'


def money(value: float | int | None, unit: str = "원") -> str:
    if value is None:
        return "–"
    return f"{int(round(float(value))):,}{unit}"

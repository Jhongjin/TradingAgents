"""The chart itself: candles, with everything drawn on top of them.

A table of pattern statistics is unreadable while a chart is open, so the
numbers come to the chart instead. Bars are drawn on a canvas, each detected
pattern is marked on the bar that completed it, the three trading sessions are
shaded behind the price with their own high and low, and the American releases
that move gold stand as vertical lines.

Everything is one file with the data inlined, so it opens from disk with no
server and no network, and the same renderer serves the web route.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .data import BarSeries
from .events import macro_events
from .patterns import PatternHit, detect_patterns
from .sessions import SESSIONS, all_session_windows, session_summary

CHART_CSS = """
:root { color-scheme: dark; --bg:#0e1117; --panel:#161a22; --line:#252b37; --ink:#e8ebf2; --ink2:#98a2b6;
  --up:#f6465d; --down:#2f6fed; --grid:#1c212c; --accent:#d8a544; }
* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:13px/1.5 -apple-system,"Segoe UI","Malgun Gothic",system-ui,sans-serif; }
header { display:flex; flex-wrap:wrap; gap:12px; align-items:center; padding:12px 16px; border-bottom:1px solid var(--line); }
header h1 { font-size:15px; margin:0; font-weight:700; letter-spacing:-0.01em; }
.price { font-size:20px; font-weight:700; font-variant-numeric:tabular-nums; }
.tabs { display:flex; gap:4px; margin-left:auto; flex-wrap:wrap; }
.tabs button { background:var(--panel); color:var(--ink2); border:1px solid var(--line); border-radius:7px;
  padding:6px 12px; font-size:12px; font-weight:600; cursor:pointer; }
.tabs button.on { background:var(--accent); color:#1a1206; border-color:var(--accent); }
.toggles { display:flex; gap:12px; align-items:center; padding:8px 16px; border-bottom:1px solid var(--line);
  color:var(--ink2); font-size:12px; flex-wrap:wrap; }
.toggles label { display:inline-flex; gap:5px; align-items:center; cursor:pointer; }
.chart-wrap { position:relative; padding:8px 16px 0; }
canvas { width:100%; display:block; cursor:crosshair; touch-action:none; }
#tip { position:absolute; pointer-events:none; background:rgba(12,15,22,.96); border:1px solid var(--line);
  border-radius:8px; padding:8px 10px; font-size:12px; display:none; max-width:300px; z-index:5; line-height:1.5; }
#tip b { display:block; margin-bottom:3px; }
.legend { display:flex; gap:14px; flex-wrap:wrap; padding:8px 16px 14px; color:var(--ink2); font-size:12px; }
.legend i { display:inline-block; width:11px; height:11px; border-radius:3px; margin-right:5px; vertical-align:-1px; }
.panels { display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:14px; padding:0 16px 28px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:11px; overflow:hidden; }
.card h2 { font-size:13px; margin:0; padding:11px 13px; border-bottom:1px solid var(--line); }
table { width:100%; border-collapse:collapse; font-size:12px; }
th { text-align:left; color:var(--ink2); font-weight:600; font-size:11px; padding:8px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }
td { padding:8px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }
tr:last-child td { border-bottom:0; }
.num { font-variant-numeric:tabular-nums; }
.up { color:var(--up); } .down { color:var(--down); } .muted { color:var(--ink2); }
.empty { padding:18px 13px; color:var(--ink2); }
.note { padding:10px 16px 26px; color:var(--ink2); font-size:11.5px; line-height:1.7; }
"""

CHART_JS = r"""
const DATA = __DATA__;
let current = DATA.default_interval;
let view = null;
const show = { patterns: true, sessions: true, events: true, levels: true };

const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
const tip = document.getElementById('tip');
const PAD = { left: 8, right: 68, top: 14, bottom: 26 };

function frame() { return DATA.intervals[current]; }

function resize() {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.parentElement.clientWidth;
  const height = Math.max(340, Math.min(620, Math.round(window.innerHeight * 0.56)));
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  canvas.style.height = height + 'px';
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  draw();
}

function resetView() {
  const bars = frame().bars;
  const visible = Math.min(bars.length, 160);
  view = { from: Math.max(0, bars.length - visible), to: bars.length };
}

function geometry() {
  const bars = frame().bars;
  const from = Math.max(0, Math.floor(view.from));
  const to = Math.min(bars.length, Math.ceil(view.to));
  const slice = bars.slice(from, to);
  const width = canvas.clientWidth, height = canvas.clientHeight;
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  let high = -Infinity, low = Infinity;
  for (const bar of slice) { if (bar[2] > high) high = bar[2]; if (bar[3] < low) low = bar[3]; }
  if (!isFinite(high) || !isFinite(low)) { high = 1; low = 0; }
  const pad = (high - low) * 0.08 || 1;
  high += pad; low -= pad;
  const step = plotW / Math.max(slice.length, 1);
  return {
    from, to, slice, width, height, plotW, plotH, high, low, step,
    x: (index) => PAD.left + (index - from + 0.5) * step,
    y: (price) => PAD.top + (high - price) / (high - low) * plotH,
  };
}

function draw() {
  const g = geometry();
  const f = frame();
  ctx.clearRect(0, 0, g.width, g.height);

  if (show.sessions) {
    for (const window of f.sessions) {
      if (window.end_index < g.from || window.start_index > g.to) continue;
      const left = g.x(Math.max(window.start_index, g.from)) - g.step / 2;
      const right = g.x(Math.min(window.end_index, g.to - 1)) + g.step / 2;
      ctx.fillStyle = window.colour + '14';
      ctx.fillRect(left, PAD.top, Math.max(right - left, 1), g.plotH);
      ctx.strokeStyle = window.colour + '55';
      ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(left, PAD.top); ctx.lineTo(left, PAD.top + g.plotH); ctx.stroke();
      ctx.setLineDash([]);
      if (right - left > 52) {
        ctx.fillStyle = window.colour; ctx.font = '10px system-ui';
        ctx.fillText(window.label, left + 4, PAD.top + 11);
      }
      if (show.levels && right - left > 26) {
        for (const [price, tone] of [[window.high, '고'], [window.low, '저']]) {
          const y = g.y(price);
          if (y < PAD.top || y > PAD.top + g.plotH) continue;
          ctx.strokeStyle = window.colour + '88';
          ctx.setLineDash([2, 4]); ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = window.colour; ctx.font = '9px system-ui';
          ctx.fillText(tone + ' ' + price.toFixed(1), left + 3, y - 2);
        }
      }
    }
  }

  ctx.strokeStyle = 'rgba(255,255,255,.05)'; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = PAD.top + (g.plotH / 4) * i;
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + g.plotW, y); ctx.stroke();
    const price = g.high - (g.high - g.low) / 4 * i;
    ctx.fillStyle = '#98a2b6'; ctx.font = '10px system-ui';
    ctx.fillText(price.toFixed(1), PAD.left + g.plotW + 6, y + 3);
  }

  if (show.events) {
    for (const event of f.events) {
      if (event.index == null || event.index < g.from || event.index >= g.to) continue;
      const x = g.x(event.index);
      ctx.strokeStyle = event.stars >= 3 ? '#ffd166' : '#7a8291';
      ctx.setLineDash([4, 3]); ctx.lineWidth = event.stars >= 3 ? 1.4 : 1;
      ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + g.plotH); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = event.stars >= 3 ? '#ffd166' : '#7a8291';
      ctx.save(); ctx.translate(x + 3, PAD.top + 12); ctx.font = '10px system-ui';
      ctx.fillText('★'.repeat(event.stars) + ' ' + event.name, 0, 0); ctx.restore();
    }
  }

  const bodyW = Math.max(1, Math.min(g.step * 0.68, 16));
  for (let i = g.from; i < g.to; i++) {
    const bar = f.bars[i]; if (!bar) continue;
    const x = g.x(i), rising = bar[4] >= bar[1];
    ctx.strokeStyle = rising ? '#f6465d' : '#2f6fed';
    ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, g.y(bar[2])); ctx.lineTo(x, g.y(bar[3])); ctx.stroke();
    const top = g.y(Math.max(bar[1], bar[4])), bottom = g.y(Math.min(bar[1], bar[4]));
    ctx.fillRect(x - bodyW / 2, top, bodyW, Math.max(bottom - top, 1));
  }

  if (show.patterns) {
    for (const hit of f.hits) {
      if (hit.index < g.from || hit.index >= g.to) continue;
      const bar = f.bars[hit.index];
      const bullish = hit.direction === 'bullish';
      const y = bullish ? g.y(bar[3]) + 11 : g.y(bar[2]) - 11;
      const x = g.x(hit.index);
      const strong = hit.confidence === '강함' || hit.confidence === '보통';
      ctx.fillStyle = bullish ? '#f6465d' : '#2f6fed';
      ctx.globalAlpha = strong ? 1 : 0.45;
      ctx.beginPath();
      if (bullish) { ctx.moveTo(x, y - 6); ctx.lineTo(x - 5, y + 3); ctx.lineTo(x + 5, y + 3); }
      else { ctx.moveTo(x, y + 6); ctx.lineTo(x - 5, y - 3); ctx.lineTo(x + 5, y - 3); }
      ctx.closePath(); ctx.fill();
      ctx.globalAlpha = 1;
    }
  }

  const first = f.bars[g.from], last = f.bars[g.to - 1];
  ctx.fillStyle = '#98a2b6'; ctx.font = '10px system-ui';
  if (first) ctx.fillText(first[0], PAD.left, g.height - 8);
  if (last) {
    const text = last[0];
    ctx.fillText(text, PAD.left + g.plotW - ctx.measureText(text).width, g.height - 8);
  }
}

function nearest(event) {
  const rect = canvas.getBoundingClientRect();
  const g = geometry();
  const index = Math.round(g.from + (event.clientX - rect.left - PAD.left) / g.step - 0.5);
  return { g, index, x: event.clientX - rect.left, y: event.clientY - rect.top };
}

canvas.addEventListener('mousemove', (event) => {
  const { g, index, x, y } = nearest(event);
  const f = frame();
  if (index < g.from || index >= g.to || !f.bars[index]) { tip.style.display = 'none'; return; }
  const bar = f.bars[index];
  const hits = f.hits.filter((hit) => hit.index === index);
  const sessions = f.sessions.filter((w) => w.start_index <= index && index <= w.end_index);
  const events = f.events.filter((e) => e.index === index);
  let body = '<b>' + bar[0] + '</b>';
  body += '시 ' + bar[1].toFixed(1) + ' 고 ' + bar[2].toFixed(1) + ' 저 ' + bar[3].toFixed(1) + ' 종 ' + bar[4].toFixed(1);
  if (sessions.length) body += '<br>세션 ' + sessions.map((w) => w.label + ' (고 ' + w.high.toFixed(1) + ' / 저 ' + w.low.toFixed(1) + ')').join(', ');
  for (const event of events) body += '<br><span style="color:#ffd166">' + '★'.repeat(event.stars) + ' ' + event.name + '</span>';
  for (const hit of hits) {
    const arrow = hit.direction === 'bullish' ? '▲' : '▼';
    body += '<br>' + arrow + ' <b style="display:inline">' + hit.label + '</b>';
    if (hit.samples) {
      body += ' 승률 ' + (hit.win_rate * 100).toFixed(0) + '% (기준대비 ' + (hit.edge_win_rate * 100).toFixed(1) + '%p)'
            + ', 표본 ' + hit.samples + ', ' + hit.confidence;
    } else { body += ' · 측정 없음'; }
  }
  tip.innerHTML = body;
  tip.style.display = 'block';
  const wrap = canvas.parentElement.getBoundingClientRect();
  tip.style.left = Math.min(x + 14, wrap.width - tip.offsetWidth - 10) + 'px';
  tip.style.top = Math.max(y - 10, 4) + 'px';
});
canvas.addEventListener('mouseleave', () => { tip.style.display = 'none'; });

canvas.addEventListener('wheel', (event) => {
  event.preventDefault();
  const bars = frame().bars;
  const span = view.to - view.from;
  const factor = event.deltaY > 0 ? 1.15 : 0.87;
  const next = Math.max(30, Math.min(bars.length, Math.round(span * factor)));
  const anchor = view.to;
  view.to = Math.min(bars.length, anchor);
  view.from = Math.max(0, view.to - next);
  draw();
}, { passive: false });

let dragging = null;
canvas.addEventListener('mousedown', (event) => { dragging = { x: event.clientX, from: view.from, to: view.to }; });
window.addEventListener('mouseup', () => { dragging = null; });
window.addEventListener('mousemove', (event) => {
  if (!dragging) return;
  const g = geometry();
  const shift = Math.round((dragging.x - event.clientX) / g.step);
  const bars = frame().bars;
  const span = dragging.to - dragging.from;
  let from = Math.max(0, Math.min(bars.length - span, dragging.from + shift));
  view.from = from; view.to = from + span;
  draw();
});

function renderPanels() {
  const f = frame();
  const recent = f.hits.filter((hit) => hit.index >= f.bars.length - 40).slice(-14).reverse();
  document.getElementById('hits').innerHTML = recent.length
    ? recent.map((hit) => '<tr><td>' + hit.time.slice(5, 16).replace('T', ' ') + '</td>'
        + '<td class="' + (hit.direction === 'bullish' ? 'up' : 'down') + '">'
        + (hit.direction === 'bullish' ? '▲ ' : '▼ ') + hit.label + '</td>'
        + '<td class="num">' + (hit.samples ? (hit.win_rate * 100).toFixed(0) + '%' : '-') + '</td>'
        + '<td class="num ' + ((hit.edge_win_rate || 0) > 0 ? 'up' : 'down') + '">'
        + (hit.samples ? ((hit.edge_win_rate * 100).toFixed(1) + '%p') : '-') + '</td>'
        + '<td class="num muted">' + (hit.samples || '-') + '</td>'
        + '<td class="muted">' + hit.confidence + '</td></tr>').join('')
    : '<tr><td colspan="6" class="empty">최근 40봉에 완성된 패턴이 없습니다.</td></tr>';

  document.getElementById('sessions').innerHTML = f.session_rows.length
    ? f.session_rows.map((row) => '<tr><td style="color:' + row.colour + '">' + row.label + '</td>'
        + '<td class="muted">' + row.day + '</td>'
        + '<td class="num">' + row.high.toFixed(1) + '</td>'
        + '<td class="num">' + row.low.toFixed(1) + '</td>'
        + '<td class="num">' + row.range.toFixed(1) + '</td>'
        + '<td class="num ' + (row.change >= 0 ? 'up' : 'down') + '">' + (row.change >= 0 ? '+' : '') + row.change.toFixed(1) + '</td></tr>').join('')
    : '<tr><td colspan="6" class="empty">세션 구간이 없습니다.</td></tr>';

  document.getElementById('events').innerHTML = f.events.length
    ? f.events.slice(-12).reverse().map((event) => '<tr><td>' + event.local.slice(5, 16).replace('T', ' ') + '</td>'
        + '<td>' + '★'.repeat(event.stars) + '</td><td>' + event.name + '</td>'
        + '<td class="muted">' + (event.index == null ? '차트 밖' : '표시됨') + '</td></tr>').join('')
    : '<tr><td colspan="4" class="empty">이 구간에 예정된 3성 지표가 없습니다.</td></tr>';
}

function select(interval) {
  current = interval;
  document.querySelectorAll('.tabs button').forEach((button) => button.classList.toggle('on', button.dataset.interval === interval));
  const f = frame();
  document.getElementById('price').textContent = f.last_price.toFixed(1);
  document.getElementById('meta').textContent = f.bars.length + '봉 · ' + f.bars[f.bars.length - 1][0];
  resetView(); draw(); renderPanels();
}

document.querySelectorAll('.tabs button').forEach((button) => {
  button.addEventListener('click', () => select(button.dataset.interval));
});
document.querySelectorAll('.toggles input').forEach((input) => {
  input.addEventListener('change', () => { show[input.dataset.key] = input.checked; draw(); });
});
window.addEventListener('resize', resize);
select(current);
resize();
"""


def _hit_rows(hits: Sequence[PatternHit], study: Mapping[str, Any] | None, *, min_samples: int = 30) -> list[dict]:
    """Each hit with the measured record attached, ready to draw."""

    lookup: dict[str, dict] = {}
    for row in (study or {}).get("patterns") or []:
        horizons = row.get("horizons") or {}
        best = None
        for stats in horizons.values():
            if int(stats.get("count") or 0) < min_samples:
                continue
            if best is None or abs(stats.get("t_stat") or 0) > abs(best.get("t_stat") or 0):
                best = stats
        if best:
            lookup[str(row.get("pattern"))] = best

    rows = []
    for hit in hits:
        stats = lookup.get(hit.pattern) or {}
        samples = int(stats.get("count") or 0)
        edge = stats.get("edge_win_rate")
        t_stat = abs(float(stats.get("t_stat") or 0))
        if not samples:
            confidence = "측정 없음"
        elif edge is None or edge <= 0:
            confidence = "기준 미달"
        elif t_stat >= 3:
            confidence = "강함"
        elif t_stat >= 2:
            confidence = "보통"
        else:
            confidence = "약함"
        rows.append(
            {
                "index": hit.index,
                "time": hit.timestamp.isoformat(),
                "pattern": hit.pattern,
                "label": hit.label,
                "direction": hit.direction,
                "samples": samples,
                "win_rate": stats.get("win_rate"),
                "edge_win_rate": edge,
                "t_stat": stats.get("t_stat"),
                "confidence": confidence,
            }
        )
    return rows


def build_frame(
    series: BarSeries,
    *,
    study: Mapping[str, Any] | None = None,
    max_bars: int = 900,
    min_stars: int = 3,
) -> dict[str, Any]:
    """Everything one timeframe needs, small enough to inline in a page."""

    bars = series.bars[-max_bars:]
    trimmed = BarSeries(symbol=series.symbol, interval=series.interval, bars=bars)
    hits = detect_patterns(trimmed)
    windows = all_session_windows(bars)

    stamp_index = {bar.timestamp: index for index, bar in enumerate(bars)}
    ordered = sorted(stamp_index)
    events = []
    if bars:
        for event in macro_events(bars[0].timestamp, bars[-1].timestamp, min_stars=min_stars):
            when = datetime.fromisoformat(event["timestamp"])
            index = None
            for candidate in ordered:
                if candidate <= when:
                    index = stamp_index[candidate]
                else:
                    break
            events.append(
                {
                    **event,
                    "index": index,
                    "local": when.astimezone().isoformat(),
                }
            )

    return {
        "interval": series.interval,
        "bars": [
            [bar.timestamp.astimezone().strftime("%m-%d %H:%M"), bar.open, bar.high, bar.low, bar.close]
            for bar in bars
        ],
        "hits": _hit_rows(hits, study),
        "sessions": windows,
        "session_rows": session_summary(windows, last=3),
        "events": events,
        "last_price": bars[-1].close if bars else 0.0,
    }


def render_chart(
    frames: Mapping[str, Mapping[str, Any]],
    *,
    symbol: str = "GC=F",
    default_interval: str | None = None,
    title: str | None = None,
) -> str:
    """One self-contained page holding every timeframe."""

    order = list(frames)
    chosen = default_interval if default_interval in frames else (order[0] if order else "1h")
    payload = {"symbol": symbol, "default_interval": chosen, "intervals": frames}
    tabs = "".join(
        f'<button data-interval="{html.escape(interval)}">{html.escape(interval)}</button>' for interval in order
    )
    legend = "".join(
        f'<span><i style="background:{session.colour}"></i>{html.escape(session.label)}</span>' for session in SESSIONS
    )
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(title or f'{symbol} 패턴 차트')}</title>
<style>{CHART_CSS}</style></head><body>
<header>
  <h1>{html.escape(symbol)}</h1>
  <span class="price" id="price">-</span>
  <span class="muted" id="meta"></span>
  <span class="tabs">{tabs}</span>
</header>
<div class="toggles">
  <label><input type="checkbox" data-key="patterns" checked> 패턴 표시</label>
  <label><input type="checkbox" data-key="sessions" checked> 세션 구분</label>
  <label><input type="checkbox" data-key="levels" checked> 세션 고저</label>
  <label><input type="checkbox" data-key="events" checked> 경제지표</label>
  <span class="muted">휠로 확대, 드래그로 이동, 봉 위에 올리면 상세</span>
</div>
<div class="chart-wrap"><canvas id="chart"></canvas><div id="tip"></div></div>
<div class="legend">{legend}
  <span><i style="background:#ffd166"></i>3성 지표</span>
  <span><i style="background:#f6465d"></i>상승 패턴</span>
  <span><i style="background:#2f6fed"></i>하락 패턴</span>
  <span class="muted">흐린 화살표는 표본이 적거나 기준을 못 넘은 패턴입니다</span>
</div>
<div class="panels">
  <div class="card"><h2>최근 완성된 패턴</h2><table>
    <thead><tr><th>시각</th><th>패턴</th><th>승률</th><th>기준대비</th><th>표본</th><th>신뢰도</th></tr></thead>
    <tbody id="hits"></tbody></table></div>
  <div class="card"><h2>세션별 고저</h2><table>
    <thead><tr><th>세션</th><th>날짜</th><th>고</th><th>저</th><th>폭</th><th>변화</th></tr></thead>
    <tbody id="sessions"></tbody></table></div>
  <div class="card"><h2>미국 주요 지표</h2><table>
    <thead><tr><th>시각</th><th>등급</th><th>지표</th><th>차트</th></tr></thead>
    <tbody id="events"></tbody></table></div>
</div>
<p class="note">{html.escape(generated)} 기준 · 승률과 기준대비는 같은 종목의 과거 같은 패턴에서 센 값이며 앞으로를 보장하지 않습니다.
시각은 이 컴퓨터의 현지 시간입니다. 세션은 도쿄·런던·뉴욕 현지 영업시간 기준이라 서머타임을 따라 움직입니다.
FOMC와 물가지표처럼 날짜가 규칙으로 정해지지 않는 발표는 직접 입력한 일정만 표시합니다.</p>
<script>{CHART_JS.replace("__DATA__", json.dumps(payload, ensure_ascii=False))}</script>
</body></html>"""

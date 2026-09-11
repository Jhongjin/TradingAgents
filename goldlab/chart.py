"""The chart itself: candles, with everything drawn on top of them.

A table of pattern statistics is unreadable while a chart is open, so the
numbers come to the chart instead. Bars are drawn on a canvas, each detected
pattern is marked on the bar that completed it, the shapes still forming are
drawn as the level they would confirm at, the three trading sessions are shaded
behind the price with their own high and low, and the American releases that
move gold stand as vertical lines.

The page can stand alone with the data inlined, or be given a data URL, in
which case it fetches each timeframe when asked for and refreshes the one on
screen on a timer. Every clock on it reads Korean time.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .data import BarSeries
from .events import macro_events
from .indicators import moving_averages, trend_lines
from .patterns import PatternHit, detect_patterns
from .patterns.forming import attach_record, detect_forming
from .sessions import SESSIONS, all_session_windows, session_summary

KST = ZoneInfo("Asia/Seoul")
DAILY_OR_LONGER = {"1d", "1wk", "1mo"}
POLL_SECONDS = {"1m": 20, "2m": 20, "5m": 30, "15m": 30, "30m": 60, "1h": 60, "4h": 120, "1d": 300, "1wk": 600, "1mo": 600}
# How often the last candle is nudged with a fresh quote, apart from the full redraw.
QUOTE_SECONDS = {"1m": 5, "2m": 5, "5m": 5, "15m": 5, "30m": 10, "1h": 10, "4h": 10, "1d": 30, "1wk": 30, "1mo": 30}
BUCKET_SECONDS = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400, "1wk": 604800, "1mo": 2678400}

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
.bias { padding:3px 9px; border-radius:6px; font-size:12px; font-weight:700; border:1px solid var(--line); }
.bias.up { color:var(--up); border-color:var(--up); } .bias.down { color:var(--down); border-color:var(--down); }
.live { font-size:11px; color:var(--ink2); display:inline-flex; gap:5px; align-items:center; }
.live i { width:7px; height:7px; border-radius:50%; background:#3fb950; display:inline-block; }
.live.stale i { background:#7a8291; }
.tabs { display:flex; gap:4px; margin-left:auto; flex-wrap:wrap; }
.tabs button { background:var(--panel); color:var(--ink2); border:1px solid var(--line); border-radius:7px;
  padding:6px 11px; font-size:12px; font-weight:600; cursor:pointer; }
.tabs button.on { background:var(--accent); color:#1a1206; border-color:var(--accent); }
.toggles { display:flex; gap:12px; align-items:center; padding:8px 16px; border-bottom:1px solid var(--line);
  color:var(--ink2); font-size:12px; flex-wrap:wrap; }
.toggles label { display:inline-flex; gap:5px; align-items:center; cursor:pointer; }
.chart-wrap { position:relative; padding:8px 16px 0; }
canvas { width:100%; display:block; cursor:crosshair; touch-action:none; }
#tip { position:absolute; pointer-events:none; background:rgba(12,15,22,.96); border:1px solid var(--line);
  border-radius:8px; padding:8px 10px; font-size:12px; display:none; max-width:320px; z-index:5; line-height:1.5; }
#tip b { display:block; margin-bottom:3px; }
#loading { position:absolute; inset:8px 16px 0; display:none; align-items:center; justify-content:center;
  background:rgba(14,17,23,.6); color:var(--ink2); font-size:13px; }
.legend { display:flex; gap:14px; flex-wrap:wrap; padding:8px 16px 14px; color:var(--ink2); font-size:12px; }
.legend i { display:inline-block; width:11px; height:11px; border-radius:3px; margin-right:5px; vertical-align:-1px; }
.legend i.line { height:2px; border-radius:0; vertical-align:3px; }
.panels { display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:14px; padding:0 16px 28px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:11px; overflow:hidden; }
.card.wide { grid-column:1 / -1; }
.card h2 { font-size:13px; margin:0; padding:11px 13px; border-bottom:1px solid var(--line); }
.card h2 small { color:var(--ink2); font-weight:400; margin-left:6px; }
.card .scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th { text-align:left; color:var(--ink2); font-weight:600; font-size:11px; padding:8px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }
td { padding:8px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }
tr:last-child td { border-bottom:0; }
.num { font-variant-numeric:tabular-nums; }
.up { color:var(--up); } .down { color:var(--down); } .muted { color:var(--ink2); }
.empty { padding:18px 13px; color:var(--ink2); white-space:normal; }
.note { padding:10px 16px 26px; color:var(--ink2); font-size:11.5px; line-height:1.7; }
@media (max-width: 640px) { td, th { padding:7px 8px; } .tabs button { padding:5px 8px; } }
"""

CHART_JS = r"""
const DATA = __DATA__;
let current = DATA.default_interval;
let view = null;
let pinned = true;          // following the newest bar
let timer = null;
const show = { patterns: true, forming: true, ma: true, trend: true, sessions: true, levels: true, events: true };
const MA_COLOUR = { '20': '#f5c518', '50': '#3fb950', '200': '#c678dd' };

const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
const tip = document.getElementById('tip');
const loading = document.getElementById('loading');
const PAD = { left: 8, right: 72, top: 14, bottom: 26 };

function frame() { return DATA.intervals[current]; }

function resize() {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.parentElement.clientWidth;
  const height = Math.max(340, Math.min(640, Math.round(window.innerHeight * 0.56)));
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  canvas.style.height = height + 'px';
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  draw();
}

function resetView(keepSpan) {
  const bars = frame().bars;
  const span = keepSpan && view ? Math.min(bars.length, view.to - view.from) : Math.min(bars.length, 160);
  view = { from: Math.max(0, bars.length - span), to: bars.length };
  pinned = true;
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

function label(x, y, text, colour, align) {
  ctx.font = '10px system-ui';
  const w = ctx.measureText(text).width + 8;
  const left = align === 'right' ? x - w : x;
  ctx.fillStyle = 'rgba(14,17,23,.85)';
  ctx.fillRect(left, y - 11, w, 14);
  ctx.fillStyle = colour;
  ctx.fillText(text, left + 4, y);
}

function draw() {
  if (!frame()) return;
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

  if (show.ma && f.ma) {
    for (const [period, values] of Object.entries(f.ma)) {
      ctx.strokeStyle = MA_COLOUR[period] || '#98a2b6'; ctx.lineWidth = 1.2;
      ctx.beginPath(); let started = false;
      for (let i = g.from; i < g.to; i++) {
        const value = values[i]; if (value == null) { started = false; continue; }
        const x = g.x(i), y = g.y(value);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      }
      ctx.stroke();
      const lastValue = values[g.to - 1];
      if (lastValue != null) label(PAD.left + g.plotW - 2, g.y(lastValue) + 4, 'MA' + period + ' ' + lastValue.toFixed(1), MA_COLOUR[period] || '#98a2b6', 'right');
    }
  }

  if (show.trend && f.trendlines) {
    for (const line of f.trendlines) {
      if (line.to_index < g.from) continue;
      const colour = line.kind === 'low' ? '#3fb950' : '#ff7b72';
      ctx.strokeStyle = colour; ctx.lineWidth = 1.3;
      ctx.setLineDash(line.broken ? [6, 4] : []);
      ctx.beginPath();
      ctx.moveTo(g.x(line.from_index), g.y(line.from_price));
      ctx.lineTo(g.x(line.to_index), g.y(line.to_price));
      ctx.stroke(); ctx.setLineDash([]);
      const y = g.y(line.to_price);
      if (y > PAD.top && y < PAD.top + g.plotH) label(g.x(line.to_index) - 4, y - 4, line.label + (line.broken ? ' 이탈' : '') + ' ' + line.to_price.toFixed(1), colour, 'right');
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

  if (show.forming && f.forming) {
    for (const shape of f.forming) {
      const y = g.y(shape.trigger);
      if (y < PAD.top || y > PAD.top + g.plotH) continue;
      const colour = shape.direction === 'bullish' ? '#f6465d' : '#2f6fed';
      const left = g.x(Math.max(shape.start_index, g.from)) - g.step / 2;
      ctx.strokeStyle = colour; ctx.lineWidth = 1.2; ctx.setLineDash([8, 4]);
      ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(PAD.left + g.plotW, y); ctx.stroke(); ctx.setLineDash([]);
      const text = (shape.direction === 'bullish' ? '▲ ' : '▼ ') + shape.label + ' · ' + shape.trigger_label + ' ' + shape.trigger.toFixed(1)
        + (shape.samples ? ' → 승률 ' + (shape.win_rate * 100).toFixed(0) + '%' : '');
      label(left + 4, y - 3, text, colour, 'left');
    }
  }

  const last = f.bars[g.to - 1];
  if (last) {
    const y = g.y(last[4]);
    ctx.strokeStyle = '#98a2b6'; ctx.setLineDash([2, 3]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + g.plotW, y); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = last[4] >= last[1] ? '#f6465d' : '#2f6fed';
    ctx.fillRect(PAD.left + g.plotW + 2, y - 8, PAD.right - 4, 16);
    ctx.fillStyle = '#fff'; ctx.font = 'bold 10px system-ui';
    ctx.fillText(last[4].toFixed(1), PAD.left + g.plotW + 6, y + 4);
  }

  const first = f.bars[g.from];
  ctx.fillStyle = '#98a2b6'; ctx.font = '10px system-ui';
  if (first) ctx.fillText(first[0], PAD.left, g.height - 8);
  if (last) {
    const text = last[0] + ' KST';
    ctx.fillText(text, PAD.left + g.plotW - ctx.measureText(text).width, g.height - 8);
  }
}

function nearest(event) {
  const rect = canvas.getBoundingClientRect();
  const g = geometry();
  const index = Math.round(g.from + (event.clientX - rect.left - PAD.left) / g.step - 0.5);
  return { g, index, x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function pct(value) { return (value * 100).toFixed(0) + '%'; }
function pctp(value) { return ((value || 0) * 100).toFixed(1) + '%p'; }

canvas.addEventListener('mousemove', (event) => {
  if (!frame()) return;
  const { g, index, x, y } = nearest(event);
  const f = frame();
  if (index < g.from || index >= g.to || !f.bars[index]) { tip.style.display = 'none'; return; }
  const bar = f.bars[index];
  const hits = f.hits.filter((hit) => hit.index === index);
  const sessions = f.sessions.filter((w) => w.start_index <= index && index <= w.end_index);
  const events = f.events.filter((e) => e.index === index);
  let body = '<b>' + bar[0] + ' KST</b>';
  body += '시 ' + bar[1].toFixed(1) + ' 고 ' + bar[2].toFixed(1) + ' 저 ' + bar[3].toFixed(1) + ' 종 ' + bar[4].toFixed(1);
  if (f.ma) {
    const parts = [];
    for (const [period, values] of Object.entries(f.ma)) if (values[index] != null) parts.push('MA' + period + ' ' + values[index].toFixed(1));
    if (parts.length) body += '<br><span class="muted">' + parts.join(' · ') + '</span>';
  }
  if (sessions.length) body += '<br>세션 ' + sessions.map((w) => w.label + ' (고 ' + w.high.toFixed(1) + ' / 저 ' + w.low.toFixed(1) + ')').join(', ');
  for (const event of events) body += '<br><span style="color:#ffd166">' + '★'.repeat(event.stars) + ' ' + event.name + '</span>';
  for (const hit of hits) {
    const arrow = hit.direction === 'bullish' ? '▲' : '▼';
    body += '<br>' + arrow + ' <b style="display:inline">' + hit.label + '</b>';
    if (hit.samples) body += ' 승률 ' + pct(hit.win_rate) + ' (기준대비 ' + pctp(hit.edge_win_rate) + '), 표본 ' + hit.samples + ', ' + hit.confidence;
    else body += ' · 측정 없음';
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
  view.to = Math.min(bars.length, view.to);
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
  const from = Math.max(0, Math.min(bars.length - span, dragging.from + shift));
  view.from = from; view.to = from + span;
  pinned = view.to >= bars.length;
  draw();
});

function confidenceCell(row) {
  return '<td class="num">' + (row.samples ? pct(row.win_rate) : '-') + '</td>'
    + '<td class="num ' + ((row.edge_win_rate || 0) > 0 ? 'up' : 'down') + '">' + (row.samples ? pctp(row.edge_win_rate) : '-') + '</td>'
    + '<td class="num muted">' + (row.samples || '-') + '</td>'
    + '<td class="muted">' + row.confidence + '</td>';
}

function renderPanels() {
  const f = frame();
  const forming = f.forming || [];
  document.getElementById('forming').innerHTML = forming.length
    ? forming.map((shape) => '<tr><td class="' + (shape.direction === 'bullish' ? 'up' : 'down') + '">'
        + (shape.direction === 'bullish' ? '▲ ' : '▼ ') + shape.label + '</td>'
        + '<td class="muted">' + shape.stage + '</td>'
        + '<td class="num">' + shape.trigger_label + ' ' + shape.trigger.toFixed(1) + '</td>'
        + '<td class="num ' + (shape.distance >= 0 ? 'up' : 'down') + '">' + (shape.distance >= 0 ? '+' : '') + (shape.distance * 100).toFixed(2) + '%</td>'
        + confidenceCell(shape) + '</tr>').join('')
    : '<tr><td colspan="8" class="empty">지금 형성 중인 구조 패턴이 없습니다. 완성된 패턴은 아래 표를 보세요.</td></tr>';

  const recent = f.hits.filter((hit) => hit.index >= f.bars.length - 40).slice(-14).reverse();
  document.getElementById('hits').innerHTML = recent.length
    ? recent.map((hit) => '<tr><td>' + hit.time_label + '</td>'
        + '<td class="' + (hit.direction === 'bullish' ? 'up' : 'down') + '">'
        + (hit.direction === 'bullish' ? '▲ ' : '▼ ') + hit.label + '</td>' + confidenceCell(hit) + '</tr>').join('')
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
    ? f.events.slice(-12).reverse().map((event) => '<tr><td>' + event.local_label + '</td>'
        + '<td>' + '★'.repeat(event.stars) + '</td><td>' + event.name + '</td>'
        + '<td class="muted">' + (event.index == null ? '차트 밖' : '표시됨') + '</td></tr>').join('')
    : '<tr><td colspan="4" class="empty">이 구간에 예정된 3성 지표가 없습니다.</td></tr>';

  const bias = f.bias || {};
  const el = document.getElementById('bias');
  el.textContent = bias.direction || '판단 보류';
  el.className = 'bias ' + (bias.direction === '상승 우세' ? 'up' : bias.direction === '하락 우세' ? 'down' : '');
  el.title = '완성 ' + (bias.completed || 0) + '건 · 형성 중 ' + (bias.forming || 0) + '건이 표본을 갖춰 반영됨';
}

function renderHeader() {
  const f = frame();
  document.getElementById('price').textContent = f.last_price.toFixed(1);
  document.getElementById('meta').textContent = f.bars.length + '봉 · 마지막 ' + f.bars[f.bars.length - 1][0] + ' KST';
}

let lastUpdate = null;     // when the chart last received anything
let lastError = null;
function liveText() {
  const live = document.getElementById('live');
  const text = live.querySelector('span');
  if (!DATA.data_url) { live.classList.add('stale'); text.textContent = '정지 화면 · ' + frame().generated_label; return; }
  if (lastError) { live.classList.add('stale'); text.textContent = '갱신 실패: ' + lastError; return; }
  if (!lastUpdate) { text.textContent = '연결 중'; return; }
  const ago = Math.max(0, Math.round((Date.now() - lastUpdate) / 1000));
  live.classList.toggle('stale', ago > (DATA.quote_seconds[current] || 10) * 4);
  text.textContent = '실시간 · ' + ago + '초 전 갱신';
}
setInterval(liveText, 1000);

function render(keepSpan) {
  renderHeader();
  if (!view || !keepSpan) resetView(false); else if (pinned) resetView(true);
  draw(); renderPanels(); liveText();
}

function apiUrl(path, interval, extra) {
  const base = DATA.data_url.replace(/\/data$/, '') + path;
  return base + (base.includes('?') ? '&' : '?') + 'interval=' + encodeURIComponent(interval) + (extra || '');
}

async function getJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error('HTTP ' + response.status);
  return response.json();
}

function fetchFrame(interval) { return getJson(apiUrl('/data', interval, '&bars=' + DATA.bars)); }
function fetchQuote(interval) { return getJson(apiUrl('/quote', interval)); }

function received() { lastUpdate = Date.now(); lastError = null; }
function failed(error) { lastError = (error && error.message) || String(error); liveText(); console.warn('goldlab refresh failed', error); }

async function refreshFrame() {
  const interval = current;
  const fresh = await fetchFrame(interval);
  if (interval !== current || !fresh || !fresh.bars || !fresh.bars.length) return;
  DATA.intervals[interval] = fresh; received(); render(true);
}

// Move the last candle with the newest quote; a bar in a newer bucket means a
// whole new candle, and that is the full redraw's job, so it is asked for.
async function refreshQuote() {
  const interval = current;
  const quote = await fetchQuote(interval);
  const f = frame();
  if (interval !== current || !quote || !quote.bars || !quote.bars.length || !f) return;
  received();
  const bucket = f.bucket_seconds || 60;
  const last = f.bars[f.bars.length - 1];
  const incoming = quote.bars[quote.bars.length - 1];
  const sameBar = Math.floor(last[5] / bucket) === Math.floor(incoming[5] / bucket);
  if (!sameBar) {
    if (incoming[5] > last[5]) { refreshFrame().catch(failed); }
    return;
  }
  f.bars[f.bars.length - 1] = incoming;
  f.last_price = incoming[4];
  for (const [period, values] of Object.entries(f.ma || {})) {
    if (values.length !== f.bars.length) continue;
    const n = parseInt(period, 10);
    if (f.bars.length >= n) {
      let sum = 0; for (let i = f.bars.length - n; i < f.bars.length; i++) sum += f.bars[i][4];
      values[values.length - 1] = Math.round(sum / n * 100) / 100;
    }
  }
  renderHeader(); draw(); liveText();
}

let quoteTimer = null;
function schedule() {
  if (timer) clearInterval(timer);
  if (quoteTimer) clearInterval(quoteTimer);
  if (!DATA.data_url) return;
  // Not gated on document.hidden: a tab embedded in an app, or in a second
  // window, reports itself hidden while it is plainly being watched.
  timer = setInterval(() => { refreshFrame().catch(failed); }, (DATA.poll_seconds[current] || 60) * 1000);
  quoteTimer = setInterval(() => { refreshQuote().catch(failed); }, (DATA.quote_seconds[current] || 10) * 1000);
}

async function select(interval) {
  current = interval;
  document.querySelectorAll('.tabs button').forEach((button) => button.classList.toggle('on', button.dataset.interval === interval));
  if (!DATA.intervals[interval]) {
    if (!DATA.data_url) return;
    loading.style.display = 'flex';
    try { DATA.intervals[interval] = await fetchFrame(interval); received(); }
    catch (error) { loading.textContent = interval + ' 시세를 불러오지 못했습니다 (' + ((error && error.message) || error) + ')'; failed(error); return; }
    finally { if (DATA.intervals[interval]) loading.style.display = 'none'; }
  } else if (DATA.data_url && !lastUpdate) {
    lastUpdate = Date.now();   // the inlined frame is as fresh as the page
  }
  view = null; render(false); schedule();
  if (DATA.data_url) refreshQuote().catch(failed);
}

document.querySelectorAll('.tabs button').forEach((button) => {
  button.addEventListener('click', () => select(button.dataset.interval));
});
document.querySelectorAll('.toggles input').forEach((input) => {
  input.addEventListener('change', () => { show[input.dataset.key] = input.checked; draw(); });
});
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && DATA.data_url) refreshFrame().catch(failed);
});
window.addEventListener('resize', resize);
select(current).then(resize);
"""


def _confidence(stats: Mapping[str, Any]) -> str:
    samples = int(stats.get("count") or 0)
    edge = stats.get("edge_win_rate")
    t_stat = abs(float(stats.get("t_stat") or 0))
    if not samples:
        return "측정 없음"
    if edge is None or edge <= 0:
        return "기준 미달"
    if t_stat >= 3:
        return "강함"
    if t_stat >= 2:
        return "보통"
    return "약함"


def _best_stats(study: Mapping[str, Any] | None, *, min_samples: int) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for row in (study or {}).get("patterns") or []:
        best = None
        for stats in (row.get("horizons") or {}).values():
            if int(stats.get("count") or 0) < min_samples:
                continue
            if best is None or abs(stats.get("t_stat") or 0) > abs(best.get("t_stat") or 0):
                best = stats
        if best:
            lookup[str(row.get("pattern"))] = best
    return lookup


def _label_time(stamp: datetime, interval: str) -> str:
    local = stamp.astimezone(KST)
    return local.strftime("%Y-%m-%d") if interval in DAILY_OR_LONGER else local.strftime("%m-%d %H:%M")


def _bar_row(bar: Any, interval: str) -> list[Any]:
    """Label, OHLC, and the epoch second the page uses to tell one candle from the next."""

    return [_label_time(bar.timestamp, interval), bar.open, bar.high, bar.low, bar.close, int(bar.timestamp.timestamp())]


def quote_payload(series: BarSeries, *, last: int = 3) -> dict[str, Any]:
    """The newest few candles only: what the page asks for every few seconds."""

    bars = series.bars[-last:]
    now = datetime.now(timezone.utc).astimezone(KST)
    return {
        "interval": series.interval,
        "bars": [_bar_row(bar, series.interval) for bar in bars],
        "bucket_seconds": BUCKET_SECONDS.get(series.interval, 60),
        "last_price": bars[-1].close if bars else None,
        "last_time": bars[-1].timestamp.astimezone(KST).isoformat() if bars else None,
        "generated_at": now.isoformat(),
        "generated_label": now.strftime("%H:%M:%S"),
    }


def _hit_rows(hits: Sequence[PatternHit], study: Mapping[str, Any] | None, *, min_samples: int = 30, interval: str = "1h") -> list[dict]:
    """Each hit with the measured record attached, ready to draw."""

    lookup = _best_stats(study, min_samples=min_samples)
    rows = []
    for hit in hits:
        stats = lookup.get(hit.pattern) or {}
        rows.append(
            {
                "index": hit.index,
                "time": hit.timestamp.astimezone(KST).isoformat(),
                "time_label": _label_time(hit.timestamp, interval),
                "pattern": hit.pattern,
                "label": hit.label,
                "direction": hit.direction,
                "samples": int(stats.get("count") or 0),
                "win_rate": stats.get("win_rate"),
                "edge_win_rate": stats.get("edge_win_rate"),
                "t_stat": stats.get("t_stat"),
                "confidence": _confidence(stats),
            }
        )
    return rows


def summarise_bias(hits: Sequence[Mapping[str, Any]], forming: Sequence[Mapping[str, Any]], *, min_samples: int = 30) -> dict[str, Any]:
    """One line for the header, weighted by each shape's measured edge.

    A count of arrows would let a dozen doji outvote one flag with a record, so
    each contributes its edge over the base rate, and only with the samples to
    have earned a vote. A shape still forming counts at half weight: it has not
    happened yet.
    """

    up = down = 0.0
    counted_completed = counted_forming = 0
    weighted = [(row, 1.0, "completed") for row in hits] + [(row, 0.5, "forming") for row in forming]
    for row, scale, kind in weighted:
        edge = row.get("edge_win_rate")
        if int(row.get("samples") or 0) < min_samples or edge is None:
            continue
        weight = abs(float(edge)) * (1 if abs(float(row.get("t_stat") or 0)) >= 2 else 0.4) * scale
        if kind == "completed":
            counted_completed += 1
        else:
            counted_forming += 1
        signed = weight if float(edge) > 0 else -weight
        if row.get("direction") == "bullish":
            up += signed
        else:
            down += signed
    total = up + down
    base = {"up": round(up, 4), "down": round(down, 4), "completed": counted_completed, "forming": counted_forming}
    if (counted_completed + counted_forming) == 0 or total <= 0:
        return {"direction": "판단 보류", **base}
    share = up / total
    direction = "상승 우세" if share >= 0.65 else ("하락 우세" if share <= 0.35 else "혼재")
    return {"direction": direction, "up_share": round(share, 4), **base}


def build_frame(
    series: BarSeries,
    *,
    study: Mapping[str, Any] | None = None,
    max_bars: int = 900,
    min_stars: int = 3,
    recent_hits: int = 40,
) -> dict[str, Any]:
    """Everything one timeframe needs, small enough to inline in a page."""

    interval = series.interval
    bars = series.bars[-max_bars:]
    trimmed = BarSeries(symbol=series.symbol, interval=interval, bars=bars)
    hits = _hit_rows(detect_patterns(trimmed), study, interval=interval)
    forming = attach_record(detect_forming(bars), study)
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
            local = when.astimezone(KST)
            events.append({**event, "index": index, "local": local.isoformat(), "local_label": local.strftime("%m-%d %H:%M")})

    recent = [hit for hit in hits if hit["index"] >= len(bars) - recent_hits]
    now = datetime.now(timezone.utc).astimezone(KST)
    return {
        "interval": interval,
        "bars": [_bar_row(bar, interval) for bar in bars],
        "bucket_seconds": BUCKET_SECONDS.get(interval, 60),
        "hits": hits,
        "forming": forming,
        "ma": moving_averages(bars),
        "trendlines": trend_lines(bars),
        "bias": summarise_bias(recent, forming),
        "sessions": windows,
        "session_rows": session_summary(windows, last=3),
        "events": events,
        "last_price": bars[-1].close if bars else 0.0,
        "last_time": bars[-1].timestamp.astimezone(KST).isoformat() if bars else None,
        "generated_at": now.isoformat(),
        "generated_label": now.strftime("%H:%M:%S"),
    }


def render_chart(
    frames: Mapping[str, Mapping[str, Any]],
    *,
    symbol: str = "GC=F",
    default_interval: str | None = None,
    title: str | None = None,
    intervals: Sequence[str] | None = None,
    data_url: str | None = None,
    bars: int = 600,
) -> str:
    """One page holding every timeframe, or fetching them from ``data_url``.

    With no data URL the page is self-contained and static: what it shows is
    what was inlined. With one, tabs load on demand and the timeframe on screen
    is refreshed on a timer, which is what makes the served chart live.
    """

    order = list(intervals) if intervals else list(frames)
    for interval in frames:
        if interval not in order:
            order.append(interval)
    chosen = default_interval if default_interval in order else (order[0] if order else "1h")
    if chosen not in frames and not data_url:
        chosen = next(iter(frames), chosen)
    payload = {
        "symbol": symbol,
        "default_interval": chosen,
        "intervals": dict(frames),
        "available": order,
        "data_url": data_url,
        "bars": bars,
        "poll_seconds": POLL_SECONDS,
        "quote_seconds": QUOTE_SECONDS,
    }
    tabs = "".join(
        f'<button data-interval="{html.escape(interval)}">{html.escape(interval)}</button>' for interval in order
    )
    legend = "".join(
        f'<span><i style="background:{session.colour}"></i>{html.escape(session.label)}</span>' for session in SESSIONS
    )
    generated = datetime.now(timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    refresh_note = (
        "마지막 봉은 5~30초마다 시세로 움직이고, 패턴·추세선·이동평균은 20초~10분마다 다시 계산됩니다. 시세는 제공처 기준이라 몇 분 지연될 수 있습니다."
        if data_url
        else "이 파일은 생성 시점의 정지 화면입니다. 실시간은 goldlab serve 명령이나 웹 주소를 이용하세요."
    )

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(title or f'{symbol} 패턴 차트')}</title>
<style>{CHART_CSS}</style></head><body>
<header>
  <h1>{html.escape(symbol)}</h1>
  <span class="price" id="price">-</span>
  <span class="bias" id="bias">판단 보류</span>
  <span class="muted" id="meta"></span>
  <span class="live" id="live"><i></i><span></span></span>
  <span class="tabs">{tabs}</span>
</header>
<div class="toggles">
  <label><input type="checkbox" data-key="patterns" checked> 완성 패턴</label>
  <label><input type="checkbox" data-key="forming" checked> 형성 중 패턴</label>
  <label><input type="checkbox" data-key="ma" checked> 이동평균 20·50·200</label>
  <label><input type="checkbox" data-key="trend" checked> 추세선</label>
  <label><input type="checkbox" data-key="sessions" checked> 세션 구분</label>
  <label><input type="checkbox" data-key="levels" checked> 세션 고저</label>
  <label><input type="checkbox" data-key="events" checked> 경제지표</label>
  <span class="muted">휠로 확대, 드래그로 이동, 봉 위에 올리면 상세</span>
</div>
<div class="chart-wrap"><canvas id="chart"></canvas><div id="tip"></div><div id="loading">불러오는 중…</div></div>
<div class="legend">{legend}
  <span><i style="background:#ffd166"></i>3성 지표</span>
  <span><i style="background:#f6465d"></i>상승 패턴</span>
  <span><i style="background:#2f6fed"></i>하락 패턴</span>
  <span><i class="line" style="background:#f5c518"></i>MA20</span>
  <span><i class="line" style="background:#3fb950"></i>MA50 · 지지선</span>
  <span><i class="line" style="background:#c678dd"></i>MA200</span>
  <span><i class="line" style="background:#ff7b72"></i>저항선</span>
  <span class="muted">흐린 화살표는 표본이 적거나 기준을 못 넘은 패턴, 점선 수평선은 형성 중인 패턴의 확인 가격입니다</span>
</div>
<div class="panels">
  <div class="card wide"><h2>형성 중인 패턴 <small>확인 가격에 닿으면 완성되며, 승률은 그 패턴의 과거 기록</small></h2><div class="scroll"><table>
    <thead><tr><th>패턴</th><th>진행</th><th>확인 가격</th><th>현재가 대비</th><th>완성 시 승률</th><th>기준대비</th><th>표본</th><th>신뢰도</th></tr></thead>
    <tbody id="forming"></tbody></table></div></div>
  <div class="card"><h2>최근 완성된 패턴</h2><div class="scroll"><table>
    <thead><tr><th>시각 (KST)</th><th>패턴</th><th>승률</th><th>기준대비</th><th>표본</th><th>신뢰도</th></tr></thead>
    <tbody id="hits"></tbody></table></div></div>
  <div class="card"><h2>세션별 고저</h2><div class="scroll"><table>
    <thead><tr><th>세션</th><th>현지 날짜</th><th>고</th><th>저</th><th>폭</th><th>변화</th></tr></thead>
    <tbody id="sessions"></tbody></table></div></div>
  <div class="card"><h2>미국 주요 지표</h2><div class="scroll"><table>
    <thead><tr><th>시각 (KST)</th><th>등급</th><th>지표</th><th>차트</th></tr></thead>
    <tbody id="events"></tbody></table></div></div>
</div>
<p class="note">{html.escape(generated)} KST 기준 · {html.escape(refresh_note)}<br>
승률과 기준대비는 같은 종목의 과거 같은 패턴에서 센 값이며 앞으로를 보장하지 않습니다. 형성 중인 패턴의 승률은 확인 가격을 지나 완성됐을 때의 과거 기록입니다.
시각은 모두 한국 시간(KST)입니다. 세션은 도쿄·런던·뉴욕 현지 영업시간 기준이라 서머타임을 따라 움직입니다.
추세선은 최근 두 개의 저점(지지)과 고점(저항)을 이은 선이며, 종가가 넘어선 선은 점선으로 바뀝니다.
FOMC와 물가지표처럼 날짜가 규칙으로 정해지지 않는 발표는 직접 입력한 일정만 표시합니다.</p>
<script>{CHART_JS.replace("__DATA__", json.dumps(payload, ensure_ascii=False))}</script>
</body></html>"""

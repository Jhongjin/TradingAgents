"""The page around the chart: a small dashboard, drawn with TradingView's library.

`goldlab.chart` builds the numbers (bars, patterns, forming shapes, bias); this
module only turns one frame of them into a page. Layout: a top bar (symbol,
timeframe, live status, last price), then a chart card with KPI tiles and the
recent signals, and a right rail with the current read, the shapes still
forming, the live record and a reserved card for similar past charts.

The page is a shell. It carries no price data of its own when it is given a
data URL: the browser asks for the frame, which keeps the first paint quick and
lets the symbol and timeframe switch without a reload. Without a data URL the
frames are inlined and the page is a static picture, which is what the
`goldlab chart` command writes to disk.

Everything here is presentation: every number shown was computed in `chart.py`.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .sessions import SESSIONS

KST = ZoneInfo("Asia/Seoul")

# Pinned to the same build the stock page loads (tradingagents/site/stock_page.py);
# a test keeps the two equal. unpkg is already allowed by the site's CSP.
LIGHTWEIGHT_CHARTS_SRC = "https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"

INTERVAL_LABELS = {"1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1D", "1wk": "1W", "1mo": "1M"}

DEFAULT_SYMBOLS = (
    {"key": "GC=F", "label": "GC 금", "name": "COMEX 금 선물", "precision": 1},
)

VIEW_CSS = """
:root { color-scheme: light dark;
  --bg:#f4f6fa; --card:#ffffff; --fg:#0f172a; --muted:#64748b; --line:#e2e8f0; --soft:#eef2f7;
  --up:#e5383b; --down:#2f6fed; --up-bg:rgba(229,56,59,.12); --down-bg:rgba(47,111,237,.12);
  --gold:#d4a017; --gold-bg:rgba(212,160,23,.16); --gold-fg:#8a6500; --shadow:0 1px 2px rgba(15,23,42,.06);
  --tip:rgba(255,255,255,.97); }
@media (prefers-color-scheme: dark) { :root {
  --bg:#0b0f17; --card:#121826; --fg:#e5e7eb; --muted:#94a3b8; --line:#1f2937; --soft:#1a2232;
  --up:#ff5d5d; --down:#5b8cff; --up-bg:rgba(255,93,93,.16); --down-bg:rgba(91,140,255,.16);
  --gold:#e0b341; --gold-bg:rgba(224,179,65,.18); --gold-fg:#e6c15f; --shadow:none;
  --tip:rgba(18,24,38,.97); } }
* { box-sizing:border-box; }
html, body { margin:0; background:var(--bg); color:var(--fg); }
body { font:13px/1.5 -apple-system,"Segoe UI","Malgun Gothic",system-ui,sans-serif; }
.gl { max-width:1480px; margin:0 auto; padding:16px; }
.top { display:flex; align-items:center; gap:12px 16px; flex-wrap:wrap; margin-bottom:14px; }
.brand { display:flex; align-items:center; gap:8px; font-weight:700; font-size:15px; letter-spacing:-.01em; }
.brand i { width:22px; height:22px; border-radius:7px; background:linear-gradient(135deg,#f5c84c,#b8860b); display:inline-block; }
.seg { display:inline-flex; background:var(--soft); border-radius:9px; padding:3px; gap:2px; flex-wrap:wrap; }
.seg button { all:unset; box-sizing:border-box; padding:5px 11px; border-radius:7px; font-weight:600; color:var(--muted); cursor:pointer; font-size:12px; }
.seg button:hover { color:var(--fg); }
.seg button:focus-visible { outline:2px solid var(--gold); outline-offset:1px; }
.seg button.on { background:var(--card); color:var(--fg); box-shadow:0 1px 2px rgba(0,0,0,.12); }
.price { margin-left:auto; display:flex; align-items:baseline; gap:10px; }
.price .code { color:var(--muted); font-size:12px; }
.price .v { font-size:22px; font-weight:700; font-variant-numeric:tabular-nums; min-width:5ch; text-align:right; }
.chip { display:inline-flex; align-items:center; gap:6px; padding:3px 9px; border-radius:999px; font-size:11px; font-weight:600; background:var(--soft); color:var(--muted); white-space:nowrap; }
.chip.up { background:var(--up-bg); color:var(--up); } .chip.down { background:var(--down-bg); color:var(--down); }
.chip.live:before { content:""; width:7px; height:7px; border-radius:50%; background:#94a3b8; }
.chip.live.on:before { background:var(--up); box-shadow:0 0 0 3px var(--up-bg); }
.chip.live.err:before { background:var(--down); }
.grid { display:grid; grid-template-columns:minmax(0,1fr) 320px; gap:14px; align-items:start; }
@media (max-width:900px) { .grid { grid-template-columns:1fr; } .price { margin-left:0; width:100%; } }
.col { display:flex; flex-direction:column; gap:14px; min-width:0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px; box-shadow:var(--shadow); min-width:0; }
.card > h3, .head { margin:0 0 10px; font-size:12px; font-weight:600; color:var(--muted); display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }
.card > h3 small, .head small { font-weight:400; font-size:11px; }
.tools { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px; }
.tog { all:unset; box-sizing:border-box; display:inline-flex; align-items:center; gap:6px; padding:3px 9px; border:1px solid var(--line); border-radius:999px; font-size:11px; font-weight:600; color:var(--muted); cursor:pointer; }
.tog i { width:8px; height:8px; border-radius:50%; background:currentColor; opacity:.35; }
.tog.on { color:var(--fg); border-color:var(--muted); } .tog.on i { opacity:1; }
.tog:focus-visible { outline:2px solid var(--gold); outline-offset:1px; }
.chart-box { position:relative; }
#chart { height:440px; }
@media (max-width:600px) { #chart { height:320px; } }
#tip { position:absolute; z-index:6; pointer-events:none; display:none; background:var(--tip); border:1px solid var(--line); border-radius:10px;
  padding:8px 10px; font-size:12px; line-height:1.55; max-width:290px; box-shadow:0 6px 20px rgba(0,0,0,.18); }
#tip b { font-weight:700; } #tip .m { color:var(--muted); }
.veil { position:absolute; inset:0; z-index:5; display:none; align-items:center; justify-content:center; text-align:center; padding:20px; color:var(--muted);
  background:linear-gradient(100deg,transparent 30%,rgba(148,163,184,.14) 50%,transparent 70%) 0 0/200% 100%, color-mix(in srgb,var(--card) 82%,transparent); }
.veil.show { display:flex; } .veil.busy { animation:sh 1.4s linear infinite; }
.veil button { all:unset; cursor:pointer; margin-top:8px; padding:5px 12px; border-radius:8px; background:var(--soft); color:var(--fg); font-weight:600; }
@keyframes sh { to { background-position:-200% 0, 0 0; } }
.legend { display:flex; gap:6px 14px; flex-wrap:wrap; margin-top:8px; font-size:11px; color:var(--muted); }
.legend i { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; vertical-align:-1px; }
.kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:12px; }
@media (max-width:700px) { .kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.kpi { border:1px solid var(--line); border-radius:10px; padding:9px 11px; min-width:0; }
.kpi .k { font-size:11px; color:var(--muted); } .kpi .v { font-size:16px; font-weight:700; font-variant-numeric:tabular-nums; margin-top:2px; }
.kpi .v.s { font-size:13px; line-height:1.5; padding-top:3px; } .kpi .sub { font-size:10.5px; color:var(--muted); }
.verdict { font-size:20px; font-weight:700; margin:2px 0 10px; }
.bar { height:8px; border-radius:99px; background:var(--soft); overflow:hidden; display:flex; }
.bar b { display:block; height:100%; transition:width .3s; }
.row { display:flex; justify-content:space-between; align-items:flex-start; padding:8px 0; border-top:1px solid var(--line); gap:10px; }
.row:first-child { border-top:0; }
.muted { color:var(--muted); font-size:11px; } .num { font-variant-numeric:tabular-nums; }
.up { color:var(--up); } .down { color:var(--down); }
.scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th { font-size:11px; color:var(--muted); text-align:left; font-weight:600; padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }
td { padding:8px; border-bottom:1px solid var(--line); white-space:nowrap; }
tr:last-child td { border-bottom:0; }
td.empty { white-space:normal; color:var(--muted); padding:16px 8px; }
.conf { display:inline-block; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:600; background:var(--soft); color:var(--muted); cursor:help; }
.conf.ok { background:var(--gold-bg); color:var(--gold-fg); }
.sk { display:block; height:12px; border-radius:6px; background:linear-gradient(100deg,var(--soft) 30%,var(--line) 50%,var(--soft) 70%) 0 0/200% 100%; animation:sh 1.4s linear infinite; }
.soon { border:1px dashed var(--line); border-radius:10px; padding:14px; color:var(--muted); text-align:center; line-height:1.6; }
.ledger { line-height:1.6; }
.notes { margin-top:14px; font-size:11.5px; color:var(--muted); line-height:1.75; }
.notes summary { cursor:pointer; font-weight:600; }
.notes p { margin:8px 0 0; }
.warn { color:var(--muted); font-size:11px; margin-top:6px; }
"""

VIEW_JS = r"""
const DATA = __DATA__;
const KST_SHIFT = 32400;                   // the chart draws UTC; shifting the stamps makes its clock read Korean time
const MA_COLOUR = { '20': '#d4a017', '50': '#6366f1', '200': '#a855f7' };
const ST = { symbol: DATA.symbol, interval: DATA.default_interval, cache: {}, frame: null, token: 0,
             show: { ma20: true, ma50: true, ma200: false, vol: true, hits: true, forming: true, trend: false, sessions: true, events: true },
             signalScope: 'recent', lowerTab: 'sessions', lastUpdate: null, lastError: null };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const symCfg = () => DATA.symbols.find((s) => s.key === ST.symbol) || DATA.symbols[0];
const prec = () => (symCfg() && symCfg().precision != null ? symCfg().precision : 1);
const fmt = (v) => (v == null ? '-' : Number(v).toLocaleString('en-US', { minimumFractionDigits: prec(), maximumFractionDigits: prec() }));
const pct = (v) => (v == null ? '-' : (v * 100).toFixed(1) + '%');
const pctp = (v) => (v == null ? '-' : (v > 0 ? '+' : '') + (v * 100).toFixed(1) + '%p');
const isDaily = () => ['1d', '1wk', '1mo'].includes(ST.interval);
const key = (symbol, interval) => symbol + '|' + interval;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------- data ----------
if (DATA.frames) for (const [interval, frame] of Object.entries(DATA.frames)) ST.cache[key(DATA.symbol, interval)] = frame;
function apiUrl(path, interval, extra) {
  const base = DATA.data_url.replace(/\/data$/, '') + path;
  return base + (base.includes('?') ? '&' : '?') + 'symbol=' + encodeURIComponent(ST.symbol) + '&interval=' + encodeURIComponent(interval) + (extra || '');
}
async function getJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error('HTTP ' + response.status);
  return response.json();
}
const fetchFrame = (interval) => getJson(apiUrl('/data', interval, '&bars=' + DATA.bars));
const fetchQuote = (interval) => getJson(apiUrl('/quote', interval));

// The first frame is requested now, in parallel with the chart library, not after it.
let firstLoad = null;
if (DATA.data_url && !ST.cache[key(ST.symbol, ST.interval)]) {
  firstLoad = fetchFrame(ST.interval).then((frame) => { ST.cache[key(ST.symbol, ST.interval)] = frame; return frame; });
  firstLoad.catch(() => {});
}

// ---------- chart ----------
let chart, candle, volume, markers, sessionPrim;
let maSeries = {}, trendSeries = [], priceLines = [];
let times = [], timeToIndex = new Map();

function chartColours() { return { text: css('--muted'), grid: css('--line') }; }
function applyTheme() {
  if (!chart) return;
  const c = chartColours();
  chart.applyOptions({ layout: { textColor: c.text }, grid: { horzLines: { color: c.grid } } });
  if (sessionPrim) sessionPrim.refresh();
}

function makeSessionPrimitive() {
  let request = null, wins = [], on = true, levels = true;
  const renderer = {
    draw(target) {
      if (!on || !wins.length || !chart) return;
      target.useMediaCoordinateSpace(({ context: c, mediaSize }) => {
        const ts = chart.timeScale();
        const half = ts.options().barSpacing / 2;
        for (const w of wins) {
          const x1 = ts.timeToCoordinate(w.t0), x2 = ts.timeToCoordinate(w.t1);
          if (x1 == null || x2 == null) continue;
          const left = x1 - half, right = x2 + half;
          if (right < 0 || left > mediaSize.width) continue;
          c.fillStyle = w.colour + '14'; c.fillRect(left, 0, Math.max(right - left, 1), mediaSize.height);
          c.strokeStyle = w.colour + '55'; c.setLineDash([3, 3]); c.lineWidth = 1;
          c.beginPath(); c.moveTo(left, 0); c.lineTo(left, mediaSize.height); c.stroke(); c.setLineDash([]);
          c.font = '10px system-ui'; c.fillStyle = w.colour;
          if (right - left > 52) c.fillText(w.label, Math.max(left, 0) + 4, 12);
          if (levels && right - left > 26) {
            for (const [price, tag] of [[w.high, '고'], [w.low, '저']]) {
              const y = candle.priceToCoordinate(price);
              if (y == null || y < 0 || y > mediaSize.height) continue;
              c.strokeStyle = w.colour + '99'; c.setLineDash([2, 4]);
              c.beginPath(); c.moveTo(left, y); c.lineTo(right, y); c.stroke(); c.setLineDash([]);
              c.font = '9px system-ui'; c.fillText(tag + ' ' + price.toFixed(prec()), left + 3, y - 2);
            }
          }
        }
      });
    },
  };
  return {
    attached(param) { request = param.requestUpdate; },
    detached() { request = null; },
    updateAllViews() {},
    paneViews() { return [{ zOrder: () => 'bottom', renderer: () => renderer }]; },
    set(next, enabled) { wins = next; on = enabled; if (request) request(); },
    refresh() { if (request) request(); },
  };
}

function buildChart() {
  const LC = window.LightweightCharts;
  const c = chartColours();
  chart = LC.createChart($('chart'), {
    autoSize: true,
    layout: { background: { type: 'solid', color: 'transparent' }, textColor: c.text, fontSize: 11 },
    grid: { vertLines: { color: 'transparent' }, horzLines: { color: c.grid } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 6 },
    crosshair: { mode: LC.CrosshairMode.Normal },
  });
  candle = chart.addSeries(LC.CandlestickSeries, { upColor: css('--up'), downColor: css('--down'), borderVisible: false, wickUpColor: css('--up'), wickDownColor: css('--down'), lastValueVisible: true, priceLineVisible: true });
  volume = chart.addSeries(LC.HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false });
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  for (const [period, colour] of Object.entries(MA_COLOUR)) {
    maSeries[period] = chart.addSeries(LC.LineSeries, { color: colour, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  }
  markers = LC.createSeriesMarkers(candle, []);
  sessionPrim = makeSessionPrimitive();
  candle.attachPrimitive(sessionPrim);
  chart.subscribeCrosshairMove(onCrosshair);
  if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
}

function rebuildTimes(f) {
  times = f.bars.map((b) => b[5] + KST_SHIFT);
  timeToIndex = new Map(); times.forEach((t, i) => timeToIndex.set(t, i));
}
function dataPoints(f) {
  const out = []; let last = -1;
  f.bars.forEach((b, i) => { const t = times[i]; if (t <= last) return; last = t; out.push({ time: t, open: b[1], high: b[2], low: b[3], close: b[4], vol: b[6] || 0 }); });
  return out;
}

function strong(hit) { return (hit.fdr === undefined ? true : !!hit.fdr) && (hit.confidence === '강함' || hit.confidence === '보통'); }

function drawOverlays(f) {
  const up = css('--up'), down = css('--down');
  const list = [];
  if (ST.show.hits) {
    for (const hit of f.hits) {
      if (hit.index == null || hit.index >= times.length) continue;
      const bull = hit.direction === 'bullish', s = strong(hit);
      list.push({ time: times[hit.index], position: bull ? 'belowBar' : 'aboveBar', shape: bull ? 'arrowUp' : 'arrowDown',
                  color: (bull ? up : down) + (s ? '' : '66'), size: s ? 1.3 : 0.7 });
    }
  }
  if (ST.show.events) {
    for (const ev of f.events) {
      if (ev.index == null || ev.index >= times.length) continue;
      list.push({ time: times[ev.index], position: 'aboveBar', shape: 'square', color: '#d4a017', size: 0.6, text: '★' });
    }
  }
  list.sort((a, b) => a.time - b.time);
  markers.setMarkers(list);

  priceLines.forEach((line) => candle.removePriceLine(line)); priceLines = [];
  if (ST.show.forming) {
    for (const shape of f.forming || []) {
      priceLines.push(candle.createPriceLine({ price: shape.trigger, color: shape.direction === 'bullish' ? up : down, lineStyle: 2, lineWidth: 1,
        axisLabelVisible: true, title: (shape.direction === 'bullish' ? '▲ ' : '▼ ') + shape.label }));
    }
  }

  trendSeries.forEach((s) => chart.removeSeries(s)); trendSeries = [];
  if (ST.show.trend) {
    for (const line of f.trendlines || []) {
      if (line.from_index >= times.length || line.to_index >= times.length || times[line.from_index] >= times[line.to_index]) continue;
      const s = chart.addSeries(window.LightweightCharts.LineSeries, { color: line.kind === 'low' ? up : down, lineWidth: 1.2, lineStyle: line.broken ? 2 : 0,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData([{ time: times[line.from_index], value: line.from_price }, { time: times[line.to_index], value: line.to_price }]);
      trendSeries.push(s);
    }
  }

  sessionPrim.set((f.sessions || []).filter((w) => w.end_index < times.length).map((w) => ({
    t0: times[w.start_index], t1: times[w.end_index], colour: w.colour, label: w.label, high: w.high, low: w.low })), ST.show.sessions);
}

function applyFrame(f, mode) {
  const ts = chart.timeScale();
  const prev = ts.getVisibleLogicalRange();
  const prevN = candle.data().length;
  let prevTimes = null;
  if (mode === 'refresh') { try { prevTimes = ts.getVisibleRange(); } catch (e) { prevTimes = null; } }
  rebuildTimes(f);
  const points = dataPoints(f);
  const hasVolume = points.some((p) => p.vol > 0);
  const upC = css('--up'), downC = css('--down');
  candle.setData(points);
  candle.applyOptions({ priceFormat: { type: 'price', precision: prec(), minMove: Math.pow(10, -prec()) } });
  volume.setData(points.map((p) => ({ time: p.time, value: p.vol, color: (p.close >= p.open ? upC : downC) + '55' })));
  volume.applyOptions({ visible: ST.show.vol && hasVolume });
  candle.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: ST.show.vol && hasVolume ? 0.2 : 0.06 } });
  for (const [period, series] of Object.entries(maSeries)) {
    const values = (f.ma || {})[period] || [];
    const rows = []; let last = -1;
    values.forEach((v, i) => { if (v != null && times[i] > last) { last = times[i]; rows.push({ time: times[i], value: v }); } });
    series.setData(rows);
    series.applyOptions({ visible: !!ST.show['ma' + period] });
  }
  drawOverlays(f);
  const n = points.length;
  if (mode === 'reset' || !prev) {
    ts.setVisibleLogicalRange({ from: Math.max(0, n - 150), to: n + 5 });
  } else {
    const pinned = prev.to >= prevN - 1.5;
    if (pinned) {
      const span = prev.to - prev.from, off = prev.to - (prevN - 1);
      ts.setVisibleLogicalRange({ from: n - 1 + off - span, to: n - 1 + off });
    } else if (prevTimes) {
      try { ts.setVisibleRange(prevTimes); } catch (e) { /* the old window left the data; keep the default */ }
    }
  }
}

// ---------- crosshair tooltip ----------
function onCrosshair(param) {
  const tip = $('tip'), f = ST.frame;
  if (!f || !param.time || !param.point || param.point.x < 0 || param.point.y < 0) { tip.style.display = 'none'; return; }
  const index = timeToIndex.get(param.time);
  const bar = index == null ? null : f.bars[index];
  if (!bar) { tip.style.display = 'none'; return; }
  const rising = bar[4] >= bar[1];
  let body = '<b>' + esc(bar[0]) + ' KST</b><br>시 ' + fmt(bar[1]) + ' · 고 ' + fmt(bar[2]) + ' · 저 ' + fmt(bar[3]) + ' · 종 <b class="' + (rising ? 'up' : 'down') + '">' + fmt(bar[4]) + '</b>';
  if (bar[6]) body += '<br><span class="m">거래량 ' + Math.round(bar[6]).toLocaleString('en-US') + '</span>';
  const parts = [];
  for (const [period, values] of Object.entries(f.ma || {})) if (values[index] != null && ST.show['ma' + period]) parts.push('MA' + period + ' ' + fmt(values[index]));
  if (parts.length) body += '<br><span class="m">' + parts.join(' · ') + '</span>';
  const wins = (f.sessions || []).filter((w) => w.start_index <= index && index <= w.end_index);
  if (wins.length) body += '<br><span class="m">세션 ' + wins.map((w) => esc(w.label) + ' (고 ' + fmt(w.high) + ' / 저 ' + fmt(w.low) + ')').join(', ') + '</span>';
  for (const ev of (f.events || []).filter((e) => e.index === index)) body += '<br><span style="color:var(--gold-fg)">' + '★'.repeat(ev.stars) + ' ' + esc(ev.name) + '</span>';
  for (const hit of (f.hits || []).filter((h) => h.index === index)) {
    body += '<br>' + (hit.direction === 'bullish' ? '▲' : '▼') + ' <b>' + esc(hit.label) + '</b>';
    body += hit.samples ? ' 승률 ' + pct(hit.win_rate) + ' (기준 대비 ' + pctp(hit.edge_win_rate) + '), 표본 ' + hit.samples + ', ' + esc(hit.confidence) : ' · 측정 없음';
  }
  tip.innerHTML = body; tip.style.display = 'block';
  const box = $('chart').getBoundingClientRect();
  const x = Math.min(Math.max(param.point.x + 16, 4), box.width - tip.offsetWidth - 4);
  const y = Math.min(Math.max(param.point.y - 12, 4), Math.max(box.height - tip.offsetHeight - 4, 4));
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}

// ---------- panels ----------
function confChip(row) {
  const basis = row.basis ? '근거: ' + row.basis : '';
  const fdr = row.fdr === undefined ? '' : (row.fdr ? ' · 거짓 발견율(FDR) 검사 통과' : ' · FDR 검사 미통과, 약함 이하로만 표시');
  const raw = row.raw_win_rate != null ? ' · 보정 전 승률 ' + pct(row.raw_win_rate) : '';
  const hz = row.horizon ? ' · 확인 기간 ' + row.horizon + '봉' : '';
  const star = row.basis && row.basis !== '전체' && row.shrunk ? ' *' : '';
  return '<span class="conf' + (row.fdr ? ' ok' : '') + '" title="' + esc(basis + fdr + raw + hz) + '">' + esc(row.confidence) + star + '</span>';
}

function renderHeader() {
  const f = ST.frame; if (!f || !f.bars.length) return;
  const last = f.bars[f.bars.length - 1];
  $('px').textContent = fmt(last[4]);
  let ref = null;
  if (isDaily()) ref = f.bars.length > 1 ? f.bars[f.bars.length - 2][4] : null;
  else { for (let i = f.bars.length - 1; i >= 0; i--) if (f.bars[i][5] <= last[5] - 86400) { ref = f.bars[i][4]; break; } if (ref == null) ref = f.bars[0][1]; }
  const chg = $('chg');
  if (ref) {
    const d = last[4] - ref;
    chg.textContent = (d >= 0 ? '+' : '') + fmt(d) + ' (' + (d >= 0 ? '+' : '') + (d / ref * 100).toFixed(2) + '%)';
    chg.className = 'chip ' + (d >= 0 ? 'up' : 'down');
  }
  chg.title = isDaily() ? '직전 봉 종가 대비' : '24시간 전 종가 대비';
  document.title = symCfg().label + ' ' + fmt(last[4]) + ' · Gold Lab';
}

function renderKpis() {
  const f = ST.frame; if (!f || !f.bars.length) return;
  const last = f.bars[f.bars.length - 1];
  const rows = isDaily() ? f.bars.slice(-20) : f.bars.filter((b) => b[5] > last[5] - 86400);
  $('k1').textContent = isDaily() ? '최근 20봉 고가' : '최근 24시간 고가';
  $('k2').textContent = isDaily() ? '최근 20봉 저가' : '최근 24시간 저가';
  $('hi').textContent = fmt(Math.max(...rows.map((b) => b[2])));
  $('lo').textContent = fmt(Math.min(...rows.map((b) => b[3])));
  const s = f.study_summary;
  $('fdr').textContent = s ? s.survivors + ' / ' + s.tested : '-';
  $('fdrsub').textContent = s ? 'FDR 통과 칸 / 검사한 칸' : '아직 측정 안 함';
  $('method').textContent = !s ? '측정 없음' : (s.method === 'walk_forward_v1' ? '순차 검증 · 수축 · FDR' : '구형 측정 (수축 없음)');
  $('methodsub').textContent = s ? (s.signals ? s.signals + '개 신호 · ' + s.start + ' ~ ' + s.end : '') : '';
}

function renderVerdict() {
  const b = (ST.frame && ST.frame.bias) || {};
  $('verdict').textContent = b.direction || '판단 보류';
  $('verdict').className = 'verdict ' + (b.direction === '상승 우세' ? 'up' : b.direction === '하락 우세' ? 'down' : '');
  $('cnt').textContent = '완성 ' + (b.completed || 0) + ' · 형성 ' + (b.forming || 0);
  const total = Math.abs(b.up || 0) + Math.abs(b.down || 0) || 1;
  $('bu').style.width = (Math.abs(b.up || 0) / total * 100) + '%';
  $('bd').style.width = (Math.abs(b.down || 0) / total * 100) + '%';
}

function renderForming() {
  const list = (ST.frame && ST.frame.forming) || [];
  $('form').innerHTML = list.length ? list.map((s) => {
    const rec = s.samples ? '완성 시 승률 ' + pct(s.win_rate) + ' · 기준 대비 ' + pctp(s.edge_win_rate) + ' · 표본 ' + s.samples : '완성 시 기록 측정 없음';
    return '<div class="row"><span><b class="' + (s.direction === 'bullish' ? 'up' : 'down') + '">' + (s.direction === 'bullish' ? '▲ ' : '▼ ') + esc(s.label) + '</b> ' + confChip(s)
      + '<br><span class="muted">' + esc(s.stage) + ' · ' + esc(rec) + '</span></span>'
      + '<span class="num" style="text-align:right">' + esc(s.trigger_label) + '<br><b>' + fmt(s.trigger) + '</b><br><span class="muted ' + (s.distance >= 0 ? 'up' : 'down') + '">' + (s.distance >= 0 ? '+' : '') + (s.distance * 100).toFixed(2) + '%</span></span></div>';
  }).join('') : '<div class="muted">지금 형성 중인 구조 패턴이 없습니다. 완성된 패턴은 최근 신호 표를 보세요.</div>';
}

function renderLedger() {
  const text = ST.frame && ST.frame.ledger_line;
  $('ledger').innerHTML = text ? esc(text).replace(/(\d+(?:\.\d+)?%)/g, '<b>$1</b>') : '<span class="muted">아직 기록이 없습니다.</span>';
}

function renderSignals() {
  const f = ST.frame; if (!f) return;
  const all = ST.signalScope === 'all';
  const rows = f.hits.filter((h) => all || h.index >= f.bars.length - 40).slice(all ? -30 : -14).reverse();
  $('sig').innerHTML = rows.length ? rows.map((h) => '<tr><td class="muted num">' + esc(h.time_label) + '</td>'
    + '<td><b class="' + (h.direction === 'bullish' ? 'up' : 'down') + '">' + (h.direction === 'bullish' ? '▲' : '▼') + '</b> ' + esc(h.label) + '</td>'
    + '<td class="num muted">' + (h.samples ? h.samples.toLocaleString('en-US') : '-') + '</td>'
    + '<td class="num">' + (h.samples ? pct(h.win_rate) : '-') + '</td>'
    + '<td class="num ' + ((h.edge_win_rate || 0) > 0 ? 'up' : 'down') + '">' + (h.samples ? pctp(h.edge_win_rate) : '-') + '</td>'
    + '<td>' + confChip(h) + '</td></tr>').join('')
    : '<tr><td colspan="6" class="empty">' + (all ? '이 구간에 완성된 패턴이 없습니다.' : '최근 40봉에 완성된 패턴이 없습니다.') + '</td></tr>';
}

function renderLower() {
  const f = ST.frame; if (!f) return;
  if (ST.lowerTab === 'sessions') {
    $('lowhead').innerHTML = '<tr><th>세션</th><th>현지 날짜</th><th>고</th><th>저</th><th>폭</th><th>변화</th></tr>';
    $('low').innerHTML = f.session_rows.length ? f.session_rows.map((r) => '<tr><td style="color:' + esc(r.colour) + ';font-weight:600">' + esc(r.label) + '</td><td class="muted">' + esc(r.day) + '</td>'
      + '<td class="num">' + fmt(r.high) + '</td><td class="num">' + fmt(r.low) + '</td><td class="num">' + fmt(r.range) + '</td>'
      + '<td class="num ' + (r.change >= 0 ? 'up' : 'down') + '">' + (r.change >= 0 ? '+' : '') + fmt(r.change) + '</td></tr>').join('')
      : '<tr><td colspan="6" class="empty">세션 구간이 없습니다.</td></tr>';
  } else {
    $('lowhead').innerHTML = '<tr><th>시각 (KST)</th><th>등급</th><th>지표</th><th>차트</th></tr>';
    $('low').innerHTML = f.events.length ? f.events.slice(-12).reverse().map((e) => '<tr><td class="num">' + esc(e.local_label) + '</td><td style="color:var(--gold-fg)">' + '★'.repeat(e.stars) + '</td><td>' + esc(e.name) + '</td>'
      + '<td class="muted">' + (e.index == null ? '차트 밖' : '표시됨') + '</td></tr>').join('')
      : '<tr><td colspan="4" class="empty">이 구간에 예정된 3성 지표가 없습니다.</td></tr>';
  }
}

function renderChrome() {
  const sc = symCfg();
  $('ctitle').textContent = sc.name + ' · ' + (DATA.interval_labels[ST.interval] || ST.interval);
  $('code').textContent = sc.key;
  document.querySelectorAll('[data-symbol]').forEach((b) => b.classList.toggle('on', b.dataset.symbol === ST.symbol));
  document.querySelectorAll('[data-interval]').forEach((b) => b.classList.toggle('on', b.dataset.interval === ST.interval));
}

function renderAll() {
  renderChrome(); renderHeader(); renderKpis(); renderVerdict(); renderForming(); renderLedger(); renderSignals(); renderLower(); liveText();
}

// ---------- live status ----------
function liveText() {
  const chip = $('live'), f = ST.frame;
  chip.classList.remove('on', 'err');
  if (!f) { chip.textContent = '불러오는 중'; return; }
  if (!DATA.data_url) { chip.textContent = '정지 화면 · ' + f.generated_label; return; }
  if (ST.lastError) { chip.classList.add('err'); chip.textContent = '갱신 실패 · ' + ST.lastError; return; }
  const delay = f.delay_seconds, bucket = f.bucket_seconds || 60;
  if (delay != null && delay > Math.max(bucket * 4, 1800)) {
    const last = f.bars[f.bars.length - 1];
    chip.textContent = '장 마감 · 마지막 봉 ' + last[0] + ' KST'; return;
  }
  const ago = ST.lastUpdate ? Math.max(0, Math.round((Date.now() - ST.lastUpdate) / 1000)) : null;
  const behind = delay != null && delay > 90 ? ' · 제공처 시세 약 ' + Math.round(delay / 60) + '분 지연' : '';
  if (ago != null && ago <= (DATA.quote_seconds[ST.interval] || 10) * 4) chip.classList.add('on');
  chip.textContent = (ago == null ? '연결 중' : '갱신 ' + ago + '초 전') + behind;
}
setInterval(liveText, 1000);

function received() { ST.lastUpdate = Date.now(); ST.lastError = null; }
function failed(error) { ST.lastError = (error && error.message) || String(error); liveText(); console.warn('goldlab refresh failed', error); }

// ---------- loading, switching, refreshing ----------
function veil(mode, text) {
  const v = $('veil');
  v.className = 'veil' + (mode ? ' show' : '') + (mode === 'busy' ? ' busy' : '');
  v.innerHTML = mode === 'error' ? '<div>' + esc(text) + '<br><button id="retry">다시 시도</button></div>' : (mode ? '<div>' + esc(text || '') + '</div>' : '');
  if (mode === 'error') $('retry').addEventListener('click', () => load());
}
function skeletonRows() {
  const row = '<tr>' + '<td><span class="sk"></span></td>'.repeat(6) + '</tr>';
  $('sig').innerHTML = row.repeat(4);
  $('form').innerHTML = '<span class="sk"></span><br><span class="sk" style="width:70%"></span>';
}

function updateUrl() {
  if (!DATA.data_url || !window.history || !history.replaceState) return;
  const params = new URLSearchParams(location.search);
  params.set('symbol', ST.symbol); params.set('interval', ST.interval);
  history.replaceState(null, '', location.pathname + '?' + params.toString());
}

async function load() {
  const symbol = ST.symbol, interval = ST.interval, token = ++ST.token;
  const k = key(symbol, interval);
  let frame = ST.cache[k];
  ST.frame = frame || null;
  renderChrome();
  if (!frame) {
    veil('busy', '시세를 불러오는 중'); skeletonRows(); $('px').textContent = '-'; $('chg').textContent = ''; $('chg').className = 'chip';
    try { frame = firstLoad && token === 1 ? await firstLoad : await fetchFrame(interval); }
    catch (error) {
      if (token !== ST.token) return;
      veil('error', symbol + ' ' + interval + ' 시세를 불러오지 못했습니다 (' + ((error && error.message) || error) + ')'); failed(error); return;
    }
    ST.cache[k] = frame;
    if (token !== ST.token) return;
    received();
  } else if (DATA.data_url && !ST.lastUpdate) { ST.lastUpdate = Date.now(); }   // an inlined frame is as fresh as the page
  ST.frame = frame; veil(null); renderAll();
  try { if (!chart) await chartReady; applyFrame(frame, 'reset'); }
  catch (error) { veil('error', '차트를 그리지 못했습니다 (' + ((error && error.message) || error) + ')'); console.warn(error); return; }
  schedule();
  if (DATA.data_url) refreshQuote().catch(failed);
}

async function refreshFrame() {
  const symbol = ST.symbol, interval = ST.interval;
  const fresh = await fetchFrame(interval);
  if (symbol !== ST.symbol || interval !== ST.interval || !fresh || !fresh.bars || !fresh.bars.length) return;
  ST.cache[key(symbol, interval)] = fresh; ST.frame = fresh; received();
  applyFrame(fresh, 'refresh'); renderAll();
}

// Move the last candle with the newest quote; a bar in a newer bucket means a
// whole new candle, and that is the full redraw's job, so it is asked for.
async function refreshQuote() {
  const symbol = ST.symbol, interval = ST.interval;
  const quote = await fetchQuote(interval);
  const f = ST.frame;
  if (symbol !== ST.symbol || interval !== ST.interval || !quote || !quote.bars || !quote.bars.length || !f || !chart) return;
  received();
  if (quote.delay_seconds != null) f.delay_seconds = quote.delay_seconds;
  const bucket = f.bucket_seconds || 60;
  const last = f.bars[f.bars.length - 1];
  const incoming = quote.bars[quote.bars.length - 1];
  if (Math.floor(last[5] / bucket) !== Math.floor(incoming[5] / bucket)) {
    if (incoming[5] > last[5]) refreshFrame().catch(failed);
    return;
  }
  f.bars[f.bars.length - 1] = incoming;
  const t = times[times.length - 1];
  candle.update({ time: t, open: incoming[1], high: incoming[2], low: incoming[3], close: incoming[4] });
  volume.update({ time: t, value: incoming[6] || 0, color: (incoming[4] >= incoming[1] ? css('--up') : css('--down')) + '55' });
  for (const [period, values] of Object.entries(f.ma || {})) {
    if (values.length !== f.bars.length) continue;
    const n = parseInt(period, 10);
    if (f.bars.length >= n) {
      let sum = 0; for (let i = f.bars.length - n; i < f.bars.length; i++) sum += f.bars[i][4];
      values[values.length - 1] = Math.round(sum / n * 100) / 100;
      maSeries[period].update({ time: t, value: values[values.length - 1] });
    }
  }
  renderHeader(); renderKpis(); liveText();
}

let timer = null, quoteTimer = null;
function schedule() {
  if (timer) clearInterval(timer);
  if (quoteTimer) clearInterval(quoteTimer);
  if (!DATA.data_url) return;
  // Not gated on document.hidden: a tab embedded in an app, or in a second
  // window, reports itself hidden while it is plainly being watched.
  timer = setInterval(() => { refreshFrame().catch(failed); }, (DATA.poll_seconds[ST.interval] || 60) * 1000);
  quoteTimer = setInterval(() => { refreshQuote().catch(failed); }, (DATA.quote_seconds[ST.interval] || 10) * 1000);
}

// ---------- wiring ----------
let chartReady = null;
function boot() {
  chartReady = Promise.resolve().then(() => { buildChart(); });
  document.querySelectorAll('[data-symbol]').forEach((b) => b.addEventListener('click', () => {
    if (b.dataset.symbol === ST.symbol) return;
    ST.symbol = b.dataset.symbol; updateUrl(); load();
  }));
  document.querySelectorAll('[data-interval]').forEach((b) => b.addEventListener('click', () => {
    if (b.dataset.interval === ST.interval) return;
    ST.interval = b.dataset.interval; updateUrl(); load();
  }));
  document.querySelectorAll('[data-toggle]').forEach((b) => b.addEventListener('click', () => {
    const k2 = b.dataset.toggle; ST.show[k2] = !ST.show[k2]; b.classList.toggle('on', ST.show[k2]); b.setAttribute('aria-pressed', String(ST.show[k2]));
    if (ST.frame && chart) { applyFrame(ST.frame, 'refresh'); }
  }));
  document.querySelectorAll('[data-scope]').forEach((b) => b.addEventListener('click', () => {
    ST.signalScope = b.dataset.scope; document.querySelectorAll('[data-scope]').forEach((x) => x.classList.toggle('on', x === b)); renderSignals();
  }));
  document.querySelectorAll('[data-lower]').forEach((b) => b.addEventListener('click', () => {
    ST.lowerTab = b.dataset.lower; document.querySelectorAll('[data-lower]').forEach((x) => x.classList.toggle('on', x === b)); renderLower();
  }));
  document.addEventListener('visibilitychange', () => { if (!document.hidden && DATA.data_url) refreshFrame().catch(failed); });
  load();
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
"""


def _json_for_script(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def render_page(
    frames: Mapping[str, Mapping[str, Any]],
    *,
    symbol: str,
    symbols: Sequence[Mapping[str, Any]] | None = None,
    default_interval: str,
    order: Sequence[str],
    data_url: str | None,
    bars: int,
    poll_seconds: Mapping[str, int],
    quote_seconds: Mapping[str, int],
    title: str | None = None,
    chart_src: str = LIGHTWEIGHT_CHARTS_SRC,
) -> str:
    """The whole page. `frames` may be empty when a data URL is given."""

    options = [dict(item) for item in (symbols or DEFAULT_SYMBOLS)]
    if symbol not in {item["key"] for item in options}:
        options.insert(0, {"key": symbol, "label": symbol, "name": symbol, "precision": 1})
    current = next(item for item in options if item["key"] == symbol)
    payload = {
        "symbol": symbol,
        "symbols": options,
        "default_interval": default_interval,
        "interval_labels": INTERVAL_LABELS,
        "frames": dict(frames) if frames else None,
        "data_url": data_url,
        "bars": bars,
        "poll_seconds": dict(poll_seconds),
        "quote_seconds": dict(quote_seconds),
    }
    symbol_buttons = (
        '<span class="seg" role="group" aria-label="종목">'
        + "".join(f'<button type="button" data-symbol="{html.escape(item["key"])}">{html.escape(item["label"])}</button>' for item in options)
        + "</span>"
        if len(options) > 1
        else ""
    )
    interval_buttons = "".join(
        f'<button type="button" data-interval="{html.escape(interval)}">{html.escape(INTERVAL_LABELS.get(interval, interval))}</button>' for interval in order
    )
    session_legend = "".join(f'<span><i style="background:{session.colour}"></i>{html.escape(session.label)}</span>' for session in SESSIONS)
    generated = datetime.now(timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    refresh_note = (
        "마지막 봉은 5~30초마다 시세로 움직이고, 패턴·추세선·이동평균은 20초~10분마다 다시 계산됩니다. 시세는 제공처 기준이라 몇 분 지연될 수 있습니다."
        if data_url
        else "이 파일은 생성 시점의 정지 화면입니다. 실시간은 goldlab serve 명령이나 웹 주소를 이용하세요."
    )
    toggles = [
        ("ma20", "MA20", MA_TOGGLE["20"], True),
        ("ma50", "MA50", MA_TOGGLE["50"], True),
        ("ma200", "MA200", MA_TOGGLE["200"], False),
        ("vol", "거래량", "#94a3b8", True),
        ("hits", "완성 패턴", "#16a34a", True),
        ("forming", "형성 중", "#dc2626", True),
        ("trend", "추세선", "#6366f1", False),
        ("sessions", "세션", "#d8a544", True),
        ("events", "경제지표", "#d4a017", True),
    ]
    toggle_html = "".join(
        f'<button type="button" class="tog{" on" if on else ""}" data-toggle="{key}" aria-pressed="{str(on).lower()}"><i style="color:{colour}"></i>{html.escape(label)}</button>'
        for key, label, colour, on in toggles
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(title or f'{current["label"]} · Gold Lab')}</title>
<style>{VIEW_CSS}</style>
<script src="{html.escape(chart_src)}" defer></script></head><body><div class="gl">
<div class="top">
  <span class="brand"><i></i>Gold Lab</span>
  {symbol_buttons}
  <span class="seg" role="group" aria-label="봉 간격">{interval_buttons}</span>
  <span class="chip live" id="live">불러오는 중</span>
  <div class="price"><span class="code" id="code">{html.escape(symbol)}</span><span class="v" id="px">-</span><span class="chip" id="chg"></span></div>
</div>
<div class="grid">
  <div class="col">
    <div class="card">
      <div class="head"><span id="ctitle">{html.escape(current["name"])}</span><small>휠로 확대 · 드래그로 이동 · 시각은 한국 시간(KST)</small></div>
      <div class="tools">{toggle_html}</div>
      <div class="chart-box"><div id="chart"></div><div id="tip"></div><div id="veil" class="veil show busy"><div>시세를 불러오는 중</div></div></div>
      <div class="legend">{session_legend}
        <span><i style="background:#d4a017"></i>3성 지표</span>
        <span>흐린 화살표는 표본이 적거나 검정을 못 넘은 패턴, 점선 수평선은 형성 중인 패턴의 확인 가격입니다</span>
      </div>
      <div class="kpis">
        <div class="kpi"><div class="k" id="k1">최근 24시간 고가</div><div class="v num" id="hi">-</div></div>
        <div class="kpi"><div class="k" id="k2">최근 24시간 저가</div><div class="v num" id="lo">-</div></div>
        <div class="kpi"><div class="k">검정 통과 패턴</div><div class="v num" id="fdr">-</div><div class="sub" id="fdrsub"></div></div>
        <div class="kpi"><div class="k">통계 방식</div><div class="v s" id="method">-</div><div class="sub" id="methodsub"></div></div>
      </div>
    </div>
    <div class="card">
      <div class="head"><span>최근 신호</span>
        <span class="seg"><button type="button" class="on" data-scope="recent">최근 40봉</button><button type="button" data-scope="all">차트 전체</button></span></div>
      <div class="scroll"><table><thead><tr><th>시각 (KST)</th><th>패턴</th><th>표본</th><th>승률 (보정)</th><th>기준 대비</th><th>신뢰도</th></tr></thead><tbody id="sig"></tbody></table></div>
      <div class="warn">승률은 신호 시점에 결과가 나와 있던 과거 신호만으로 센 뒤 표본 수에 따라 기준 쪽으로 당겨 보정한 값입니다. 신뢰도에 마우스를 올리면 근거와 FDR 결과가 보입니다.</div>
    </div>
    <div class="card">
      <div class="head"><span>세션과 지표</span>
        <span class="seg"><button type="button" class="on" data-lower="sessions">세션별 고저</button><button type="button" data-lower="events">미국 주요 지표</button></span></div>
      <div class="scroll"><table><thead id="lowhead"></thead><tbody id="low"></tbody></table></div>
    </div>
  </div>
  <div class="col">
    <div class="card"><h3><span>지금 판단</span><span id="cnt"></span></h3>
      <div class="verdict" id="verdict">-</div>
      <div class="bar"><b id="bu" style="background:var(--up);width:0"></b><span style="flex:1"></span><b id="bd" style="background:var(--down);width:0"></b></div>
      <div class="row muted" style="border:0;padding-bottom:0"><span>상승 근거</span><span>하락 근거</span></div>
      <div class="warn">패턴 개수가 아니라 각 패턴의 기준 대비 우위로 가중합니다. 검정을 통과하지 못한 패턴은 0.4배, 형성 중인 패턴은 절반으로 셉니다.</div>
    </div>
    <div class="card"><h3><span>형성 중</span><small>확인 가격까지</small></h3><div id="form"></div></div>
    <div class="card"><h3><span>실전 기록</span><small>실제로 낸 신호의 성적</small></h3><div class="ledger" id="ledger"></div></div>
    <div class="card"><h3><span>비슷한 과거 차트</span><small>준비 중</small></h3><div class="soon">최근 60봉과 가장 닮은 과거 10곳,<br>그 뒤 흐름의 분포가 여기에 표시됩니다.</div></div>
  </div>
</div>
<details class="notes"><summary>읽는 법과 한계</summary>
<p>{html.escape(generated)} KST 기준 · {html.escape(refresh_note)}</p>
<p>승률과 기준 대비는 같은 종목의 과거 같은 패턴에서 센 값이며 앞으로를 보장하지 않습니다. 형성 중인 패턴의 승률은 확인 가격을 지나 완성됐을 때의 과거 기록입니다.
승률 칸의 값은 신호 시점에 이미 결과가 나와 있던 과거 신호만으로 센 뒤 표본 수에 따라 기준 쪽으로 당겨 보정한 값이고, 많은 패턴을 한꺼번에 검사해 생기는 우연을 거르는 검사(FDR)를 통과하지 못하면 '약함' 이하로만 표시합니다. 신뢰도 옆 * 는 세션·추세 같은 맥락별 기록을 썼다는 뜻입니다.</p>
<p>시각은 모두 한국 시간(KST)입니다. 세션은 도쿄·런던·뉴욕 현지 영업시간 기준이라 서머타임을 따라 움직입니다.
추세선은 최근 두 개의 저점(지지)과 고점(저항)을 이은 선이며, 종가가 넘어선 선은 점선으로 바뀝니다.
FOMC와 물가지표처럼 날짜가 규칙으로 정해지지 않는 발표는 직접 입력한 일정만 표시합니다.</p>
</details>
<p class="warn" style="margin-top:12px">모든 수치는 과거 기록이며 거래 권유가 아닙니다. 차트는 <a href="https://www.tradingview.com/" rel="noopener noreferrer" target="_blank" style="color:inherit">TradingView Lightweight Charts</a> 기반입니다.</p>
</div>
<script>{VIEW_JS.replace("__DATA__", _json_for_script(payload))}</script>
</body></html>"""


MA_TOGGLE = {"20": "#d4a017", "50": "#6366f1", "200": "#a855f7"}

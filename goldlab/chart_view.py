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
svg.fan { width:100%; height:auto; display:block; } svg.fan text { font-size:8.5px; fill:var(--muted); }
svg.fan .fg { stroke:var(--line); stroke-width:1; stroke-dasharray:2 3; } svg.fan .fz { stroke:var(--muted); stroke-width:1; }
svg.fan .fl { fill:none; stroke-width:1.2; opacity:.38; } svg.fan .fl.up { stroke:var(--up); } svg.fan .fl.down { stroke:var(--down); }
svg.fan .fm { fill:none; stroke:var(--fg); stroke-width:2.4; }
.notes { margin-top:14px; font-size:11.5px; color:var(--muted); line-height:1.75; }
.notes summary { cursor:pointer; font-weight:600; }
.notes p { margin:8px 0 0; }
.warn { color:var(--muted); font-size:11px; margin-top:6px; }
.rev h4 { margin:14px 0 4px; font-size:12px; font-weight:700; }
.rev h4:first-child { margin-top:0; }
.rev ul { margin:0; padding-left:18px; line-height:1.65; }
.rev li { margin:2px 0; }
.rev sup.ev { color:var(--muted); font-size:9px; cursor:help; margin-left:2px; }
.rev .foot { margin-top:12px; padding-top:8px; border-top:1px solid var(--line); font-weight:600; }
.rev details { margin-top:10px; border:1px solid var(--line); border-radius:10px; padding:8px 10px; }
.rev details > summary { cursor:pointer; font-weight:600; color:var(--muted); font-size:12px; }
.turn { border-top:1px solid var(--line); padding:8px 0; margin-top:8px; }
.turn:first-of-type { border-top:0; }
.turn .who { display:flex; gap:8px; flex-wrap:wrap; align-items:baseline; }
.turn .tag { display:inline-block; padding:1px 7px; border-radius:6px; background:var(--soft); color:var(--muted); font-size:10.5px; font-weight:600; }
.turn .bad { color:var(--down); }
.jrn .kpis { margin-top:0; }
.jrn form { margin:12px 0; padding:12px; border:1px solid var(--line); border-radius:12px; background:var(--soft); }
.jrn .frow { display:flex; gap:8px 10px; flex-wrap:wrap; align-items:flex-end; margin-top:8px; }
.jrn .frow:first-child { margin-top:0; }
.jrn label { display:flex; flex-direction:column; gap:3px; font-size:11px; color:var(--muted); font-weight:600; }
.jrn input[type=text], .jrn input[type=number], .jrn input[type=datetime-local], .jrn input[type=password], .jrn select {
  font:inherit; font-size:13px; padding:6px 8px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--fg); min-width:0; }
.jrn input.w-price { width:104px; } .jrn input.w-n { width:64px; } .jrn input.w-time { width:172px; } .jrn input.w-reason { width:100%; }
.jrn .grow { flex:1 1 220px; }
.jrn button.act { all:unset; box-sizing:border-box; cursor:pointer; padding:7px 14px; border-radius:9px; font-weight:700; font-size:12.5px; background:var(--fg); color:var(--card); }
.jrn button.act.ghost { background:var(--card); color:var(--fg); border:1px solid var(--line); }
.jrn button.act:focus-visible, .jrn .tog:focus-visible { outline:2px solid var(--gold); outline-offset:1px; }
.jrn button.act[disabled] { opacity:.5; cursor:default; }
.jrn .side button.on.long { background:var(--up-bg); color:var(--up); } .jrn .side button.on.short { background:var(--down-bg); color:var(--down); }
.jrn .picks .tog.on { border-color:var(--gold); color:var(--gold-fg); }
.jrn .msg { font-size:12px; min-height:16px; } .jrn .msg.err { color:var(--down); }
.jrn tr.jr { cursor:pointer; } .jrn tr.jr:hover td { background:var(--soft); }
.jrn tr.jd td { white-space:normal; background:var(--soft); }
.jrn .jd .grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:6px 18px; font-size:12px; line-height:1.6; }
.jrn .tagchip { display:inline-block; padding:1px 7px; margin:0 3px 3px 0; border-radius:999px; background:var(--soft); font-size:10.5px; font-weight:600; color:var(--muted); }
.jrn tr.jd .tagchip { background:var(--card); }
.jrn .res.win { color:var(--up); font-weight:700; } .jrn .res.loss { color:var(--down); font-weight:700; }
.jrn .lock { display:flex; gap:8px; flex-wrap:wrap; align-items:center; justify-content:center; }
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
  chart.subscribeClick(onChartClick);
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
  for (const m of journalMarkers()) list.push(m);
  list.sort((a, b) => a.time - b.time);
  markers.setMarkers(list);
  drawJournalLines();

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

// ---------- similar past charts (research only: never a forecast) ----------
const ANALOG_SOON = '<div class="soon">최근 60봉과 가장 닮은 과거 10곳,<br>그 뒤 흐름의 분포가 여기에 표시됩니다.</div>';
const kstText = (iso) => new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const spct = (v) => (v == null ? '-' : (v > 0 ? '+' : '') + (v * 100).toFixed(2) + '%');

function fanSvg(a) {
  const W = 300, H = 150, L = 38, R = 16, T = 8, B = 18;
  const paths = a.analogs.map((x) => x.forward), med = a.median_path || [];
  const steps = Math.max(...paths.map((p) => p.length)) - 1;
  const all = []; paths.forEach((p) => p.forEach((v) => all.push(Math.abs(v)))); all.sort((x, y) => x - y);
  const lim = Math.max(all[Math.floor(all.length * 0.97)] || 0, 1e-4) * 1.1;
  const X = (i) => (L + (W - L - R) * i / steps).toFixed(1);
  const Y = (v) => (T + (H - T - B) * (1 - (Math.max(-lim, Math.min(lim, v)) + lim) / (2 * lim))).toFixed(1);
  const line = (p) => p.map((v, i) => (i ? 'L' : 'M') + X(i) + ' ' + Y(v)).join('');
  let s = '<svg class="fan" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="닮은 과거 구간 뒤의 흐름">';
  [lim, 0, -lim].forEach((v) => { s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(v) + '" y2="' + Y(v) + '" class="' + (v === 0 ? 'fz' : 'fg') + '"/><text x="' + (L - 4) + '" y="' + (Number(Y(v)) + 3) + '" text-anchor="end">' + (v > 0 ? '+' : '') + (v * 100).toFixed(1) + '%</text>'; });
  (a.horizons || []).forEach((h) => { if (h <= steps) s += '<line x1="' + X(h) + '" x2="' + X(h) + '" y1="' + T + '" y2="' + (H - B) + '" class="fg"/><text x="' + X(h) + '" y="' + (H - 4) + '" text-anchor="middle">+' + h + '</text>'; });
  paths.forEach((p) => { s += '<path d="' + line(p) + '" class="fl ' + (p[p.length - 1] >= 0 ? 'up' : 'down') + '"/>'; });
  if (med.length) s += '<path d="' + line(med) + '" class="fm"/>';
  return s + '</svg>';
}

function renderAnalogs() {
  const a = ST.frame && ST.frame.analogs, body = $('abody'), sub = $('asub');
  if (!a || !a.analogs || !a.analogs.length) { sub.textContent = '준비 중'; body.innerHTML = ANALOG_SOON; return; }
  const f = ST.frame, lastBar = f && f.bars.length ? f.bars[f.bars.length - 1][5] : 0;
  const ageH = (Date.now() - new Date(a.computed_at).getTime()) / 3600000;
  const trading = lastBar && (Date.now() / 1000 - lastBar) < 6 * 3600;      // bars are still arriving
  const stale = trading && ageH > 3;
  sub.innerHTML = '계산 ' + esc(kstText(a.computed_at)) + ' KST' + (stale ? ' · <b style="color:var(--down)">오래됨 (' + Math.floor(ageH) + '시간 전)</b>' : '');
  const rows = (a.horizons || []).map((h) => {
    const s = (a.summary || {})[String(h)]; if (!s) return '';
    const cls = s.median >= 0 ? 'up' : 'down';
    return '<tr><td class="muted">' + h + '봉 뒤</td><td class="num"><b class="' + (s.share_up >= 0.5 ? 'up' : 'down') + '">' + s.up + '/' + s.n + ' 상승</b><br><span class="muted">기준 ' + pct(s.base_share_up) + '</span></td>'
      + '<td class="num ' + cls + '">' + spct(s.median) + '<br><span class="muted">' + spct(s.q25) + ' ~ ' + spct(s.q75) + '</span></td></tr>';
  }).join('');
  const v = a.validation;
  const vrows = v ? Object.entries(v.horizons || {}).map(([h, r]) => esc(h) + '봉 적중 ' + pct(r.hit_rate) + ' (기준 ' + pct(r.base) + ', n=' + (r.n || 0) + ')').join(' · ') : '';
  const list = a.analogs.map((x) => '<div class="row" style="padding:5px 0"><span class="num">' + esc(kstText(x.end)) + '</span><span class="muted num">유사도 ' + (x.similarity * 100).toFixed(0) + '%</span></div>').join('');
  body.innerHTML = (stale ? '<div class="warn" style="margin:0 0 6px;color:var(--down)">계산한 지 오래돼 지금 차트와 어긋날 수 있습니다.</div>' : '')
    + fanSvg(a)
    + '<div class="muted" style="margin:2px 0 6px">가는 선: 닮은 ' + a.analogs.length + '곳의 그 뒤 흐름 (지금 종가를 0으로, 지금 변동성에 맞춰 환산) · 굵은 선: 중앙값</div>'
    + '<table><thead><tr><th></th><th>상승 비율</th><th>중앙값 (사분위)</th></tr></thead><tbody>' + rows + '</tbody></table>'
    + '<details style="margin-top:8px"><summary class="muted" style="cursor:pointer">닮은 ' + a.analogs.length + '곳 (종료 시각, KST)</summary>' + list + '</details>'
    + '<div class="warn"><b>' + (v ? esc(v.line) : '검증 기록 없음: 아직 순차 검증을 하지 않았습니다') + '</b>' + (vrows ? '<br>' + vrows : '') + '<br>과거 사례의 분포를 보여 줄 뿐 앞날의 예측이 아닙니다.</div>';
}

// ---------- AI review note (past-record review only: never advice) ----------
const REVIEW_SOON = '<div class="soon">거래일 한국 시간 오전 7시 마감 뒤, 그날 기록한 신호가 어떻게 됐는지<br>세 AI가 토론해 쓴 복기 노트가 여기에 표시됩니다.</div>';
const REVIEW_SECTIONS = [['summary', '오늘 장 요약'], ['signals', '신호와 결과 (맞음/틀림)'], ['context', '상황별로 본 것'], ['drift', '기록이 흔들리는 패턴'], ['journal', '내 판단 복기'], ['watch', '내일 볼 것 (관찰 포인트만)'], ['dissent', '이견']];
const arrows = (t) => esc(t).replace(/▲/g, '<b class="up">▲</b>').replace(/▼/g, '<b class="down">▼</b>');
const money = (v) => (v == null ? '-' : '$' + Number(v).toFixed(3));

function reviewItems(r, items) {
  const ev = r.evidence || {};
  return '<ul>' + (items || []).map((s) => '<li>' + arrows(s.text)
    + (s.evidence || []).map((id) => '<sup class="ev" title="' + esc(ev[id] || id) + '">' + esc(id) + '</sup>').join('') + '</li>').join('') + '</ul>';
}

function reviewTurn(r, t) {
  const o = t.output || {}, u = t.usage || {};
  let body = '';
  if (!t.ok) body = '<div class="bad">' + (t.skipped ? '건너뜀' : '실패') + ': ' + esc(t.error || '') + '</div>';
  else if (t.turn === 'critic') {
    body = '<ul>' + (o.challenges || []).map((c) => '<li><span class="tag">' + esc(c.type || '') + '</span> ' + arrows(c.text || '') + '</li>').join('') + '</ul>'
      + ((o.hypotheses || []).length ? '<div class="muted">제안한 가설</div><ul>' + o.hypotheses.map((h) => '<li>' + arrows(h.text || '') + '</li>').join('') + '</ul>' : '');
  } else if (t.turn === 'verifier') {
    const ps = o.problems || [];
    body = '<div class="muted">대조한 문장 ' + esc(o.checked == null ? '-' : o.checked) + '개 · 문제 ' + ps.length + '개</div>'
      + (ps.length ? '<ul>' + ps.map((p) => '<li><span class="tag">' + esc(p.status || '') + '</span> ' + arrows(p.text || '') + '<br><span class="muted">' + esc(p.reason || '') + '</span></li>').join('') + '</ul>' : '')
      + (o.overall ? '<div class="muted">' + arrows(o.overall) + '</div>' : '');
  } else {
    body = REVIEW_SECTIONS.filter(([k]) => (o[k] || []).length).map(([k, title]) => '<div class="muted">' + esc(title) + '</div><ul>' + (o[k] || []).map((s) => '<li>' + arrows(typeof s === 'string' ? s : (s.text || '')) + '</li>').join('') + '</ul>').join('');
  }
  return '<div class="turn"><div class="who"><b>' + esc(t.label) + '</b><span class="tag">' + esc(t.provider) + ' · ' + esc(t.model) + '</span><span class="muted">' + money(u.cost_usd) + ' · 입력 ' + (u.input_tokens || 0) + ' 출력 ' + (u.output_tokens || 0) + '</span></div>' + body + '</div>';
}

function renderReview() {
  const r = ST.frame && ST.frame.review, body = $('rbody'), sub = $('rsub');
  if (!r) { ST.reviewSig = null; sub.textContent = '준비 중'; body.innerHTML = REVIEW_SOON; return; }
  const sig = r.symbol + '|' + r.date + '|' + r.generated_at;
  if (ST.reviewSig === sig) return;                       // keep a opened 토론 보기 open across refreshes
  ST.reviewSig = sig;
  sub.innerHTML = esc(r.date) + ' (KST) · ' + (r.mode === 'debate' ? '3자 토론' : '<b style="color:var(--down)">단독 작성</b>') + ' · ' + money((r.usage || {}).cost_usd);
  const secs = REVIEW_SECTIONS.map(([k, title]) => {
    const items = (r.sections || {})[k] || [];
    if ((k === 'dissent' || k === 'journal') && !items.length) return '';
    return '<h4>' + esc(title) + '</h4>' + (items.length ? reviewItems(r, items) : '<div class="muted">근거가 확인된 내용이 없어 비웠습니다</div>');
  }).join('');
  const hyp = '<h4>검증할 가설</h4>' + ((r.hypotheses || []).length ? '<ul>' + r.hypotheses.map((h) => {
    const res = h.result;
    const tip = res ? '표본 ' + res.n + ' · 승률 ' + pct(res.win_rate) + ' (기준 ' + pct(res.base_win_rate) + ') · p ' + (res.p_value == null ? '-' : res.p_value) + ' · ' + (res.reason || '') : (h.expressible ? '주간 작업에서 10년 기록으로 검증합니다' : '검증 불가: ' + (h.why_not || ''));
    return '<li>' + arrows(h.text) + ' <span class="conf' + (h.status === '통과' ? ' ok' : '') + '" title="' + esc(tip) + '">' + esc(h.status) + '</span></li>';
  }).join('') + '</ul>' : '<div class="muted">제안된 가설이 없습니다</div>');
  const turns = (r.turns || []).map((t) => reviewTurn(r, t)).join('');
  const gone = r.guard_removed || [];
  const debate = '<details><summary>토론 보기 (분석가 초안 · 비판 · 검증 · 분석가 최종)</summary>' + turns
    + '<div class="muted" style="margin-top:8px">코드 점검: 증거 팩에 없는 숫자나 거래 권유로 읽히는 문장 ' + gone.length + '개를 지웠습니다.</div>'
    + (gone.length ? '<ul>' + gone.map((g) => '<li class="muted">' + esc(g.text) + ' <span class="tag">' + esc(g.reason) + (g.numbers && g.numbers.length ? ': ' + esc(g.numbers.join(', ')) : '') + '</span></li>').join('') + '</ul>' : '')
    + '</details>';
  body.innerHTML = '<div class="rev"><div class="muted" style="margin-bottom:8px">' + esc(r.mode_line || '') + ' · 작성 ' + esc(kstText(r.generated_at)) + ' KST</div>'
    + secs + hyp + debate + '<div class="foot">' + esc(r.footer) + '</div></div>';
}

// ---------- my own calls (private: every request carries the operator code) ----------
const TOKEN_KEY = 'tradingagents.admin.worker_token';       // the admin console keeps the same code here
const J = { entries: [], stats: null, tags: ['추세추종', '역추세', '돌파', '지표발표', '뉴스'], side: 'long', pick: null, chosen: new Set(), custom: [],
            dirty: { price: false, time: false }, open: new Set(), lines: [], draft: [], state: 'lock', timer: null, busy: false };
const jToken = () => { try { return (localStorage.getItem(TOKEN_KEY) || '').trim(); } catch (e) { return ''; } };
const SIDE_KO = { long: '롱', short: '숏', flat: '관망' };
const EXIT_KO = { manual: '직접 종료', stop: '스톱', target: '목표', horizon: '시간 종료', open: '진행 중' };
const usd = (v) => (v == null ? '-' : (v < 0 ? '-$' : '+$') + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 }));
const rtxt = (v) => (v == null ? '' : (v > 0 ? '+' : '') + v.toFixed(2) + 'R');
const kstInput = (d) => new Date(d).toLocaleString('sv-SE', { timeZone: 'Asia/Seoul' }).replace(' ', 'T').slice(0, 16);
const kstShort = (iso) => new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const fromKstInput = (v) => new Date(v + ':00+09:00').toISOString();
const pnlCls = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : '');

async function jfetch(method, path, body) {
  const response = await fetch('/api/admin/lab/gold/journal' + (path || ''), {
    method, cache: 'no-store',
    headers: Object.assign({ 'X-TradingAgents-Worker-Token': jToken() }, body ? { 'Content-Type': 'application/json' } : {}),
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null; try { data = await response.json(); } catch (e) { data = null; }
  if (!response.ok) { const err = new Error((data && data.detail) || ('HTTP ' + response.status)); err.status = response.status; throw err; }
  return data;
}

function jMessage(text, bad) { const m = $('jmsg'); if (m) { m.textContent = text || ''; m.className = 'msg' + (bad ? ' err' : ''); } }

function jSetState(state, note) {
  J.state = state;
  $('jlock').hidden = state === 'ready';
  $('jbody').hidden = state !== 'ready';
  $('jsub').textContent = state === 'ready' ? '내가 낸 판단을 기록하고 채점합니다 · 주문이 나가지 않습니다' : (note || '접근 코드를 입력하면 열립니다');
  $('jlockmsg').textContent = note || '';
}

async function loadJournal() {
  if (!jToken()) { jSetState('lock', ''); return; }
  try {
    const data = await jfetch('GET', '?limit=60');
    J.entries = data.entries || []; J.stats = data.stats; if (data.tags) J.tags = data.tags;
    jSetState('ready'); renderJournal(); renderJournalPrefill(); drawJournal();
  } catch (error) {
    if (error.status === 401 || error.status === 403) { jSetState('lock', '접근 코드가 맞지 않습니다'); return; }
    if (error.status === 503) { jSetState('lock', '저장소가 아직 준비되지 않았습니다: ' + error.message); return; }
    jSetState('lock', '불러오지 못했습니다: ' + error.message);
  }
  scheduleJournal();
}

function scheduleJournal() {
  if (J.timer) clearInterval(J.timer);
  J.timer = setInterval(() => { if (J.state === 'ready' && J.entries.some((e) => e.grade && e.grade.status === 'open' && e.side !== 'flat') && !J.busy) loadJournal().catch(() => {}); }, 60000);
}

function renderJournalPrefill() {
  if (J.state !== 'ready') return;
  const f = ST.frame; if (!f || !f.bars.length) return;
  const last = f.bars[f.bars.length - 1];
  if (!J.dirty.price && $('jprice')) $('jprice').value = last[4].toFixed(prec());
  if (!J.dirty.time && $('jtime')) $('jtime').value = kstInput(Date.now());
  const sc = symCfg(); if ($('jsym')) $('jsym').textContent = sc.label;
}

function renderTagChips() {
  const all = J.tags.concat(J.custom);
  $('jtags').innerHTML = all.map((t) => '<button type="button" class="tog' + (J.chosen.has(t) ? ' on' : '') + '" data-jtag="' + esc(t) + '" aria-pressed="' + J.chosen.has(t) + '"><i></i>' + esc(t) + '</button>').join('')
    + '<input type="text" id="jnewtag" maxlength="12" placeholder="+ 태그" style="width:84px" aria-label="새 태그">';
  document.querySelectorAll('[data-jtag]').forEach((b) => b.addEventListener('click', () => { const t = b.dataset.jtag; if (J.chosen.has(t)) J.chosen.delete(t); else if (J.chosen.size < 6) J.chosen.add(t); renderTagChips(); }));
  const nt = $('jnewtag');
  nt.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); const t = nt.value.trim().slice(0, 12); if (t && !J.tags.includes(t) && !J.custom.includes(t)) J.custom.push(t); if (t && J.chosen.size < 6) J.chosen.add(t); renderTagChips(); $('jnewtag').focus(); } });
}

function statBox(label, value, sub, cls) { return '<div class="kpi"><div class="k">' + esc(label) + '</div><div class="v num ' + (cls || '') + '">' + value + '</div><div class="sub">' + esc(sub || '') + '</div></div>'; }

function bucketRow(name, b) {
  return '<tr><td>' + esc(name) + '</td><td class="num">' + b.n + '</td><td class="num">' + (b.hit_rate == null ? '-' : pct(b.hit_rate)) + '</td><td class="num ' + pnlCls(b.avg_r) + '">' + (b.avg_r == null ? '-' : rtxt(b.avg_r)) + '</td><td class="num ' + pnlCls(b.net_usd) + '">' + usd(b.net_usd) + '</td></tr>';
}

function renderJournalStats() {
  const s = J.stats; if (!s) { $('jstats').innerHTML = ''; $('jtagtable').innerHTML = ''; return; }
  const t = s.total;
  $('jstats').innerHTML = statBox('종료한 판단', t.n + '건', '진행 중 ' + t.open + ' · 관망 ' + t.watch)
    + statBox('적중률', t.hit_rate == null ? '-' : pct(t.hit_rate), t.n ? t.wins + '/' + t.n + '건 이익' : '아직 없음')
    + statBox('평균 R', t.avg_r == null ? '-' : rtxt(t.avg_r), 'R = 비용 뺀 손익 / 스톱까지 위험 (' + t.r_n + '건)', pnlCls(t.avg_r))
    + statBox('순손익 (비용 후)', usd(t.net_usd), '슬리피지 1틱 양쪽 + 수수료', pnlCls(t.net_usd));
  const rows = [];
  for (const [tag, b] of Object.entries(s.by_tag || {})) rows.push(bucketRow('# ' + tag, b));
  const tr = { with: '추세 태그와 같은 방향', against: '추세 태그와 반대 방향', range: '추세 태그 횡보' };
  for (const [k, b] of Object.entries(s.by_trend || {})) rows.push(bucketRow(tr[k], b));
  const sg = { agree: '연구소 신호와 같은 쪽', against: '연구소 신호와 반대쪽', mixed: '연구소 신호 엇갈림', none: '직전 신호 없음' };
  for (const [k, b] of Object.entries(s.by_signal || {})) rows.push(bucketRow(sg[k], b));
  for (const [k, b] of Object.entries(s.by_side || {})) if (b.n) rows.push(bucketRow('방향 ' + SIDE_KO[k], b));
  $('jtagtable').innerHTML = rows.length ? '<table><thead><tr><th>구분</th><th>건수</th><th>적중</th><th>평균 R</th><th>순손익</th></tr></thead><tbody>' + rows.join('') + '</tbody></table>'
    + (t.small_sample ? '<div class="warn">종료한 판단이 ' + (30) + '건 미만이라 비율은 우연일 수 있습니다. 표본이 쌓일 때까지 참고만 하세요.</div>' : '') : '<div class="muted">종료한 판단이 쌓이면 태그별·맥락별 성적이 여기에 표시됩니다.</div>';
}

function entryDetail(e) {
  const g = e.grade || {}, lab = e.lab || {}, al = g.alignment || {};
  const bits = [];
  if (e.reason) bits.push('<div><b>이유</b> ' + esc(e.reason) + '</div>');
  if (e.tags && e.tags.length) bits.push('<div>' + e.tags.map((t) => '<span class="tagchip">' + esc(t) + '</span>').join('') + '</div>');
  const grade = [];
  if (e.side === 'flat') {
    if (g.bars_seen) grade.push('관망 뒤 ' + g.bars_seen + '봉: 변화 ' + fmt(g.move_points) + ' (' + (g.move_pct > 0 ? '+' : '') + g.move_pct + '%) · 위로 최대 ' + fmt(g.up_max_points) + ' · 아래로 최대 ' + fmt(g.down_max_points));
  } else {
    if (g.risk_points) grade.push('스톱까지 ' + fmt(g.risk_points) + ' (위험 ' + usd(g.risk_usd).replace('+', '') + ')');
    grade.push('총손익 ' + usd(g.gross_usd) + ' · 비용 -$' + Math.abs(g.cost_usd || 0).toFixed(0) + ' · 순손익 <b class="' + pnlCls(g.net_usd) + '">' + usd(g.net_usd) + '</b>' + (g.r_net != null ? ' · <b class="' + pnlCls(g.r_net) + '">' + rtxt(g.r_net) + '</b>' : ''));
    grade.push('보유 중 유리하게 최대 ' + fmt(g.mfe_points) + (g.mfe_r != null ? ' (' + g.mfe_r.toFixed(2) + 'R)' : '') + ' · 불리하게 최대 ' + fmt(g.mae_points) + (g.mae_r != null ? ' (' + g.mae_r.toFixed(2) + 'R)' : ''));
    if (g.plan_first && g.plan_first !== 'none') grade.push('계획 기준으로는 ' + (g.plan_first === 'stop' ? '스톱' : '목표') + '에 먼저 닿음' + (g.plan_ambiguous ? ' (한 봉이 둘 다 닿아 스톱 처리)' : ''));
    if (g.held_minutes != null) grade.push('보유 ' + (g.held_minutes >= 120 ? (g.held_minutes / 60).toFixed(1) + '시간' : g.held_minutes + '분'));
  }
  bits.push('<div class="grid2">' + grade.map((x) => '<div>' + x + '</div>').join('') + '</div>');
  const ctx = lab.context, lines = [];
  const CK = { session: { us: '미국장', europe: '유럽장', asia: '아시아장', off: '세션 밖' }, trend: { up: '상승 추세', down: '하락 추세', range: '횡보', unknown: '추세 불명' },
               vol: { low: '변동성 낮음', mid: '변동성 보통', high: '변동성 높음', unknown: '변동성 불명' }, event: { near: '지표 발표 근처', far: '지표와 먼 시간' } };
  if (ctx) lines.push('그 시각 맥락: ' + ['session', 'trend', 'vol', 'event'].map((k) => esc((CK[k] || {})[ctx[k]] || ctx[k])).join(' · '));
  const c = lab.signal_counts || {};
  if (lab.bar_before) lines.push('직전 1시간 연구소 신호: ▲ ' + (c.bullish || 0) + '건 · ▼ ' + (c.bearish || 0) + '건' + ((lab.signals || []).length ? ' (' + lab.signals.slice(0, 3).map((s) => esc(s.label)).join(', ') + ')' : ''));
  const an = lab.analogs && lab.analogs.summary;
  if (an) { const h = Object.keys(an).sort((a, b) => a - b)[0]; if (h && an[h]) lines.push('닮은 차트 ' + h + '봉 뒤 상승 비율 ' + pct(an[h].share_up)); }
  const rel = { agree: '기록 방향이 연구소 신호와 같은 쪽', against: '기록 방향이 연구소 신호와 반대쪽', mixed: '연구소 신호가 엇갈림' }[al.signals];
  const trel = { with: '추세 태그와 같은 방향', against: '추세 태그와 반대 방향', range: '추세 태그는 횡보' }[al.trend];
  if (rel || trel) lines.push([rel, trel].filter(Boolean).join(' · '));
  for (const flag of al.tag_flags || []) lines.push('<span class="down">' + esc(flag) + '</span>');
  for (const n of (lab.notes || []).concat(g.notes || [])) lines.push('<span class="muted">' + esc(n) + '</span>');
  if (lines.length) bits.push('<div class="muted" style="margin-top:6px"><b>연구소가 그 시각에 본 것</b> (진입 봉 이전 자료만)</div>' + lines.map((x) => '<div style="font-size:12px">' + x + '</div>').join(''));
  const actions = '<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
    + (e.side !== 'flat' && !e.exit_ts && g.status === 'open' ? '<span class="muted">직접 종료:</span><input type="number" step="any" class="w-price" data-jexit-price="' + esc(e.id) + '" placeholder="종료 가격"><button type="button" class="act ghost" data-jexit="' + esc(e.id) + '">종료 기록</button>' : '')
    + (e.exit_ts && e.side !== 'flat' ? '<button type="button" class="act ghost" data-jreopen="' + esc(e.id) + '">종료 취소 (자동 채점으로)</button>' : '')
    + '<button type="button" class="act ghost" data-jdel="' + esc(e.id) + '">삭제</button></div>';
  return '<tr class="jd"><td colspan="5">' + bits.join('') + actions + '</td></tr>';
}

function renderJournal() {
  renderJournalStats();
  const rows = J.entries.map((e) => {
    const g = e.grade || {}, sc = DATA.symbols.find((s) => s.key === e.symbol) || { label: e.symbol, precision: 1 };
    const px = (v) => (v == null ? '-' : Number(v).toLocaleString('en-US', { minimumFractionDigits: sc.precision, maximumFractionDigits: sc.precision }));
    const sideCls = e.side === 'long' ? 'up' : e.side === 'short' ? 'down' : '';
    let result;
    if (e.side === 'flat') result = '<span class="muted">관망' + (g.status === 'closed' && g.move_points != null ? ' · 이후 ' + (g.move_points > 0 ? '+' : '') + px(g.move_points) : ' · 진행 중') + '</span>';
    else if (g.status === 'open') result = '<span class="muted">진행 중 </span><span class="' + pnlCls(g.net_usd) + '">' + usd(g.net_usd) + (g.r_net != null ? ' · ' + rtxt(g.r_net) : '') + '</span>';
    else result = '<span class="res ' + g.result + '">' + usd(g.net_usd) + (g.r_net != null ? ' · ' + rtxt(g.r_net) : '') + '</span> <span class="muted">' + esc(EXIT_KO[g.exit_reason] || '') + '</span>';
    const open = J.open.has(e.id);
    return '<tr class="jr" data-jrow="' + esc(e.id) + '" tabindex="0" aria-expanded="' + open + '"><td class="muted num">' + esc(kstShort(e.entry_ts)) + '</td>'
      + '<td><b class="' + sideCls + '">' + SIDE_KO[e.side] + '</b> <span class="muted">' + esc(sc.label.split(' ')[0]) + ' ×' + e.contracts + '</span></td>'
      + '<td class="num">' + px(e.entry_price) + (g.exit_price != null && e.side !== 'flat' ? ' → ' + px(g.exit_price) : '') + '</td>'
      + '<td class="num">' + result + '</td>'
      + '<td>' + (e.tags || []).slice(0, 2).map((t) => '<span class="tagchip">' + esc(t) + '</span>').join('') + '</td></tr>' + (open ? entryDetail(e) : '');
  });
  $('jlist').innerHTML = rows.length ? '<div class="scroll"><table><thead><tr><th>시각 (KST)</th><th>판단</th><th>가격</th><th>결과 (비용 후)</th><th>태그</th></tr></thead><tbody>' + rows.join('') + '</tbody></table></div>'
    : '<div class="soon">아직 기록한 판단이 없습니다.<br>위 입력칸에서 방향을 고르고 기록하면 여기에 쌓이고, 채점은 5분봉으로 자동입니다.</div>';
  document.querySelectorAll('[data-jrow]').forEach((tr) => {
    const toggle = () => { const id = tr.dataset.jrow; if (J.open.has(id)) J.open.delete(id); else J.open.add(id); renderJournal(); };
    tr.addEventListener('click', toggle); tr.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); } });
  });
  document.querySelectorAll('[data-jdel]').forEach((b) => b.addEventListener('click', () => journalDelete(b.dataset.jdel)));
  document.querySelectorAll('[data-jexit]').forEach((b) => b.addEventListener('click', () => journalExit(b.dataset.jexit)));
  document.querySelectorAll('[data-jreopen]').forEach((b) => b.addEventListener('click', () => journalPatch(b.dataset.jreopen, { exit_ts: null, exit_price: null }, '종료를 취소했습니다')));
}

async function journalPatch(id, body, done) {
  if (J.busy) return; J.busy = true;
  try { await jfetch('PATCH', '/' + encodeURIComponent(id), body); jMessage(done || '저장했습니다'); await loadJournal(); }
  catch (error) { jMessage(error.message, true); }
  finally { J.busy = false; }
}
function journalExit(id) {
  const input = document.querySelector('[data-jexit-price="' + id + '"]');
  const price = input && input.value;
  if (!price) { jMessage('종료 가격을 입력하세요', true); return; }
  journalPatch(id, { exit_ts: new Date().toISOString(), exit_price: price }, '종료를 기록했습니다');
}
async function journalDelete(id) {
  if (!window.confirm('이 기록을 삭제할까요? 되돌릴 수 없습니다.')) return;
  if (J.busy) return; J.busy = true;
  try { await jfetch('DELETE', '/' + encodeURIComponent(id)); J.open.delete(id); jMessage('삭제했습니다'); await loadJournal(); }
  catch (error) { jMessage(error.message, true); }
  finally { J.busy = false; }
}

async function journalSubmit(ev) {
  ev.preventDefault();
  if (J.busy) return;
  const body = { symbol: ST.symbol, interval: ST.interval, side: J.side, entry_price: $('jprice').value, entry_ts: fromKstInput($('jtime').value),
                 stop: $('jstop').value || null, target: $('jtarget').value || null, contracts: $('jn').value || 1, reason: $('jreason').value,
                 tags: Array.from(J.chosen), horizon_bars: $('jhorizon').value };
  if (J.side === 'flat') { body.stop = null; body.target = null; }
  J.busy = true; $('jgo').disabled = true; jMessage('저장하는 중');
  try {
    const out = await jfetch('POST', '', body);
    J.open.add(out.entry.id);
    $('jstop').value = ''; $('jtarget').value = ''; $('jreason').value = ''; J.chosen.clear(); J.dirty = { price: false, time: false }; setPick(null);
    renderTagChips(); renderJournalPrefill(); drawDraft();
    jMessage('기록했습니다 (연구소가 그 시각에 본 것도 함께 저장됨)'); J.busy = false; await loadJournal();
  } catch (error) { jMessage(error.message, true); }
  finally { J.busy = false; $('jgo').disabled = false; }
}

// ---- chart: click to set a price, draft lines, saved lines and markers ----
function setPick(kind) {
  J.pick = J.pick === kind ? null : kind;
  document.querySelectorAll('[data-pick]').forEach((b) => { const on = b.dataset.pick === J.pick; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
  const c = $('chart'); if (c) c.style.cursor = J.pick ? 'crosshair' : '';
  jMessage(J.pick ? { entry: '차트에서 기록할 가격을 클릭하세요', stop: '차트에서 스톱 가격을 클릭하세요', target: '차트에서 목표 가격을 클릭하세요' }[J.pick] : '');
}
function onChartClick(param) {
  if (!J.pick || J.state !== 'ready' || !param.point || !candle) return;
  const raw = candle.coordinateToPrice(param.point.y); if (raw == null) return;
  const price = raw.toFixed(prec());
  if (J.pick === 'entry') {
    $('jprice').value = price; J.dirty.price = true;
    const f = ST.frame, lastT = times.length ? times[times.length - 1] : null;
    if (param.time && lastT != null && param.time < lastT) { $('jtime').value = kstInput((param.time - KST_SHIFT) * 1000); J.dirty.time = true; }
    else { $('jtime').value = kstInput(Date.now()); J.dirty.time = false; }
  } else if (J.pick === 'stop') $('jstop').value = price; else $('jtarget').value = price;
  setPick(null); drawDraft();
}
function lineOpts(price, colour, style, title) { return { price, color: colour, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }; }
function drawDraft() {
  if (!candle) return;
  J.draft.forEach((l) => candle.removePriceLine(l)); J.draft = [];
  if (J.state !== 'ready' || J.side === 'flat') return;
  const num = (id) => { const v = parseFloat($(id).value); return isFinite(v) && v > 0 ? v : null; };
  const e = num('jprice'), s = num('jstop'), t = num('jtarget');
  const col = J.side === 'long' ? css('--up') : css('--down');
  if (e && (s || t)) J.draft.push(candle.createPriceLine(lineOpts(e, col, 1, '기록 가격 (미저장)')));
  if (s) J.draft.push(candle.createPriceLine(lineOpts(s, css('--muted'), 3, '스톱 (미저장)')));
  if (t) J.draft.push(candle.createPriceLine(lineOpts(t, css('--gold'), 3, '목표 (미저장)')));
}
function barTimeFor(sec) {
  // the chart bar an instant falls in: the last bar that opened at or before it
  let lo = 0, hi = times.length - 1, best = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (times[mid] - KST_SHIFT <= sec) { best = mid; lo = mid + 1; } else hi = mid - 1; }
  return best < 0 ? null : times[best];
}
function journalMarkers() {
  const out = [], up = css('--up'), down = css('--down'), muted = css('--muted');
  if (J.state !== 'ready') return out;
  for (const e of J.entries) {
    if (e.symbol !== ST.symbol) continue;
    const g = e.grade || {}, t = barTimeFor(new Date(e.entry_ts).getTime() / 1000);
    if (t == null) continue;
    const win = g.result === 'win' ? up : g.result === 'loss' ? down : muted;
    const tail = g.status === 'closed' && e.side !== 'flat' ? ' ' + (g.r_net != null ? rtxt(g.r_net) : usd(g.net_usd)) : '';
    if (e.side === 'long') out.push({ time: t, position: 'belowBar', shape: 'arrowUp', color: up, size: 1.4, text: '롱' + tail });
    else if (e.side === 'short') out.push({ time: t, position: 'aboveBar', shape: 'arrowDown', color: down, size: 1.4, text: '숏' + tail });
    else out.push({ time: t, position: 'aboveBar', shape: 'circle', color: muted, size: 1, text: '관망' });
    if (e.side !== 'flat' && g.status === 'closed' && g.exit_ts) {
      const x = barTimeFor(new Date(g.exit_ts).getTime() / 1000);
      if (x != null) out.push({ time: x, position: e.side === 'long' ? 'aboveBar' : 'belowBar', shape: 'circle', color: win, size: 0.9, text: EXIT_KO[g.exit_reason] });
    }
  }
  return out;
}
function drawJournal() { if (ST.frame && chart) drawOverlays(ST.frame); }
function drawJournalLines() {
  if (!candle) return;
  J.lines.forEach((l) => candle.removePriceLine(l)); J.lines = [];
  if (J.state === 'ready') {
    for (const e of J.entries) {
      if (e.symbol !== ST.symbol || e.side === 'flat' || !e.grade || e.grade.status !== 'open') continue;
      const col = e.side === 'long' ? css('--up') : css('--down'), name = SIDE_KO[e.side];
      J.lines.push(candle.createPriceLine(lineOpts(e.entry_price, col, 0, name + ' 기록 ' + e.contracts + '계약')));
      if (e.stop) J.lines.push(candle.createPriceLine(lineOpts(e.stop, css('--muted'), 2, name + ' 스톱')));
      if (e.target) J.lines.push(candle.createPriceLine(lineOpts(e.target, css('--gold'), 2, name + ' 목표')));
    }
  }
  drawDraft();
}

function initJournal() {
  renderTagChips();
  $('jsave').addEventListener('click', () => {
    const v = $('jcode').value.trim(); if (!v) return;
    try { localStorage.setItem(TOKEN_KEY, v); } catch (e) { $('jlockmsg').textContent = '이 브라우저는 코드를 저장하지 못합니다'; return; }
    $('jcode').value = ''; loadJournal();
  });
  $('jcode').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('jsave').click(); } });
  $('jforget').addEventListener('click', () => { try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ } J.entries = []; J.stats = null; jSetState('lock', '접근 코드를 지웠습니다'); drawJournal(); });
  document.querySelectorAll('[data-jside]').forEach((b) => b.addEventListener('click', () => {
    J.side = b.dataset.jside;
    document.querySelectorAll('[data-jside]').forEach((x) => x.classList.toggle('on', x === b));
    document.querySelectorAll('[data-jside]').forEach((x) => { x.classList.remove('long', 'short'); }); b.classList.add(J.side === 'long' ? 'long' : J.side === 'short' ? 'short' : 'x');
    const flat = J.side === 'flat'; $('jstop').disabled = flat; $('jtarget').disabled = flat; drawDraft();
  }));
  document.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => setPick(b.dataset.pick)));
  $('jprice').addEventListener('input', () => { J.dirty.price = true; drawDraft(); });
  $('jtime').addEventListener('input', () => { J.dirty.time = true; });
  $('jstop').addEventListener('input', drawDraft); $('jtarget').addEventListener('input', drawDraft);
  $('jform').addEventListener('submit', journalSubmit);
  loadJournal();
}

function renderChrome() {
  const sc = symCfg();
  $('ctitle').textContent = sc.name + ' · ' + (DATA.interval_labels[ST.interval] || ST.interval);
  $('code').textContent = sc.key;
  document.querySelectorAll('[data-symbol]').forEach((b) => b.classList.toggle('on', b.dataset.symbol === ST.symbol));
  document.querySelectorAll('[data-interval]').forEach((b) => b.classList.toggle('on', b.dataset.interval === ST.interval));
}

function renderAll() {
  renderChrome(); renderHeader(); renderKpis(); renderVerdict(); renderForming(); renderLedger(); renderSignals(); renderLower(); renderAnalogs(); renderReview(); renderJournalPrefill(); liveText();
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
  if (DATA.data_url && $('jcard')) initJournal();
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
    journal_card = (
        '<div class="card jrn" id="jcard"><h3><span>내 판단 기록</span><small id="jsub">접근 코드를 입력하면 열립니다</small></h3>'
        '<div id="jlock" class="soon"><div class="lock"><input type="password" id="jcode" autocomplete="off" placeholder="접근 코드" aria-label="접근 코드" style="width:180px">'
        '<button type="button" class="act" id="jsave">열기</button></div>'
        '<div class="muted" id="jlockmsg" style="margin-top:8px"></div>'
        '<div class="muted" style="margin-top:6px">운영 토큰(관리 화면에서 쓰는 것과 같은 값)을 이 브라우저에만 저장합니다. 코드 없이는 기록을 쓰거나 읽을 수 없습니다.</div></div>'
        '<div id="jbody" class="jrn-body" hidden>'
        '<div class="kpis" id="jstats"></div>'
        '<form id="jform" autocomplete="off">'
        '<div class="frow"><span class="seg side" role="group" aria-label="방향">'
        '<button type="button" class="on long" data-jside="long">롱</button><button type="button" data-jside="short">숏</button><button type="button" data-jside="flat">관망</button></span>'
        '<span class="picks" style="display:flex;gap:6px;flex-wrap:wrap">'
        '<button type="button" class="tog" data-pick="entry" aria-pressed="false"><i></i>차트에서 가격·시각</button>'
        '<button type="button" class="tog" data-pick="stop" aria-pressed="false"><i></i>스톱 찍기</button>'
        '<button type="button" class="tog" data-pick="target" aria-pressed="false"><i></i>목표 찍기</button></span>'
        '<span class="muted">종목 <b id="jsym"></b> (위에서 고른 종목 기준)</span></div>'
        '<div class="frow">'
        '<label>기록 시각 (KST)<input type="datetime-local" id="jtime" class="w-time" required></label>'
        '<label>기록 가격<input type="number" step="any" id="jprice" class="w-price" required></label>'
        '<label>스톱<input type="number" step="any" id="jstop" class="w-price"></label>'
        '<label>목표<input type="number" step="any" id="jtarget" class="w-price"></label>'
        '<label>계약<input type="number" min="1" max="100" value="1" id="jn" class="w-n"></label>'
        '<label>자동 종료<select id="jhorizon"><option value="72">6시간</option><option value="144" selected>12시간</option>'
        '<option value="288">24시간</option><option value="864">3일</option></select></label></div>'
        '<div class="frow"><label class="grow">이유 (한 줄)<input type="text" id="jreason" class="w-reason" maxlength="300" placeholder="왜 이 방향으로 판단했는지"></label></div>'
        '<div class="frow"><span class="muted">태그</span><span id="jtags" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"></span></div>'
        '<div class="frow"><button class="act" id="jgo" type="submit">판단 기록</button><span class="msg" id="jmsg" role="status"></span></div>'
        '</form>'
        '<div id="jlist"></div>'
        '<details class="notes" style="margin-top:10px"><summary>태그·맥락별 성적</summary><div id="jtagtable" style="margin-top:8px"></div></details>'
        '<div class="warn">종료 가격을 적지 않으면 스톱·목표·자동 종료 시간 중 먼저 오는 쪽으로 5분봉에서 자동 채점합니다. 한 봉이 스톱과 목표에 모두 닿으면 스톱으로 칩니다. '
        '손익은 슬리피지 1틱(양쪽)과 수수료를 뺀 값이고, 연구소가 그 시각에 본 것은 진입 봉 이전 자료만 씁니다. 주문은 나가지 않습니다. '
        '<button type="button" class="act ghost" id="jforget" style="padding:3px 9px;font-size:11px">이 브라우저의 접근 코드 지우기</button></div>'
        '</div></div>'
        if data_url
        else ""
    )
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
    {journal_card}
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
    <div class="card" id="rcard"><h3><span>AI 복기</span><small id="rsub">준비 중</small></h3><div id="rbody"><div class="soon">거래일 한국 시간 오전 7시 마감 뒤, 그날 기록한 신호가 어떻게 됐는지<br>세 AI가 토론해 쓴 복기 노트가 여기에 표시됩니다.</div></div></div>
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
    <div class="card" id="acard"><h3><span>비슷한 과거 차트</span><small id="asub">준비 중</small></h3><div id="abody"><div class="soon">최근 60봉과 가장 닮은 과거 10곳,<br>그 뒤 흐름의 분포가 여기에 표시됩니다.</div></div></div>
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

"""Server-rendered public pages for the TradingAgents Korea site."""

from __future__ import annotations

import html
import json
from typing import Any

from tradingagents.storage import StorageRepository

from .public_api import build_public_stock_payload
from .seo import stock_canonical_url


def render_public_stock_page(
    ticker: str,
    *,
    repo: StorageRepository | None = None,
    chart_start: str | None = None,
    chart_end: str | None = None,
    as_of_date: str | None = None,
    max_analysis_age_days: int = 1,
    site_base_url: str | None = None,
) -> str:
    """Render the first public stock-analysis page.

    The page intentionally stays dependency-free: it uses the same JSON payload
    as the API and draws the price chart with a small inline canvas renderer.
    """

    payload = build_public_stock_payload(
        ticker,
        repo=repo,
        chart_start=chart_start,
        chart_end=chart_end,
        as_of_date=as_of_date,
        max_analysis_age_days=max_analysis_age_days,
    )
    model = _view_model(payload, site_base_url=site_base_url)
    payload_json = _script_json(payload)
    reports_html = _report_cards(model["reports"])
    notices_html = "".join(f"<li>{_h(notice)}</li>" for notice in payload.get("notices", []))

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(model["title"])}</title>
  <meta name="description" content="{_h(model["description"])}">
  <link rel="canonical" href="{_h(model["canonical_url"])}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(model["title"])}">
  <meta property="og:description" content="{_h(model["description"])}">
  <meta property="og:url" content="{_h(model["canonical_url"])}">
  <style>{PAGE_CSS}</style>
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    <form class="ticker-search" action="/stocks" method="get">
      <label class="sr-only" for="ticker">종목코드 또는 종목명</label>
      <input id="ticker" name="ticker" list="tickerSuggestions" maxlength="80" value="{_h(model["code"])}" placeholder="005930 또는 삼성전자" autocomplete="off">
      <datalist id="tickerSuggestions"></datalist>
      <button type="submit">조회</button>
    </form>
  </header>

  <main class="shell">
    <section class="summary-band" aria-labelledby="stock-title">
      <div>
        <p class="eyebrow">{_h(model["market_line"])}</p>
        <h1 id="stock-title">{_h(model["name"])} <span>{_h(model["code"])}</span></h1>
        <p class="asof">{_h(model["generated_at"])} 기준</p>
      </div>
      <div class="decision-box">
        <span class="decision-label">AI 판단</span>
        <strong>{_h(model["rating"])}</strong>
        <span>{_h(model["action"])}</span>
      </div>
    </section>

    <section class="workspace">
      <section class="chart-panel" aria-labelledby="chart-title">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">KRW OHLCV</p>
            <h2 id="chart-title">가격 흐름</h2>
          </div>
          <span class="status-pill">{_h(model["chart_status"])}</span>
        </div>
        <div class="chart-wrap">
          <canvas id="priceChart" aria-label="{_h(model["name"])} 가격 차트"></canvas>
          <p id="chartFallback" class="chart-fallback" hidden>차트 데이터 대기 중</p>
        </div>
      </section>

      <aside class="side-rail" aria-label="핵심 지표">
        <section class="metric-grid">
          <article>
            <span>종가</span>
            <strong>{_h(model["close"])}</strong>
          </article>
          <article>
            <span>변동</span>
            <strong class="{_h(model["change_class"])}">{_h(model["change"])}</strong>
          </article>
          <article>
            <span>거래량</span>
            <strong>{_h(model["volume"])}</strong>
          </article>
          <article>
            <span>분석 상태</span>
            <strong>{_h(model["analysis_state"])}</strong>
          </article>
        </section>

        <section class="analysis-panel">
          <p class="eyebrow">공개 분석</p>
          <h2>{_h(model["analysis_title"])}</h2>
          <p>{_h(model["rationale"])}</p>
        </section>
      </aside>
    </section>

    <section class="report-section" aria-labelledby="reports-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Agent Reports</p>
          <h2 id="reports-title">분석 리포트</h2>
        </div>
        <span class="status-pill">{_h(model["refresh_state"])}</span>
      </div>
      <div class="report-grid">
        {reports_html}
      </div>
    </section>

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>{notices_html}</ul>
    </section>
  </main>

  <script id="stock-payload" type="application/json">{payload_json}</script>
  <script>{PAGE_JS}</script>
</body>
</html>"""


def _view_model(payload: dict[str, Any], *, site_base_url: str | None = None) -> dict[str, Any]:
    ticker = payload["ticker"]
    chart = payload.get("chart", {})
    points = [point for point in chart.get("points", []) if point.get("close") is not None]
    latest = points[-1] if points else {}
    previous = points[-2] if len(points) > 1 else {}
    close = latest.get("close")
    previous_close = previous.get("close")
    change_value = close - previous_close if close is not None and previous_close is not None else None
    change_rate = (change_value / previous_close * 100) if change_value is not None and previous_close else None

    analysis = payload.get("analysis", {})
    decision = analysis.get("decision") or {}
    refresh = payload.get("analysis_refresh", {})
    reports = analysis.get("reports") or []

    name = ticker.get("name") or ticker.get("code")
    code = ticker.get("code", "")
    market = ticker.get("market", "KR")
    benchmark = ticker.get("benchmark_symbol") or "KR Benchmark"
    rating = decision.get("rating") or _analysis_status_label(analysis.get("status"))
    action = decision.get("action") or "read-only"

    return {
        "title": f"{name} ({code}) | TradingAgents Korea",
        "description": f"{name} {code} 한국 주식 AI 분석, KRW 차트, 공개 리포트.",
        "name": name,
        "code": code,
        "market_line": f"{market} / {benchmark}",
        "canonical_url": stock_canonical_url(code, site_base_url=site_base_url),
        "generated_at": _short_datetime(payload.get("generated_at")),
        "rating": str(rating),
        "action": str(action).upper(),
        "close": _money(close),
        "change": _change(change_value, change_rate),
        "change_class": _change_class(change_value),
        "volume": _number(latest.get("volume")),
        "analysis_state": _analysis_status_label(analysis.get("status")),
        "analysis_title": _analysis_title(analysis, decision),
        "rationale": _analysis_rationale(decision),
        "reports": reports[:6],
        "refresh_state": "업데이트 권장" if refresh.get("recommended") else "분석 최신",
        "chart_status": _chart_status_label(chart.get("status")),
    }


def _report_cards(reports: list[dict[str, Any]]) -> str:
    if not reports:
        return """
        <article class="report-card empty">
          <span>pending</span>
          <h3>리포트 대기</h3>
          <p>공개 분석이 완료되면 에이전트별 리포트가 표시됩니다.</p>
        </article>
        """

    cards = []
    for report in reports:
        title = report.get("title") or report.get("role") or "report"
        role = report.get("role") or "agent"
        content = _excerpt(report.get("content") or "", limit=420)
        cards.append(
            f"""
            <article class="report-card">
              <span>{_h(str(role))}</span>
              <h3>{_h(str(title))}</h3>
              <p>{_h(content)}</p>
            </article>
            """
        )
    return "\n".join(cards)


def _analysis_status_label(status: Any) -> str:
    return {
        "available": "분석 완료",
        "missing": "분석 대기",
        "not_configured": "저장소 미연결",
        "skipped": "분석 제외",
    }.get(str(status), "상태 확인")


def _analysis_title(analysis: dict[str, Any], decision: dict[str, Any]) -> str:
    if analysis.get("status") == "available":
        rating = decision.get("rating") or "완료"
        return f"{rating} 의견"
    return _analysis_status_label(analysis.get("status"))


def _analysis_rationale(decision: dict[str, Any]) -> str:
    rationale = decision.get("rationale") or decision.get("raw_decision")
    if not rationale:
        return "저장된 공개 분석이 아직 없습니다."
    return _excerpt(str(rationale), limit=260)


def _chart_status_label(status: Any) -> str:
    return {
        "available": "차트 연결",
        "unavailable": "차트 대기",
        "skipped": "차트 제외",
    }.get(str(status), "차트 확인")


def _money(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.0f}원"


def _change(value: float | None, rate: float | None) -> str:
    if value is None or rate is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.0f}원 / {sign}{rate:.2f}%"


def _change_class(value: float | None) -> str:
    if value is None:
        return "neutral"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _number(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.0f}"


def _short_datetime(value: Any) -> str:
    if not value:
        return "-"
    return str(value).replace("T", " ")[:16]


def _excerpt(value: str, *, limit: int) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "..."


def _script_json(payload: dict[str, Any]) -> str:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _h(value: Any) -> str:
    return html.escape(str(value), quote=True)


PAGE_CSS = """
:root {
  color-scheme: light;
  --bg: #f6f7f4;
  --surface: #ffffff;
  --surface-strong: #f0f5f4;
  --ink: #17201f;
  --muted: #66716f;
  --line: #dce3df;
  --accent: #146b63;
  --accent-strong: #0f4e49;
  --gain: #b42318;
  --loss: #1d4ed8;
  --warn: #8a5a0a;
  --shadow: 0 18px 50px rgba(20, 31, 28, 0.08);
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  background: var(--bg);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

a {
  color: inherit;
  text-decoration: none;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px clamp(16px, 4vw, 40px);
  border-bottom: 1px solid var(--line);
  background: rgba(246, 247, 244, 0.94);
  backdrop-filter: blur(12px);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 800;
  letter-spacing: 0;
}

.brand-mark {
  display: inline-grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 6px;
  background: var(--accent);
  color: white;
  font-size: 13px;
}

.ticker-search {
  display: flex;
  gap: 8px;
  width: min(100%, 320px);
}

.ticker-search input {
  min-width: 0;
  width: 100%;
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  font-variant-numeric: tabular-nums;
}

.ticker-search button {
  height: 40px;
  padding: 0 16px;
  border: 0;
  border-radius: 6px;
  background: var(--ink);
  color: white;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.shell {
  width: min(1280px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0 48px;
}

.summary-band {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 20px;
  padding: 26px 0 24px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--accent-strong);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1,
h2,
h3,
p {
  margin-top: 0;
}

h1 {
  margin-bottom: 10px;
  font-size: clamp(32px, 6vw, 62px);
  line-height: 0.95;
  letter-spacing: 0;
}

h1 span {
  color: var(--muted);
  font-size: clamp(22px, 3vw, 34px);
  font-weight: 700;
}

h2 {
  margin-bottom: 0;
  font-size: 20px;
  letter-spacing: 0;
}

h3 {
  margin-bottom: 10px;
  font-size: 16px;
  letter-spacing: 0;
}

.asof {
  margin-bottom: 0;
  color: var(--muted);
  font-size: 14px;
}

.decision-box {
  display: grid;
  align-content: center;
  min-width: 220px;
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: var(--shadow);
}

.decision-label,
.status-pill {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.decision-box strong {
  display: block;
  margin: 6px 0;
  font-size: 28px;
}

.decision-box span:last-child {
  color: var(--accent);
  font-weight: 800;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 380px);
  gap: 18px;
  align-items: stretch;
}

.chart-panel,
.analysis-panel,
.report-section,
.notice-strip,
.metric-grid article,
.report-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.chart-panel,
.report-section {
  padding: 20px;
  box-shadow: var(--shadow);
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-strong);
  white-space: nowrap;
}

.chart-wrap {
  position: relative;
  min-height: 340px;
  aspect-ratio: 16 / 9;
}

#priceChart {
  display: block;
  width: 100%;
  height: 100%;
}

.chart-fallback {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  margin: 0;
  color: var(--muted);
}

.side-rail {
  display: grid;
  gap: 18px;
  align-content: start;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.metric-grid article {
  min-height: 112px;
  padding: 16px;
}

.metric-grid span {
  display: block;
  margin-bottom: 12px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
}

.metric-grid strong {
  display: block;
  overflow-wrap: anywhere;
  font-size: 21px;
  font-variant-numeric: tabular-nums;
  line-height: 1.12;
}

.positive {
  color: var(--gain);
}

.negative {
  color: var(--loss);
}

.neutral {
  color: var(--ink);
}

.analysis-panel {
  padding: 18px;
}

.analysis-panel p:last-child {
  margin-bottom: 0;
  color: var(--muted);
  line-height: 1.6;
}

.report-section {
  margin-top: 18px;
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.report-card {
  min-height: 190px;
  padding: 16px;
}

.report-card span {
  display: inline-block;
  margin-bottom: 12px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.report-card p {
  margin-bottom: 0;
  color: var(--muted);
  line-height: 1.58;
}

.report-card.empty {
  grid-column: 1 / -1;
}

.notice-strip {
  margin-top: 18px;
  padding: 14px 18px;
  background: #fffaf0;
}

.notice-strip ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding-left: 18px;
  color: #725318;
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 980px) {
  .summary-band,
  .workspace {
    grid-template-columns: 1fr;
  }

  .summary-band {
    display: grid;
  }

  .decision-box {
    min-width: 0;
  }

  .report-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .topbar {
    align-items: stretch;
    flex-direction: column;
  }

  .ticker-search {
    width: 100%;
  }

  .shell {
    width: min(100% - 24px, 1280px);
    padding-top: 18px;
  }

  .metric-grid,
  .report-grid {
    grid-template-columns: 1fr;
  }

  .chart-wrap {
    min-height: 260px;
    aspect-ratio: 4 / 3;
  }
}
"""


PAGE_JS = """
(() => {
  const searchForm = document.querySelector(".ticker-search");
  const searchInput = document.getElementById("ticker");
  const suggestions = document.getElementById("tickerSuggestions");
  let lastSearchController = null;

  async function searchTickers(query) {
    const trimmed = query.trim();
    if (!trimmed) return [];
    if (lastSearchController) lastSearchController.abort();
    lastSearchController = new AbortController();
    const response = await fetch(`/api/tickers/search?q=${encodeURIComponent(trimmed)}&limit=8`, {
      signal: lastSearchController.signal,
      headers: { "Accept": "application/json" }
    });
    if (!response.ok) return [];
    const payload = await response.json();
    return payload.items || [];
  }

  if (searchInput && suggestions) {
    searchInput.addEventListener("input", async () => {
      const query = searchInput.value.trim();
      if (query.length < 2) {
        suggestions.replaceChildren();
        return;
      }
      try {
        const items = await searchTickers(query);
        suggestions.replaceChildren(...items.map((item) => {
          const option = document.createElement("option");
          option.value = item.code;
          option.label = `${item.name} / ${item.market}`;
          return option;
        }));
      } catch (error) {
        if (error.name !== "AbortError") suggestions.replaceChildren();
      }
    });
  }

  if (searchForm && searchInput) {
    searchForm.addEventListener("submit", async (event) => {
      const query = searchInput.value.trim();
      if (/^\\d{6}$/.test(query)) return;
      event.preventDefault();
      try {
        const items = await searchTickers(query);
        if (items.length > 0) {
          window.location.assign(`/stocks/${items[0].code}`);
        }
      } catch (_) {
        searchForm.submit();
      }
    });
  }

  const node = document.getElementById("stock-payload");
  const canvas = document.getElementById("priceChart");
  const fallback = document.getElementById("chartFallback");
  if (!node || !canvas) return;

  const payload = JSON.parse(node.textContent || "{}");
  const points = (payload.chart?.points || []).filter((point) => Number.isFinite(point.close));
  if (points.length < 2) {
    if (fallback) fallback.hidden = false;
    return;
  }

  const ctx = canvas.getContext("2d");
  const money = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
  const dates = points.map((point) => point.date);
  const closes = points.map((point) => Number(point.close));
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const pad = Math.max((max - min) * 0.12, max * 0.01, 1);
  const yMin = min - pad;
  const yMax = max + pad;

  function fitCanvas() {
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    return rect;
  }

  function xAt(index, width, left, right) {
    if (points.length === 1) return left;
    return left + (index / (points.length - 1)) * (width - left - right);
  }

  function yAt(value, height, top, bottom) {
    return top + ((yMax - value) / (yMax - yMin)) * (height - top - bottom);
  }

  function draw() {
    const rect = fitCanvas();
    const width = rect.width;
    const height = rect.height;
    const left = 58;
    const right = 18;
    const top = 24;
    const bottom = 42;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = "#dce3df";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#66716f";
    ctx.font = "12px system-ui, sans-serif";
    ctx.textBaseline = "middle";

    for (let i = 0; i <= 4; i += 1) {
      const y = top + (i / 4) * (height - top - bottom);
      const value = yMax - (i / 4) * (yMax - yMin);
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(width - right, y);
      ctx.stroke();
      ctx.fillText(money.format(value), 0, y);
    }

    const firstX = xAt(0, width, left, right);
    const lastX = xAt(points.length - 1, width, left, right);
    const baseY = height - bottom;

    const area = ctx.createLinearGradient(0, top, 0, baseY);
    area.addColorStop(0, "rgba(20, 107, 99, 0.22)");
    area.addColorStop(1, "rgba(20, 107, 99, 0.02)");

    ctx.beginPath();
    closes.forEach((close, index) => {
      const x = xAt(index, width, left, right);
      const y = yAt(close, height, top, bottom);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.lineTo(lastX, baseY);
    ctx.lineTo(firstX, baseY);
    ctx.closePath();
    ctx.fillStyle = area;
    ctx.fill();

    ctx.beginPath();
    closes.forEach((close, index) => {
      const x = xAt(index, width, left, right);
      const y = yAt(close, height, top, bottom);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#146b63";
    ctx.lineWidth = 2.4;
    ctx.stroke();

    const lastClose = closes[closes.length - 1];
    const lastY = yAt(lastClose, height, top, bottom);
    ctx.fillStyle = "#146b63";
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#66716f";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(dates[0], left, height - 12);
    ctx.textAlign = "right";
    ctx.fillText(dates[dates.length - 1], width - right, height - 12);
    ctx.textAlign = "left";
  }

  draw();
  window.addEventListener("resize", draw);
})();
"""

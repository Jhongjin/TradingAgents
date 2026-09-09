"""Public stock page (`/stocks/{ticker}`) rendered on the shared design system.

The page keeps the legacy view model, fragment builders and the interactive
chart engine (``PAGE_JS`` in :mod:`web_pages`) and only replaces the outer
markup and CSS. Everything the chart script queries by id, class or data
attribute is preserved:

* ids: ``stock-payload``, ``priceChart``, ``priceChartCanvas``,
  ``chartDrawingLayer``, ``chartLegend``, ``chartFallback``, ``chartTooltip``,
  ``chartToolState``, ``simulationPreview``, ``ticker``, ``tickerSuggestions``
* classes: ``.ticker-search``, ``.chart-tab``, ``.chart-tool-button``,
  ``.status-pill``, ``.simulation-grid``, ``.is-active``, ``.is-drawing-trend``
* data attributes: ``data-chart-indicator``, ``data-chart-setting``,
  ``data-chart-apply-settings``, ``data-chart-draw-trend``,
  ``data-chart-clear-trends``, ``data-chart-fit``, ``data-simulation-url``,
  ``data-ticker-lookup``
"""

from __future__ import annotations

from typing import Any

from tradingagents.storage import StorageRepository

from .design_system import THEME_TOKENS, badge, h, icon, render_shell, stat_tile

LIGHTWEIGHT_CHARTS_SRC = "https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"

# The chart engine draws light axis text on a transparent layer and its canvas
# fallback paints its own dark surface, so the chart stage keeps a fixed dark
# backdrop in every theme. The values come from the design-system dark tokens.
_CHART_STAGE = THEME_TOKENS["dark"]

STOCK_CSS = f"""
.ds.stock-page {{ --chart-bg: {_CHART_STAGE["panel"]}; --chart-fg: {_CHART_STAGE["ink2"]}; --chart-line: {_CHART_STAGE["line"]}; }}
/* hero */
.ds .stock-hero {{ display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 24px; align-items: end; padding: 28px 0 24px; }}
.ds .stock-hero h1 {{ margin-top: 10px; font-size: 32px; }}
.ds .stock-hero h1 .stock-code {{ margin-left: 6px; font-size: 18px; font-weight: 500; color: var(--muted); }}
.ds .stock-lede {{ margin-top: 8px; max-width: 60ch; font-size: 15px; }}
.ds .stock-hero-actions {{ margin-top: 16px; gap: 8px; }}
.ds .ticker-search {{ display: flex; gap: 8px; margin-top: 14px; max-width: 440px; }}
.ds .ticker-search .field {{ height: 38px; }}
.ds .ticker-search input {{ width: 100%; border: 0; background: transparent; outline: none; font: inherit; color: var(--ink); font-variant-numeric: tabular-nums; }}
.ds .ticker-search input::placeholder {{ color: var(--muted); }}
.ds .stock-jumpbar {{ width: fit-content; max-width: 100%; margin-top: 14px; }}
.ds .stock-hero-stack {{ display: grid; gap: 12px; min-width: 0; }}
.ds .stock-decision {{ padding: 14px 16px; }}
.ds .stock-decision .v {{ margin-top: 2px; font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }}
.ds .stock-signal-card {{ display: grid; gap: 8px; padding: 16px; background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 14px; box-shadow: var(--shadow); }}
.ds .stock-signal-card > span, .ds .stock-signal-card dt {{ font-size: 12px; font-weight: 500; color: var(--muted); }}
.ds .stock-signal-card strong {{ font-size: 28px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.1; font-variant-numeric: tabular-nums; }}
.ds .stock-signal-card small {{ font-size: 13px; color: var(--ink2); }}
.ds .stock-signal-card dl {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 4px 0 0; }}
.ds .stock-signal-card dl div {{ min-width: 0; padding: 8px 10px; background: var(--bg2); border-radius: 10px; }}
.ds .stock-signal-card dd {{ margin: 3px 0 0; font-weight: 600; overflow-wrap: anywhere; }}
.ds .stock-stats {{ margin-bottom: 20px; }}
/* shared legacy fragments */
.ds .status-pill, .ds .data-pill {{ display: inline-flex; align-items: center; height: 24px; padding: 0 9px; border-radius: 999px; background: var(--bg2); color: var(--ink2); font-size: 12px; font-weight: 600; white-space: nowrap; }}
.ds .eyebrow {{ margin: 0 0 4px; font-size: 12px; font-weight: 500; color: var(--muted); }}
.ds .panel-heading {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }}
/* chart controls */
.ds .chart-toolbar {{ display: flex; flex-wrap: wrap; gap: 12px 18px; margin-bottom: 10px; }}
.ds .chart-control-block {{ display: flex; flex-direction: column; gap: 6px; min-width: 0; }}
.ds .chart-control-block > span {{ font-size: 12px; font-weight: 500; color: var(--muted); }}
.ds .chart-tabs {{ display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; background: var(--bg2); border-radius: 10px; }}
.ds .chart-tab {{ display: inline-flex; align-items: center; height: 28px; padding: 0 10px; border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--ink2); white-space: nowrap; }}
.ds .chart-tab:hover {{ color: var(--ink); text-decoration: none; }}
.ds .chart-tab.is-active {{ color: var(--ink); background: var(--panel); font-weight: 600; box-shadow: var(--shadow); }}
.ds .chart-tab.is-disabled {{ opacity: .5; cursor: not-allowed; }}
.ds .chart-tools {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; margin-bottom: 10px; padding: 10px 12px; background: var(--bg2); border-radius: 12px; }}
.ds .chart-tool-group {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }}
.ds .chart-tool-group > span, .ds .chart-tools small {{ font-size: 12px; color: var(--muted); }}
.ds .chart-tools small {{ flex-basis: 100%; }}
.ds .chart-tool-button {{ display: inline-flex; align-items: center; height: 28px; padding: 0 10px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--panel); color: var(--ink2); font: inherit; font-size: 12px; font-weight: 600; cursor: pointer; }}
.ds .chart-tool-button:hover, .ds .chart-tool-button.is-active {{ border-color: var(--accent); background: var(--accent-soft); color: var(--accent-ink); }}
.ds .chart-setting-field {{ display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--muted); font-size: 12px; }}
.ds .chart-setting-field span {{ white-space: nowrap; }}
.ds .chart-setting-field input {{ width: 52px; height: 22px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--ink); font: inherit; font-size: 12px; text-align: center; }}
.ds .chart-caption {{ margin: 0 0 10px; font-size: 13px; color: var(--muted); }}
.ds .data-source-strip {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin: 0 0 12px; overflow: hidden; border: 1px solid var(--line); border-radius: 10px; background: var(--line); }}
.ds .data-source-strip div {{ min-width: 0; padding: 8px 10px; background: var(--panel); }}
.ds .data-source-strip dt {{ font-size: 11px; color: var(--muted); }}
.ds .data-source-strip dd {{ margin: 3px 0 0; font-size: 13px; font-weight: 600; color: var(--ink); overflow-wrap: anywhere; }}
/* chart stage */
.ds .chart-wrap {{ position: relative; min-height: 420px; aspect-ratio: 16 / 10; overflow: hidden; border-radius: 12px; background: var(--chart-bg); }}
.ds .tv-price-chart, .ds .chart-canvas-fallback, .ds .chart-drawing-layer {{ display: block; position: absolute; inset: 0; width: 100%; height: 100%; }}
.ds .tv-price-chart.is-drawing-trend {{ cursor: crosshair; }}
.ds .chart-drawing-layer {{ z-index: 1; overflow: visible; pointer-events: none; }}
.ds .chart-drawing-layer line {{ stroke: var(--accent); stroke-width: 2; }}
.ds .chart-legend {{ position: absolute; top: 10px; right: 12px; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; max-width: min(520px, calc(100% - 24px)); pointer-events: none; }}
.ds .chart-legend span {{ display: inline-flex; align-items: center; height: 22px; padding: 0 8px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--ink2); font-size: 12px; font-weight: 600; white-space: nowrap; }}
.ds .chart-fallback {{ position: absolute; inset: 0; display: grid; place-items: center; margin: 0; padding: 20px; text-align: center; color: var(--chart-fg); }}
.ds .chart-tooltip {{ position: absolute; z-index: 2; top: 12px; max-width: min(260px, calc(100% - 24px)); padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); box-shadow: var(--shadow); color: var(--ink); font-size: 12px; pointer-events: none; }}
.ds .chart-tooltip strong, .ds .chart-tooltip span {{ display: block; white-space: nowrap; }}
.ds .chart-tooltip span {{ margin-top: 4px; color: var(--muted); }}
.ds .chart-attribution a {{ font-weight: 600; }}
/* analysis side rail */
.ds .stock-analysis-title {{ font-size: 15px; }}
.ds .stock-rationale {{ margin: 6px 0 12px; }}
.ds .analysis-confidence-panel {{ display: grid; gap: 6px; margin-top: 14px; padding: 12px 14px; border: 1px solid var(--line); border-left: 3px solid var(--amber); border-radius: 10px; background: var(--amber-soft); }}
.ds .analysis-confidence-panel span {{ font-size: 11px; color: var(--muted); }}
.ds .analysis-confidence-panel strong {{ font-size: 16px; color: var(--ink); }}
.ds .analysis-confidence-panel p, .ds .analysis-confidence-panel ul {{ margin: 0; font-size: 13px; color: var(--ink2); }}
.ds .analysis-confidence-panel ul {{ display: grid; gap: 2px; padding-left: 18px; }}
.ds .analysis-confidence-panel.confidence-high {{ border-left-color: var(--accent); background: var(--accent-soft); }}
.ds .analysis-confidence-panel.confidence-low {{ border-left-color: var(--orange); background: var(--orange-soft); }}
.ds .simulation-preview {{ display: grid; gap: 10px; margin-top: 10px; min-height: 60px; }}
.ds .simulation-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
.ds .simulation-grid div {{ min-width: 0; padding: 8px 10px; background: var(--bg2); border-radius: 10px; }}
.ds .simulation-grid span {{ display: block; font-size: 12px; color: var(--muted); }}
.ds .simulation-grid strong {{ display: block; margin-top: 3px; font-size: 15px; font-weight: 600; color: var(--ink); overflow-wrap: anywhere; }}
.ds .simulation-preview p {{ font-size: 13px; color: var(--ink2); }}
/* lenses, reports, outcomes */
.ds .lens-section, .ds .outcome-section {{ margin-top: 20px; }}
.ds .lens-grid, .ds .outcome-grid, .ds .report-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
.ds .lens-card, .ds .outcome-card, .ds .report-card {{ min-width: 0; padding: 16px; background: var(--panel); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow); }}
.ds .lens-card {{ border-left-width: 4px; }}
.ds .lens-card div {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }}
.ds .lens-card span, .ds .outcome-card > span {{ order: 2; display: inline-flex; align-items: center; height: 22px; padding: 0 8px; border-radius: 999px; background: var(--bg2); color: var(--ink2); font-size: 12px; font-weight: 600; white-space: nowrap; }}
.ds .lens-card h3, .ds .outcome-card h3, .ds .report-card h3 {{ font-size: 15px; }}
.ds .lens-card p, .ds .outcome-card p, .ds .report-card p {{ font-size: 13px; color: var(--ink2); line-height: 1.6; }}
.ds .lens-card p + p {{ margin-top: 8px; font-size: 12px; font-weight: 600; color: var(--accent-ink); word-break: break-word; }}
.ds .lens-positive {{ border-left-color: var(--gain); }}
.ds .lens-caution {{ border-left-color: var(--amber); }}
.ds .lens-neutral, .ds .lens-unavailable {{ border-left-color: var(--line-strong); }}
.ds .outcome-card h3 {{ margin: 10px 0 6px; }}
.ds .outcome-card dl {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 12px 0 0; }}
.ds .outcome-card dl div {{ padding: 8px 10px; border-radius: 10px; background: var(--bg2); }}
.ds .outcome-card dt {{ font-size: 12px; color: var(--muted); }}
.ds .outcome-card dd {{ margin: 3px 0 0; font-weight: 600; font-variant-numeric: tabular-nums; }}
.ds .outcome-completed {{ border-left: 4px solid var(--accent); }}
.ds .outcome-section-copy {{ margin-top: 4px; font-size: 13px; color: var(--ink2); }}
.ds .report-card > span {{ display: inline-block; margin-bottom: 8px; font-size: 12px; font-weight: 600; color: var(--accent-ink); }}
.ds .report-card p {{ margin-top: 8px; }}
.ds .report-card.empty {{ grid-column: 1 / -1; }}
.ds .analysis-quality-strip {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 12px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line); }}
.ds .analysis-quality-strip strong {{ font-size: 13px; color: var(--ink); }}
.ds .analysis-quality-strip small {{ font-size: 12px; color: var(--muted); }}
.ds .analysis-quality-strip.risk-low strong {{ color: var(--accent-ink); }}
.ds .analysis-quality-strip.risk-medium strong {{ color: var(--amber); }}
.ds .analysis-quality-strip.risk-high strong {{ color: var(--orange); }}
.ds .analysis-feed-actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line); }}
.ds .analysis-feed-actions a {{ display: inline-flex; align-items: center; justify-content: center; height: 32px; padding: 0 12px; border: 1px solid var(--line-strong); border-radius: 9px; background: var(--panel); color: var(--ink); font-size: 13px; font-weight: 600; box-shadow: var(--shadow); }}
.ds .analysis-feed-actions a:hover {{ border-color: var(--accent); text-decoration: none; }}
.ds .analysis-feed-actions a:first-child {{ border-color: var(--accent); background: var(--accent); color: var(--on-accent); }}
.ds .notice-strip {{ margin-top: 20px; padding: 14px 18px; }}
.ds .notice-strip ul {{ display: grid; gap: 4px; margin: 0; padding-left: 18px; font-size: 13px; color: var(--ink2); }}
@media (max-width: 960px) {{
  .ds .stock-hero {{ grid-template-columns: 1fr; }}
  .ds .lens-grid, .ds .outcome-grid, .ds .report-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .ds .data-source-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
}}
@media (max-width: 640px) {{
  .ds .stock-hero h1 {{ font-size: 26px; }}
  .ds .ticker-search {{ max-width: none; }}
  .ds .lens-grid, .ds .outcome-grid, .ds .report-grid, .ds .simulation-grid, .ds .stock-signal-card dl {{ grid-template-columns: 1fr; }}
  .ds .chart-wrap {{ height: min(72vw, 340px); min-height: 260px; aspect-ratio: auto; }}
  .ds .chart-tabs, .ds .chart-tool-group {{ width: 100%; }}
  .ds .chart-tab, .ds .chart-tool-button, .ds .chart-setting-field {{ flex: 1 1 auto; justify-content: center; }}
}}
"""

_CHANGE_TONE = {"positive": ("up", "b-gain"), "negative": ("down", "b-loss"), "neutral": ("flat", "b-grey")}
_CHART_STATUS_TONE = {"차트 연결": "b-teal", "차트 대기": "b-amber", "차트 제외": "b-grey"}


def render_public_stock_page(
    ticker: str,
    *,
    repo: StorageRepository | None = None,
    chart_start: str | None = None,
    chart_end: str | None = None,
    as_of_date: str | None = None,
    max_analysis_age_days: int = 1,
    chart_vendor: str | None = None,
    chart_interval: str | None = None,
    site_base_url: str | None = None,
) -> str:
    """Render the public stock page on the shared design system.

    Signature matches ``web_pages.render_public_stock_page``. The payload is
    resolved through ``web_pages.build_public_stock_payload`` so existing
    monkeypatches keep working; the legacy view model and fragment builders are
    reused unchanged.
    """

    from . import web_pages as legacy  # imported lazily to avoid an import cycle

    payload = legacy.build_public_stock_payload(
        ticker,
        repo=repo,
        chart_start=chart_start,
        chart_end=chart_end,
        as_of_date=as_of_date,
        max_analysis_age_days=max_analysis_age_days,
        chart_vendor=chart_vendor,
        chart_interval=chart_interval,
    )
    notice_items = legacy._stock_notice_items(payload.get("notices", []))
    page_payload = {**payload, "notices": notice_items}
    model = legacy._view_model(page_payload, site_base_url=site_base_url)
    lede = f"{model['name']}({model['code']})의 최근 주가, AI 리포트, 모의매매 검증 결과를 보여줍니다."
    model["description"] = lede

    body = _render_body(model, page_payload, legacy, lede=lede)
    extra_head = _extra_head(model, page_payload, legacy)
    return render_shell(
        title=str(model["title"]),
        body=body,
        description=lede,
        active=None,
        canonical_path=f"/stocks/{model['code']}",
        site_base_url=site_base_url,
        extra_head=extra_head,
        extra_css=STOCK_CSS,
        extra_js=legacy.PAGE_JS,
        search=False,
        body_class="stock-page",
    )


def _extra_head(model: dict[str, Any], payload: dict[str, Any], legacy: Any) -> str:
    structured = legacy._script_json(legacy._structured_data(model, payload))
    title = h(model["title"])
    description = h(model["description"])
    canonical = h(model["canonical_url"])
    # og/twitter meta come from render_shell; only the page's JSON-LD is added here
    del title, description, canonical
    return f'<script type="application/ld+json">{structured}</script>'


def _render_body(model: dict[str, Any], payload: dict[str, Any], legacy: Any, *, lede: str) -> str:
    code = str(model["code"])
    name = str(model["name"])
    analysis = payload.get("analysis") or {}
    change_class, change_tone = _CHANGE_TONE.get(str(model.get("change_class")), _CHANGE_TONE["neutral"])
    chart_status = str(model["chart_status"])
    refresh_recommended = model.get("refresh_state") == "업데이트 권장"

    signal_html = legacy._stock_signal_card(model)
    chart_controls_html = legacy._chart_controls(model)
    chart_tools_html = legacy._chart_tools()
    chart_source_html = legacy._data_source_strip(model["chart_source_rows"], label="차트 데이터 기준")
    analysis_source_html = legacy._data_source_strip(model["analysis_source_rows"], label="AI 리서치 출처")
    confidence_html = legacy._analysis_confidence_panel(model["analysis_confidence"])
    reports_html = legacy._report_cards(model["reports"])
    report_actions_html = legacy._stock_report_actions(model)
    lenses_html = legacy._strategy_lens_cards(payload.get("strategy_lenses") or [])
    outcomes_html = legacy._outcome_cards(analysis.get("outcomes") or [])
    notices_html = "".join(f"<li>{h(notice)}</li>" for notice in payload.get("notices") or [])
    payload_json = legacy._script_json(payload)

    request_href = "/member?mode=signup&amp;tab=analysis#analysis-request-section"

    hero = f"""<section class="hero">
  <div class="shell stock-hero">
    <div class="stock-hero-main">
      <div class="row wrap" style="gap: 8px;">{badge(str(model["market_line"]), "b-navy")}{badge(f"{model['generated_at']} 기준", "b-grey", icon_name="clock")}</div>
      <h1 id="stock-title">{h(name)}<span class="stock-code num">{h(code)}</span></h1>
      <p class="stock-lede ink2">{h(lede)}</p>
      <div class="row wrap stock-hero-actions">
        <a class="btn primary" href="/analyses?ticker={h(code)}">{icon("book", 16)}리포트 보기</a>
        <a class="btn" href="{request_href}">{icon("send", 16)}새 분석 요청</a>
      </div>
      <form class="ticker-search" action="/stocks" method="get" role="search">
        <label class="field"><span class="muted">{icon("search", 14)}</span><input id="ticker" name="ticker" list="tickerSuggestions" maxlength="80" value="{h(code)}" placeholder="005930 또는 삼성전자" autocomplete="off" aria-label="종목코드 또는 종목명"></label>
        <datalist id="tickerSuggestions"></datalist>
        <button class="btn" type="submit">조회</button>
      </form>
      <nav class="tabs stock-jumpbar" aria-label="본문 빠른 이동">
        <a href="#stock-chart-section">가격</a>
        <a href="#stock-analysis-section">AI 의견</a>
        <a href="#stock-reports-section">AI 리포트</a>
        <a href="#analysis-outcomes">검증 결과</a>
      </nav>
    </div>
    <aside class="stock-hero-stack" aria-label="종목 요약">
      <div class="card stock-decision">
        <p class="label">AI 의견 요약</p>
        <p class="v">{h(model["rating"])}</p>
        <p class="small ink2">{h(model["action"])}</p>
      </div>
      {signal_html}
    </aside>
  </div>
</section>"""

    tiles = "".join(
        [
            stat_tile("wallet", "b-teal", "종가", h(model["close"]), f"{model['generated_at']} 기준"),
            stat_tile("trend", change_tone, "전일 대비", h(model["change"]), "직전 봉 기준", value_class=change_class),
            stat_tile("layers", "b-blue", "거래량", h(model["volume"]), "최근 봉 기준"),
            stat_tile("brain", "b-violet", "분석 상태", h(model["analysis_state"]), str(model["refresh_state"])),
        ]
    )

    chart_card = f"""<section id="stock-chart-section" class="card" aria-labelledby="chart-title">
      <div class="card-h">
        <h2 id="chart-title">{icon("trend", 16)}가격 차트</h2>
        <div class="row wrap" style="gap: 6px;">{badge(chart_status, _CHART_STATUS_TONE.get(chart_status, "b-grey"))}{badge(str(model["chart_vendor_label"]), "b-grey")}</div>
      </div>
      <div class="card-b">
        {chart_controls_html}
        {chart_tools_html}
        <p class="chart-caption">{h(model["chart_caption"])}</p>
        {chart_source_html}
        <div class="chart-wrap" data-chart-engine="tradingview-lightweight">
          <div id="priceChart" class="tv-price-chart" role="img" aria-label="{h(name)} 가격 차트"></div>
          <canvas id="priceChartCanvas" class="chart-canvas-fallback" aria-label="{h(name)} 가격 차트 예비 렌더러" hidden></canvas>
          <svg id="chartDrawingLayer" class="chart-drawing-layer" aria-hidden="true"></svg>
          <div class="chart-legend" id="chartLegend" aria-hidden="true"></div>
          <div class="chart-tooltip" id="chartTooltip" hidden></div>
          <p id="chartFallback" class="chart-fallback" hidden>{h(model["chart_fallback"])}</p>
        </div>
      </div>
      <div class="card-f">
        <span>지표와 추세선은 이 브라우저에만 저장합니다.</span>
        <span class="chart-attribution"><a href="https://www.tradingview.com/" rel="noopener noreferrer" target="_blank">TradingView Lightweight Charts</a> 기반 차트입니다.</span>
      </div>
    </section>"""

    side = f"""<div class="stack">
      <section id="stock-analysis-section" class="card" aria-labelledby="analysis-title">
        <div class="card-h">
          <h2 id="analysis-title">{icon("brain", 16)}AI 의견</h2>
          {badge(str(model["analysis_state"]), "b-violet")}
        </div>
        <div class="card-b">
          <h3 class="stock-analysis-title">{h(model["analysis_title"])}</h3>
          <p class="stock-rationale small ink2">{h(model["rationale"])}</p>
          {analysis_source_html}
          {confidence_html}
        </div>
      </section>
      <section id="stock-simulation-section" class="card" aria-labelledby="simulation-title">
        <div class="card-h">
          <h2 id="simulation-title">{icon("wallet", 16)}모의 매매 기록</h2>
          {badge("실제 주문 없음", "b-grey", icon_name="shield")}
        </div>
        <div class="card-b">
          <p class="small ink2">AI 의견을 기준으로 모의 매수와 청산을 기록합니다.</p>
          <div id="simulationPreview" class="simulation-preview" data-simulation-url="/api/simulations/preview/{h(code)}">
            <span class="status-pill">확인 중</span>
          </div>
        </div>
      </section>
    </div>"""

    reports_card = f"""<section id="stock-reports-section" class="card" aria-labelledby="reports-title">
      <div class="card-h">
        <h2 id="reports-title">{icon("book", 16)}AI 리포트</h2>
        {badge(str(model["refresh_state"]), "b-amber" if refresh_recommended else "b-teal")}
      </div>
      <div class="card-b">
        <div class="report-grid">
          {reports_html}
        </div>
        {report_actions_html}
      </div>
    </section>"""

    notices = f"""<section class="soft notice-strip" aria-label="투자 유의사항">
      <ul>{notices_html}</ul>
    </section>"""

    scripts = (
        f'<script id="stock-payload" type="application/json">{payload_json}</script>\n'
        f'<script src="{LIGHTWEIGHT_CHARTS_SRC}"></script>'
    )

    return f"""{hero}
<section class="block">
  <div class="shell">
    <div class="grid-4 stock-stats">{tiles}</div>
    <div class="grid-main">
      {chart_card}
      {side}
    </div>
    {lenses_html}
    <section class="block">{reports_card}</section>
    {outcomes_html}
    {notices}
  </div>
</section>
{scripts}"""

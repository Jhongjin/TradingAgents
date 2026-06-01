"""Server-rendered public pages for the TradingAgents Korea site."""

from __future__ import annotations

import html
import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from tradingagents.storage import StorageRepository

from .analysis_api import (
    build_public_analysis_bundle_payload,
    build_public_analysis_feed_payload,
    build_public_analysis_outcomes_payload,
)
from .public_api import build_public_stock_payload
from .seo import canonical_url, stock_canonical_url


TOP_NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("/", "종목 검색"),
    ("/analyses", "AI 리포트"),
    ("/outcomes", "사후 결과"),
    ("/features/methodology", "분석 기준"),
)


def _top_nav(*, label: str = "주요 메뉴", current: str = "") -> str:
    current_path = current.split("#", 1)[0]

    def link(href: str, text: str, *, class_name: str | None = None, visible: str | None = None, hidden: bool = False) -> str:
        classes = f' class="{class_name}"' if class_name else ""
        visible_attr = f' data-auth-visible="{visible}"' if visible else ""
        hidden_attr = " hidden" if hidden else ""
        current_attr = ' aria-current="page"' if current_path == href else ""
        return f'<a{classes} href="{_h(href)}"{visible_attr}{hidden_attr}{current_attr}>{_h(text)}</a>'

    public_links = "\n      ".join(link(href, text) for href, text in TOP_NAV_ITEMS)
    auth_links = "\n      ".join(
        (
            link("/member", "로그인", class_name="top-auth-link", visible="signed-out"),
            link("/member?mode=signup", "내 공간 만들기", class_name="top-join-link", visible="signed-out"),
            link("/mypage", "내 공간", class_name="top-dashboard-link", visible="signed-in", hidden=True),
            link("/admin", "운영 콘솔", class_name="top-admin-link", visible="admin", hidden=True),
        )
    )
    return f"""<nav class="top-links" aria-label="{_h(label)}">
      {public_links}
      {auth_links}
    </nav>"""


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
    """Render the first public stock-analysis page.

    The page uses the same JSON payload as the API and upgrades the price chart
    with TradingView Lightweight Charts when available, while keeping the local
    canvas renderer as a dependency-free fallback.
    """

    payload = build_public_stock_payload(
        ticker,
        repo=repo,
        chart_start=chart_start,
        chart_end=chart_end,
        as_of_date=as_of_date,
        max_analysis_age_days=max_analysis_age_days,
        chart_vendor=chart_vendor,
        chart_interval=chart_interval,
    )
    notice_items = _stock_notice_items(payload.get("notices", []))
    page_payload = {**payload, "notices": notice_items}
    model = _view_model(page_payload, site_base_url=site_base_url)
    payload_json = _script_json(page_payload)
    structured_data_json = _script_json(_structured_data(model, page_payload))
    chart_controls_html = _chart_controls(model)
    reports_html = _report_cards(model["reports"])
    stock_report_actions_html = _stock_report_actions(model)
    lenses_html = _strategy_lens_cards(payload.get("strategy_lenses") or [])
    outcomes_html = _outcome_cards((payload.get("analysis") or {}).get("outcomes") or [])
    notices_html = "".join(f"<li>{_h(notice)}</li>" for notice in notice_items)
    chart_source_html = _data_source_strip(model["chart_source_rows"], label="차트 데이터 기준")
    chart_tools_html = _chart_tools()
    analysis_source_html = _data_source_strip(model["analysis_source_rows"], label="AI 리서치 출처")
    confidence_html = _analysis_confidence_panel(model["analysis_confidence"])
    stock_signal_html = _stock_signal_card(model)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(model["title"])}</title>
  <meta name="description" content="{_h(model["description"])}">
  <link rel="canonical" href="{_h(model["canonical_url"])}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(model["title"])}">
  <meta property="og:description" content="{_h(model["description"])}">
  <meta property="og:url" content="{_h(model["canonical_url"])}">
  <script type="application/ld+json">{structured_data_json}</script>
  <style>{PAGE_CSS}</style>
</head>
<body class="public-home market-page stock-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="종목과 리서치", current="/")}
    <form class="ticker-search" action="/stocks" method="get">
      <label class="sr-only" for="ticker">종목코드 또는 종목명</label>
      <input id="ticker" name="ticker" list="tickerSuggestions" maxlength="80" value="{_h(model["code"])}" placeholder="005930 또는 삼성전자" autocomplete="off">
      <datalist id="tickerSuggestions"></datalist>
      <button type="submit">조회</button>
    </form>
  </header>

  <main id="main-content" class="shell market-shell">
    <section class="summary-band" aria-labelledby="stock-title">
      <div>
        <p class="eyebrow">{_h(model["market_line"])}</p>
        <h1 id="stock-title">{_h(model["name"])} <span>{_h(model["code"])}</span></h1>
        <p class="asof">{_h(model["generated_at"])} 기준</p>
        <p class="stock-hero-copy">가격 흐름, AI 의견, 사후 결과를 한 화면에서 확인합니다.</p>
        <div class="stock-hero-actions" aria-label="종목 상세 주요 이동">
          <a href="/analyses?ticker={_h(model["code"])}">리포트 보기</a>
          <a href="/member?mode=signup&tab=analysis#analysis-request-section">새 분석 요청</a>
        </div>
        <nav class="stock-mobile-jumpbar" aria-label="모바일 종목 상세 빠른 이동">
          <a href="#stock-chart-section">가격 보기</a>
          <a href="#stock-reports-section">리포트 보기</a>
          <a href="/member?mode=signup&tab=analysis#analysis-request-section">분석 요청</a>
        </nav>
      </div>
      <aside class="stock-hero-stack" aria-label="종목 리서치 요약">
        <div class="decision-box">
          <span class="decision-label">AI 의견 요약</span>
          <strong>{_h(model["rating"])}</strong>
          <span>{_h(model["action"])}</span>
        </div>
        {stock_signal_html}
      </aside>
    </section>

    <section class="workspace">
      <section id="stock-chart-section" class="chart-panel" aria-labelledby="chart-title">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">가격</p>
            <h2 id="chart-title">가격 차트</h2>
          </div>
          <div class="chart-heading-meta">
            <span class="status-pill">{_h(model["chart_status"])}</span>
            <span class="data-pill">{_h(model["chart_vendor_label"])}</span>
          </div>
        </div>
        {chart_controls_html}
        {chart_tools_html}
        <p class="chart-caption">{_h(model["chart_caption"])}</p>
        {chart_source_html}
        <div class="chart-wrap" data-chart-engine="tradingview-lightweight">
          <div id="priceChart" class="tv-price-chart" role="img" aria-label="{_h(model["name"])} 가격 차트"></div>
          <canvas id="priceChartCanvas" class="chart-canvas-fallback" aria-label="{_h(model["name"])} 가격 차트 예비 렌더러" hidden></canvas>
          <svg id="chartDrawingLayer" class="chart-drawing-layer" aria-hidden="true"></svg>
          <div class="chart-legend" id="chartLegend" aria-hidden="true"></div>
          <div class="chart-tooltip" id="chartTooltip" hidden></div>
          <p id="chartFallback" class="chart-fallback" hidden>{_h(model["chart_fallback"])}</p>
        </div>
        <p class="chart-attribution"><a href="https://www.tradingview.com/" rel="noopener noreferrer" target="_blank">TradingView Lightweight Charts</a> 기반 차트입니다.</p>
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

        <section id="stock-analysis-section" class="analysis-panel">
          <p class="eyebrow">AI 리서치</p>
          <h2>{_h(model["analysis_title"])}</h2>
          <p>{_h(model["rationale"])}</p>
          {analysis_source_html}
          {confidence_html}
        </section>

        <section id="stock-simulation-section" class="simulation-panel" aria-labelledby="simulation-title">
          <p class="eyebrow">AI 가상매매</p>
          <h2 id="simulation-title">가상 매수·매도 기록</h2>
          <div id="simulationPreview" class="simulation-preview" data-simulation-url="/api/simulations/preview/{_h(model["code"])}">
            <span class="status-pill">확인 중</span>
          </div>
        </section>
      </aside>
    </section>

    {lenses_html}

    <section id="stock-reports-section" class="report-section" aria-labelledby="reports-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">저장된 리포트</p>
          <h2 id="reports-title">AI 리포트</h2>
        </div>
        <span class="status-pill">{_h(model["refresh_state"])}</span>
      </div>
      <div class="report-grid">
        {reports_html}
      </div>
      {stock_report_actions_html}
    </section>

    {outcomes_html}

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>{notices_html}</ul>
    </section>
  </main>

  <script id="stock-payload" type="application/json">{payload_json}</script>
  <script src="https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"></script>
  <script>{PAGE_JS}</script>
</body>
</html>"""


def render_public_analysis_feed_page(
    *,
    repo: StorageRepository | None = None,
    ticker: str | None = None,
    limit: int = 20,
    max_limit: int = 50,
    site_base_url: str | None = None,
) -> str:
    """Render a public completed-analysis feed page."""

    payload = _analysis_feed_payload(repo, ticker=ticker, limit=limit, max_limit=max_limit)
    model = _analysis_feed_view_model(payload, site_base_url=site_base_url)
    has_items = bool(model["items"])
    summary_html = _analysis_summary_cards(model["summary"], basis_label=model["basis_label"]) if has_items else ""
    track_record_html = _analysis_track_record_cards(model["summary"], basis_label=model["basis_label"]) if has_items else ""
    pipeline_html = (
        """
    <section class="analysis-pipeline-strip" aria-label="공개 분석 공개 기준">
      <article>
        <span>01</span>
        <strong>AI 리포트</strong>
        <small>완료 리포트만 표시</small>
      </article>
      <article>
        <span>02</span>
        <strong>AI 의견과 근거</strong>
        <small>본문과 원문 분리</small>
      </article>
      <article>
        <span>03</span>
        <strong>사후 결과</strong>
        <small>5일/20일 결과</small>
      </article>
    </section>
    """
        if has_items
        else ""
    )
    filter_state_html = _analysis_filter_state(model)
    feed_toolbar_html = _analysis_feed_toolbar(model)
    cards_html = _analysis_feed_cards(
        model["items"],
        ticker_code=model["ticker_code"],
        filter_label=model["filter_label"],
    )
    payload_json = _script_json(payload)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(model["title"])}</title>
  <meta name="description" content="{_h(model["description"])}">
  <link rel="canonical" href="{_h(model["canonical_url"])}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(model["title"])}">
  <meta property="og:description" content="{_h(model["description"])}">
  <meta property="og:url" content="{_h(model["canonical_url"])}">
  <style>{PAGE_CSS}</style>
</head>
<body class="public-home market-page analysis-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="공개 리서치", current="/analyses")}
  </header>

  <main id="main-content" class="shell market-shell">
    <section class="summary-band" aria-labelledby="feed-title">
      <div>
        <p class="eyebrow">공개 리서치</p>
        <h1 id="feed-title">AI 리포트</h1>
        <p class="asof">{_h(model["subtitle"])}</p>
      </div>
      <div class="decision-box">
        <span class="decision-label">AI 리포트</span>
        <strong>{_h(model["item_count"])}</strong>
        <span>{_h(model["status"])}</span>
      </div>
    </section>

    <section class="analysis-filter-panel" aria-label="공개 분석 필터">
      <div class="analysis-filter-stack">
        <form class="analysis-filter-form" action="/analyses" method="get">
          <label for="analysisTicker">종목명 또는 코드</label>
          <input id="analysisTicker" name="ticker" list="analysisTickerSuggestions" maxlength="80" value="{_h(str(model["ticker_code"] or ""))}" placeholder="005930 또는 삼성전자" autocomplete="off" data-ticker-lookup data-ticker-submit>
          <datalist id="analysisTickerSuggestions"></datalist>
          <button type="submit">리포트 찾기</button>
          <a href="/analyses">전체 보기</a>
        </form>
        {filter_state_html}
      </div>
      <p>종목명이나 6자리 코드로 공개 리포트만 검색합니다.</p>
    </section>

    {pipeline_html}

    {summary_html}

    {track_record_html}

    <section class="report-section" aria-labelledby="feed-list-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">리포트 목록</p>
          <h2 id="feed-list-title">최근 AI 리포트</h2>
        </div>
        <span class="status-pill">{_h(model["filter_label"])}</span>
      </div>
      {feed_toolbar_html}
      <div class="analysis-feed-grid">
        {cards_html}
      </div>
    </section>

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>
        <li>AI 분석은 정보 제공용이며 투자 조언이 아닙니다.</li>
        <li>실거래와 브로커 주문 실행은 의도적으로 지원하지 않습니다.</li>
      </ul>
    </section>
  </main>

  <script id="analysis-feed-payload" type="application/json">{payload_json}</script>
  <script>{PAGE_JS}</script>
</body>
</html>"""


def render_public_outcomes_page(
    *,
    repo: StorageRepository | None = None,
    ticker: str | None = None,
    status: str | None = None,
    limit: int = 20,
    max_limit: int = 50,
    site_base_url: str | None = None,
) -> str:
    """Render a public outcome verification dashboard."""

    payload = _analysis_outcomes_payload(repo, ticker=ticker, status=status, limit=limit, max_limit=max_limit)
    model = _analysis_outcomes_view_model(payload, site_base_url=site_base_url)
    has_items = bool(model["items"])
    summary_html = _analysis_outcome_summary_cards(model["summary"]) if has_items else ""
    cadence_html = _analysis_outcome_cadence_strip(model) if has_items else ""
    filter_state_html = _outcome_filter_state(model)
    feed_toolbar_html = _outcome_feed_toolbar(model)
    cards_html = _analysis_outcome_feed_cards(
        model["items"],
        ticker_code=model["ticker_code"],
        filter_status=model["filter_status"],
        filter_label=model["filter_label"],
    )
    payload_json = _script_json(payload)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(model["title"])}</title>
  <meta name="description" content="{_h(model["description"])}">
  <link rel="canonical" href="{_h(model["canonical_url"])}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(model["title"])}">
  <meta property="og:description" content="{_h(model["description"])}">
  <meta property="og:url" content="{_h(model["canonical_url"])}">
  <style>{PAGE_CSS}</style>
</head>
<body class="public-home market-page outcome-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="공개 리서치", current="/outcomes")}
  </header>

  <main id="main-content" class="shell market-shell">
    <section class="summary-band outcome-hero" aria-labelledby="outcomes-title">
      <div>
        <p class="eyebrow">사후 점검</p>
        <h1 id="outcomes-title">리포트 사후 결과</h1>
        <p class="asof">{_h(model["subtitle"])}</p>
        <div class="analysis-detail-actions">
          <a href="/analyses">AI 리포트</a>
          <a href="/features/outcomes">계산 기준</a>
          <a href="/api/analysis-outcomes">원문 데이터</a>
        </div>
      </div>
      <div class="decision-box">
        <span class="decision-label">사후 결과</span>
        <strong>{_h(model["item_count"])}</strong>
        <span>{_h(model["status_label"])}</span>
      </div>
    </section>

    <section class="analysis-filter-panel outcome-filter-panel" aria-label="사후 결과 필터">
      <div class="analysis-filter-stack">
        <form class="analysis-filter-form outcome-filter-form" action="/outcomes" method="get">
          <label for="outcomeTicker">종목명 또는 코드</label>
          <input id="outcomeTicker" name="ticker" list="outcomeTickerSuggestions" maxlength="80" value="{_h(str(model["ticker_code"] or ""))}" placeholder="005930 또는 삼성전자" autocomplete="off" data-ticker-lookup data-ticker-submit>
          <datalist id="outcomeTickerSuggestions"></datalist>
          <label for="outcomeStatus">상태</label>
          <select id="outcomeStatus" name="status">
            {_outcome_status_options(model["filter_status"])}
          </select>
          <button type="submit">사후 결과 찾기</button>
          <a href="/outcomes">전체 보기</a>
        </form>
        {filter_state_html}
      </div>
      <p>조회할 종목코드나 종목명을 입력하세요.</p>
    </section>

    {summary_html}

    {cadence_html}

    <section class="report-section outcome-feed-section" aria-labelledby="outcome-feed-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">사후 결과 목록</p>
          <h2 id="outcome-feed-title">최근 사후 결과</h2>
        </div>
        <span class="status-pill">{_h(model["filter_label"])}</span>
      </div>
      {feed_toolbar_html}
      <div class="outcome-feed-grid">
        {cards_html}
      </div>
    </section>

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>
        <li>사후 결과는 과거 리포트 점검 자료이며 미래 수익을 보장하지 않습니다.</li>
        <li>TradingAgents Korea는 실거래 주문이나 브로커 주문 실행 기능을 제공하지 않습니다.</li>
      </ul>
    </section>
  </main>

  <script id="outcomes-payload" type="application/json">{payload_json}</script>
  <script>{PAGE_JS}</script>
</body>
</html>"""


def render_public_analysis_detail_page(
    analysis_run_id: str,
    *,
    repo: StorageRepository | None = None,
    site_base_url: str | None = None,
) -> str:
    """Render one addressable public analysis report page."""

    payload = build_public_analysis_bundle_payload(repo, analysis_run_id=analysis_run_id) if repo is not None else None
    if payload is None:
        raise ValueError("Public analysis not found")
    model = _analysis_detail_view_model(payload, analysis_run_id=analysis_run_id, site_base_url=site_base_url)
    reports_html = _analysis_detail_report_cards(
        model["reports"],
        run_id=model["run_id"],
        ticker_code=model["ticker_code"],
    )
    decision_html = _analysis_detail_decision_card(
        model["decision"],
        run_id=model["run_id"],
        ticker_code=model["ticker_code"],
    )
    outcomes_html = _outcome_cards(model["outcomes"])
    provenance_html = _analysis_detail_provenance(model)
    detail_map_html = _analysis_detail_map(model)
    next_actions_html = _analysis_detail_next_actions(model)
    payload_json = _script_json(payload)
    structured_data_json = _script_json(_analysis_detail_structured_data(model, payload))

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(model["title"])}</title>
  <meta name="description" content="{_h(model["description"])}">
  <link rel="canonical" href="{_h(model["canonical_url"])}">
  <meta property="og:type" content="article">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(model["title"])}">
  <meta property="og:description" content="{_h(model["description"])}">
  <meta property="og:url" content="{_h(model["canonical_url"])}">
  <style>{PAGE_CSS}</style>
  <script type="application/ld+json">{structured_data_json}</script>
</head>
<body class="public-home market-page analysis-page analysis-detail-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="공개 리서치", current="/analyses")}
  </header>

  <main id="main-content" class="shell market-shell">
    <section class="analysis-detail-hero" aria-labelledby="analysis-detail-title">
      <div>
        <p class="eyebrow">공개 분석 리포트</p>
        <h1 id="analysis-detail-title">{_h(model["heading"])}</h1>
        <p class="asof">{_h(model["subtitle"])}</p>
        <p class="analysis-detail-lede">공개 데이터와 AI 의견을 정리한 리포트입니다. 기준일, 출처, 본문, 사후 결과를 함께 확인합니다.</p>
        <div class="analysis-detail-meta-strip" aria-label="리포트 기준">
          <span>{_h(model["market"])}</span>
          <span>{_h(model["ticker_code"])}</span>
          <span>{_h(model["trade_date"])} 기준</span>
          <span>주문 없음</span>
        </div>
        <div class="analysis-detail-actions">
          <a href="/stocks/{_h(model["ticker_code"])}">종목 보기</a>
          <a href="/analyses">리포트 목록</a>
          <a class="subtle-action" href="/api/analyses/{_h(model["run_id"])}">원문 데이터</a>
        </div>
      </div>
      <aside class="decision-box analysis-detail-decision">
        <span class="decision-label">투자 조언 아님</span>
        <strong>{_h(model["decision_label"])}</strong>
        <span>{_h(model["data_basis"])}</span>
      </aside>
    </section>

    {detail_map_html}

    <section id="analysis-provenance" class="analysis-provenance-grid" aria-label="리포트 출처와 한계">
      {provenance_html}
    </section>

    {decision_html}

    <section id="analysis-reports" class="report-section analysis-detail-reports" aria-labelledby="analysis-reports-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">AI 리포트</p>
          <h2 id="analysis-reports-title">AI 리포트</h2>
        </div>
        <span class="status-pill">{_h(model["report_count_label"])}</span>
      </div>
      <div class="analysis-report-stack">
        {reports_html}
      </div>
      <p class="analysis-report-note">본문 일부만 먼저 보여줍니다. 전체 원문은 원문 데이터에서 확인하세요.</p>
    </section>

    {outcomes_html}

    {next_actions_html}

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>
        <li>이 AI 리포트는 정보 제공용이며 투자 조언이나 매수/매도 지시가 아닙니다.</li>
        <li>TradingAgents Korea는 실거래 주문이나 브로커 주문 실행 기능을 제공하지 않습니다.</li>
      </ul>
    </section>
  </main>

  <script id="analysis-detail-payload" type="application/json">{payload_json}</script>
  <script>{PAGE_JS}</script>
</body>
</html>"""


def render_public_home_page(
    *,
    repo: StorageRepository | None = None,
    site_base_url: str | None = None,
) -> str:
    """Render the public landing page for Korean stock analysis."""

    payload = _analysis_feed_payload(repo, ticker=None, limit=6, max_limit=50)
    model = _home_view_model(payload, site_base_url=site_base_url)
    recent_html = _analysis_feed_cards(model["recent_items"])
    quick_html = _quick_ticker_cards()

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(model["title"])}</title>
  <meta name="description" content="{_h(model["description"])}">
  <link rel="canonical" href="{_h(model["canonical_url"])}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(model["title"])}">
  <meta property="og:description" content="{_h(model["description"])}">
  <meta property="og:url" content="{_h(model["canonical_url"])}">
  <style>{PAGE_CSS}</style>
</head>
<body class="public-home">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="공개 리서치", current="/")}
  </header>

  <main id="main-content" class="home-shell home-shell-art">
    <section class="home-hero home-hero-artboard" aria-labelledby="home-title">
      <div class="home-hero-copy home-hero-content">
        <p class="home-kicker">실거래 주문 없이 오직 데이터로 증명하는 한국 주식 AI 관제 시스템</p>
        <h1 id="home-title">한국 주식 AI 관제 시스템</h1>
        <p class="home-lede">다차원 AI 데이터 엔진이 찾아낸 한국 주식의 맥락. 종목 검색 한 번으로 가격 흐름, DART 공시, Naver 뉴스 반응, 그리고 AI 가상 매매 시뮬레이션까지 단 하나의 통합 타임라인 차트에서 관제하세요.</p>
        <form class="ticker-search home-search home-command-search" action="/stocks" method="get">
          <label class="sr-only" for="ticker">종목코드 또는 종목명</label>
          <input id="ticker" name="ticker" list="tickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" autocomplete="off">
          <datalist id="tickerSuggestions"></datalist>
          <button type="submit">조회</button>
        </form>
        <div class="home-cta-row home-action-row" aria-label="첫 방문자 주요 행동">
          <a class="home-sample-pill" href="/stocks/005930" aria-label="삼성전자 샘플 분석실 바로가기"><span aria-hidden="true">💡</span> 삼성전자 샘플 분석실 바로가기</a>
          <a class="home-secondary-link" href="/member?mode=signup">내 공간 만들기</a>
        </div>
        <aside class="home-member-preview" aria-label="AI 관제 흐름">
          <strong>AI 관제 흐름</strong>
          <ul>
            <li><span>데이터 수집</span><small>KRX·DART·뉴스 반응을 같은 기준일로 묶습니다.</small></li>
            <li><span>AI 리포트</span><small>복수 에이전트가 근거와 판단을 구조화합니다.</small></li>
            <li><span>가상매매</span><small>리포트 이후 가상 진입·청산 기록을 남깁니다.</small></li>
          </ul>
        </aside>
      </div>
      <div class="home-hero-visual home-signal-art" aria-label="한국 주식 AI 분석 신호 아트보드">
        <div class="home-analyst-window-caption">
          <span>삼성전자(005930) 실시간 AI 가상 관제 시뮬레이션 예시</span>
          <small>Read-only</small>
        </div>
        <canvas id="homeSignalCanvas" class="home-signal-canvas" aria-hidden="true"></canvas>
        <div class="home-market-field" aria-hidden="true">
          <span class="home-scanline"></span>
          <span class="home-index-map"></span>
          <span class="home-signal-thread"></span>
        </div>
        <div class="home-console signal-stock-card">
          <div class="home-console-top">
            <span>AI 가상 관제</span>
            <span>주문 차단</span>
          </div>
          <div class="home-console-focus">
            <span id="homeSignalTicker">005930 / 삼성전자</span>
            <strong id="homeSignalDecision">가상 진입 대기</strong>
            <small id="homeSignalMeta">가격 흐름 + 공시 + 뉴스 반응 + 5일/20일 사후 결과</small>
          </div>
          <div class="home-sparkline" aria-hidden="true">
            <i style="--h: 38%"></i>
            <i style="--h: 62%"></i>
            <i style="--h: 48%"></i>
            <i style="--h: 74%"></i>
            <i style="--h: 55%"></i>
            <i style="--h: 86%"></i>
            <i style="--h: 68%"></i>
            <i style="--h: 79%"></i>
          </div>
          <div class="home-console-grid signal-vector-row">
            <div><span>가격</span><strong>캔들 차트</strong></div>
            <div><span>공시</span><strong>DART</strong></div>
            <div><span>뉴스</span><strong>Naver</strong></div>
            <div><span>사후 결과</span><strong>5일 / 20일</strong></div>
          </div>
        </div>
        <div class="home-pipeline signal-flow-row" aria-hidden="true">
          <span>KRX</span>
          <span>DART</span>
          <span>뉴스</span>
          <span>AI</span>
          <span>리포트</span>
        </div>
        <div class="home-live-tape" aria-hidden="true">
          <div class="home-live-tape-track">
            <span>005930 삼성전자 / 정밀 캔들 / DART 공시</span>
            <span>000660 SK하이닉스 / 시장 대비 / 뉴스 반응</span>
            <span>035420 NAVER / 공시 확인 / 20일 기록</span>
            <span>086520 에코프로 / 변동성 점검 / 주문 없음</span>
            <span>005930 삼성전자 / 정밀 캔들 / DART 공시</span>
            <span>000660 SK하이닉스 / 시장 대비 / 뉴스 반응</span>
          </div>
        </div>
      </div>
    </section>

    <section class="home-start-strip" aria-label="서비스 요약">
      <div class="home-trust-panel" aria-label="신뢰 운영 기준">
        <div>
          <span>공식·공개 데이터</span>
          <strong>KRX / DART / Naver</strong>
        </div>
        <div>
          <span>사후 결과</span>
          <strong>5일/20일 사후 결과</strong>
        </div>
        <div>
          <span>투자자 보호</span>
          <strong>실거래 주문 기능 차단</strong>
        </div>
      </div>
      <dl class="home-proof-row home-signal-strip" aria-label="운영 상태">
        <div>
          <dt>시장</dt>
          <dd>KOSPI/KOSDAQ</dd>
        </div>
        <div>
          <dt>데이터</dt>
          <dd>공식·공개 출처</dd>
        </div>
        <div>
          <dt>모드</dt>
          <dd>주문 없음</dd>
        </div>
      </dl>
    </section>

    <section class="home-service-map" aria-labelledby="service-map-title">
      <div class="home-section-heading">
        <div>
          <p class="eyebrow">사용 흐름</p>
          <h2 id="service-map-title">AI 리서치부터 가상 매매 시뮬레이션까지의 파이프라인</h2>
        </div>
        <p>종목 검색에서 AI 리포트, 개인 기록, AI 가상매매까지 이어지는 조회 전용 데이터 운영 흐름입니다.</p>
      </div>
      <div class="home-service-grid">
        <article>
          <span>01</span>
          <strong>멀티 에이전트 다차원 분석</strong>
          <p>종목코드나 종목명으로 가격, 공시, 뉴스, AI 의견, 데이터 출처를 한 화면에서 연결합니다.</p>
          <a href="/stocks/005930">샘플 종목 보기</a>
        </article>
        <article>
          <span>02</span>
          <strong>개인 매매 일지 및 관심그룹</strong>
          <p>개인 매매 일지와 관심그룹을 분리해 관리합니다. 실제 계좌나 주문 경로는 연결하지 않습니다.</p>
          <a href="/member?mode=signup">내 공간 만들기</a>
        </article>
        <article>
          <span>03</span>
          <strong>실시간 AI 리포트 생성 대기열 운영</strong>
          <p>더 살펴보고 싶은 한국 종목을 대기열에 올리고, 처리 상태와 완료 리포트 연결을 확인합니다.</p>
          <a href="/member?mode=signup&tab=analysis#analysis-request-section">분석 요청으로 시작하기</a>
        </article>
      </div>
    </section>

    <section class="home-lens-band" aria-labelledby="lens-home-title">
      <div class="home-section-heading">
        <div>
          <p class="eyebrow">분석 흐름</p>
          <h2 id="lens-home-title">하나의 차트 위로 융합되는 5대 핵심 시그널 맵</h2>
        </div>
        <p>가격 흐름, 공시, 뉴스, AI 의견, 사후 결과를 같은 타임라인에서 읽도록 공개 분석의 맥락을 만듭니다. <a href="/features/research">AI 리포트 흐름 보기</a></p>
      </div>
      <div class="home-lens-grid">
        <article><span>01</span><strong>가격</strong><p>정밀 캔들 차트와 이동평균, 거래량 흐름을 통해 가격의 맥락을 분석합니다.</p></article>
        <article><span>02</span><strong>공시</strong><p>DART 공시와 재무 이벤트를 분석 흐름에 반영합니다.</p></article>
        <article><span>03</span><strong>뉴스</strong><p>Naver 뉴스 신호로 단기 이슈와 시장 반응을 추적합니다.</p></article>
        <article><span>04</span><strong>AI 의견</strong><p>복수 에이전트의 근거와 의견을 AI 리포트 구조로 정리합니다.</p></article>
        <article><span>05</span><strong>사후 결과</strong><p>5일/20일 흐름으로 분석 이후를 되돌아봅니다.</p></article>
      </div>
    </section>

    <section class="home-analysis-zone home-recent-intel" aria-labelledby="recent-title">
      <div class="home-section-copy">
        <p class="eyebrow">AI 리포트</p>
        <h2 id="recent-title">최근 공개 분석</h2>
        <p>완료된 AI 분석은 종목 페이지와 공개 목록에 누적됩니다. AI 의견, 모델, 리포트 수, 시장 대비를 빠르게 훑고 원문 데이터까지 확인할 수 있습니다.</p>
        <a class="home-secondary-link" href="/analyses">전체 리포트</a>
      </div>
      <div class="home-analysis-grid">
        {recent_html}
      </div>
    </section>

    <section class="home-band home-stock-jump" aria-labelledby="quick-title">
      <div class="home-section-heading">
        <div>
          <p class="eyebrow">바로가기</p>
          <h2 id="quick-title">주요 종목 바로가기</h2>
        </div>
        <p>삼성전자, SK하이닉스, NAVER처럼 자주 확인하는 종목은 바로 차트와 공개 분석 페이지로 이동합니다.</p>
      </div>
      <div class="home-ticker-rail">
        {quick_html}
      </div>
    </section>

    <section class="home-band home-member-band" aria-labelledby="member-title">
      <div class="home-section-heading">
        <div>
          <p class="eyebrow">회원 기능</p>
          <h2 id="member-title">내 리서치 공간이 열립니다</h2>
        </div>
        <a class="home-primary-link" href="/member?mode=signup">회원으로 시작하기</a>
      </div>
      <div class="home-flow-list">
        <article>
          <span class="home-flow-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false"><path d="M4 5.5h16M7 9v9m5-6v6m5-10v10M5 19h14"/></svg>
          </span>
          <strong>개인 매매 일지</strong>
          <p>매수·매도 기록, 평균단가, 목표가, 손절가를 실제 주문 연결 없이 정리합니다.</p>
        </article>
        <article>
          <span class="home-flow-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false"><path d="M13 3 5 14h6l-1 7 9-12h-6l1-6Z"/></svg>
          </span>
          <strong>관심그룹</strong>
          <p>자주 보는 종목을 그룹으로 묶고 메모와 현재 상태를 함께 확인합니다.</p>
        </article>
        <article>
          <span class="home-flow-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false"><path d="M12 21a9 9 0 1 0-9-9m9 5v-5l4-4M8 12h4"/></svg>
          </span>
          <strong>분석 요청 대기열</strong>
          <p>원하는 종목을 AI 리포트 생성 대기열에 올리고 완료 리포트를 추적합니다.</p>
        </article>
      </div>
    </section>

    <section class="home-ops-strip home-readonly-banner" aria-label="안전한 조회 전용 운영 원칙">
      <div>
        <p class="eyebrow">운영 원칙</p>
        <h2>안전한 조회 전용 운영 원칙</h2>
      </div>
      <ul>
        <li>실제 주문, 계좌 연결, 투자 자문을 제공하지 않습니다.</li>
        <li>AI 분석과 AI 가상매매는 판단 근거를 정리하는 정보 제공용 자료입니다.</li>
        <li><a href="/features/methodology">분석 기준</a>, <a href="/disclaimer">투자 유의사항</a>, <a href="/terms">이용약관</a>, <a href="/privacy">개인정보처리방침</a>을 공개합니다.</li>
      </ul>
    </section>
  </main>

  <script>{PAGE_JS}</script>
</body>
</html>"""


FEATURE_DETAIL_PAGES: dict[str, dict[str, Any]] = {
    "research": {
        "path": "/features/research",
        "title": "AI 리포트 흐름 | TradingAgents Korea",
        "description": "가격, 공시, 뉴스, AI 의견을 한 화면에 묶는 공개 리포트 흐름입니다.",
        "eyebrow": "AI 리포트",
        "heading": "가격·출처·AI 의견을 한 화면에서 봅니다",
        "lead": "종목명이나 6자리 코드로 검색하면 가격 흐름, 데이터 출처, AI 리포트, 사후 결과를 바로 확인할 수 있습니다. 저장과 새 요청은 내 공간에서 이어집니다.",
        "proof": (("공개 페이지", "종목·분석 피드"), ("데이터", "KRX / DART / Naver"), ("주문", "실거래 차단")),
        "cards": (
            ("종목 조회", "6자리 한국 종목코드와 종목명 검색으로 KOSPI/KOSDAQ 종목을 찾습니다."),
            ("차트 데이터", "OHLCV 차트, 가격 상태, 데이터 제공처 표기를 종목 화면에만 전달합니다."),
            ("공개 분석", "완료된 AI 리포트와 판단, 모델, 리포트 수를 공개 피드와 연결합니다."),
        ),
        "journey_heading": "검색 후 바로 읽을 수 있습니다",
        "journey_intro": "공개 화면에서는 종목을 먼저 보고, 다시 볼 종목만 내 공간에 담습니다.",
        "journey": (
            ("01", "종목 검색", "삼성전자처럼 종목명으로 검색해도 6자리 코드 화면으로 이동합니다."),
            ("02", "출처 확인", "가격 기준일, 제공처, 대체 데이터 사용 여부를 먼저 봅니다."),
            ("03", "리포트 읽기", "AI 의견과 에이전트별 리포트를 투자 판단의 참고자료로 읽습니다."),
            ("04", "가입 후 저장", "관심그룹과 분석 요청은 로그인한 내 공간에만 저장됩니다."),
        ),
        "steps": ("종목 검색", "KRX 가격 데이터", "DART 공시", "Naver 뉴스", "AI 리포트"),
        "cta_label": "삼성전자 예시 보기",
        "cta_href": "/stocks/005930",
        "secondary_cta_label": "내 공간 보기",
        "secondary_cta_href": "/features/member-workspace",
        "diagram_label": "AI 리포트",
    },
    "member-workspace": {
        "path": "/features/member-workspace",
        "title": "내 공간 | TradingAgents Korea",
        "description": "로그인한 사용자를 위한 매매 일지, 관심그룹, 분석 요청 대기열의 구성 방식입니다.",
        "eyebrow": "내 공간",
        "heading": "가입하면 매매 일지, 관심그룹, 분석 요청을 한 곳에서 관리합니다",
        "lead": "로그인 후에는 매매 일지, 관심그룹, 분석 요청을 내 계정에 저장합니다. 실제 주문·계좌 연결은 없습니다.",
        "proof": (("인증", "이메일 로그인"), ("저장", "사용자별 개인 기록"), ("범위", "조회/기록 전용")),
        "cards": (
            ("매매 일지", "매수·매도 기록, 평균단가, 비용, 목표가, 손절가를 직접 관리합니다."),
            ("관심그룹", "한국 종목코드 기준 관심그룹과 메모를 사용자별로 분리합니다."),
            ("분석 요청 대기열", "원하는 종목과 날짜를 대기열에 넣고 처리 상태를 확인합니다."),
        ),
        "journey_heading": "로그인 후에는 개인 기록만 따로 열립니다",
        "journey_intro": "내 공간은 AI 리포트를 읽은 뒤 내가 다시 볼 종목과 요청 상태를 보관하는 공간입니다.",
        "journey": (
            ("01", "가입/로그인", "이메일 인증 세션을 확인한 뒤에만 개인 데이터를 불러옵니다."),
            ("02", "매매 일지", "매수·매도 내역과 목표가를 주문 연결 없이 직접 남깁니다."),
            ("03", "관심그룹 저장", "다시 확인할 한국 종목을 메모와 함께 묶어 둡니다."),
            ("04", "분석 요청", "필요한 종목만 대기열에 넣고 완료 리포트 연결을 확인합니다."),
        ),
        "steps": ("로그인", "내 공간", "개인 기록", "분석 요청", "주문 차단"),
        "cta_label": "내 공간 만들기",
        "cta_href": "/member?mode=signup",
        "secondary_cta_label": "AI 리포트 먼저 보기",
        "secondary_cta_href": "/features/research",
        "diagram_label": "내 공간",
    },
    "outcomes": {
        "path": "/features/outcomes",
        "title": "사후 결과 | TradingAgents Korea",
        "description": "AI 분석 이후 5일/20일 결과와 시장 대비 차이를 AI 리포트에 연결하는 구조입니다.",
        "eyebrow": "사후 결과",
        "heading": "리포트가 나온 뒤 5일/20일 결과를 다시 확인합니다",
        "lead": "AI 리포트 기준일 뒤 5일/20일 수익률과 시장 대비 차이를 남겨, 리포트를 이후 흐름과 함께 되돌아봅니다.",
        "proof": (("기록", "5일 / 20일"), ("지표", "수익률 / 시장 대비"), ("노출", "AI 리포트")),
        "cards": (
            ("결과 저장", "분석 기준일과 확인 기간별 결과를 저장해 AI 리포트와 연결합니다."),
            ("시장 기준 비교", "KOSPI/KOSDAQ 흐름과 비교한 차이를 함께 보여줍니다."),
            ("운영 점검", "운영 작업이 사후 결과 대상을 처리하고 실패 상태를 확인합니다."),
        ),
        "journey_heading": "사후 결과는 추천 성과가 아니라 리포트 품질 기록입니다",
        "journey_intro": "이 화면은 투자 결과를 보장하지 않고, 과거 공개 리서치가 이후 시장에서 어떻게 움직였는지 확인하는 자료입니다.",
        "journey": (
            ("01", "원 리포트 확인", "어떤 기준일의 AI 의견인지 먼저 확인합니다."),
            ("02", "기간 확인", "5일 또는 20일 확인 기간과 평가일을 봅니다."),
            ("03", "시장 비교", "종목 수익률과 시장 기준 수익률의 차이를 읽습니다."),
            ("04", "다음 판단", "결과를 매매 지시가 아니라 리포트 품질 점검 자료로 남깁니다."),
        ),
        "steps": ("분석 완료", "사후 결과", "시장 기준", "차이 확인", "공개 리뷰"),
        "cta_label": "사후 결과 보기",
        "cta_href": "/outcomes",
        "secondary_cta_label": "분석 기준 보기",
        "secondary_cta_href": "/features/methodology",
        "diagram_label": "사후 결과",
    },
    "methodology": {
        "path": "/features/methodology",
        "title": "분석 기준 | TradingAgents Korea",
        "description": "TradingAgents Korea의 데이터 출처, AI 분석 한계, 사후 결과, 주문 없는 운영 원칙입니다.",
        "eyebrow": "분석 기준",
        "heading": "출처, 기준일, 한계를 함께 확인합니다",
        "lead": "KRX 가격, DART 공시, Naver 뉴스, AI 리포트, 5일·20일 사후 결과를 한 흐름으로 연결합니다. TradingAgents Korea는 리서치 근거만 제공하며 투자 실행 권한은 보유하지 않습니다.",
        "proof": (("출처", "KRX 가격 · DART 공시 · Naver 뉴스"), ("사후 결과", "5일 · 20일 흐름 확인"), ("권한", "실거래 주문 차단")),
        "cards": (
            ("데이터 출처", "가격, 공시, 뉴스가 어디서 왔는지와 대체 경로 사용 여부를 표시하고 원문 데이터 링크를 함께 제공합니다."),
            ("AI 한계", "AI 리포트는 투자 판단 보조 정보입니다. 거래소 지연, 데이터 누락, 모델 해석 오류 가능성을 함께 고지합니다."),
            ("사후 결과", "완료된 공개 분석은 사후 결과 작업이 5일/20일 뒤 종목 수익률과 시장 기준 차이를 추적합니다."),
            ("회원 경계", "회원 매매 일지와 관심그룹은 개인 기록이며 AI 리포트 목록과 분리해 호출합니다."),
            ("운영 보안", "운영 키는 브라우저 세션 입력값으로만 사용하고 HTML, 문서, 커밋에 포함하지 않습니다."),
            ("실행 차단", "증권 계좌 주문 권한은 연결하지 않습니다. 화면의 분석, 기록, 가상매매는 모두 실제 주문과 분리됩니다."),
        ),
        "journey_heading": "출처·한계·성과를 함께 검증합니다",
        "journey_intro": "분석 기준은 화면의 숫자와 문장을 어떤 순서로 읽어야 하는지 알려주는 읽기 순서입니다.",
        "journey": (
            ("01", "출처", "가격, 공시, 뉴스, 리포트가 어디서 왔는지 확인합니다."),
            ("02", "기준일", "차트와 리포트가 같은 날짜 기준인지 점검합니다."),
            ("03", "한계", "누락, 지연, 모델 오류 가능성을 전제로 읽습니다."),
            ("04", "사후 결과", "5일/20일 기록으로 리포트 품질을 계속 되돌아봅니다."),
        ),
        "steps": ("출처 표기", "분석 기준", "AI 리포트", "사후 결과", "주문 없음"),
        "cta_label": "공개 분석 보기",
        "cta_href": "/analyses",
        "secondary_cta_label": "사후 결과 보기",
        "secondary_cta_href": "/features/outcomes",
        "diagram_label": "분석 기준",
        "compact_typography": True,
    },
}


def feature_detail_slugs() -> tuple[str, ...]:
    return tuple(FEATURE_DETAIL_PAGES)


def feature_detail_paths() -> tuple[str, ...]:
    return tuple(str(page["path"]) for page in FEATURE_DETAIL_PAGES.values())


def render_feature_index_page(*, site_base_url: str | None = None) -> str:
    """Render the public feature hub for first-time visitors."""

    feature_cards = "".join(
        f"""<a class="feature-index-card" href="{_h(str(page["path"]))}">
          <span>{index:02d}</span>
          <strong>{_h(str(page["heading"]))}</strong>
          <small>{_h(str(page["description"]))}</small>
        </a>"""
        for index, page in enumerate(FEATURE_DETAIL_PAGES.values(), start=1)
    )
    proof_html = "".join(
        f"""<div><dt>{_h(label)}</dt><dd>{_h(value)}</dd></div>"""
        for label, value in (
            ("공개 리서치", "검색 / 분석 / 사후 결과"),
            ("회원 공간", "관심그룹 / 매매 일지 / 요청"),
            ("투자 실행", "실거래 주문 차단"),
        )
    )
    canonical = canonical_url("/features", site_base_url=site_base_url)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>처음 시작하기 | TradingAgents Korea</title>
  <meta name="description" content="TradingAgents Korea의 종목 검색, AI 리포트, 내 공간, 사후 결과, 분석 기준을 한 번에 확인합니다.">
  <link rel="canonical" href="{_h(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="처음 시작하기 | TradingAgents Korea">
  <meta property="og:description" content="종목 검색부터 내 공간까지, TradingAgents Korea에서 바로 이어갈 순서를 안내합니다.">
  <meta property="og:url" content="{_h(canonical)}">
  <style>{PAGE_CSS}</style>
</head>
<body class="public-home feature-page feature-index-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav()}
  </header>

  <main id="main-content" class="home-shell feature-shell">
    <section class="feature-hero" aria-labelledby="feature-index-title">
      <div class="feature-copy">
        <p class="home-kicker">처음 방문자 흐름</p>
        <h1 id="feature-index-title">종목을 읽고, 필요한 기록만 내 공간에 남깁니다</h1>
        <p>먼저 종목을 검색하고 AI 리포트를 읽어보세요. 가입 후에는 관심그룹, 분석 요청, 매매 일지를 내 공간에 저장합니다. 주문은 실행하지 않습니다.</p>
        <dl class="home-proof-row feature-proof-row" aria-label="서비스 범위">
          {proof_html}
        </dl>
        <div class="home-cta-row">
          <a class="home-primary-link" href="/stocks/005930">샘플 종목 보기</a>
          <a class="home-secondary-link" href="/member?mode=signup">내 공간 만들기</a>
          <a class="home-secondary-link" href="/analyses">공개 분석 보기</a>
        </div>
      </div>
      <div class="feature-diagram" aria-label="서비스 이용 흐름">
        <div class="feature-diagram-top">
          <span>TA-KR</span>
          <span>READ ONLY</span>
        </div>
        <div class="feature-step-track">
          <span>종목 검색</span>
          <span>AI 리포트</span>
          <span>회원 기록</span>
          <span>요청 대기열</span>
          <span>주문 차단</span>
        </div>
        <div class="feature-signal-card">
          <span>첫 방문 경로</span>
          <strong>검색은 공개, 기록은 회원 공간</strong>
          <small>공개 데이터와 개인 기록을 분리해 불러옵니다.</small>
        </div>
      </div>
    </section>

    <section class="feature-index-grid" aria-label="사용 흐름 목록">
      {feature_cards}
    </section>

    <section class="feature-journey" aria-labelledby="feature-index-journey-title">
      <div class="feature-journey-heading">
        <p class="eyebrow">사용자 흐름</p>
        <h2 id="feature-index-journey-title">처음 방문자가 바로 이어갈 수 있는 순서</h2>
        <p>공개 리서치로 먼저 확인하고, 다시 볼 종목이나 새 분석 요청만 회원 공간에 보관하세요.</p>
      </div>
      <div class="feature-journey-grid">
        <article><span>01</span><strong>종목 검색</strong><p>6자리 코드나 종목명으로 공개 가격, 뉴스, 공시, 리포트를 확인합니다.</p></article>
        <article><span>02</span><strong>근거 확인</strong><p>기준일과 출처, AI 의견, 리포트 본문, 사후 결과를 차례로 읽습니다.</p></article>
        <article><span>03</span><strong>회원 저장</strong><p>가입 후 매매 일지, 관심그룹, 분석 요청을 내 공간에 남깁니다.</p></article>
        <article><span>04</span><strong>주문 없음</strong><p>서비스는 브로커 주문 권한을 갖지 않고 기록과 조회 흐름만 제공합니다.</p></article>
      </div>
    </section>
  </main>

  <script>{PAGE_JS}</script>
</body>
</html>"""


POLICY_PAGES: dict[str, dict[str, Any]] = {
    "privacy": {
        "path": "/privacy",
        "title": "개인정보처리방침 | TradingAgents Korea",
        "description": "TradingAgents Korea가 회원 인증, 매매 일지, 분석 요청을 처리할 때 다루는 개인정보와 보관 원칙입니다.",
        "eyebrow": "정책 / 개인정보",
        "heading": "개인정보는 기록과 인증에 필요한 만큼만 다룹니다",
        "lead": "TradingAgents Korea는 공개 리서치와 개인 기록을 분리합니다. 회원 기능은 로그인 세션을 확인한 뒤에만 열리고, 매매 일지·관심그룹·분석 요청은 사용자가 직접 남긴 기록을 다시 확인하고 관리하기 위한 목적으로만 사용합니다.",
        "summary": (("범위", "인증·매매 일지"), ("보관", "사용자별 개인 기록"), ("권한", "주문 실행 없음")),
        "callouts": (
            ("인증", "이메일 로그인과 세션 확인에 필요한 공개 설정만 브라우저에 노출합니다."),
            ("개인 기록", "매매 일지, 관심그룹, 분석 요청은 로그인한 사용자 기록으로 분리합니다."),
            ("외부 서비스", "서비스 운영에는 Vercel, Supabase, OpenAI 및 공개 데이터 제공처가 사용될 수 있습니다."),
        ),
        "sections": (
            (
                "수집하는 정보",
                (
                    "회원 가입과 로그인에 필요한 이메일 주소, 인증 세션 정보",
                    "사용자가 직접 입력한 매매 일지, 매매 기록, 목표가·손절가 메모",
                    "관심그룹, 분석 요청 종목, 요청 메모, 처리 상태와 생성 시각",
                    "서비스 안정성 확인에 필요한 요청 로그, 오류 정보, 상태 점검 결과",
                ),
            ),
            (
                "이용 목적",
                (
                    "회원 본인의 기록을 불러오고 수정할 수 있게 하기 위해 사용합니다.",
                    "분석 요청 대기열을 처리하고 AI 리포트와 사후 결과를 연결하기 위해 사용합니다.",
                    "보안, 장애 대응, 오남용 방지, 성능 개선을 위해 최소한의 운영 로그를 확인합니다.",
                ),
            ),
            (
                "보관과 삭제",
                (
                    "회원 기록은 서비스 운영과 사용자의 조회 목적이 유지되는 동안 보관될 수 있습니다.",
                    "불필요해진 데이터는 운영 정책과 법적 의무에 따라 삭제 또는 익명화할 수 있습니다.",
                    "계정 또는 기록 삭제 요청이 필요한 경우 서비스 운영 채널을 통해 요청할 수 있습니다.",
                ),
            ),
            (
                "제3자 서비스",
                (
                    "인증과 데이터 저장에는 Supabase, 배포와 서버 실행에는 Vercel이 사용될 수 있습니다.",
                    "AI 리포트 생성에는 OpenAI API가 사용될 수 있으며, 공개 종목 데이터는 KRX, DART, Naver 등 출처를 표시합니다.",
                    "광고 또는 분석 도구가 도입되는 경우 공개 페이지와 운영 고지에 반영합니다.",
                ),
            ),
        ),
        "next_actions": (
            ("회원 기능 보기", "/features/member-workspace", "가입하면 어떤 기록 공간이 열리는지 먼저 확인합니다."),
            ("내 공간 열기", "/mypage", "로그인 후 관심그룹과 분석 요청을 내 공간에서 관리합니다."),
            ("분석 기준 확인", "/features/methodology", "데이터 출처와 AI 분석 한계를 함께 읽습니다."),
        ),
    },
    "terms": {
        "path": "/terms",
        "title": "이용약관 | TradingAgents Korea",
        "description": "TradingAgents Korea의 주문 없는 리서치 서비스 이용 조건과 회원 기능의 경계를 설명합니다.",
        "eyebrow": "정책 / 이용약관",
        "heading": "이 서비스는 투자 실행이 아닌 근거 확인을 돕습니다",
        "lead": "TradingAgents Korea는 한국 주식 공개 데이터, AI 리포트, 사후 결과, 회원 매매 일지를 제공하는 리서치 플랫폼입니다. 사용자는 정보를 직접 검토하고 판단해야 하며, 서비스는 매매 주문 권한을 갖지 않습니다.",
        "summary": (("서비스", "AI 리서치"), ("회원 기능", "기록·조회·요청"), ("거래", "실거래 차단")),
        "callouts": (
            ("주문 없음", "자동매매나 브로커 주문 실행 기능은 제공하지 않습니다."),
            ("사용자 관리", "회원 기록은 사용자가 직접 입력하고 관리하는 수동 데이터입니다."),
            ("AI 리포트", "완료된 공개 분석은 종목 페이지와 AI 리포트에 노출될 수 있습니다."),
        ),
        "sections": (
            (
                "서비스 범위",
                (
                    "공개 종목 상세, AI 리포트, 사후 결과, 방법론 설명 페이지를 제공합니다.",
                    "회원에게는 매매 일지, 관심그룹, 분석 요청 대기열을 제공합니다.",
                    "브로커 주문, 자동매매, 실거래 위임 기능은 제공하지 않습니다.",
                ),
            ),
            (
                "사용자 책임",
                (
                    "투자 판단과 매매 실행 여부는 전적으로 사용자 본인의 책임입니다.",
                    "사용자는 입력한 기록의 정확성, 계정 보안, 비밀번호 관리에 책임을 집니다.",
                    "서비스를 비정상적으로 호출하거나 권한 없는 데이터 접근을 시도해서는 안 됩니다.",
                ),
            ),
            (
                "콘텐츠와 데이터",
                (
                    "AI 리포트와 공개 데이터는 정보 제공 목적이며 완전성, 적시성, 수익 가능성을 보장하지 않습니다.",
                    "KRX, DART, Naver 등 외부 데이터 제공처의 장애나 지연이 발생할 수 있습니다.",
                    "서비스는 데이터 출처, 기준일, 대체 경로 사용 여부를 가능한 범위에서 표시합니다.",
                ),
            ),
            (
                "서비스 변경",
                (
                    "운영자는 기능, 화면, 데이터 제공처, 공개 정책을 개선하거나 변경할 수 있습니다.",
                    "중요한 보안 또는 운영상 이유가 있으면 일부 기능을 제한할 수 있습니다.",
                    "약관 또는 정책이 변경되면 공개 페이지 또는 운영 고지를 통해 반영합니다.",
                ),
            ),
        ),
        "next_actions": (
            ("공개 분석 보기", "/analyses", "완료된 AI 리포트와 사후 결과 상태를 공개 화면에서 확인합니다."),
            ("가입 후 기록 공간 보기", "/features/member-workspace", "내 관심그룹과 매매 일지가 어떻게 분리되는지 봅니다."),
            ("투자 유의사항 읽기", "/disclaimer", "AI 리포트와 사후 결과를 읽을 때의 한계를 확인합니다."),
        ),
    },
    "disclaimer": {
        "path": "/disclaimer",
        "title": "투자 유의사항 | TradingAgents Korea",
        "description": "TradingAgents Korea의 AI 분석, 공개 데이터, 사후 결과를 읽을 때 필요한 투자 유의사항입니다.",
        "eyebrow": "안내 / 투자 유의사항",
        "heading": "AI 리포트는 투자 조언이 아니라 검토 자료입니다",
        "lead": "TradingAgents Korea의 화면, 리포트, 차트, 사후 결과는 한국 주식 투자 판단을 돕는 정보입니다. 특정 종목의 매수·매도·보유를 권유하지 않으며, 과거 기록 또는 AI 판단은 미래 수익을 보장하지 않습니다.",
        "summary": (("성격", "정보 제공"), ("한계", "오류·지연 가능"), ("성과", "미래 보장 아님")),
        "callouts": (
            ("투자 조언 아님", "리포트와 점수는 투자 자문, 일임, 중개, 주문 권유가 아닙니다."),
            ("데이터 위험", "가격, 공시, 뉴스, 재무 데이터는 지연·누락·정정될 수 있습니다."),
            ("사후 결과", "5일/20일 기록은 리포트 품질 추적용이며 미래 결과를 약속하지 않습니다."),
        ),
        "sections": (
            (
                "투자 조언 아님",
                (
                    "서비스의 모든 콘텐츠는 정보 제공 목적이며 개인별 투자 목적, 재산 상황, 위험 선호를 반영하지 않습니다.",
                    "AI 의견과 요약 표시는 사용자의 독립적인 검토를 돕는 참고 정보입니다.",
                    "실제 매매 전에는 공식 공시, 원자료, 전문가 의견, 본인의 투자 원칙을 함께 확인해야 합니다.",
                ),
            ),
            (
                "데이터 한계",
                (
                    "시장 휴장, 데이터 제공처 장애, API 쿼터, 데이터 정정, 종목명 변경, 상장폐지 등으로 표시 정보가 달라질 수 있습니다.",
                    "차트, 공시, 뉴스, 재무 데이터는 기준일과 출처를 함께 확인해야 합니다.",
                    "대체 데이터가 사용된 경우 정확도와 최신성이 원래 데이터 제공처와 다를 수 있습니다.",
                ),
            ),
            (
                "AI 모델 한계",
                (
                    "AI 리포트는 누락, 환각, 계산 오류, 문맥 오해, 최신 사건 미반영 가능성이 있습니다.",
                    "리포트의 문장과 결론은 원자료 검토를 대체하지 않습니다.",
                    "모델, 분석 지시, 데이터 제공처 변경에 따라 분석 품질과 표현이 달라질 수 있습니다.",
                ),
            ),
            (
                "사후 결과 해석",
                (
                    "5일/20일 기록과 시장 대비는 사후 측정값이며 거래 비용, 세금, 체결 가능성을 모두 반영하지 않을 수 있습니다.",
                    "과거 분석의 양호한 기록은 이후 분석 또는 동일 종목의 미래 흐름을 보장하지 않습니다.",
                    "사후 결과 통계는 AI 리포트 품질을 추적하기 위한 운영 지표로 읽어야 합니다.",
                ),
            ),
        ),
        "next_actions": (
            ("방법론 확인", "/features/methodology", "데이터 출처, 기준일, 주문 차단 원칙을 함께 확인합니다."),
            ("사후 결과 보기", "/outcomes", "과거 리포트 후 5일/20일 결과를 검토합니다."),
            ("공개 분석 보기", "/analyses", "실제 AI 리포트를 읽고 원문 데이터까지 확인합니다."),
        ),
    },
}


def policy_page_slugs() -> tuple[str, ...]:
    return tuple(POLICY_PAGES)


def policy_page_paths() -> tuple[str, ...]:
    return tuple(str(page["path"]) for page in POLICY_PAGES.values())


def render_feature_detail_page(slug: str, *, site_base_url: str | None = None) -> str:
    """Render a public feature detail page using the landing-page visual language."""

    page = FEATURE_DETAIL_PAGES.get(slug)
    if page is None:
        raise ValueError("Unknown feature page")

    title_class_attr = ' class="feature-title-compact"' if page.get("compact_typography") else ""
    journey_class = " feature-journey-compact" if page.get("compact_typography") else ""
    diagram_class = " feature-diagram-compact" if page.get("compact_typography") else ""
    proof_html = "".join(
        f"""<div><dt>{_h(label)}</dt><dd>{_h(value)}</dd></div>"""
        for label, value in page["proof"]
    )
    card_html = "".join(
        f"""<article><span>{index:02d}</span><strong>{_h(title)}</strong><p>{_h(copy)}</p></article>"""
        for index, (title, copy) in enumerate(page["cards"], start=1)
    )
    journey_html = "".join(
        f"""<article><span>{_h(number)}</span><strong>{_h(title)}</strong><p>{_h(copy)}</p></article>"""
        for number, title, copy in page.get("journey", ())
    )
    step_html = "".join(f"<span>{_h(step)}</span>" for step in page["steps"])
    canonical = canonical_url(str(page["path"]), site_base_url=site_base_url)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(page["title"])}</title>
  <meta name="description" content="{_h(page["description"])}">
  <link rel="canonical" href="{_h(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(page["title"])}">
  <meta property="og:description" content="{_h(page["description"])}">
  <meta property="og:url" content="{_h(canonical)}">
  <style>{PAGE_CSS}</style>
</head>
<body class="public-home feature-page feature-detail-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="정책 페이지")}
  </header>

  <main id="main-content" class="home-shell feature-shell">
    <section class="feature-hero" aria-labelledby="feature-title">
      <div class="feature-copy">
        <p class="home-kicker">{_h(page["eyebrow"])}</p>
        <h1 id="feature-title"{title_class_attr}>{_h(page["heading"])}</h1>
        <p>{_h(page["lead"])}</p>
        <dl class="home-proof-row feature-proof-row" aria-label="기능 기준">
          {proof_html}
        </dl>
        <div class="home-cta-row">
          <a class="home-primary-link" href="{_h(page["cta_href"])}">{_h(page["cta_label"])}</a>
          <a class="home-secondary-link" href="{_h(page.get("secondary_cta_href", "/features/member-workspace"))}">{_h(page.get("secondary_cta_label", "회원 기능 보기"))}</a>
        </div>
      </div>
      <div class="feature-diagram{diagram_class}" aria-label="기능 데이터 흐름">
        <div class="feature-diagram-top">
          <span>TA-KR</span>
          <span>주문 없음</span>
        </div>
        <div class="feature-step-track">
          {step_html}
        </div>
        <div class="feature-signal-card">
          <span>{_h(str(page.get("diagram_label") or page["eyebrow"]))}</span>
          <strong>{_h(page["heading"])}</strong>
          <small>{_h(page["description"])}</small>
        </div>
      </div>
    </section>

    <section class="feature-card-grid" aria-label="기능 세부 구성">
      {card_html}
    </section>

    <section class="feature-journey{journey_class}" aria-labelledby="feature-journey-title">
      <div class="feature-journey-heading">
        <p class="eyebrow">사용자 흐름</p>
        <h2 id="feature-journey-title">{_h(str(page.get("journey_heading", "처음 방문자도 바로 이어갈 수 있습니다")))}</h2>
        <p>{_h(str(page.get("journey_intro", "공개 리서치를 먼저 확인하고 필요한 기록만 내 공간에 저장합니다.")))}</p>
      </div>
      <div class="feature-journey-grid">
        {journey_html}
      </div>
    </section>

    <section class="home-ops-strip feature-boundary" aria-label="데이터 경계">
      <div>
        <p class="eyebrow">데이터 경계</p>
        <h2>필요한 데이터만 불러옵니다</h2>
      </div>
      <ul>
        <li>공개 상세 페이지는 안내 내용과 로그인 상태 표시만 사용합니다.</li>
        <li>회원 데이터는 로그인 상태를 확인한 뒤 내 공간에서만 불러옵니다.</li>
      </ul>
    </section>
  </main>

  <script>{PAGE_JS}</script>
</body>
</html>"""


def render_policy_page(slug: str, *, site_base_url: str | None = None) -> str:
    """Render a public policy page in the same visual system as the research site."""

    page = POLICY_PAGES.get(slug)
    if page is None:
        raise ValueError("Unknown policy page")

    summary_html = "".join(
        f"""<div><dt>{_h(label)}</dt><dd>{_h(value)}</dd></div>"""
        for label, value in page["summary"]
    )
    callout_html = "".join(
        f"""<article><span>{index:02d}</span><strong>{_h(title)}</strong><small>{_h(copy)}</small></article>"""
        for index, (title, copy) in enumerate(page["callouts"], start=1)
    )
    sections_html = "".join(
        f"""<article class="policy-card">
        <span>{index:02d}</span>
        <h2>{_h(title)}</h2>
        <ul>{"".join(f"<li>{_h(item)}</li>" for item in items)}</ul>
      </article>"""
        for index, (title, items) in enumerate(page["sections"], start=1)
    )
    next_actions_html = "".join(
        f"""<a href="{_h(href)}"><span>{index:02d}</span><strong>{_h(label)}</strong><small>{_h(copy)}</small></a>"""
        for index, (label, href, copy) in enumerate(page.get("next_actions", ()), start=1)
    )
    canonical = canonical_url(str(page["path"]), site_base_url=site_base_url)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(page["title"])}</title>
  <meta name="description" content="{_h(page["description"])}">
  <link rel="canonical" href="{_h(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(page["title"])}">
  <meta property="og:description" content="{_h(page["description"])}">
  <meta property="og:url" content="{_h(canonical)}">
  <style>{PAGE_CSS}</style>
</head>
<body class="public-home market-page policy-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="서비스 안내", current=str(page["path"]))}
  </header>

  <main id="main-content" class="home-shell policy-shell">
    <section class="policy-hero" aria-labelledby="policy-title">
      <div class="policy-copy">
        <p class="home-kicker">{_h(page["eyebrow"])}</p>
        <h1 id="policy-title">{_h(page["heading"])}</h1>
        <p>{_h(page["lead"])}</p>
        <dl class="home-proof-row feature-proof-row policy-proof-row" aria-label="정책 요약">
          {summary_html}
        </dl>
      </div>
      <aside class="policy-stamp" aria-label="정책 핵심 원칙">
        <div class="policy-stamp-top">
          <span>공개 정책</span>
          <span>주문 없음</span>
        </div>
        <strong>{_h(page["title"]).split("|")[0].strip()}</strong>
        <p>{_h(page["description"])}</p>
        <div class="policy-callout-grid">
          {callout_html}
        </div>
      </aside>
    </section>

    <section class="policy-card-grid" aria-label="정책 세부 내용">
      {sections_html}
    </section>

    <section class="policy-next-actions" aria-labelledby="policy-next-actions-title">
      <div>
        <p class="eyebrow">다음으로 확인할 화면</p>
        <h2 id="policy-next-actions-title">정책을 읽은 뒤 실제 서비스 흐름으로 이어갑니다</h2>
        <p>법적 안내에서 끝나지 않고, 공개 리서치와 내 공간이 어떻게 분리되는지 바로 확인할 수 있습니다.</p>
      </div>
      <div class="policy-next-action-grid">
        {next_actions_html}
      </div>
    </section>

    <section class="home-ops-strip policy-boundary" aria-label="서비스 정책 연결">
      <div>
        <p class="eyebrow">신뢰 경계</p>
        <h2>AI 리포트와 회원 기록의 경계를 분리합니다</h2>
      </div>
      <ul>
        <li><a href="/features/methodology">분석 기준</a>에서 데이터 출처와 AI 분석 한계를 함께 확인할 수 있습니다.</li>
        <li><a href="/disclaimer">투자 유의사항</a>, <a href="/terms">이용약관</a>, <a href="/privacy">개인정보처리방침</a>은 공개 페이지로 제공합니다.</li>
        <li>TradingAgents Korea는 실거래 주문 기능을 제공하지 않는 주문 없는 AI 리서치 플랫폼입니다.</li>
      </ul>
    </section>
  </main>

  <script>{PAGE_JS}</script>
</body>
</html>"""


def render_admin_console_page(*, site_base_url: str | None = None) -> str:
    """Render a noindex operator console that never embeds worker secrets."""

    canonical = canonical_url("/admin", site_base_url=site_base_url)
    analysis_worker_max = _positive_env_int("TRADINGAGENTS_WORKER_MAX_REQUESTS", 1)
    outcome_worker_max = _positive_env_int("TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS", 20)
    paper_worker_max = _positive_env_int("TRADINGAGENTS_PAPER_SIMULATION_WORKER_MAX_RUNS", 20)
    outcome_default = min(10, outcome_worker_max)
    paper_default = min(10, paper_worker_max)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>운영 콘솔 | TradingAgents Korea</title>
  <meta name="description" content="TradingAgents Korea 운영 대기열과 상태를 점검하는 운영 콘솔입니다.">
  <meta name="robots" content="noindex,nofollow">
  <link rel="canonical" href="{_h(canonical)}">
  <style>{PAGE_CSS}</style>
</head>
<body class="public-home admin-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="운영 메뉴", current="/admin")}
  </header>

  <main id="main-content" class="home-shell admin-shell">
    <section class="admin-hero" aria-labelledby="admin-title">
      <div>
        <p class="home-kicker">운영 콘솔 / 비밀값 저장 없음</p>
        <h1 id="admin-title">운영 작업을 확인하고 실행합니다</h1>
        <p>운영 토큰은 브라우저 세션에만 보관되고 운영 API 호출 헤더로만 전송됩니다.</p>
      </div>
      <form class="admin-token-panel" id="adminTokenForm">
        <label>
          <span>운영 토큰</span>
          <input id="adminWorkerToken" name="worker_token" type="password" autocomplete="off" placeholder="Vercel 운영 토큰 값">
        </label>
        <div class="admin-token-actions">
          <button type="submit">세션에 저장</button>
          <button type="button" data-admin-token-clear>토큰 지우기</button>
        </div>
        <small id="adminTokenState">Vercel 환경변수 TRADINGAGENTS_WORKER_TOKEN, DASHBOARD_ADMIN_TOKEN, OPERATOR_ACCESS_CODE 중 설정된 값을 입력하세요. 운영 버튼은 토큰 입력 후 활성화됩니다.</small>
      </form>
    </section>

    <section class="admin-health-strip" aria-label="운영 기준 요약">
      <article>
        <span>상태 점검</span>
        <strong>수동 확인</strong>
        <small>배포 trace, storage, KRX 응답을 같은 패널에서 확인합니다.</small>
      </article>
      <article>
        <span>작업자</span>
        <strong>운영 토큰 입력</strong>
        <small>HTML에는 secret을 싣지 않고 세션 스토리지에만 둡니다.</small>
      </article>
      <article>
        <span>대기열</span>
        <strong>실행 전 확인</strong>
        <small>저장 전에 어떤 항목이 처리될지 먼저 확인합니다.</small>
      </article>
      <article>
        <span>경계</span>
        <strong>주문 없음</strong>
        <small>운영 콘솔에도 실거래 주문 경로는 없습니다.</small>
      </article>
    </section>

    <section class="admin-workflow-strip" aria-label="권장 운영 순서">
      <article>
        <span>01</span>
        <strong>상태 점검</strong>
        <small>페이지 진입 시 자동 조회하고, 필요할 때 KRX와 외부 데이터 응답 점검을 추가합니다.</small>
      </article>
      <article>
        <span>02</span>
        <strong>실행 전 확인</strong>
        <small>저장 없이 이번 실행 후보와 제한값을 확인합니다.</small>
      </article>
      <article>
        <span>03</span>
        <strong>작업 실행</strong>
        <small>확인한 대상 중 제한된 건수만 실제로 저장합니다.</small>
      </article>
      <article>
        <span>04</span>
        <strong>감사 확인</strong>
        <small>결과 데이터와 상태 패널을 함께 보고 다음 운영 대기열을 결정합니다.</small>
      </article>
    </section>

    <section class="admin-ops-panel" aria-labelledby="admin-ops-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">운영 요약</p>
          <h2 id="admin-ops-title">대기열 현황과 최근 결과</h2>
          <p class="panel-copy">운영 대기열, 사후 결과, AI 가상매매 처리 상태를 요약합니다.</p>
        </div>
        <button type="button" data-admin-ops-summary>운영 요약 조회</button>
      </div>
      <div class="admin-ops-grid" id="adminOpsSummary" aria-live="polite">
        <div class="ops-cell is-waiting">
          <span>대기열</span>
          <strong>대기</strong>
          <small>운영 토큰 저장 후 운영 요약을 조회하세요.</small>
        </div>
      </div>
      <div class="admin-recent-grid" id="adminRecentPanel" aria-label="최근 운영 항목"></div>
      <pre id="adminOpsOutput">대기 중</pre>
    </section>

    <section class="admin-grid" aria-label="운영 작업">
      <article class="admin-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">상태 점검</p>
            <h2>서비스 상태</h2>
          </div>
          <div class="admin-check-row">
            <label class="admin-inline-check"><input id="adminProbeKrx" type="checkbox"> KRX 응답 점검</label>
            <label class="admin-inline-check"><input id="adminProbeVendors" type="checkbox"> 외부 데이터 응답 점검</label>
          </div>
        </div>
        <button type="button" data-admin-readiness>상태 확인</button>
        <div class="admin-readiness-panel" id="adminReadinessPanel" aria-live="polite">
          <div class="readiness-cell is-waiting">
            <span>Status</span>
            <strong>대기</strong>
            <small>상태 점검을 실행하면 배포와 외부 데이터 상태를 요약합니다.</small>
          </div>
        </div>
        <pre id="adminReadinessOutput">대기 중</pre>
      </article>

      <article class="admin-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">분석 요청 대기열</p>
            <h2>AI 리포트 생성</h2>
          </div>
          <span class="status-pill">운영 권한</span>
        </div>
        <div class="admin-action-controls">
          <label class="admin-number-field" for="adminRequestLimit">
            <span>이번 실행 건수</span>
            <input id="adminRequestLimit" type="number" min="1" max="{analysis_worker_max}" value="{analysis_worker_max}">
          </label>
          <div class="button-row">
            <button type="button" data-admin-action="requests-dry-run">실행 전 확인</button>
            <button type="button" data-admin-action="requests-process">리포트 생성</button>
          </div>
          <small class="admin-limit-hint" id="adminRequestLimitHint">현재 최대 {analysis_worker_max}건</small>
        </div>
        <small class="admin-action-help">실행 전 확인은 저장 없이 이번 후보만 보여줍니다. 리포트 생성은 요청 상태를 처리 중으로 바꾸고 AI 리포트를 저장합니다.</small>
        <div class="admin-action-panel" id="adminRequestsPanel" aria-live="polite">
          <div class="action-cell is-waiting">
            <span>분석 리포트</span>
            <strong>대기</strong>
            <small>회원이 요청한 종목을 AI 리포트로 생성합니다.</small>
          </div>
        </div>
        <pre id="adminRequestsOutput">대기 중</pre>
      </article>

      <article class="admin-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">사후 결과 작업</p>
            <h2>5일/20일 사후 결과</h2>
          </div>
          <span class="status-pill">5일 / 20일</span>
        </div>
        <div class="admin-action-controls">
          <label class="admin-number-field" for="adminOutcomeLimit">
            <span>이번 실행 건수</span>
            <input id="adminOutcomeLimit" type="number" min="1" max="{outcome_worker_max}" value="{outcome_default}">
          </label>
          <div class="button-row">
            <button type="button" data-admin-action="outcomes-dry-run">실행 전 확인</button>
            <button type="button" data-admin-action="outcomes-process">사후 결과 계산</button>
          </div>
          <small class="admin-limit-hint" id="adminOutcomeLimitHint">현재 최대 {outcome_worker_max}건</small>
        </div>
        <small class="admin-action-help">실행 전 확인은 저장 없이 후보 리포트만 보여줍니다. 사후 결과 계산은 5일/20일 수익률과 시장 대비를 저장합니다.</small>
        <div class="admin-action-panel" id="adminOutcomesPanel" aria-live="polite">
          <div class="action-cell is-waiting">
            <span>사후 결과</span>
            <strong>대기</strong>
            <small>완료 리포트의 5일/20일 이후 성과를 저장합니다.</small>
          </div>
        </div>
        <pre id="adminOutcomesOutput">대기 중</pre>
      </article>

      <article class="admin-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">AI 가상매매</p>
            <h2>가상매매 기록 생성</h2>
          </div>
          <span class="status-pill">주문 없음</span>
        </div>
        <div class="admin-action-controls">
          <label class="admin-number-field" for="adminPaperSimulationLimit">
            <span>이번 실행 건수</span>
            <input id="adminPaperSimulationLimit" type="number" min="1" max="{paper_worker_max}" value="{paper_default}">
          </label>
          <div class="button-row">
            <button type="button" data-admin-action="paper-dry-run">실행 전 확인</button>
            <button type="button" data-admin-action="paper-process">가상매매 기록 생성</button>
          </div>
          <small class="admin-limit-hint" id="adminPaperSimulationLimitHint">현재 최대 {paper_worker_max}건</small>
        </div>
        <small class="admin-action-help">실행 전 확인은 저장 없이 후보 리포트와 보유 중인 가상 포지션만 보여줍니다. 기록 생성은 실제 주문 없이 가상 매수·매도 기록만 저장합니다.</small>
        <div class="admin-action-panel" id="adminPaperSimulationPanel" aria-live="polite">
          <div class="action-cell is-waiting">
            <span>AI 가상매매</span>
            <strong>대기</strong>
            <small>완료 리포트 기준의 가상 매수·매도 근거를 저장합니다. 실제 주문은 없습니다.</small>
          </div>
        </div>
        <pre id="adminPaperSimulationOutput">대기 중</pre>
      </article>
    </section>
  </main>

  <script>{PAGE_JS}</script>
  <script>{ADMIN_PAGE_JS}</script>
</body>
</html>"""


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def render_member_dashboard_page(*, site_base_url: str | None = None, canonical_path: str = "/member") -> str:
    """Render the authenticated member dashboard shell."""

    model = {
        "title": "회원 대시보드 | TradingAgents Korea",
        "description": "매매 일지, 관심그룹, 한국 주식 분석 요청, AI 가상매매 기록을 관리합니다.",
        "canonical_url": canonical_url(canonical_path, site_base_url=site_base_url),
    }
    config_json = _script_json(_public_supabase_config())

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(model["title"])}</title>
  <meta name="description" content="{_h(model["description"])}">
  <meta name="robots" content="noindex,nofollow">
  <link rel="canonical" href="{_h(model["canonical_url"])}">
  <style>{PAGE_CSS}</style>
</head>
<body class="member-page is-member-checking">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="내 공간 메뉴", current="/mypage")}
  </header>

  <main id="main-content" class="shell member-shell">
    <section class="member-session-gate" id="memberSessionGate" aria-live="polite" aria-label="회원 세션 확인">
      <p class="eyebrow">세션 확인</p>
      <h1 id="memberSessionTitle">세션을 확인하고 있습니다</h1>
      <p id="memberSessionMessage">로그인 상태가 남아 있으면 바로 내 공간으로 이동하고, 없으면 로그인/가입 화면을 엽니다.</p>
      <div class="member-session-meter" aria-hidden="true"><span></span></div>
    </section>

    <section class="member-auth-landing" id="memberAuthLanding" aria-labelledby="member-auth-title">
      <div class="member-auth-copy">
        <p class="eyebrow">회원 전용 공간</p>
        <h1 id="member-auth-title">나만의 AI 리서치 공간을 시작하세요</h1>
        <p class="member-auth-lead">매매 일지, 관심그룹, AI 분석 요청, 가상매매 복기 요약을 내 공간에서 함께 관리합니다.</p>
        <div class="member-auth-points" aria-label="회원 영역 원칙">
          <article>
            <span>01</span>
            <strong>주문 없음 원칙</strong>
            <small>실거래 주문 기능은 차단하고 기록과 조회 흐름만 제공합니다.</small>
          </article>
          <article>
            <span>02</span>
            <strong>공식 출처 기준</strong>
            <small>KRX, DART, 공개 뉴스 흐름을 분리해 분석 근거를 남깁니다.</small>
          </article>
          <article>
            <span>03</span>
            <strong>내 공간</strong>
            <small>로그인한 사용자에게만 저장 기록과 분석 요청 상태를 보여줍니다.</small>
          </article>
        </div>
      </div>

      <section class="member-panel auth-panel" aria-labelledby="auth-panel-title">
        <div class="panel-heading auth-heading">
          <div>
            <p class="eyebrow">보안 로그인</p>
            <h2 id="auth-panel-title">로그인 / 가입</h2>
          </div>
          <span class="status-pill">조회 전용</span>
        </div>
        <form class="member-form auth-form" id="authForm">
          <label>
            <span>이메일</span>
            <input name="email" type="email" autocomplete="email" required>
          </label>
          <label>
            <span>비밀번호</span>
            <span class="password-row">
              <input name="password" type="password" autocomplete="current-password" required>
              <button class="ghost-button password-toggle" id="passwordToggle" type="button" aria-pressed="false" aria-label="비밀번호 표시">비밀번호 표시</button>
            </span>
          </label>
          <div class="button-row auth-button-row" aria-label="인증 작업">
            <button type="button" data-auth-action="signin">로그인</button>
            <button type="button" data-auth-action="signup">가입하기</button>
          </div>
          <p class="auth-form-note">처음이라면 가입하기로 내 공간을 열 수 있습니다.</p>
          <div class="member-empty auth-status" id="authStatus" role="status" aria-live="polite">내 공간 진입을 위해 인증이 필요합니다.</div>
        </form>
      </section>
    </section>

    <section class="member-workspace" id="memberWorkspace" hidden>
      <section class="summary-band member-summary-band" aria-labelledby="member-title">
        <div>
          <p class="eyebrow">회원 공간</p>
          <h1 id="member-title">내 공간</h1>
          <p class="asof" id="memberStatus">로그인 상태 확인 중</p>
          <p class="member-workspace-lede">홈에서 오늘 할 일을 보고, 필요한 기록과 요청을 이어갑니다.</p>
        </div>
        <div class="member-signed-in" id="memberSignedIn" hidden>
          <span class="status-pill" id="memberSignedInState">대시보드 확인 중</span>
          <strong id="memberSignedInUser">회원 세션</strong>
          <small id="memberSignedInMeta">대시보드를 불러오고 있습니다.</small>
          <button class="ghost-button" id="signOutButton" type="button">로그아웃</button>
        </div>
        <div class="decision-box">
          <span class="decision-label">거래 기능</span>
          <strong>OFF</strong>
          <span>조회/기록 전용</span>
        </div>
      </section>

      <nav class="member-tab-strip" role="tablist" aria-label="내 공간 섹션">
        <a id="home-tab" class="is-active" href="#member-home-section" role="tab" data-member-tab="home" aria-controls="member-home-section" aria-selected="true">홈 <span id="memberHomeStatus">준비됨</span></a>
        <a id="portfolio-tab" href="#portfolio-section" role="tab" data-member-tab="portfolio" aria-controls="portfolio-section" aria-selected="false">매매 일지 <span id="portfolioTabCount">0</span></a>
        <a id="watchlist-tab" href="#watchlist-section" role="tab" data-member-tab="watchlist" aria-controls="watchlist-section" aria-selected="false">관심그룹 <span id="watchlistTabCount">0</span></a>
        <a id="analysis-tab" href="#analysis-request-section" role="tab" data-member-tab="analysis" aria-controls="analysis-request-section" aria-selected="false">분석 요청 <span id="analysisTabCount">0</span></a>
        <a id="paper-simulation-tab" href="#paper-simulation-section" role="tab" data-member-tab="paper" aria-controls="paper-simulation-section" aria-selected="false">AI 가상매매 <span id="paperSimulationTabCount">0</span></a>
      </nav>

      <section class="member-grid" aria-label="회원 기능">
        <section class="member-panel member-home-panel" id="member-home-section" role="tabpanel" data-member-panel="home" aria-labelledby="home-tab">
          <div class="panel-heading">
            <div>
              <p class="eyebrow">내 공간</p>
              <h2>홈</h2>
              <p class="panel-copy">오늘 이어갈 항목입니다.</p>
            </div>
            <span class="status-pill">조회/기록 전용</span>
          </div>
          <section class="member-overview-strip" id="memberOverview" aria-label="내 공간 요약">
            <article>
              <span>매매 일지</span>
              <strong id="memberOverviewPortfolios">0</strong>
              <small>일지</small>
            </article>
            <article>
              <span>관심그룹</span>
              <strong id="memberOverviewWatchlists">0</strong>
              <small>종목 목록</small>
            </article>
            <article>
              <span>대기 중 요청</span>
              <strong id="memberOverviewActiveRequests">0</strong>
              <small>대기/처리 중</small>
            </article>
            <article>
              <span>리포트</span>
              <strong id="memberOverviewCompletedReports">0</strong>
              <small>완료 리포트</small>
            </article>
            <article>
              <span>AI 가상매매</span>
              <strong id="memberOverviewPaperSimulations">0</strong>
              <small>가상매매 기록</small>
            </article>
          </section>
          <p class="member-home-state-note" id="memberHomeStateNote" aria-live="polite">저장된 항목을 불러오고 있습니다.</p>
          <section class="member-primary-action" id="memberPrimaryAction" data-member-primary-action="portfolio" aria-live="polite">
            <div>
              <span>다음 작업</span>
              <strong id="memberPrimaryActionTitle">첫 매매 일지를 만들어 보세요</strong>
              <small id="memberPrimaryActionCopy">실제 계좌 주문과 연결되지 않는 조회 전용 기록 공간입니다. 평단, 목표가, 손절선을 직접 남겨 투자 시나리오를 점검하세요.</small>
            </div>
            <button class="home-primary-link" type="button" id="memberPrimaryActionButton" data-member-jump="portfolio">매매 일지 시작</button>
          </section>
          <div class="member-home-grid" aria-label="다음 작업">
            <article class="member-home-card">
              <span>01</span>
              <strong>매매 일지</strong>
              <small>평단, 수수료, 목표가를 직접 남깁니다.</small>
              <button class="ghost-button" type="button" data-member-jump="portfolio">일지 쓰기</button>
            </article>
            <article class="member-home-card">
              <span>02</span>
              <strong>관심그룹</strong>
              <small>자주 보는 종목을 그룹으로 묶습니다.</small>
              <button class="ghost-button" type="button" data-member-jump="watchlist">그룹 만들기</button>
            </article>
            <article class="member-home-card">
              <span>03</span>
              <strong>분석 요청</strong>
              <small>요청 가능 횟수와 진행 상태를 확인합니다.</small>
              <button class="ghost-button" type="button" data-member-jump="analysis">요청하기</button>
            </article>
            <article class="member-home-card member-paper-card">
              <span>04</span>
              <strong>AI 가상매매</strong>
              <small>AI의 가상 매수·매도 기록을 봅니다.</small>
              <button class="ghost-button" type="button" data-member-jump="paper">가상매매 보기</button>
            </article>
          </div>
          <div class="member-home-links" aria-label="보조 이동">
            <a class="member-report-link" href="/analyses">AI 리포트 보기</a>
            <a class="member-report-link" href="/outcomes">사후 결과 보기</a>
            <a class="member-admin-link" href="/admin">운영 콘솔</a>
          </div>
        </section>

        <section class="member-panel" id="portfolio-section" role="tabpanel" data-member-panel="portfolio" aria-labelledby="portfolio-tab" hidden>
          <div class="panel-heading">
            <div>
              <p class="eyebrow">매매 일지</p>
              <h2>매매 일지</h2>
              <p class="panel-copy">종목, 단가, 수량, 목표가를 직접 기록합니다.</p>
            </div>
            <button class="ghost-button" id="refreshMemberData" type="button">새로고침</button>
          </div>
          <div class="member-form-stack">
            <div class="member-form-block">
              <strong>새 매매 일지</strong>
              <small class="member-form-hint">먼저 일지 이름을 만듭니다.</small>
              <form class="member-form compact-form" id="portfolioForm">
                <input name="name" maxlength="80" placeholder="예: 장기 관심주" aria-label="매매 일지 이름" required>
                <button type="submit">추가</button>
              </form>
            </div>
            <div class="member-form-block">
              <strong>매수/매도 기록</strong>
              <small class="member-form-hint">종목명이나 6자리 코드, 날짜, 단가, 수량을 입력하면 평균단가와 손익을 계산합니다.</small>
              <form class="member-form trade-form" id="tradeForm">
                <select name="portfolio_id" aria-label="매매 일지 선택" required></select>
                <input name="ticker_code" list="memberTickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" aria-label="종목코드 또는 종목명" autocomplete="off" data-member-ticker-lookup required>
                <select name="side" aria-label="매수 또는 매도" required>
                  <option value="buy">매수</option>
                  <option value="sell">매도</option>
                </select>
                <input name="trade_date" type="date" aria-label="거래일" required>
                <input name="price" type="number" min="1" step="1" placeholder="단가" aria-label="거래 단가" inputmode="numeric" required>
                <input name="quantity" type="number" min="1" step="1" placeholder="수량" aria-label="거래 수량" inputmode="numeric" required>
                <input name="fee" type="number" min="0" step="1" placeholder="수수료" aria-label="수수료" inputmode="numeric">
                <input name="tax" type="number" min="0" step="1" placeholder="세금" aria-label="세금" inputmode="numeric">
                <button type="submit">기록</button>
              </form>
            </div>
            <div class="member-form-block">
              <strong>목표/손절 메모</strong>
              <small class="member-form-hint">목표가와 손절가는 주문으로 연결되지 않는 개인 메모입니다.</small>
              <form class="member-form target-form" id="targetForm">
                <select name="portfolio_id" aria-label="매매 일지 선택" required></select>
                <input name="ticker_code" list="memberTickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" aria-label="종목코드 또는 종목명" autocomplete="off" data-member-ticker-lookup required>
                <input name="target_price" type="number" min="1" step="1" placeholder="목표가" aria-label="목표가" inputmode="numeric">
                <input name="stop_price" type="number" min="1" step="1" placeholder="손절가" aria-label="손절가" inputmode="numeric">
                <input name="memo" maxlength="500" placeholder="목표 메모" aria-label="목표 메모">
                <button type="submit">저장</button>
              </form>
            </div>
          </div>
          <div class="member-list" id="portfolioList"></div>
        </section>

        <section class="member-panel" id="watchlist-section" role="tabpanel" data-member-panel="watchlist" aria-labelledby="watchlist-tab" hidden>
          <div class="panel-heading">
            <div>
              <p class="eyebrow">관심그룹</p>
              <h2>관심그룹</h2>
            </div>
            <span class="status-pill">KR</span>
          </div>
          <div class="member-form-stack">
            <div class="member-form-block">
              <strong>새 관심그룹</strong>
              <small class="member-form-hint">예: 반도체, 2차전지처럼 자주 보는 종목을 묶습니다.</small>
              <form class="member-form compact-form" id="watchlistForm">
                <input name="name" maxlength="80" placeholder="예: 반도체 관심그룹" aria-label="관심그룹 이름" required>
                <button type="submit">그룹 만들기</button>
              </form>
            </div>
            <div class="member-form-block">
              <strong>종목 담기</strong>
              <small class="member-form-hint">종목명이나 6자리 코드와 메모를 남기면 목록에서 현재가 상태를 함께 확인합니다.</small>
              <form class="member-form compact-form" id="watchlistItemForm">
                <select name="watchlist_id" aria-label="관심그룹 선택" required></select>
                <input name="ticker_code" list="memberTickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" aria-label="종목코드 또는 종목명" autocomplete="off" data-member-ticker-lookup required>
                <input name="memo" maxlength="500" placeholder="메모" aria-label="관심그룹 종목 메모">
                <button type="submit">종목 담기</button>
              </form>
            </div>
          </div>
          <div class="member-list" id="watchlistList"></div>
        </section>

        <section class="member-panel" id="analysis-request-section" role="tabpanel" data-member-panel="analysis" aria-labelledby="analysis-tab" hidden>
          <div class="panel-heading">
            <div>
              <p class="eyebrow">분석 요청</p>
              <h2>새 분석 요청</h2>
              <p class="panel-copy">요청 상태, 가능 횟수, 완료 리포트를 확인합니다.</p>
            </div>
            <span class="status-pill">요청 대기열</span>
          </div>
          <p class="member-form-hint member-request-hint">종목명이나 6자리 코드만 입력하면 최근 기준일로 요청합니다. 특정 날짜로 보고 싶을 때만 날짜를 선택하세요.</p>
          <form class="member-form analysis-request-form" id="analysisRequestForm">
            <select name="watchlist_ticker" id="analysisWatchlistTickerSelect" aria-label="관심그룹 종목 선택"></select>
            <input name="ticker" list="memberTickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" aria-label="분석 요청 종목코드 또는 종목명" autocomplete="off" data-member-ticker-lookup required>
            <input name="requested_trade_date" type="date" aria-label="분석 기준일">
            <input name="reason" maxlength="500" placeholder="궁금한 점 메모" aria-label="요청 메모">
            <button type="submit">요청</button>
          </form>
          <div class="member-list" id="analysisRequestList"></div>
        </section>

        <section class="member-panel" id="paper-simulation-section" role="tabpanel" data-member-panel="paper" aria-labelledby="paper-simulation-tab" hidden>
          <div class="panel-heading">
            <div>
              <p class="eyebrow">AI 가상매매</p>
              <h2>가상매매 기록</h2>
              <p class="panel-copy">완료된 AI 리포트 기준으로 가상 매수·매도 기록을 보여줍니다.</p>
            </div>
            <span class="status-pill">주문 없음</span>
          </div>
          <ol class="paper-simulation-flow" aria-label="AI 가상매매 흐름">
            <li><span>01</span><strong>리포트</strong><small>AI 의견 저장</small></li>
            <li><span>02</span><strong>매수</strong><small>가상 매수 기록</small></li>
            <li><span>03</span><strong>평가</strong><small>보유·청산 추적</small></li>
            <li><span>04</span><strong>복기</strong><small>승률과 손익 확인</small></li>
          </ol>
          <div class="member-list" id="paperSimulationList"></div>
        </section>
      </section>
    </section>
  </main>

  <datalist id="memberTickerSuggestions"></datalist>
  <script id="member-config" type="application/json">{config_json}</script>
  <script>{MEMBER_PAGE_JS}</script>
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
    rating = (
        _decision_rating_label(decision.get("rating"))
        if decision.get("rating")
        else _analysis_status_label(analysis.get("status"))
    )
    action = _decision_action_label(decision.get("action"), fallback="조회 전용")

    return {
        "title": f"{name} ({code}) | TradingAgents Korea",
        "description": f"{name} {code} 한국 주식 AI 리서치, KRW 차트, AI 리포트, 사후 결과.",
        "name": name,
        "code": code,
        "market_line": f"{market} / {benchmark}",
        "canonical_url": stock_canonical_url(code, site_base_url=site_base_url),
        "generated_at": _short_datetime(payload.get("generated_at")),
        "rating": str(rating),
        "action": str(action),
        "close": _money(close),
        "change": _change(change_value, change_rate),
        "change_class": _change_class(change_value),
        "volume": _number(latest.get("volume")),
        "analysis_state": _analysis_status_label(analysis.get("status")),
        "analysis_title": _analysis_title(analysis, decision),
        "rationale": _analysis_rationale(decision),
        "run_id": str((analysis.get("run") or {}).get("id") or ""),
        "reports": reports[:6],
        "refresh_state": "업데이트 권장" if refresh.get("recommended") else "분석 최신",
        "chart_status": _chart_status_label(chart.get("status")),
        "chart_vendor": _chart_vendor_value(chart.get("vendor")),
        "chart_vendor_label": _chart_vendor_label(chart.get("vendor")),
        "chart_interval": _chart_interval_value(chart.get("interval")),
        "chart_interval_label": _chart_interval_label(chart.get("interval")),
        "chart_start_date": str(chart.get("start_date") or ""),
        "chart_end_date": str(chart.get("end_date") or ""),
        "chart_range_days": _chart_range_days(chart.get("start_date"), chart.get("end_date")),
        "chart_point_count": len(points),
        "chart_source_rows": _chart_source_rows(chart, points),
        "chart_caption": _chart_caption(chart, points),
        "chart_fallback": _chart_fallback_message(chart),
        "analysis_source_rows": _analysis_source_rows(analysis, refresh),
        "analysis_confidence": _analysis_confidence_model(analysis=analysis, refresh=refresh, chart=chart, points=points),
    }


def _chart_controls(model: dict[str, Any]) -> str:
    code = str(model.get("code") or "")
    end = _date_or_today(model.get("chart_end_date"))
    active_days = model.get("chart_range_days")
    active_interval = _chart_interval_value(model.get("chart_interval"))
    active_vendor = str(model.get("chart_vendor") or "")
    period_options = _chart_period_options(active_interval)
    range_links = []
    for key, label, days in period_options:
        start = end - timedelta(days=days)
        params = {
            "chart_start": start.isoformat(),
            "chart_end": end.isoformat(),
            "chart_interval": active_interval,
        }
        if active_vendor and active_vendor != "unknown":
            params["chart_vendor"] = "yfinance" if _chart_interval_is_intraday(active_interval) else active_vendor
        href = _stock_query_href(
            code,
            params,
        )
        active = _period_is_active(active_days, days)
        current_attr = ' aria-current="page"' if active else ""
        range_links.append(
            f'<a class="chart-tab{" is-active" if active else ""}" href="{_h(href)}"'
            f'{current_attr}>{_h(label)}</a>'
        )

    interval_tabs = []
    for value, label, days in _chart_interval_options():
        start = end - timedelta(days=days)
        params = {
            "chart_start": start.isoformat(),
            "chart_end": end.isoformat(),
            "chart_interval": value,
        }
        if _chart_interval_is_intraday(value):
            params["chart_vendor"] = "yfinance"
        elif active_vendor and active_vendor != "yfinance":
            params["chart_vendor"] = active_vendor
        href = _stock_query_href(code, params)
        active = active_interval == value
        current_attr = ' aria-current="page"' if active else ""
        title_attr = ' title="60분봉"' if value == "60m" else ""
        interval_tabs.append(
            f'<a class="chart-tab{" is-active" if active else ""}" href="{_h(href)}"{title_attr}'
            f'{current_attr}>{_h(label)}</a>'
        )

    vendor = model.get("chart_vendor")
    if _chart_interval_is_intraday(active_interval):
        yfinance_href = _stock_query_href(code, {"chart_interval": active_interval, "chart_vendor": "yfinance"})
        vendor_links = [
            f'<a class="chart-tab is-active" aria-current="page" href="{_h(yfinance_href)}">Yahoo 시간·분봉</a>'
        ]
    else:
        vendor_params = {"chart_interval": active_interval}
        pykrx_href = _stock_query_href(code, {**vendor_params, "chart_vendor": "pykrx"})
        krx_href = _stock_query_href(code, {**vendor_params, "chart_vendor": "krx"})
        vendor_links = [
            f'<a class="chart-tab{" is-active" if vendor == "pykrx" else ""}" href="{_h(pykrx_href)}">pykrx</a>',
            f'<a class="chart-tab{" is-active" if vendor == "krx" else ""}" href="{_h(krx_href)}">KRX 14일</a>',
        ]

    return (
        '<div class="chart-toolbar" aria-label="차트 설정">'
        '<div class="chart-control-block"><span>기간</span>'
        '<nav class="chart-tabs" aria-label="차트 기간">'
        + "".join(range_links)
        + "</nav></div>"
        '<div class="chart-control-block"><span>봉</span>'
        '<nav class="chart-tabs chart-interval-tabs" aria-label="차트 주기">'
        + "".join(interval_tabs)
        + "</nav></div>"
        '<div class="chart-control-block"><span>데이터</span>'
        '<nav class="chart-tabs chart-vendor-tabs" aria-label="차트 데이터 소스">'
        + "".join(vendor_links)
        + "</nav></div>"
        "</div>"
    )


def _chart_tools() -> str:
    indicators = [
        ("ma5", "MA5", True),
        ("ma20", "MA20", True),
        ("ma60", "MA60", False),
        ("ma120", "MA120", False),
        ("bollinger", "볼린저", False),
        ("volume", "거래량", True),
    ]
    buttons = "".join(
        f'<button type="button" class="chart-tool-button{" is-active" if active else ""}" '
        f'data-chart-indicator="{_h(key)}" aria-pressed="{"true" if active else "false"}">{_h(label)}</button>'
        for key, label, active in indicators
    )
    return f"""
    <div class="chart-tools" aria-label="차트 도구">
      <div class="chart-tool-group">
        <span>지표</span>
        {buttons}
      </div>
      <div class="chart-tool-group chart-settings-group">
        <span>설정</span>
        <label class="chart-setting-field"><span>단기 MA</span><input type="number" min="2" max="60" step="1" value="5" data-chart-setting="maFast"></label>
        <label class="chart-setting-field"><span>기준 MA</span><input type="number" min="5" max="120" step="1" value="20" data-chart-setting="maBase"></label>
        <label class="chart-setting-field"><span>볼린저</span><input type="number" min="5" max="80" step="1" value="20" data-chart-setting="bollingerPeriod"></label>
        <label class="chart-setting-field"><span>편차</span><input type="number" min="1" max="4" step="0.5" value="2" data-chart-setting="bollingerDeviation"></label>
        <button type="button" class="chart-tool-button" data-chart-apply-settings>적용</button>
      </div>
      <div class="chart-tool-group">
        <span>그리기</span>
        <button type="button" class="chart-tool-button" data-chart-draw-trend aria-pressed="false">추세선</button>
        <button type="button" class="chart-tool-button" data-chart-clear-trends>선 지우기</button>
      </div>
      <div class="chart-tool-group">
        <span>보기</span>
        <button type="button" class="chart-tool-button" data-chart-fit>전체 보기</button>
      </div>
      <small id="chartToolState">지표와 추세선은 차트 위에서 조정합니다.</small>
    </div>
    """


def _stock_signal_card(model: dict[str, Any]) -> str:
    confidence = model.get("analysis_confidence") or {}
    return f"""
    <div class="stock-signal-card">
      <span>현재가 요약</span>
      <strong>{_h(model.get("close") or "-")}</strong>
      <small>{_h(model.get("change") or "-")} · {_h(model.get("chart_vendor_label") or "데이터 확인")} 기준</small>
      <dl>
        <div>
          <dt>AI 상태</dt>
          <dd>{_h(model.get("analysis_state") or "-")}</dd>
        </div>
        <div>
          <dt>근거</dt>
          <dd>{_h(confidence.get("label") or "확인 필요")}</dd>
        </div>
      </dl>
    </div>
    """


def _stock_report_actions(model: dict[str, Any]) -> str:
    code = str(model.get("code") or "")
    run_id = str(model.get("run_id") or "")
    detail_href = f"/analyses/{run_id}" if run_id else (f"/analyses?ticker={code}" if code else "/analyses")
    api_href = f"/api/analyses/{run_id}" if run_id else (f"/api/stocks/{code}" if code else "/api/analyses")
    list_href = f"/analyses?ticker={code}" if code else "/analyses"
    request_href = "/member?mode=signup&tab=analysis#analysis-request-section"
    primary_label = "전체 리포트 읽기" if run_id else "이 종목 리포트"
    secondary_href = list_href if run_id else request_href
    secondary_label = "같은 종목 리포트" if run_id else "분석 요청"
    return f"""
    <div class="analysis-feed-actions stock-report-actions" aria-label="리포트 다음 이동">
      <a href="{_h(detail_href)}">{_h(primary_label)}</a>
      <a href="{_h(secondary_href)}">{_h(secondary_label)}</a>
      <a href="{_h(api_href)}">원문 데이터</a>
    </div>
    """


def _stock_query_href(code: str, params: dict[str, str]) -> str:
    query = urlencode({key: value for key, value in params.items() if value})
    return f"/stocks/{code}?{query}" if query else f"/stocks/{code}"


def _data_source_strip(rows: list[tuple[str, str]], *, label: str) -> str:
    if not rows:
        return ""
    items = "".join(
        f"""
        <div>
          <dt>{_h(key)}</dt>
          <dd>{_h(value)}</dd>
        </div>
        """
        for key, value in rows
    )
    return f"""
    <dl class="data-source-strip" aria-label="{_h(label)}">
      {items}
    </dl>
    """


def _chart_source_rows(chart: dict[str, Any], points: list[dict[str, Any]]) -> list[tuple[str, str]]:
    point_count = chart.get("point_count")
    if point_count is None:
        point_count = len(points)
    requested = chart.get("requested_vendor") or chart.get("vendor") or "-"
    resolved = chart.get("resolved_vendor") or chart.get("vendor") or "-"
    start = str(chart.get("start_date") or "-")
    end = str(chart.get("end_date") or "-")
    range_label = f"{start}~{end}" if start != "-" or end != "-" else "-"
    source_note = f"자동 전환: {resolved}" if chart.get("fallback_used") else f"{resolved} 사용"
    return [
        ("데이터", str(chart.get("data_source_label") or _chart_vendor_label(chart.get("vendor")))),
        ("기간", range_label),
        ("봉", f"{_chart_interval_label(chart.get('interval'))} · {point_count}개"),
        ("표시", source_note if requested == "auto" else f"{requested} → {resolved}"),
    ]


def _analysis_source_rows(analysis: dict[str, Any], refresh: dict[str, Any]) -> list[tuple[str, str]]:
    run = analysis.get("run") or {}
    provider = run.get("model_provider") or "AI"
    run_id = str(run.get("id") or "")
    source = f"공개 분석 {run_id[:8]}" if run_id else _analysis_status_label(analysis.get("status"))
    return [
        ("출처", source),
        ("기준일", str(run.get("trade_date") or "-")),
        ("신선도", _analysis_refresh_label(refresh)),
        ("모델", str(provider)),
    ]


def _analysis_refresh_label(refresh: dict[str, Any]) -> str:
    reason = str(refresh.get("reason") or "-")
    age = refresh.get("age_days")
    age_label = f" / {age}일 경과" if age is not None else ""
    if reason in {"storage_not_configured", "analysis_skipped"}:
        prefix = "확인 대기"
    else:
        prefix = "업데이트 권장" if refresh.get("recommended") else "최신"
    return f"{prefix} ({_analysis_refresh_reason_label(reason)}{age_label})"


def _analysis_refresh_reason_label(reason: str) -> str:
    return {
        "-": "확인 정보 없음",
        "fresh": "최근 리포트",
        "analysis_skipped": "분석 생략",
        "storage_not_configured": "저장소 확인 대기",
        "no_completed_public_analysis": "완료된 공개 리포트 없음",
    }.get(str(reason or "-"), str(reason or "확인 정보 없음"))


def _analysis_confidence_model(
    *,
    analysis: dict[str, Any],
    refresh: dict[str, Any],
    chart: dict[str, Any],
    points: list[dict[str, Any]],
) -> dict[str, Any]:
    status = str(analysis.get("status") or "unknown")
    reports = analysis.get("reports") or []
    outcomes = analysis.get("outcomes") or []
    decision = analysis.get("decision")
    warnings = _analysis_missing_data_warnings(
        status=status,
        refresh=refresh,
        report_count=len(reports),
        has_decision=bool(decision),
        outcome_count=len(outcomes),
        chart=chart,
        point_count=len(points),
    )
    score = 0
    if status == "available":
        score += 2
    if not refresh.get("recommended") and status == "available":
        score += 1
    if reports:
        score += 1
    if decision:
        score += 1
    if outcomes:
        score += 1
    if chart.get("status") == "available" and points:
        score += 1

    if status != "available" or score <= 2:
        level = "low"
        label = "데이터 부족"
    elif score <= 4:
        level = "medium"
        label = "근거 보통"
    else:
        level = "high"
        label = "근거 충분"

    return {
        "level": level,
        "label": label,
        "score": score,
        "summary": _analysis_confidence_summary(status=status, score=score, warnings=warnings),
        "warnings": warnings,
    }


def _analysis_missing_data_warnings(
    *,
    status: str,
    refresh: dict[str, Any],
    report_count: int,
    has_decision: bool,
    outcome_count: int,
    chart: dict[str, Any],
    point_count: int,
) -> list[str]:
    warnings: list[str] = []
    if status == "missing":
        warnings.append("공개 분석이 아직 저장되지 않았습니다.")
    elif status == "not_configured":
        warnings.append("저장된 AI 리포트를 아직 확인할 수 없습니다.")
    elif status == "unavailable":
        warnings.append("공개 분석 응답을 확인하지 못했습니다.")
    elif status != "available":
        warnings.append("공개 분석 상태를 확인해야 합니다.")

    if refresh.get("recommended"):
        reason = refresh.get("reason") or "refresh_recommended"
        warnings.append(f"분석 업데이트 권장: {_analysis_refresh_reason_label(str(reason))}")
    if status == "available" and report_count == 0:
        warnings.append("AI 리포트가 저장되지 않았습니다.")
    if status == "available" and not has_decision:
        warnings.append("AI 의견 레코드가 저장되지 않았습니다.")
    if status == "available" and outcome_count == 0:
        warnings.append("5일/20일 사후 결과가 아직 없습니다.")
    if chart.get("status") != "available":
        warnings.append(_chart_fallback_message(chart))
    elif point_count == 0:
        warnings.append("차트 거래일 데이터가 비어 있습니다.")
    return warnings


def _analysis_confidence_summary(*, status: str, score: int, warnings: list[str]) -> str:
    if status != "available":
        return "아직 공개 분석이 없어 일부 근거만 표시합니다."
    if warnings:
        return "일부 근거가 비어 있습니다. 기준일과 원문을 확인하세요."
    return f"분석, 판단, 차트가 함께 저장되어 있습니다. 근거 점수 {score}/7."


def _analysis_confidence_panel(confidence: dict[str, Any]) -> str:
    warnings = confidence.get("warnings") or []
    warning_items = "".join(f"<li>{_h(warning)}</li>" for warning in warnings)
    warning_html = f"<ul>{warning_items}</ul>" if warning_items else "<p>표시된 근거에서 큰 누락은 보이지 않습니다.</p>"
    level = str(confidence.get("level") or "low")
    return f"""
    <div class="analysis-confidence-panel confidence-{_h(level)}" aria-label="분석 근거 상태">
      <span>근거 상태</span>
      <strong>{_h(confidence.get("label") or "확인 필요")}</strong>
      <p>{_h(confidence.get("summary") or "")}</p>
      {warning_html}
    </div>
    """


def _period_is_active(active_days: Any, option_days: int) -> bool:
    if active_days is None:
        return option_days == 180
    try:
        days = int(active_days)
    except (TypeError, ValueError):
        return False
    if option_days == 1:
        return days <= 2
    if option_days == 7:
        return 2 < days <= 10
    if option_days == 30:
        return 10 < days <= 45
    if option_days == 90:
        return 45 < days <= 120
    return days > 120


def _date_or_today(value: Any) -> date:
    parsed = _parse_date(value)
    if parsed is not None:
        return parsed
    return datetime.now().date()


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _chart_range_days(start: Any, end: Any) -> int | None:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date is None or end_date is None or end_date < start_date:
        return None
    return (end_date - start_date).days


def _chart_vendor_value(value: Any) -> str:
    selected = str(value or "unknown").strip().lower().replace("_", "-")
    if selected in {"krx-openapi", "krx-open-api"}:
        return "krx"
    return selected


def _chart_vendor_label(value: Any) -> str:
    selected = _chart_vendor_value(value)
    if selected == "krx":
        return "KRX Open API"
    if selected == "pykrx":
        return "pykrx"
    if selected == "yfinance":
        return "Yahoo Finance"
    if selected == "auto":
        return "auto"
    return "데이터 제공처 확인"


def _chart_interval_value(value: Any) -> str:
    selected = str(value or "1d").strip().lower().replace("_", "-")
    aliases = {
        "daily": "1d",
        "day": "1d",
        "1day": "1d",
        "weekly": "1wk",
        "week": "1wk",
        "1w": "1wk",
        "monthly": "1mo",
        "month": "1mo",
        "1month": "1mo",
        "1h": "60m",
        "hourly": "60m",
        "hour": "60m",
        "60min": "60m",
        "30min": "30m",
        "15min": "15m",
        "5min": "5m",
        "1min": "1m",
    }
    selected = aliases.get(selected, selected)
    return selected if selected in {"1d", "1wk", "1mo", "60m", "30m", "15m", "5m", "1m"} else "1d"


def _chart_interval_label(value: Any) -> str:
    return {
        "1d": "일봉",
        "1wk": "주봉",
        "1mo": "월봉",
        "60m": "1시간봉",
        "30m": "30분봉",
        "15m": "15분봉",
        "5m": "5분봉",
        "1m": "1분봉",
    }.get(_chart_interval_value(value), "일봉")


def _chart_interval_is_intraday(value: Any) -> bool:
    return _chart_interval_value(value) in {"60m", "30m", "15m", "5m", "1m"}


def _chart_interval_options() -> list[tuple[str, str, int]]:
    return [
        ("1d", "일봉", 180),
        ("1wk", "주봉", 365),
        ("1mo", "월봉", 730),
        ("60m", "1시간봉", 30),
        ("30m", "30분봉", 5),
        ("15m", "15분봉", 5),
        ("5m", "5분봉", 1),
        ("1m", "1분봉", 1),
    ]


def _chart_period_options(interval: Any) -> list[tuple[str, str, int]]:
    value = _chart_interval_value(interval)
    if value == "1m":
        return [("1D", "1일", 1)]
    if value == "5m":
        return [("1D", "1일", 1), ("1W", "1주", 7)]
    if value in {"15m", "30m"}:
        return [("1D", "1일", 1), ("1W", "1주", 7), ("1M", "1개월", 30)]
    if value == "60m":
        return [("1D", "1일", 1), ("1W", "1주", 7), ("1M", "1개월", 30), ("3M", "3개월", 90)]
    return [
        ("1D", "1일", 1),
        ("1W", "1주", 7),
        ("1M", "1개월", 30),
        ("3M", "3개월", 90),
        ("6M", "6개월", 180),
    ]


def _chart_caption(chart: dict[str, Any], points: list[dict[str, Any]]) -> str:
    start = chart.get("start_date") or "-"
    end = chart.get("end_date") or "-"
    vendor = _chart_vendor_label(chart.get("vendor"))
    interval = _chart_interval_label(chart.get("interval"))
    point_label = f"{len(points):,}개 봉" if points else "차트 데이터 없음"
    resolved = chart.get("resolved_vendor") or chart.get("vendor") or "데이터 제공처"
    fallback_note = f" · 자동 전환: {resolved}" if chart.get("fallback_used") else ""
    return f"{interval} · {vendor} · {point_label} · {start}~{end}{fallback_note}"


def _chart_fallback_message(chart: dict[str, Any]) -> str:
    if chart.get("status") == "unavailable":
        error = chart.get("error")
        if error:
            return f"차트 데이터를 불러오지 못했습니다: {error}"
        return "차트 데이터 공급원이 현재 응답하지 않습니다."
    if chart.get("status") == "skipped":
        return "차트 표시가 비활성화되었습니다."
    return "차트 데이터가 부족합니다."


def _analysis_feed_payload(
    repo: StorageRepository | None,
    *,
    ticker: str | None,
    limit: int,
    max_limit: int,
) -> dict[str, Any]:
    if repo is None:
        return {
            "status": "not_configured",
            "ticker_code": ticker,
            "limit": limit,
            "items": [],
            "item_count": 0,
            "summary": {
                "completed_count": 0,
                "unique_ticker_count": 0,
                "latest_trade_date": None,
                "market_counts": {},
                "model_provider_counts": {},
            },
        }
    return build_public_analysis_feed_payload(repo, ticker=ticker, limit=limit, max_limit=max_limit)


def _analysis_outcomes_payload(
    repo: StorageRepository | None,
    *,
    ticker: str | None,
    status: str | None,
    limit: int,
    max_limit: int,
) -> dict[str, Any]:
    if repo is None:
        return {
            "status": "not_configured",
            "ticker_code": ticker,
            "filter_status": status,
            "limit": limit,
            "items": [],
            "item_count": 0,
            "summary": {
                "completed_count": 0,
                "pending_count": 0,
                "unavailable_count": 0,
                "positive_alpha_count": 0,
                "positive_alpha_rate": None,
                "average_alpha_return": None,
                "average_raw_return": None,
            },
        }
    return build_public_analysis_outcomes_payload(repo, ticker=ticker, status=status, limit=limit, max_limit=max_limit)


def _analysis_feed_view_model(payload: dict[str, Any], *, site_base_url: str | None = None) -> dict[str, Any]:
    ticker_code = payload.get("ticker_code")
    items = payload.get("items") or []
    limit = int(payload.get("limit") or len(items) or 20)
    basis_label = f"{ticker_code} 필터 결과" if ticker_code else f"최근 {limit}건 기준"
    title = "AI 리포트 | TradingAgents Korea"
    description = "TradingAgents Korea의 한국 주식 AI 리포트입니다."
    summary = payload.get("summary") or {}
    return {
        "title": title,
        "description": description,
        "canonical_url": canonical_url("/analyses", site_base_url=site_base_url),
        "subtitle": "공개 AI 리포트와 5일·20일 사후 결과를 함께 봅니다.",
        "status": f"{_analysis_feed_status_label(payload.get('status'))} · 실시간 데이터 트랙킹",
        "ticker_code": ticker_code,
        "filter_label": f"{ticker_code} 필터" if ticker_code else "전체 종목",
        "item_count": str(len(items)),
        "basis_label": basis_label,
        "summary": summary,
        "items": items,
    }


def _analysis_filter_state(model: dict[str, Any]) -> str:
    ticker = str(model.get("ticker_code") or "").strip()
    count = str(model.get("item_count") or "0")
    basis_label = str(model.get("basis_label") or "최근 AI 리포트")
    if ticker:
        return f"""
        <div class="analysis-filter-state" aria-label="현재 분석 필터 상태">
          <span>{_h(ticker)} 필터 적용</span>
          <span>결과 {_h(count)}건</span>
          <a href="/stocks/{_h(ticker)}">종목 페이지</a>
          <a href="/outcomes?ticker={_h(ticker)}">사후 결과</a>
        </div>
        """
    return f"""
    <div class="analysis-filter-state" aria-label="현재 분석 필터 상태">
      <span>전체 AI 리포트</span>
      <span>{_h(basis_label)}</span>
      <a href="/outcomes">사후 결과</a>
    </div>
    """


def _analysis_feed_toolbar(model: dict[str, Any]) -> str:
    count = str(model.get("item_count") or "0")
    basis_label = str(model.get("basis_label") or "최근 AI 리포트")
    filter_label = str(model.get("filter_label") or "전체 종목")
    has_filter = bool(str(model.get("ticker_code") or "").strip())
    count_label = f"결과 {_h(count)}건" if has_filter or count != "0" else "아카이브 대기"
    return f"""
    <div class="analysis-feed-toolbar" aria-label="리포트 목록 상태">
      <span>{count_label}</span>
      <span>정렬: 최신 기준일순</span>
      <span>{_h(filter_label)}</span>
      <small>{_h(basis_label)} 목록입니다. 상세, 종목, 사후 결과로 이동합니다.</small>
    </div>
    """


def _outcome_filter_state(model: dict[str, Any]) -> str:
    ticker = str(model.get("ticker_code") or "").strip()
    status = str(model.get("filter_status") or "").strip()
    count = str(model.get("item_count") or "0건")
    filter_label = str(model.get("filter_label") or "전체 사후 결과")
    query: dict[str, str] = {"limit": "20"}
    if ticker:
        query["ticker"] = ticker
    if status:
        query["status"] = status
    api_path = f"/api/analysis-outcomes?{urlencode(query)}"
    if ticker or status:
        stock_link = f'<a href="/stocks/{_h(ticker)}">종목 페이지</a>' if ticker else ""
        analyses_href = f"/analyses?ticker={_h(ticker)}" if ticker else "/analyses"
        return f"""
        <div class="analysis-filter-state outcome-filter-state" aria-label="현재 사후 결과 필터 상태">
          <span>{_h(filter_label)} 적용</span>
          <span>결과 {_h(count)}</span>
          {stock_link}
          <a href="{analyses_href}">AI 리포트</a>
          <a href="{_h(api_path)}">원문 데이터</a>
        </div>
        """
    return f"""
    <div class="analysis-filter-state outcome-filter-state" aria-label="현재 사후 결과 필터 상태">
      <span>전체 사후 결과</span>
      <span>5일 / 20일</span>
      <a href="/analyses">AI 리포트</a>
      <a href="{_h(api_path)}">원문 데이터</a>
    </div>
    """


def _outcome_feed_toolbar(model: dict[str, Any]) -> str:
    count = str(model.get("item_count") or "0건")
    filter_label = str(model.get("filter_label") or "전체 사후 결과")
    has_filter = bool(str(model.get("ticker_code") or "").strip() or str(model.get("filter_status") or "").strip())
    count_label = f"결과 {_h(count)}" if has_filter or count != "0건" else "검증 대기열"
    return f"""
    <div class="analysis-feed-toolbar outcome-feed-toolbar" aria-label="사후 결과 목록 상태">
      <span>{count_label}</span>
      <span>정렬: 최신 기준일순</span>
      <span>{_h(filter_label)}</span>
      <small>원 리포트와 종목 화면으로 바로 이동합니다.</small>
    </div>
    """


def _analysis_outcomes_view_model(payload: dict[str, Any], *, site_base_url: str | None = None) -> dict[str, Any]:
    ticker_code = payload.get("ticker_code")
    filter_status = payload.get("filter_status")
    items = payload.get("items") or []
    filters = []
    if ticker_code:
        filters.append(str(ticker_code))
    if filter_status:
        filters.append(_outcome_status_label(str(filter_status)))
    filter_label = " / ".join(filters) if filters else "전체 사후 결과"
    return {
        "title": "사후 결과 | TradingAgents Korea",
        "description": "TradingAgents Korea 공개 리서치의 5일/20일 이후 결과와 시장 대비 차이를 확인합니다.",
        "canonical_url": canonical_url("/outcomes", site_base_url=site_base_url),
        "subtitle": "AI 리포트 발행 이후 5일 및 20일간의 절대 수익률 추이를 추적하고, 동기간 시장(KOSPI/KOSDAQ) 대비 초과 수익률(Alpha)을 정밀 검증합니다.",
        "status_label": _analysis_outcomes_status_label(payload.get("status")),
        "ticker_code": ticker_code,
        "filter_status": filter_status,
        "filter_label": filter_label,
        "item_count": f"{len(items)}건",
        "summary": payload.get("summary") or {},
        "items": items,
    }


def _analysis_detail_view_model(
    payload: dict[str, Any],
    *,
    analysis_run_id: str,
    site_base_url: str | None = None,
) -> dict[str, Any]:
    run = payload.get("run") or {}
    decision = payload.get("decision") or {}
    reports = payload.get("reports") or []
    outcomes = payload.get("outcomes") or []
    summary = payload.get("summary") or {}
    run_id = str(run.get("id") or analysis_run_id)
    ticker_code = str(run.get("ticker_code") or "")
    ticker_name = str(run.get("ticker_name") or ticker_code or "공개 분석")
    market = str(run.get("market") or "KR")
    trade_date = str(run.get("trade_date") or "-")
    provider = str(run.get("model_provider") or "AI")
    deep_model = str(run.get("deep_model") or "")
    quick_model = str(run.get("quick_model") or "")
    metadata = run.get("metadata_json") if isinstance(run.get("metadata_json"), dict) else {}
    source_label = str(metadata.get("source") or "저장된 분석")
    currency_label = str(metadata.get("currency") or "KRW")
    language_label = str(metadata.get("output_language") or "ko-KR")
    analyst_label = _metadata_list_label(metadata.get("selected_analysts"), fallback="저장된 분석 역할 없음")
    created_label = _compact_timestamp(run.get("created_at"))
    completed_label = _compact_timestamp(run.get("completed_at"))
    rating_raw = summary.get("decision_rating") or decision.get("rating")
    action_raw = summary.get("decision_action") or decision.get("action")
    rating = _decision_rating_label(rating_raw)
    action = _decision_action_label(action_raw)
    model_bits = [provider]
    if deep_model:
        model_bits.append(f"상세 모델 {deep_model}")
    if quick_model:
        model_bits.append(f"빠른 모델 {quick_model}")
    heading = f"{ticker_name} 공개 분석 리포트"
    description = (
        f"{trade_date} 기준 {ticker_name}({ticker_code}) 공개 AI 분석입니다. "
        f"AI 의견 {rating}, 리포트 {len(reports)}개, 사후 결과 {summary.get('completed_outcome_count', 0)}건을 제공합니다."
    )
    return {
        "title": f"{ticker_name} {ticker_code} 공개 분석 리포트 | TradingAgents Korea",
        "description": description,
        "canonical_url": canonical_url(f"/analyses/{run_id}", site_base_url=site_base_url),
        "heading": heading,
        "subtitle": f"{trade_date} 기준 / {market} / 분석 {run_id[:8]}",
        "run": run,
        "run_id": run_id,
        "ticker_code": ticker_code,
        "ticker_name": ticker_name,
        "market": market,
        "trade_date": trade_date,
        "decision": decision,
        "decision_label": _decision_pair_label(rating_raw, action_raw),
        "data_basis": f"{trade_date} 기준, 공개 분석",
        "reports": reports,
        "outcomes": outcomes,
        "summary": summary,
        "model_label": " / ".join(model_bits),
        "source_label": source_label,
        "currency_label": currency_label,
        "language_label": language_label,
        "analyst_label": analyst_label,
        "timestamp_label": _timestamp_pair_label(created_label, completed_label),
        "metadata_note": f"생성 경로 {source_label} / 통화 {currency_label} / 언어 {language_label}",
        "report_count_label": f"{len(reports)}개 리포트",
        "completed_outcome_label": f"{summary.get('completed_outcome_count', 0)}개 완료",
        "average_alpha_label": _percent(summary.get("average_alpha_return"), signed=True),
    }


def _metadata_list_label(value: Any, *, fallback: str) -> str:
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(items) if items else fallback
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _compact_timestamp(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value)
    if "T" in text:
        date_part, _, time_part = text.partition("T")
    elif " " in text:
        date_part, _, time_part = text.partition(" ")
    else:
        return text
    return f"{date_part} {time_part[:5]}" if time_part else date_part


def _timestamp_pair_label(created: str, completed: str) -> str:
    if created == "-" and completed == "-":
        return "저장 시각 없음"
    if completed == "-":
        return f"생성 {created}"
    if created == "-":
        return f"완료 {completed}"
    return f"생성 {created} / 완료 {completed}"


def _home_view_model(payload: dict[str, Any], *, site_base_url: str | None = None) -> dict[str, Any]:
    return {
        "title": "TradingAgents Korea | 한국 주식 AI 분석",
        "description": "한국 주식 종목코드와 종목명으로 AI 분석, KRW 차트, AI 리포트를 탐색합니다.",
        "canonical_url": canonical_url("/", site_base_url=site_base_url),
        "recent_items": payload.get("items") or [],
    }


def _quick_ticker_cards() -> str:
    quick = [
        ("005930", "삼성전자", "KOSPI"),
        ("000660", "SK하이닉스", "KOSPI"),
        ("035420", "NAVER", "KOSPI"),
        ("035720", "카카오", "KOSPI"),
        ("051910", "LG화학", "KOSPI"),
        ("086520", "에코프로", "KOSDAQ"),
    ]
    cards = []
    for code, name, market in quick:
        cards.append(
            f"""
            <article class="analysis-feed-card quick-ticker-card">
              <div class="quick-card-head">
                <span>{_h(market)}</span>
                <a class="quick-card-action" href="/stocks/{_h(code)}">차트 관제 <span aria-hidden="true">↗</span></a>
              </div>
              <h3><a href="/stocks/{_h(code)}">{_h(name)} <small>{_h(code)}</small></a></h3>
              <p>가격 흐름과 공개 분석 상태를 바로 확인합니다.</p>
            </article>
            """
        )
    return "\n".join(cards)


def _analysis_summary_cards(summary: dict[str, Any], *, basis_label: str = "현재 목록 기준") -> str:
    latest = summary.get("latest_trade_date") or "-"
    markets = summary.get("market_counts") if isinstance(summary.get("market_counts"), dict) else {}
    providers = summary.get("model_provider_counts") if isinstance(summary.get("model_provider_counts"), dict) else {}
    ratings = summary.get("decision_rating_counts") if isinstance(summary.get("decision_rating_counts"), dict) else {}
    top_market = _top_count_label(markets) or "-"
    top_provider = _top_count_label(providers) or "-"
    top_rating = _top_count_label(ratings, formatter=_decision_rating_label) or "-"
    cards = [
        ("완료 리포트", summary.get("completed_count", 0), basis_label),
        ("커버 종목", summary.get("unique_ticker_count", 0), "중복 제외"),
        ("최신 기준일", latest, f"평균 시장 대비 {_percent(summary.get('average_alpha_return'), signed=True)}"),
        ("주요 AI 의견/시장", top_rating, top_market),
    ]
    html_cards = []
    for label, value, note in cards:
        html_cards.append(
            f"""
            <article>
              <span>{_h(label)}</span>
              <strong>{_h(value)}</strong>
              <small>{_h(note)}</small>
            </article>
            """
        )
    return f"""
    <section class="analysis-summary-grid" aria-label="공개 분석 커버리지 요약">
      {"".join(html_cards)}
    </section>
    """


def _analysis_track_record_cards(summary: dict[str, Any], *, basis_label: str = "현재 공개 목록 기준") -> str:
    completed_outcomes = int(summary.get("completed_outcome_count") or 0)
    outcome_covered = int(summary.get("outcome_covered_count") or 0)
    coverage = _percent(summary.get("outcome_coverage_rate"))
    positive_rate = _percent(summary.get("positive_alpha_rate"))
    average_alpha = _percent(summary.get("average_alpha_return"), signed=True)
    positive_count = int(summary.get("positive_alpha_count") or 0)
    cards = [
        ("사후 결과 완료", f"{completed_outcomes}건", f"결과 연결 리포트 {outcome_covered}개"),
        ("평균 시장 대비", average_alpha, "종목 수익률 - 시장 기준"),
        ("시장 우위 기록", positive_rate, f"양수 기록 {positive_count}건"),
        ("커버리지", coverage, basis_label),
    ]
    if completed_outcomes == 0:
        cards = [
            ("사후 결과 대기", "0건", "결과가 완료되면 채워집니다."),
            ("평균 시장 대비", "-", "결과 데이터 대기"),
            ("시장 우위 기록", "-", "결과 데이터 대기"),
            ("커버리지", "-", basis_label),
        ]
    html_cards = []
    for label, value, note in cards:
        html_cards.append(
            f"""
            <article>
              <span>{_h(label)}</span>
              <strong>{_h(value)}</strong>
              <small>{_h(note)}</small>
            </article>
            """
        )
    return f"""
    <section class="analysis-track-record" aria-labelledby="track-record-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">사후 결과</p>
          <h2 id="track-record-title">사후 결과</h2>
        </div>
        <span class="status-pill">5일 / 20일</span>
      </div>
      <div class="analysis-track-grid">
        {"".join(html_cards)}
      </div>
    </section>
    """


def _analysis_outcome_summary_cards(summary: dict[str, Any]) -> str:
    completed = int(summary.get("completed_count") or 0)
    pending = int(summary.get("pending_count") or 0)
    unavailable = int(summary.get("unavailable_count") or 0)
    positive_alpha = int(summary.get("positive_alpha_count") or 0)
    average_alpha = _percent(summary.get("average_alpha_return"), signed=True)
    average_raw = _percent(summary.get("average_raw_return"), signed=True)
    positive_rate = _percent(summary.get("positive_alpha_rate"))
    cards = [
        ("사후 결과 완료", f"{completed}건", "사후 결과 완료"),
        ("평균 시장 대비", average_alpha, f"종목 평균 {average_raw}"),
        ("시장 우위 기록", positive_rate, f"양수 차이 {positive_alpha}건"),
        ("대기/확인 필요", f"{pending}/{unavailable}", "대기 / 데이터 없음"),
    ]
    html_cards = []
    for label, value, note in cards:
        html_cards.append(
            f"""
            <article>
              <span>{_h(label)}</span>
              <strong>{_h(value)}</strong>
              <small>{_h(note)}</small>
            </article>
            """
        )
    return f"""
    <section class="analysis-summary-grid outcome-summary-grid" aria-label="사후 결과 요약">
      {"".join(html_cards)}
    </section>
    """


def _analysis_outcome_cadence_strip(model: dict[str, Any]) -> str:
    filter_label = model.get("filter_label") or "전체 사후 결과"
    return f"""
    <section class="analysis-pipeline-strip outcome-cadence-strip" aria-label="사후 결과 흐름">
      <article>
        <span>01</span>
        <strong>기준일</strong>
        <small>리포트 거래일</small>
      </article>
      <article>
        <span>02</span>
        <strong>기간</strong>
        <small>5일 또는 20일</small>
      </article>
      <article>
        <span>03</span>
        <strong>차이</strong>
        <small>종목 - 시장 기준</small>
      </article>
      <article>
        <span>04</span>
        <strong>원 리포트</strong>
        <small>{_h(str(filter_label))}에서 바로 이동</small>
      </article>
    </section>
    """


def _analysis_outcome_feed_cards(
    items: list[dict[str, Any]],
    *,
    ticker_code: str | None = None,
    filter_status: str | None = None,
    filter_label: str = "전체 사후 결과",
) -> str:
    if not items:
        if ticker_code or filter_status:
            ticker = str(ticker_code or "").strip()
            status_label = _outcome_status_label(str(filter_status or "")) if filter_status else "전체 상태"
            title_bits = [bit for bit in (ticker, status_label if filter_status else None) if bit]
            title = f"{' '.join(title_bits)} 기록 없음" if title_bits else "조건에 맞는 기록 없음"
            analyses_href = f"/analyses?ticker={_h(ticker)}" if ticker else "/analyses"
            stock_action = f'<a href="/stocks/{_h(ticker)}">종목 페이지</a>' if ticker else ""
            return f"""
            <article class="analysis-feed-card outcome-feed-card empty">
              <span>필터 결과 없음</span>
              <h3>{_h(title)}</h3>
              <p>조건에 맞는 결과가 아직 없습니다. 기간이 부족하거나 가격 데이터가 비어 있을 수 있습니다.</p>
              <div class="analysis-feed-signal-row" aria-label="사후 결과 필터 결과 없음">
                <span>{_h(str(filter_label))}</span>
                <span>결과 0건</span>
                <span>조건 변경 가능</span>
              </div>
              <div class="analysis-feed-actions">
                <a href="/outcomes">필터 초기화</a>
                <a href="{analyses_href}">AI 리포트</a>
                {stock_action}
                <a href="/member?mode=signup&tab=analysis#analysis-request-section">분석 요청</a>
              </div>
            </article>
            """
        return """
        <article class="analysis-feed-card outcome-feed-card empty">
          <span>TRACKING QUEUE</span>
          <h3>현재 평가 대기열에 등록된 사후 성과 검증 데이터가 존재하지 않습니다.</h3>
          <p>TradingAgents 시스템이 평일 크론탭(Cron) 스케줄러를 통해 KRX 종가 데이터 및 리포트 진입 시점 대비 사후 성과를 실시간 계산 중입니다. 백테스팅 엔진의 구동 모습을 즉시 확인하시려면 아래 샘플 분석실을 확인해 보세요.</p>
          <div class="analysis-feed-signal-row" aria-label="사후 결과 대기 상태">
            <span>성과 검증 대기열</span>
            <span>KRX 종가 추적</span>
            <span>Alpha 계산 준비</span>
          </div>
          <div class="analysis-feed-actions outcome-empty-cta-row">
            <a href="/stocks/005930#analysis-outcomes">💡 삼성전자 사후 성과 검증실 바로가기</a>
            <a href="/analyses">AI 리포트</a>
            <a href="/features/outcomes">기준</a>
            <a href="/member?mode=signup&tab=analysis#analysis-request-section">분석 요청</a>
          </div>
        </article>
        """

    cards = []
    for item in items:
        code = str(item.get("ticker_code") or "")
        name = str(item.get("ticker_name") or code or "공개 분석")
        market = str(item.get("market") or "KR")
        status = str(item.get("status") or "pending")
        status_label = _outcome_status_label(status)
        run_id = str(item.get("analysis_run_id") or "")
        horizon = item.get("horizon_days") or "-"
        trade_date = item.get("trade_date") or "-"
        evaluated_at = item.get("evaluated_at") or "-"
        actual_days = item.get("actual_holding_days")
        actual_days_label = f"{actual_days}일" if actual_days is not None else "-"
        raw_return = _percent(item.get("raw_return"), signed=True)
        benchmark_return = _percent(item.get("benchmark_return"), signed=True)
        alpha_return = _percent(item.get("alpha_return"), signed=True)
        decision = _decision_pair_label(item.get("decision_rating"), item.get("decision_action"))
        report_path = f"/analyses/{run_id}" if run_id else "/analyses"
        stock_path = f"/stocks/{code}" if code else "/analyses"
        analyses_path = f"/analyses?ticker={code}" if code else "/analyses"
        query = {"limit": "20"}
        if code:
            query["ticker"] = code
        if status:
            query["status"] = status
        api_path = f"/api/analysis-outcomes?{urlencode(query)}"
        alpha_class = _analysis_outcome_alpha_class(item.get("alpha_return"))
        cards.append(
            f"""
            <article class="analysis-feed-card outcome-feed-card {alpha_class} outcome-{_h(status)}">
              <div class="analysis-feed-card-top">
                <span>{_h(market)} / 기준일 {_h(str(trade_date))}</span>
                <small>{_h(str(horizon))}D / 평가일 {_h(str(evaluated_at))}</small>
              </div>
              <h3><a href="{_h(report_path)}">{_h(name)} <small>{_h(code)}</small></a></h3>
              <small class="analysis-feed-meta-line">상태 {_h(status_label)} / 보유 {_h(actual_days_label)} / AI {_h(str(decision))}</small>
              <p>{_h(str(horizon))}일 결과를 시장 기준과 비교했습니다.</p>
              <div class="analysis-feed-signal-row" aria-label="시장 대비 계산 기준">
                <span>차이 {_h(alpha_return)}</span>
                <span>종목 {_h(raw_return)}</span>
                <span>시장 {_h(benchmark_return)}</span>
                <span>{_h(status_label)}</span>
              </div>
              <dl class="analysis-feed-metrics">
                <div><dt>종목</dt><dd>{_h(raw_return)}</dd></div>
                <div><dt>시장 기준</dt><dd>{_h(benchmark_return)}</dd></div>
                <div><dt>시장 대비</dt><dd>{_h(alpha_return)}</dd></div>
                <div><dt>관측일</dt><dd>{_h(actual_days_label)}</dd></div>
                <div><dt>데이터 기준일</dt><dd>{_h(str(trade_date))}</dd></div>
                <div><dt>분석 ID</dt><dd>{_h(run_id[:8] or "-")}</dd></div>
              </dl>
              <div class="analysis-feed-actions">
                <a href="{_h(report_path)}">리포트 상세</a>
                <a href="{_h(stock_path)}">종목 보기</a>
                <a href="{_h(analyses_path)}">같은 종목 리포트</a>
                <a class="subtle-action" href="{_h(api_path)}">원문 데이터</a>
              </div>
            </article>
            """
        )
    return "\n".join(cards)


def _analysis_outcome_alpha_class(value: Any) -> str:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        number = None
    if number is None:
        return "is-neutral-alpha"
    if number > 0:
        return "is-positive-alpha"
    if number < 0:
        return "is-negative-alpha"
    return "is-neutral-alpha"


def _outcome_status_options(selected: Any) -> str:
    selected_value = str(selected or "")
    options = [
        ("", "전체"),
        ("completed", "완료"),
        ("pending", "대기"),
        ("unavailable", "데이터 없음"),
    ]
    html_options = []
    for value, label in options:
        selected_attr = " selected" if value == selected_value else ""
        html_options.append(f'<option value="{_h(value)}"{selected_attr}>{_h(label)}</option>')
    return "".join(html_options)


def _analysis_feed_cards(
    items: list[dict[str, Any]],
    *,
    ticker_code: str | None = None,
    filter_label: str = "전체 종목",
) -> str:
    if not items:
        if ticker_code:
            ticker = str(ticker_code)
            return f"""
            <article class="analysis-feed-card empty">
              <span>아직 공개 기록 없음</span>
              <h3>{_h(ticker)} 공개 분석 없음</h3>
              <p>조건에 맞는 AI 리포트가 아직 없습니다. 종목 페이지를 먼저 확인하거나 내 공간에서 분석을 요청하세요.</p>
              <div class="analysis-feed-signal-row" aria-label="필터 결과 없음">
                <span>{_h(str(filter_label))}</span>
                <span>리포트 0개</span>
                <span>사후 결과 대기</span>
              </div>
              <div class="analysis-feed-actions">
                <a href="/analyses">필터 초기화</a>
                <a href="/stocks/{_h(ticker)}">종목 페이지</a>
                <a href="/member?mode=signup&tab=analysis#analysis-request-section">분석 요청</a>
              </div>
            </article>
            """
        return """
        <article class="analysis-feed-card empty">
          <span>REPORT ARCHIVE</span>
          <h3>발행된 공개 AI 분석 리포트가 존재하지 않습니다.</h3>
          <p>TradingAgents AI 엔진이 한국 시장 분석을 준비하고 있습니다. 데이터 흐름을 먼저 보려면 아래 샘플 종목 리서치실로 이동하거나, 내 공간에서 새 종목 분석을 요청해 보세요.</p>
          <div class="analysis-feed-signal-row" aria-label="공개 분석 대기 상태">
            <span>리포트 아카이브</span>
            <span>AI 엔진 대기열</span>
            <span>사후 결과 연결</span>
          </div>
          <div class="analysis-feed-actions analysis-empty-cta-row">
            <a href="/stocks/005930">💡 샘플 종목 리서치실 바로가기</a>
            <a href="/features/methodology">분석 기준</a>
            <a href="/member?mode=signup&tab=analysis#analysis-request-section">분석 요청</a>
          </div>
        </article>
        """

    cards = []
    for item in items:
        code = item.get("ticker_code") or ""
        name = item.get("ticker_name") or code
        market = item.get("market") or "KR"
        trade_date = item.get("trade_date") or "-"
        model_provider = item.get("model_provider") or "AI"
        decision = _decision_pair_label(item.get("decision_rating"), item.get("decision_action"))
        alpha = _percent(item.get("alpha_return"), signed=True)
        horizon = item.get("outcome_horizon_days")
        outcome_label = f"{horizon}일 기록" if horizon else "결과 대기"
        alpha_class = _analysis_outcome_alpha_class(item.get("alpha_return"))
        report_count = item.get("report_count")
        reports = f"{report_count}개" if report_count is not None else "-"
        run_id = str(item.get("id") or "")
        run_label = run_id[:8] or "-"
        status_label = _analysis_feed_status_label(item.get("status"))
        report_path = item.get("report_path") or (f"/analyses/{run_id}" if run_id else "/analyses")
        api_path = item.get("api_path") or (f"/api/analyses/{run_id}" if run_id else "/api/analyses")
        outcome_path = f"/outcomes?ticker={code}" if code else "/outcomes"
        benchmark_label = alpha if alpha != "-" else "차이 대기"
        cards.append(
            f"""
            <article class="analysis-feed-card {alpha_class}">
              <div class="analysis-feed-card-top">
                <span>{_h(str(market))} / 기준일 {_h(str(trade_date))}</span>
                <small>분석 ID {_h(run_label)}</small>
              </div>
              <h3><a href="{_h(str(report_path))}">{_h(str(name))} <small>{_h(str(code))}</small></a></h3>
              <small class="analysis-feed-meta-line">{_h(str(model_provider))} / 리포트 {_h(reports)} / {_h(benchmark_label)}</small>
              <p>AI 의견과 결과를 요약합니다. 상세에서 출처와 본문을 확인하세요.</p>
              <div class="analysis-feed-signal-row" aria-label="분석 카드 상태">
                <span>AI {_h(str(decision))}</span>
                <span>{_h(reports)} 리포트</span>
                <span>{_h(outcome_label)} / {_h(benchmark_label)}</span>
              </div>
              <dl class="analysis-feed-metrics">
                <div><dt>데이터 기준일</dt><dd>{_h(str(trade_date))}</dd></div>
                <div><dt>상태</dt><dd>{_h(status_label)}</dd></div>
                <div><dt>모델</dt><dd>{_h(str(model_provider))}</dd></div>
                <div><dt>리포트</dt><dd>{_h(reports)}</dd></div>
                <div><dt>시장 대비</dt><dd>{_h(alpha)}</dd></div>
              </dl>
              <div class="analysis-feed-actions">
                <a href="{_h(str(report_path))}">리포트 상세</a>
                <a href="/stocks/{_h(str(code))}">종목 보기</a>
                <a href="{_h(str(outcome_path))}">사후 결과</a>
                <a class="subtle-action" href="{_h(str(api_path))}">원문 데이터</a>
              </div>
            </article>
            """
        )
    return "\n".join(cards)


def _analysis_detail_map(model: dict[str, Any]) -> str:
    reports = model.get("reports") or []
    outcomes = model.get("outcomes") or []
    run_id = str(model.get("run_id") or "")
    summary = model.get("summary") or {}
    cards = [
        ("01", "기준 리포트", f"ID {run_id[:8] or '-'}", model.get("timestamp_label") or "저장 시각 없음"),
        ("02", "AI 의견", model.get("decision_label") or "-", model.get("data_basis") or "기준 데이터 확인"),
        ("03", "AI 리포트", f"{len(reports)}개", model.get("analyst_label") or "리포트 확인"),
        (
            "04",
            "사후 결과",
            f"{summary.get('completed_outcome_count', len(outcomes) or 0)}개 완료",
            f"평균 시장 대비 {model.get('average_alpha_label') or '-'}",
        ),
    ]
    card_html = "".join(
        f"""
        <article>
          <span>{_h(number)}</span>
          <strong>{_h(title)}</strong>
          <small>{_h(value)}</small>
          <em>{_h(note)}</em>
        </article>
        """
        for number, title, value, note in cards
    )
    return f"""
    <section class="analysis-detail-map" aria-label="리포트 읽기 순서">
      <div class="analysis-detail-map-heading">
        <div>
          <p class="eyebrow">빠른 이동</p>
          <h2>리포트 핵심으로 이동</h2>
          <p class="analysis-map-copy">출처, AI 의견, 본문, 사후 결과를 바로 확인합니다.</p>
        </div>
        <nav aria-label="리포트 섹션 바로가기">
          <a href="#analysis-provenance">출처</a>
          <a href="#analysis-decision">의견</a>
          <a href="#analysis-reports">AI 리포트</a>
          <a href="#analysis-outcomes">사후 결과</a>
        </nav>
      </div>
      <div class="analysis-detail-map-grid">
        {card_html}
      </div>
    </section>
    """


def _analysis_detail_next_actions(model: dict[str, Any]) -> str:
    ticker_code = str(model.get("ticker_code") or "")
    run_id = str(model.get("run_id") or "")
    stock_href = f"/stocks/{ticker_code}" if ticker_code else "/analyses"
    outcomes_href = f"/outcomes?ticker={ticker_code}" if ticker_code else "/outcomes"
    request_href = "/member?mode=signup&tab=analysis#analysis-request-section"
    return f"""
    <section class="analysis-next-actions" aria-labelledby="analysis-next-actions-title">
      <div>
        <p class="eyebrow">다음 확인</p>
        <h2 id="analysis-next-actions-title">다음 이동</h2>
        <p>종목, 사후 결과, 새 분석 요청, 원문 데이터로 이동합니다.</p>
      </div>
      <div class="analysis-next-action-grid">
        <a href="{_h(stock_href)}">
          <span>01</span>
          <strong>종목 보기</strong>
          <small>가격과 공시 확인</small>
        </a>
        <a href="{_h(outcomes_href)}">
          <span>02</span>
          <strong>사후 결과</strong>
          <small>5일/20일 결과</small>
        </a>
        <a href="{_h(request_href)}">
          <span>03</span>
          <strong>새 분석 요청</strong>
          <small>로그인 후 요청</small>
        </a>
        <a href="/api/analyses/{_h(run_id)}">
          <span>04</span>
          <strong>원문 데이터</strong>
          <small>저장 원문</small>
        </a>
      </div>
    </section>
    """


def _analysis_detail_report_cards(
    reports: list[dict[str, Any]],
    *,
    run_id: str,
    ticker_code: str,
) -> str:
    if not reports:
        return f"""
        <article class="analysis-detail-report-card empty">
          <span>아직 없음</span>
          <h3>아직 저장된 리포트가 없습니다</h3>
          <p>저장된 AI 리포트가 아직 없습니다. 원문 데이터나 종목 페이지를 확인하세요.</p>
          <div class="analysis-empty-actions">
            <a href="/api/analyses/{_h(str(run_id))}">원문 데이터</a>
            <a href="/stocks/{_h(str(ticker_code))}">종목 페이지</a>
            <a href="/analyses">AI 리포트</a>
            <a href="/member?mode=signup&tab=analysis#analysis-request-section">새 분석 요청</a>
          </div>
        </article>
        """

    cards = []
    for report in reports:
        role = str(report.get("role") or "agent")
        title = str(report.get("title") or role)
        content = _excerpt(str(report.get("content") or ""), limit=1600)
        body_html = _analysis_report_body_html(content or "리포트 본문이 비어 있습니다.")
        quality_html = _analysis_quality_html(_report_quality(report))
        cards.append(
            f"""
            <article class="analysis-detail-report-card">
              <span>{_h(role)}</span>
              <h3>{_h(title)}</h3>
              <small class="analysis-report-excerpt-label">본문 발췌</small>
              {quality_html}
              <div class="analysis-detail-report-body">
                {body_html}
              </div>
            </article>
            """
        )
    return "\n".join(cards)


def _analysis_report_body_html(content: str) -> str:
    paragraphs = [part.strip() for part in content.replace("\r\n", "\n").split("\n") if part.strip()]
    if not paragraphs:
        paragraphs = ["리포트 본문이 비어 있습니다."]
    return "\n".join(f"<p>{_h(paragraph)}</p>" for paragraph in paragraphs[:6])


def _report_quality(report: dict[str, Any]) -> dict[str, Any] | None:
    metadata = report.get("metadata_json") or report.get("metadata") or {}
    quality = report.get("quality_checks") or (metadata.get("quality_checks") if isinstance(metadata, dict) else None)
    return quality if isinstance(quality, dict) else None


def _analysis_quality_html(quality: dict[str, Any] | None) -> str:
    if not quality:
        return ""
    compact = _analysis_quality_compact_html(quality)
    checks = quality.get("checks") or []
    flagged = [check for check in checks if check.get("status") != "pass"][:4]
    if not flagged:
        flagged = [{"label": "Grounding", "status": "pass", "detail": "핵심 기준을 통과했습니다."}]
    items = "\n".join(
        f"<li><strong>{_h(str(check.get('label') or check.get('id') or 'check'))}</strong>"
        f"<small>{_h(str(check.get('status') or '-'))} · {_h(str(check.get('detail') or ''))}</small></li>"
        for check in flagged
    )
    return f"""
      {compact}
      <ul class="analysis-quality-list" aria-label="리포트 근거 점검 상세">
        {items}
      </ul>
    """


def _analysis_quality_compact_html(quality: dict[str, Any] | None) -> str:
    if not quality:
        return ""
    risk = str(quality.get("risk_level") or "medium")
    risk_label = {"low": "낮음", "medium": "검토", "high": "높음"}.get(risk, "검토")
    passed = quality.get("passed_count", 0)
    total = quality.get("total_count", 0)
    warnings = int(quality.get("warning_count") or 0) + int(quality.get("failed_count") or 0)
    return f"""
      <div class="analysis-quality-strip risk-{_h(risk)}">
        <strong>근거 점검: {_h(risk_label)}</strong>
        <small>{_h(str(passed))}/{_h(str(total))}개 기준 통과 · 확인 필요 {warnings}건</small>
      </div>
    """


def _analysis_detail_decision_card(
    decision: dict[str, Any],
    *,
    run_id: str,
    ticker_code: str,
) -> str:
    if not decision:
        body = f"""
        <article class="analysis-rationale-card empty">
          <span>아직 없음</span>
          <h2>아직 저장된 AI 의견이 없습니다</h2>
          <p>원문 데이터와 종목 페이지에서 저장 상태를 확인하세요.</p>
          <div class="analysis-empty-actions">
            <a href="/api/analyses/{_h(str(run_id))}">원문 데이터</a>
            <a href="/stocks/{_h(str(ticker_code))}">종목 페이지</a>
            <a href="/member?mode=signup&tab=analysis#analysis-request-section">새 분석 요청</a>
          </div>
        </article>
        """
    else:
        rating = _decision_rating_label(decision.get("rating"))
        action = _decision_action_label(decision.get("action"))
        target_weight = decision.get("target_weight")
        rationale = decision.get("rationale") or decision.get("raw_decision") or "AI 의견 근거가 저장되지 않았습니다."
        body = f"""
        <article class="analysis-rationale-card">
          <span>의견 체크포인트</span>
          <h2>AI 의견: {_h(rating)}</h2>
          <p>{_h(_excerpt(str(rationale), limit=900))}</p>
          <dl>
            <div><dt>해석</dt><dd>{_h(action)}</dd></div>
            <div><dt>목표 비중</dt><dd>{_h(_percent(target_weight) if target_weight is not None else "-")}</dd></div>
          </dl>
        </article>
        """
    return f"""
    <section id="analysis-decision" class="analysis-rationale-section" aria-label="AI 의견">
      {body}
    </section>
    """


def _analysis_detail_provenance(model: dict[str, Any]) -> str:
    cells = [
        ("데이터 기준일", model["trade_date"], model["timestamp_label"]),
        ("데이터 출처", "KRX/DART/Naver", "시세, 공시, 뉴스 연결 기준입니다. 장애와 누락은 원문 데이터와 본문을 함께 확인합니다."),
        ("분석 역할", model["analyst_label"], "저장된 분석 설정 기준"),
        ("모델", model["model_label"], model["metadata_note"]),
        ("사후 결과", model["completed_outcome_label"], f"평균 시장 대비 {model['average_alpha_label']}"),
        ("공개 분석 ID", model["run_id"], "화면 리포트와 원문 데이터가 같은 ID를 공유합니다."),
        ("표시 방식", "화면 요약 + 원문 데이터", "화면 요약은 저장된 리포트 묶음을 읽기 좋게 정리한 것입니다."),
        ("한계", "주문 없는 리서치", "투자 조언/주문 아님. 휴장, 제공처 장애, 누락 데이터, 모델 오류 가능성이 있습니다."),
    ]
    return "".join(
        f"""
        <article>
          <span>{_h(label)}</span>
          <strong>{_h(value)}</strong>
          <small>{_h(note)}</small>
        </article>
        """
        for label, value, note in cells
    )


def _analysis_detail_structured_data(model: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    run = payload.get("run") or {}
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": model["heading"],
        "description": model["description"],
        "url": model["canonical_url"],
        "inLanguage": "ko-KR",
        "datePublished": str(run.get("created_at") or run.get("trade_date") or ""),
        "dateModified": str(run.get("updated_at") or run.get("created_at") or run.get("trade_date") or ""),
        "publisher": {
            "@type": "Organization",
            "name": "TradingAgents Korea",
        },
        "about": {
            "@type": "Thing",
            "name": model["ticker_name"],
            "identifier": model["ticker_code"],
            "additionalType": "KoreanStock",
        },
    }


def _decision_rating_label(value: Any, *, fallback: str = "-") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    normalized = raw.lower().replace("_", " ").replace("-", " ")
    labels = {
        "strong buy": "강한 매수 검토",
        "buy": "매수 검토",
        "accumulate": "비중 확대 검토",
        "outperform": "긍정 관찰",
        "hold": "보유 관찰",
        "neutral": "중립 관찰",
        "market perform": "시장 흐름 관찰",
        "underperform": "주의 관찰",
        "reduce": "비중 축소 검토",
        "sell": "축소 검토",
        "strong sell": "강한 축소 검토",
        "avoid": "관망",
    }
    return labels.get(normalized, raw)


def _decision_action_label(value: Any, *, fallback: str = "주문 없음") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    normalized = raw.lower().replace("_", " ").replace("-", " ")
    labels = {
        "strong buy": "강한 매수 검토",
        "buy": "매수 검토",
        "accumulate": "비중 확대 검토",
        "hold": "보유 관찰",
        "watch": "관찰",
        "wait": "대기",
        "neutral": "중립 관찰",
        "reduce": "비중 축소 검토",
        "sell": "축소 검토",
        "avoid": "관망",
        "read only": "조회 전용",
        "read-only": "조회 전용",
        "none": "주문 없음",
    }
    return labels.get(normalized, raw)


def _decision_pair_label(rating: Any, action: Any) -> str:
    rating_label = _decision_rating_label(rating, fallback="")
    action_label = _decision_action_label(action, fallback="")
    if rating_label and action_label and rating_label != action_label:
        return f"{rating_label} / {action_label}"
    return rating_label or action_label or "-"


def _top_count_label(counts: dict[str, Any], *, formatter: Callable[[Any], str] | None = None) -> str | None:
    if not counts:
        return None
    key, value = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))[0]
    label = formatter(key) if formatter else str(key)
    return f"{label} {value}"


def _analysis_feed_status_label(status: Any) -> str:
    return {
        "available": "분석 사용 가능",
        "not_configured": "AI 리포트 준비 중",
    }.get(str(status), "상태 확인")


def _analysis_outcomes_status_label(status: Any) -> str:
    return {
        "available": "사후 결과 사용 가능",
        "not_configured": "사후 결과 준비 중",
        "unavailable": "사후 결과 확인 필요",
    }.get(str(status), "상태 확인")


def _report_cards(reports: list[dict[str, Any]]) -> str:
    if not reports:
        return """
        <article class="report-card empty">
          <span>대기</span>
          <h3>리포트 대기</h3>
          <p>AI 리포트가 준비되면 AI 본문이 표시됩니다.</p>
        </article>
        """

    cards = []
    for report in reports:
        title = report.get("title") or report.get("role") or "report"
        role = report.get("role") or "agent"
        content = _excerpt(report.get("content") or "", limit=420)
        quality_html = _analysis_quality_compact_html(_report_quality(report))
        cards.append(
            f"""
            <article class="report-card">
              <span>{_h(str(role))}</span>
              <h3>{_h(str(title))}</h3>
              {quality_html}
              <p>{_h(content)}</p>
            </article>
            """
        )
    return "\n".join(cards)


def _strategy_lens_cards(lenses: list[dict[str, Any]]) -> str:
    if not lenses:
        return ""

    cards = []
    for lens in lenses:
        status = str(lens.get("status") or "neutral")
        title = str(lens.get("title") or lens.get("id") or "렌즈")
        summary = str(lens.get("summary") or "데이터를 확인 중입니다.")
        metrics = lens.get("metrics") if isinstance(lens.get("metrics"), dict) else {}
        metric_bits = _lens_metric_bits(metrics)
        metrics_html = f"<p>{_h(metric_bits)}</p>" if metric_bits else ""
        cards.append(
            f"""
            <article class="lens-card lens-{_h(status)}">
              <div>
                <span>{_h(_lens_status_label(status))}</span>
                <h3>{_h(title)}</h3>
              </div>
              <p>{_h(summary)}</p>
              {metrics_html}
            </article>
            """
        )

    return f"""
    <section class="lens-section" aria-labelledby="lens-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">체크포인트</p>
          <h2 id="lens-title">투자 체크포인트</h2>
        </div>
        <span class="status-pill">주문 없음</span>
      </div>
      <div class="lens-grid">
        {"".join(cards)}
      </div>
    </section>
    """


def _outcome_cards(outcomes: list[dict[str, Any]]) -> str:
    if not outcomes:
        cards = """
        <article class="outcome-card empty">
          <span>대기</span>
          <h3>사후 결과 대기</h3>
          <p>거래일이 충분히 쌓이면 5일/20일 결과가 표시됩니다.</p>
          <div class="analysis-feed-actions outcome-card-actions">
            <a href="/analyses">AI 리포트</a>
            <a href="/features/outcomes">기준</a>
          </div>
        </article>
        """
    else:
        cards = "\n".join(_outcome_card(outcome) for outcome in outcomes[:6])
    return f"""
    <section id="analysis-outcomes" class="outcome-section" aria-labelledby="outcome-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">사후 결과</p>
          <h2 id="outcome-title">사후 결과</h2>
          <p class="outcome-section-copy">리포트 작성 뒤 5일/20일 흐름을 시장과 비교합니다.</p>
        </div>
        <span class="status-pill">시장 대비</span>
      </div>
      <div class="outcome-grid">
        {cards}
      </div>
    </section>
    """


def _outcome_card(outcome: dict[str, Any]) -> str:
    status = str(outcome.get("status") or "pending")
    horizon = outcome.get("horizon_days") or "-"
    raw_return = _percent(outcome.get("raw_return"))
    alpha_return = _percent(outcome.get("alpha_return"), signed=True)
    actual_days = outcome.get("actual_holding_days")
    title = f"{horizon}일 기록"
    if status == "completed":
        summary = f"종목 수익률 {raw_return}, 시장 대비 {alpha_return}"
    elif status == "pending":
        summary = f"현재 {actual_days or 0}거래일만 관측되어 사후 결과를 기다리는 중입니다."
    else:
        summary = "결과 데이터를 아직 확보하지 못했습니다."
    return f"""
    <article class="outcome-card outcome-{_h(status)}">
      <span>{_h(_outcome_status_label(status))}</span>
      <h3>{_h(title)}</h3>
      <p>{_h(summary)}</p>
      <dl>
        <div><dt>종목</dt><dd>{_h(raw_return)}</dd></div>
        <div><dt>시장 대비</dt><dd>{_h(alpha_return)}</dd></div>
        <div><dt>기준일</dt><dd>{_h(outcome.get("trade_date") or "-")}</dd></div>
        <div><dt>평가일</dt><dd>{_h(outcome.get("evaluated_at") or "-")}</dd></div>
      </dl>
    </article>
    """


def _structured_data(model: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    ticker = payload.get("ticker", {})
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": model["title"],
        "description": model["description"],
        "url": model["canonical_url"],
        "inLanguage": "ko-KR",
        "isPartOf": {
            "@type": "WebSite",
            "name": "TradingAgents Korea",
            "url": model["canonical_url"].split("/stocks/")[0] if "/stocks/" in model["canonical_url"] else "/",
        },
        "about": {
            "@type": "Thing",
            "name": ticker.get("name"),
            "identifier": ticker.get("code"),
            "additionalType": "KoreanStock",
        },
        "dateModified": payload.get("generated_at"),
        "publisher": {
            "@type": "Organization",
            "name": "TradingAgents Korea",
        },
    }


def _analysis_status_label(status: Any) -> str:
    return {
        "available": "분석 완료",
        "missing": "분석 대기",
        "not_configured": "공개 분석 준비 중",
        "skipped": "분석 제외",
    }.get(str(status), "상태 확인")


def _analysis_title(analysis: dict[str, Any], decision: dict[str, Any]) -> str:
    if analysis.get("status") == "available":
        rating = _decision_rating_label(decision.get("rating"), fallback="완료")
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


def _lens_status_label(status: str) -> str:
    return {
        "positive": "긍정",
        "neutral": "중립",
        "caution": "주의",
        "unavailable": "대기",
    }.get(status, "확인")


def _lens_metric_bits(metrics: dict[str, Any]) -> str:
    preferred = [
        "return_20d",
        "volume_ratio",
        "drawdown_from_window_high",
        "annualized_volatility_20d",
        "analysis_status",
        "refresh_reason",
        "live_trading",
    ]
    bits = []
    for key in preferred:
        if key not in metrics or metrics[key] is None:
            continue
        bits.append(f"{key}: {metrics[key]}")
        if len(bits) >= 2:
            break
    return " / ".join(bits)


def _outcome_status_label(status: str) -> str:
    return {
        "completed": "완료",
        "pending": "대기",
        "unavailable": "데이터 없음",
    }.get(status, "확인")


def _money(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.0f}원"


def _percent(value: Any, *, signed: bool = False) -> str:
    if value is None:
        return "-"
    parsed = float(value) * 100
    prefix = "+" if signed and parsed > 0 else ""
    return f"{prefix}{parsed:.2f}%"


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


def _public_supabase_config() -> dict[str, str | bool | None]:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL") or os.getenv("TRADINGAGENTS_SUPABASE_URL")
    anon_key = (
        os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    )
    return {
        "configured": bool(url and anon_key),
        "supabase_url": url.rstrip("/") if url else None,
        "supabase_anon_key": anon_key,
    }


def _h(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _stock_notice_items(notices: Iterable[Any]) -> list[str]:
    translated: list[str] = []
    for notice in notices:
        text = str(notice or "").strip()
        if not text:
            continue
        lower = text.lower()
        if "informational purposes" in lower or "investment advice" in lower:
            translated.append("AI 분석은 정보 제공용이며 투자 조언이 아닙니다.")
        elif "live trading" in lower or "broker order" in lower:
            translated.append("실거래와 브로커 주문 실행은 의도적으로 지원하지 않습니다.")
        else:
            translated.append(text)
    if translated:
        return translated
    return [
        "AI 분석은 정보 제공용이며 투자 조언이 아닙니다.",
        "실거래와 브로커 주문 실행은 의도적으로 지원하지 않습니다.",
    ]


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
  --app-font-stack: Geist, "Geist Fallback", "Noto Sans KR", "Noto Sans KR Fallback", -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
}

html {
  font-family: var(--app-font-stack);
  text-rendering: geometricPrecision;
}

* {
  box-sizing: border-box;
}

[hidden] {
  display: none !important;
}

body {
  margin: 0;
  min-width: 320px;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--app-font-stack);
}

button,
input,
select,
textarea {
  font-family: var(--app-font-stack);
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

.top-links {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
}

.top-links a {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid transparent;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease, transform 160ms ease;
}

.top-links a:hover {
  background: var(--surface-strong);
  color: var(--ink);
}

.top-links a[aria-current="page"] {
  border-color: rgba(20, 107, 99, 0.36);
  background: rgba(20, 107, 99, 0.1);
  color: var(--ink);
}

.top-links a[hidden] {
  display: none;
}

.top-links .top-auth-link,
.top-links .top-dashboard-link,
.top-links .top-admin-link {
  border: 1px solid var(--line);
  color: var(--ink);
}

.top-links .top-join-link {
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #ffffff;
}

.top-links .top-join-link:hover {
  background: #0f5d55;
  color: #ffffff;
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
  min-width: 68px;
  height: 40px;
  padding: 0 16px;
  border: 0;
  border-radius: 6px;
  background: var(--ink);
  color: white;
  font: inherit;
  font-weight: 700;
  white-space: nowrap;
  cursor: pointer;
}

.shell {
  width: min(1280px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0 48px;
}

.public-home {
  background:
    linear-gradient(90deg, rgba(20, 107, 99, 0.05) 1px, transparent 1px),
    linear-gradient(#f7f4ec, #eef3ef 46%, #f6f7f4 100%);
  background-size: 72px 100%, auto;
}

.public-home .topbar {
  background: rgba(247, 244, 236, 0.92);
}

.home-shell {
  width: min(1440px, calc(100% - 32px));
  margin: 0 auto;
  padding: 24px 0 60px;
}

.home-hero {
  display: grid;
  grid-template-columns: minmax(0, 0.94fr) minmax(420px, 0.76fr);
  gap: 56px;
  align-items: center;
  min-height: 560px;
  padding: 30px 0 40px;
  border-bottom: 1px solid rgba(23, 32, 31, 0.14);
}

.home-hero-copy {
  max-width: 720px;
}

.home-hero h1 {
  margin-bottom: 18px;
  font-size: 68px;
  line-height: 0.94;
  letter-spacing: 0;
}

.home-lede {
  max-width: 660px;
  margin-bottom: 24px;
  color: #3d4846;
  font-size: 18px;
  line-height: 1.7;
}

.home-hero-search {
  width: min(100%, 620px);
  padding: 8px;
  border: 1px solid rgba(23, 32, 31, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 24px 60px rgba(23, 32, 31, 0.08);
}

.home-hero-search input,
.home-hero-search button {
  height: 48px;
}

.home-cta-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 14px;
}

.home-primary-link,
.home-secondary-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 0 16px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 800;
  transition: transform 180ms ease, background 180ms ease, border-color 180ms ease;
}

.home-primary-link {
  border: 1px solid var(--ink);
  background: var(--ink);
  color: #ffffff;
}

.home-secondary-link {
  border: 1px solid rgba(23, 32, 31, 0.18);
  background: rgba(255, 255, 255, 0.6);
  color: var(--ink);
}

.home-primary-link:hover,
.home-secondary-link:hover {
  transform: translateY(-1px);
}

.home-primary-link:active,
.home-secondary-link:active {
  transform: translateY(1px);
}

.home-proof-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  max-width: 690px;
  margin: 34px 0 0;
  padding-top: 18px;
  border-top: 1px solid rgba(23, 32, 31, 0.16);
}

.home-proof-row div {
  min-width: 0;
}

.home-proof-row dt {
  margin-bottom: 8px;
  color: var(--accent-strong);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.home-proof-row dd {
  margin: 0;
  color: var(--ink);
  font-size: 14px;
  font-weight: 800;
}

.home-hero-visual {
  position: relative;
  min-height: 480px;
  overflow: hidden;
  border: 1px solid rgba(243, 245, 239, 0.14);
  border-radius: 8px;
  background:
    linear-gradient(rgba(255, 255, 255, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.055) 1px, transparent 1px),
    #111817;
  background-size: 44px 44px, 44px 44px, auto;
  color: #f3f5ef;
  box-shadow: 0 32px 80px rgba(18, 25, 23, 0.24);
}

.home-hero-visual::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(120deg, transparent 0 18%, rgba(20, 107, 99, 0.16) 18% 19%, transparent 19% 100%),
    linear-gradient(74deg, transparent 0 64%, rgba(214, 167, 59, 0.22) 64% 65%, transparent 65% 100%);
  opacity: 0.8;
}

.home-radar {
  position: absolute;
  top: 28px;
  right: 28px;
  width: 330px;
  aspect-ratio: 1;
  border: 1px solid rgba(119, 196, 184, 0.34);
  border-radius: 50%;
  opacity: 0.62;
}

.home-radar span,
.home-radar::after {
  content: "";
  position: absolute;
  border-radius: 50%;
}

.home-radar span {
  inset: var(--ring);
  border: 1px solid rgba(119, 196, 184, 0.28);
}

.home-radar span:nth-child(1) {
  --ring: 56px;
}

.home-radar span:nth-child(2) {
  --ring: 112px;
}

.home-radar span:nth-child(3) {
  --ring: 156px;
  background: rgba(119, 196, 184, 0.12);
}

.home-radar::after {
  left: 50%;
  top: 50%;
  width: 1px;
  height: 44%;
  border-radius: 0;
  background: linear-gradient(rgba(214, 167, 59, 0.92), transparent);
  transform-origin: top center;
  animation: homeRadarSweep 9s linear infinite;
}

.home-console {
  position: absolute;
  left: 34px;
  right: 34px;
  bottom: 34px;
  z-index: 1;
  border: 1px solid rgba(243, 245, 239, 0.16);
  border-radius: 8px;
  background: rgba(17, 24, 23, 0.82);
  backdrop-filter: blur(10px);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.home-console-top,
.home-console-grid,
.home-pipeline {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.home-console-top {
  border-bottom: 1px solid rgba(243, 245, 239, 0.12);
}

.home-console-top span,
.home-pipeline span {
  padding: 12px;
  color: rgba(243, 245, 239, 0.58);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.home-console-top span:first-child {
  grid-column: span 3;
  color: #77c4b8;
}

.home-console-focus {
  padding: 26px 24px 18px;
}

.home-console-focus span,
.home-console-focus small {
  display: block;
  color: rgba(243, 245, 239, 0.62);
  font-family: var(--app-font-stack);
  font-size: 12px;
}

.home-console-focus strong {
  display: block;
  margin: 6px 0;
  color: #ffffff;
  font-size: 34px;
  line-height: 1;
  letter-spacing: 0;
}

.home-sparkline {
  display: flex;
  align-items: end;
  gap: 7px;
  height: 84px;
  margin: 0 24px 22px;
  border-bottom: 1px solid rgba(243, 245, 239, 0.22);
}

.home-sparkline i {
  flex: 1;
  height: var(--h);
  border-radius: 3px 3px 0 0;
  background: linear-gradient(#d6a73b, #77c4b8);
  opacity: 0.86;
}

.home-console-grid {
  border-top: 1px solid rgba(243, 245, 239, 0.12);
}

.home-console-grid div {
  min-width: 0;
  padding: 14px;
  border-right: 1px solid rgba(243, 245, 239, 0.12);
}

.home-console-grid div:last-child {
  border-right: 0;
}

.home-console-grid span {
  display: block;
  margin-bottom: 6px;
  color: rgba(243, 245, 239, 0.52);
  font-size: 12px;
}

.home-console-grid strong {
  font-family: var(--app-font-stack);
  font-size: 13px;
}

.home-pipeline {
  position: absolute;
  left: 34px;
  right: 34px;
  top: 34px;
  z-index: 1;
  border: 1px solid rgba(243, 245, 239, 0.12);
  border-radius: 8px;
  background: rgba(17, 24, 23, 0.56);
}

.home-pipeline span {
  border-right: 1px solid rgba(243, 245, 239, 0.12);
}

.home-pipeline span:last-child {
  border-right: 0;
}

.home-band,
.home-analysis-zone,
.home-ops-strip {
  border-bottom: 1px solid rgba(23, 32, 31, 0.13);
}

.home-band {
  padding: 48px 0;
}

.home-section-heading {
  display: grid;
  grid-template-columns: minmax(0, 0.7fr) minmax(280px, 0.3fr);
  gap: 28px;
  align-items: end;
  margin-bottom: 22px;
}

.home-section-heading p,
.home-section-copy p {
  margin-bottom: 0;
  color: var(--muted);
  line-height: 1.65;
}

.home-section-heading .home-primary-link {
  justify-self: end;
}

.home-ticker-rail {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(230px, 1fr);
  gap: 12px;
  overflow-x: auto;
  padding: 2px 0 8px;
  scroll-snap-type: x mandatory;
}

.home-ticker-rail .analysis-feed-card {
  min-height: 186px;
  scroll-snap-align: start;
}

.home-ticker-rail .analysis-feed-card:hover,
.home-analysis-grid .analysis-feed-card:hover {
  transform: translateY(-2px);
}

.home-ticker-rail .analysis-feed-card,
.home-analysis-grid .analysis-feed-card {
  transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}

.home-analysis-zone {
  display: grid;
  grid-template-columns: minmax(280px, 0.36fr) minmax(0, 0.64fr);
  gap: 42px;
  align-items: start;
  padding: 54px 0;
}

.home-section-copy {
  position: sticky;
  top: 92px;
}

.home-section-copy h2 {
  margin-bottom: 14px;
  font-size: 34px;
  line-height: 1.05;
}

.home-section-copy .home-secondary-link {
  margin-top: 22px;
}

.home-analysis-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(0, 0.92fr);
  gap: 14px;
}

.home-analysis-grid .analysis-feed-card:first-child:not(.empty) {
  grid-row: span 2;
  min-height: 370px;
  background: #ffffff;
}

.home-ops-strip {
  display: grid;
  grid-template-columns: minmax(0, 0.46fr) minmax(0, 0.54fr);
  gap: 32px;
  align-items: center;
  padding: 28px 0;
}

.home-ops-strip h2 {
  font-size: 24px;
  line-height: 1.16;
}

.home-ops-strip ul {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--muted);
  line-height: 1.55;
}

.home-ops-strip li {
  padding-top: 10px;
  border-top: 1px solid rgba(23, 32, 31, 0.13);
}

.home-ops-strip a {
  color: inherit;
  font-weight: 900;
  text-decoration: underline;
  text-underline-offset: 4px;
}

.home-member-band {
  border-bottom: 0;
}

.home-flow-list {
  display: grid;
  gap: 0;
  border-top: 1px solid rgba(23, 32, 31, 0.14);
}

.home-flow-list article {
  display: grid;
  grid-template-columns: 60px minmax(180px, 0.32fr) minmax(0, 1fr);
  gap: 18px;
  align-items: baseline;
  padding: 18px 0;
  border-bottom: 1px solid rgba(23, 32, 31, 0.12);
}

.home-flow-list span {
  color: var(--accent-strong);
  font-family: var(--app-font-stack);
  font-size: 13px;
  font-weight: 800;
}

.home-flow-list strong {
  font-size: 18px;
}

.home-flow-list p {
  margin: 0;
  color: var(--muted);
  line-height: 1.6;
}

@keyframes homeRadarSweep {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.summary-band {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 20px;
  padding: 26px 0 24px;
}

.home-search-band {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 520px);
  gap: 24px;
  align-items: end;
  padding: 30px 0 24px;
}

.home-search {
  width: 100%;
}

.home-search input,
.home-search button {
  height: 48px;
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

.workspace > * {
  min-width: 0;
}

.chart-panel,
.analysis-panel,
.simulation-panel,
.report-section,
.notice-strip,
.metric-grid article,
.report-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  max-width: 100%;
}

.chart-panel,
.report-section {
  width: 100%;
  padding: 20px;
  box-shadow: var(--shadow);
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.chart-heading-meta,
.chart-toolbar,
.chart-control-block,
.chart-tabs {
  display: flex;
  align-items: center;
}

.chart-heading-meta {
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.chart-toolbar {
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 10px;
  min-width: 0;
}

.chart-control-block {
  align-items: flex-start;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.chart-control-block > span {
  color: var(--muted);
  font-size: 11px;
  font-weight: 900;
}

.chart-tools,
.chart-tool-group {
  display: flex;
  align-items: center;
  min-width: 0;
}

.chart-tools {
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 10px;
  margin: 0 0 10px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(20, 107, 99, 0.05);
}

.chart-tool-group {
  flex-wrap: wrap;
  gap: 6px;
}

.chart-settings-group {
  gap: 8px;
}

.chart-setting-field {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 30px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.chart-setting-field span {
  white-space: nowrap;
}

.chart-setting-field input {
  width: 54px;
  height: 24px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface-strong);
  color: var(--ink);
  font: inherit;
  font-size: 12px;
  font-weight: 900;
  text-align: center;
}

.chart-tool-group > span,
.chart-tools small {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.chart-tool-button {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--muted);
  font: inherit;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
  transition: background 180ms ease, border-color 180ms ease, color 180ms ease, transform 180ms ease;
}

.chart-tool-button:hover,
.chart-tool-button.is-active {
  border-color: rgba(20, 107, 99, 0.45);
  background: var(--surface-strong);
  color: var(--accent-strong);
}

.chart-tool-button:active {
  transform: translateY(1px);
}

.chart-tabs {
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.chart-tab,
.data-pill {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  min-width: 0;
  white-space: nowrap;
}

.chart-tab:hover,
.chart-tab.is-active {
  border-color: rgba(20, 107, 99, 0.45);
  background: var(--surface-strong);
  color: var(--accent-strong);
}

.chart-tab.is-active {
  box-shadow: inset 0 0 0 1px rgba(20, 107, 99, 0.18);
}

.chart-tab.is-disabled {
  opacity: 0.46;
  cursor: not-allowed;
}

.chart-caption {
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 13px;
}

.data-source-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  margin: 0 0 12px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--line);
}

.data-source-strip div {
  min-width: 0;
  padding: 10px;
  background: var(--surface);
}

.data-source-strip dt {
  color: var(--muted);
  font-family: var(--app-font-stack);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.data-source-strip dd {
  margin: 5px 0 0;
  color: var(--ink);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.3;
  overflow-wrap: anywhere;
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
  min-height: 420px;
  aspect-ratio: 16 / 10;
}

.chart-attribution {
  margin: 10px 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.4;
}

.chart-attribution a {
  color: inherit;
  font-weight: 700;
  text-underline-offset: 3px;
}

.tv-price-chart,
.chart-canvas-fallback,
.chart-drawing-layer {
  display: block;
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.tv-price-chart[hidden],
.chart-canvas-fallback[hidden] {
  display: none;
}

.tv-price-chart.is-drawing-trend {
  cursor: crosshair;
}

.chart-drawing-layer {
  z-index: 1;
  overflow: visible;
  pointer-events: none;
}

.chart-drawing-layer line {
  stroke: var(--accent);
  stroke-width: 2;
  filter: drop-shadow(0 0 5px rgba(20, 107, 99, 0.28));
}

.chart-legend {
  position: absolute;
  top: 10px;
  right: 12px;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  max-width: min(520px, calc(100% - 24px));
  pointer-events: none;
}

.chart-legend span {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid rgba(220, 227, 223, 0.9);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.chart-fallback {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  margin: 0;
  color: var(--muted);
}

.chart-tooltip {
  position: absolute;
  z-index: 2;
  top: 12px;
  max-width: min(260px, calc(100% - 24px));
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 12px 32px rgba(20, 31, 28, 0.12);
  color: var(--ink);
  font-size: 12px;
  pointer-events: none;
}

.chart-tooltip strong,
.chart-tooltip span {
  display: block;
  white-space: nowrap;
}

.chart-tooltip span {
  margin-top: 4px;
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

.lens-section {
  margin-top: 18px;
}

.lens-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.lens-card {
  min-height: 164px;
  padding: 16px;
  border: 1px solid var(--line);
  border-left-width: 4px;
  border-radius: 8px;
  background: var(--surface);
}

.lens-card div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.lens-card span {
  order: 2;
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  background: var(--surface-strong);
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.lens-card h3 {
  margin: 0;
  font-size: 18px;
}

.lens-card p {
  margin: 0;
  color: var(--muted);
}

.lens-card p + p {
  margin-top: 10px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  word-break: break-word;
}

.lens-positive {
  border-left-color: #c0392b;
}

.lens-caution {
  border-left-color: #1f5f9f;
}

.lens-neutral,
.lens-unavailable {
  border-left-color: #9aa6a1;
}

.analysis-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.analysis-summary-grid article {
  min-height: 112px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.analysis-summary-grid span,
.analysis-summary-grid small {
  display: block;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
}

.analysis-summary-grid strong {
  display: block;
  margin: 10px 0 8px;
  overflow-wrap: anywhere;
  font-size: 24px;
  line-height: 1.12;
}

.analysis-pipeline-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin-top: 16px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--line);
}

.analysis-pipeline-strip article {
  display: grid;
  gap: 9px;
  min-height: 128px;
  padding: 18px;
  background: var(--surface);
}

.analysis-pipeline-strip span {
  color: var(--accent);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 900;
}

.analysis-pipeline-strip strong {
  color: var(--ink);
  font-size: 18px;
}

.analysis-pipeline-strip small {
  color: var(--muted);
  line-height: 1.5;
}

.analysis-track-record {
  margin-top: 18px;
}

.analysis-track-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.analysis-track-grid article {
  min-height: 118px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.analysis-track-grid span,
.analysis-track-grid small {
  display: block;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
}

.analysis-track-grid strong {
  display: block;
  margin: 10px 0 8px;
  overflow-wrap: anywhere;
  font-family: var(--app-font-stack);
  font-size: 24px;
  font-variant-numeric: tabular-nums;
  line-height: 1.12;
}

.outcome-section {
  margin-top: 18px;
}

.outcome-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.outcome-card {
  min-height: 168px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.outcome-card span {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  background: var(--surface-strong);
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.outcome-card h3 {
  margin: 12px 0 8px;
}

.outcome-card p {
  color: var(--muted);
}

.outcome-card dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.outcome-card dl div {
  padding: 8px;
  border-radius: 6px;
  background: var(--surface-strong);
}

.outcome-card dt {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.outcome-card dd {
  margin: 4px 0 0;
  font-weight: 900;
}

.analysis-panel,
.simulation-panel {
  padding: 18px;
}

.analysis-panel .data-source-strip {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 14px;
}

.analysis-confidence-panel {
  display: grid;
  gap: 8px;
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--warn);
  border-radius: 8px;
  background: rgba(138, 90, 10, 0.08);
}

.analysis-confidence-panel span {
  color: var(--muted);
  font-family: var(--app-font-stack);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.analysis-confidence-panel strong {
  color: var(--ink);
  font-size: 18px;
}

.analysis-confidence-panel p,
.analysis-confidence-panel ul {
  margin: 0;
  color: var(--muted);
  line-height: 1.5;
}

.analysis-confidence-panel ul {
  padding-left: 18px;
}

.analysis-confidence-panel.confidence-high {
  border-left-color: var(--accent);
  background: rgba(20, 107, 99, 0.08);
}

.analysis-confidence-panel.confidence-low {
  border-left-color: var(--warn);
}

.analysis-panel p {
  margin-bottom: 0;
  color: var(--muted);
  line-height: 1.6;
}

.simulation-panel {
  display: grid;
  gap: 12px;
}

.simulation-panel h2 {
  margin: 0;
  font-size: 22px;
}

.simulation-preview {
  display: grid;
  gap: 10px;
  min-height: 92px;
}

.simulation-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--line);
}

.simulation-grid div {
  min-width: 0;
  padding: 10px;
  background: var(--surface);
}

.simulation-grid span {
  display: block;
  color: var(--muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.06em;
}

.simulation-grid strong {
  display: block;
  margin-top: 6px;
  color: var(--ink);
  font-size: 15px;
  overflow-wrap: anywhere;
}

.simulation-preview p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
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

.analysis-feed-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.outcome-feed-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.analysis-feed-card {
  display: grid;
  gap: 12px;
  min-height: 178px;
  padding: 16px;
  border: 1px solid var(--line);
  border-top: 3px solid var(--accent);
  border-radius: 8px;
  background: var(--surface);
}

.analysis-feed-card.is-positive-alpha {
  border-top-color: var(--accent);
}

.analysis-feed-card.is-negative-alpha {
  border-top-color: var(--gain);
}

.analysis-feed-card.is-neutral-alpha {
  border-top-color: var(--warn);
}

.analysis-feed-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.analysis-feed-card-top span {
  margin: 0;
}

.analysis-feed-card-top small {
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.analysis-feed-card span {
  display: inline-block;
  margin-bottom: 12px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.analysis-feed-card h3 a {
  display: inline-block;
}

.analysis-feed-card small {
  color: var(--muted);
  font-size: 13px;
}

.analysis-feed-card .analysis-feed-meta-line {
  color: var(--home-readable, rgba(246, 243, 232, 0.82));
  font-family: var(--app-font-stack);
  font-weight: 800;
  line-height: 1.4;
}

.analysis-feed-card p {
  margin: 0 0 2px;
  color: var(--muted);
  line-height: 1.5;
}

.analysis-feed-signal-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.analysis-feed-card .analysis-feed-signal-row span {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  margin: 0;
  padding: 0 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-strong);
  color: var(--ink);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0;
  line-height: 1.2;
  text-transform: none;
}

.analysis-feed-card dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

.analysis-feed-card dl.analysis-feed-metrics {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--line);
}

.analysis-feed-card dl div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid var(--line);
  padding-top: 8px;
}

.analysis-feed-card dl.analysis-feed-metrics div {
  display: grid;
  gap: 4px;
  min-width: 0;
  border-top: 0;
  padding: 9px 10px;
  background: var(--surface-strong);
}

.analysis-feed-card dt {
  color: var(--muted);
  font-size: 13px;
}

.analysis-feed-card dd {
  margin: 0;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.analysis-feed-card.empty {
  grid-column: 1 / -1;
}

.analysis-empty-plan {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--line);
}

.analysis-empty-plan div {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 9px;
  align-items: start;
  min-height: 74px;
  padding: 12px;
  background: var(--surface-strong);
}

.analysis-empty-plan strong {
  display: inline-grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 999px;
  background: var(--accent);
  color: #ffffff;
  font-size: 12px;
}

.analysis-empty-plan span {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.45;
  text-transform: none;
}

.outcome-feed-card {
  min-height: 214px;
}

.outcome-feed-card.outcome-pending {
  border-top-color: var(--home-brass);
}

.outcome-feed-card.outcome-unavailable {
  border-top-color: var(--home-vermilion);
}

.outcome-feed-card dl div {
  min-width: 0;
}

.outcome-feed-card dd {
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.outcome-page .summary-band h1 {
  word-break: keep-all;
}

.outcome-page .summary-band .asof,
.outcome-feed-card h3,
.outcome-feed-card p {
  overflow-wrap: anywhere;
}

.outcome-hero-copy {
  max-width: 720px;
  margin: 14px 0 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-size: clamp(15px, 1.4vw, 18px);
  line-height: 1.64;
  overflow-wrap: anywhere;
}

.outcome-page .decision-box {
  width: 100%;
}

.analysis-feed-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(94px, 1fr));
  gap: 8px;
  padding-top: 4px;
  border-top: 1px solid var(--line);
}

.analysis-feed-actions a {
  display: inline-grid;
  min-height: 34px;
  place-items: center;
  padding: 0 11px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--ink);
  font-size: 13px;
  font-weight: 900;
}

.analysis-feed-actions a:first-child {
  border-color: var(--accent);
  background: var(--accent);
  color: #ffffff;
}

.analysis-feed-actions a.subtle-action,
.analysis-detail-actions a.subtle-action {
  border-color: rgba(246, 243, 232, 0.12);
  background: rgba(246, 243, 232, 0.045);
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
}

.feature-shell,
.admin-shell {
  padding: clamp(52px, 8vw, 96px) 0 80px;
}

.feature-detail-page .feature-shell {
  padding-top: clamp(36px, 6vw, 72px);
}

.feature-hero,
.admin-hero {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(360px, 0.62fr);
  gap: clamp(28px, 5vw, 76px);
  align-items: start;
}

.feature-copy,
.admin-hero > div {
  display: grid;
  gap: 22px;
}

.feature-detail-page .feature-copy {
  gap: 18px;
}

.feature-copy h1,
.admin-hero h1 {
  max-width: 780px;
  margin: 0;
  color: var(--home-ink);
  font-size: clamp(48px, 6.4vw, 92px);
  line-height: 0.96;
  letter-spacing: 0;
  text-wrap: balance;
}

.feature-detail-page .feature-copy h1 {
  font-size: clamp(44px, 5.8vw, 82px);
}

.feature-detail-page .feature-copy h1.feature-title-compact {
  max-width: 26ch;
  font-size: clamp(2rem, 2.8vw, 2.5rem);
  line-height: 1.3;
  letter-spacing: -0.03em;
}

.feature-copy > p,
.admin-hero > div > p {
  max-width: 680px;
  margin: 0;
  color: var(--home-readable, rgba(246, 243, 232, 0.8));
  font-size: clamp(17px, 2vw, 21px);
  line-height: 1.72;
}

.feature-proof-row {
  max-width: 760px;
}

.public-home .feature-proof-row {
  border-top-color: rgba(246, 243, 232, 0.2);
}

.public-home .feature-proof-row dt {
  color: rgba(143, 216, 189, 0.94);
}

.public-home .feature-proof-row dd {
  color: rgba(246, 243, 232, 0.9);
}

.feature-diagram {
  position: sticky;
  top: 96px;
  display: grid;
  gap: 18px;
  min-height: 520px;
  padding: 26px;
  border: 1px solid rgba(246, 243, 232, 0.16);
  background:
    linear-gradient(90deg, rgba(246, 243, 232, 0.04) 1px, transparent 1px),
    linear-gradient(0deg, rgba(246, 243, 232, 0.04) 1px, transparent 1px),
    rgba(15, 22, 18, 0.78);
  background-size: 42px 42px;
  box-shadow: 0 30px 90px rgba(0, 0, 0, 0.28);
}

.feature-diagram-top {
  display: flex;
  justify-content: space-between;
  color: rgba(246, 243, 232, 0.72);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.feature-step-track {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  align-self: start;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
}

.feature-step-track span {
  min-height: 58px;
  display: grid;
  place-items: center;
  padding: 8px;
  background: rgba(246, 243, 232, 0.05);
  color: rgba(246, 243, 232, 0.76);
  font-size: 11px;
  font-weight: 800;
  text-align: center;
}

.feature-signal-card {
  align-self: end;
  display: grid;
  gap: 12px;
  padding: 24px;
  border: 1px solid rgba(207, 255, 40, 0.24);
  background: rgba(13, 19, 15, 0.86);
}

.feature-signal-card span {
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 800;
}

.feature-signal-card strong {
  color: var(--home-ink);
  font-size: clamp(28px, 4vw, 54px);
  line-height: 1;
}

.feature-diagram-compact .feature-signal-card strong {
  max-width: 100%;
  font-size: clamp(1.35rem, 1.8vw, 1.5rem);
  line-height: 1.4;
  letter-spacing: -0.03em;
  overflow-wrap: normal;
  text-wrap: balance;
  white-space: normal;
  word-break: keep-all;
}

.feature-signal-card small {
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  line-height: 1.6;
}

.feature-card-grid,
.feature-index-grid,
.admin-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin-top: clamp(42px, 7vw, 88px);
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.14);
}

.admin-grid {
  align-items: start;
}

.feature-card-grid article,
.feature-index-card,
.admin-card {
  display: grid;
  gap: 16px;
  min-height: 220px;
  padding: 24px;
  background: rgba(15, 22, 18, 0.76);
}

.feature-index-card {
  color: inherit;
  text-decoration: none;
  transition:
    border-color 0.16s ease,
    background 0.16s ease,
    transform 0.16s ease;
}

.feature-index-card:hover,
.feature-index-card:focus-visible {
  background: rgba(207, 255, 35, 0.09);
  transform: translateY(-2px);
}

.feature-card-grid span,
.feature-index-card span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 900;
}

.feature-card-grid strong,
.feature-index-card strong,
.admin-card h2 {
  color: var(--home-ink);
  font-size: 22px;
}

.feature-card-grid p,
.feature-index-card small,
.feature-boundary li,
.admin-card label,
.admin-ops-panel pre,
.admin-card pre,
.admin-token-panel small {
  color: rgba(246, 243, 232, 0.78);
}

.feature-card-grid p {
  margin: 0;
  line-height: 1.62;
}

.feature-journey {
  display: grid;
  grid-template-columns: minmax(240px, 0.58fr) minmax(0, 1.42fr);
  gap: 18px;
  align-items: stretch;
  margin-top: 18px;
  padding: 18px;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(215, 255, 63, 0.06), rgba(143, 216, 189, 0.035)),
    rgba(15, 22, 18, 0.72);
}

.feature-journey.feature-journey-compact {
  align-items: center;
  padding-block: clamp(18px, 2.4vw, 28px);
}

.feature-journey-heading h2 {
  max-width: 18ch;
  margin: 0;
  color: var(--home-ink);
  font-size: clamp(28px, 3.4vw, 48px);
  line-height: 1;
  text-wrap: balance;
}

.feature-journey-compact .feature-journey-heading h2 {
  max-width: 22ch;
  font-size: clamp(2rem, 2.8vw, 2.5rem);
  line-height: 1.25;
  letter-spacing: -0.03em;
}

.feature-journey-heading p:not(.eyebrow) {
  max-width: 58ch;
  margin: 14px 0 0;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  line-height: 1.68;
}

.feature-journey-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.12);
}

.feature-journey-grid article {
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: 170px;
  padding: 18px;
  background: rgba(9, 13, 11, 0.46);
}

.feature-journey-compact .feature-journey-grid article {
  gap: 8px;
  min-height: 150px;
  padding: 15px;
}

.feature-journey-grid span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 900;
}

.feature-journey-grid strong {
  color: var(--home-ink);
  font-size: 18px;
  line-height: 1.15;
}

.feature-journey-grid p {
  margin: 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  line-height: 1.55;
}

.policy-shell {
  padding: clamp(48px, 7vw, 88px) 0 82px;
}

.policy-hero {
  display: grid;
  grid-template-columns: minmax(0, 0.86fr) minmax(340px, 0.58fr);
  gap: clamp(28px, 5vw, 72px);
  align-items: start;
  padding-bottom: clamp(34px, 5vw, 64px);
  border-bottom: 1px solid var(--home-line);
}

.policy-copy {
  display: grid;
  gap: 22px;
}

.policy-copy h1 {
  max-width: 820px;
  margin: 0;
  color: var(--home-ink);
  font-size: clamp(46px, 6vw, 86px);
  line-height: 0.98;
  letter-spacing: 0;
  text-wrap: balance;
}

.policy-copy > p {
  max-width: 760px;
  margin: 0;
  color: var(--home-readable);
  font-size: clamp(17px, 1.9vw, 21px);
  line-height: 1.72;
}

.policy-proof-row {
  max-width: 720px;
}

.policy-stamp {
  position: sticky;
  top: 96px;
  display: grid;
  gap: 18px;
  padding: 24px;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-left: 4px solid var(--home-acid);
  border-radius: 8px;
  background:
    linear-gradient(90deg, rgba(246, 243, 232, 0.04) 1px, transparent 1px),
    linear-gradient(0deg, rgba(246, 243, 232, 0.04) 1px, transparent 1px),
    rgba(15, 22, 18, 0.82);
  background-size: 42px 42px;
  box-shadow: 0 30px 90px rgba(0, 0, 0, 0.28);
}

.policy-stamp-top {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: rgba(246, 243, 232, 0.74);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.policy-stamp strong {
  color: var(--home-ink);
  font-size: clamp(28px, 3.6vw, 48px);
  line-height: 1;
}

.policy-stamp p {
  margin: 0;
  color: var(--home-muted-readable);
  line-height: 1.62;
}

.policy-callout-grid {
  display: grid;
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.14);
}

.policy-callout-grid article {
  display: grid;
  gap: 8px;
  min-height: 118px;
  padding: 16px;
  background: rgba(9, 13, 11, 0.46);
}

.policy-callout-grid span,
.policy-card span {
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

.policy-callout-grid strong {
  color: var(--home-ink);
  font-size: 18px;
}

.policy-callout-grid small {
  color: var(--home-muted-readable);
  line-height: 1.5;
}

.policy-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin-top: clamp(34px, 5vw, 62px);
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.14);
}

.policy-card {
  display: grid;
  align-content: start;
  gap: 16px;
  min-height: 280px;
  padding: clamp(20px, 2.6vw, 28px);
  background:
    linear-gradient(135deg, rgba(246, 243, 232, 0.072), rgba(246, 243, 232, 0.032)),
    rgba(15, 22, 18, 0.78);
}

.policy-card h2 {
  margin: 0;
  color: var(--home-ink);
  font-size: clamp(24px, 3vw, 36px);
  line-height: 1.05;
}

.policy-card ul {
  display: grid;
  gap: 10px;
  margin: 0;
  padding-left: 18px;
}

.policy-card li {
  color: var(--home-muted-readable);
  line-height: 1.62;
}

.policy-next-actions {
  display: grid;
  grid-template-columns: minmax(260px, 0.72fr) minmax(0, 1.28fr);
  gap: 18px;
  align-items: stretch;
  margin-top: clamp(26px, 4vw, 46px);
  padding: 18px;
  border: 1px solid rgba(215, 255, 63, 0.22);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(215, 255, 63, 0.055), rgba(143, 216, 189, 0.028)),
    rgba(15, 22, 18, 0.76);
}

.policy-next-actions h2 {
  max-width: 20ch;
  margin: 0;
  color: var(--home-ink);
  font-size: clamp(28px, 3vw, 42px);
  line-height: 1.05;
  text-wrap: balance;
}

.policy-next-actions p:not(.eyebrow) {
  max-width: 58ch;
  margin: 12px 0 0;
  color: var(--home-readable);
  line-height: 1.68;
}

.policy-next-action-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.13);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.12);
}

.policy-next-action-grid a {
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: 150px;
  padding: 18px;
  background: rgba(9, 13, 11, 0.5);
  color: inherit;
  text-decoration: none;
}

.policy-next-action-grid a:hover {
  background: rgba(215, 255, 63, 0.085);
}

.policy-next-action-grid span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

.policy-next-action-grid strong {
  color: var(--home-ink);
  font-size: 18px;
  line-height: 1.15;
}

.policy-next-action-grid small {
  color: var(--home-muted-readable);
  line-height: 1.55;
}

.policy-boundary {
  margin-top: clamp(34px, 5vw, 62px);
}

.policy-boundary a,
.public-home .home-ops-strip a {
  color: var(--home-acid);
  font-weight: 900;
  text-decoration: none;
}

.policy-boundary a:hover,
.public-home .home-ops-strip a:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.admin-token-panel,
.admin-card {
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(15, 22, 18, 0.78);
}

.admin-token-panel {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto;
  align-items: end;
  column-gap: 0.5rem;
  row-gap: 8px;
  padding: 22px;
  --admin-control-height: 44px;
}

.admin-token-actions {
  display: flex;
  align-items: stretch;
  align-self: end;
  flex-wrap: nowrap;
  gap: 0.5rem;
}

.admin-token-panel small {
  grid-column: 1 / -1;
  line-height: 1.45;
}

.admin-token-panel label,
.admin-number-field {
  display: grid;
  gap: 8px;
  font-size: 13px;
  font-weight: 800;
}

.admin-number-field small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  font-size: 12px;
  font-weight: 800;
}

.admin-limit-hint {
  grid-column: 1 / -1;
  margin-top: -2px;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  font-size: 12px;
  font-weight: 800;
}

.admin-token-panel input,
.admin-number-field input {
  width: 100%;
  height: var(--admin-control-height, 44px);
  padding: 0 12px;
  border: 1px solid rgba(246, 243, 232, 0.18);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.06);
  color: var(--home-ink);
  font: inherit;
}

.admin-token-panel button,
.admin-card button {
  height: var(--admin-control-height, 44px);
  padding: 0 14px;
  border: 1px solid var(--home-acid);
  border-radius: 6px;
  background: var(--home-acid);
  color: #10130f;
  font: inherit;
  font-weight: 900;
  cursor: pointer;
}

.admin-action-controls {
  display: grid;
  grid-template-columns: minmax(96px, 0.38fr) repeat(2, minmax(116px, 1fr));
  align-items: end;
  gap: 0.5rem;
  --admin-control-height: 44px;
}

.admin-action-controls .admin-number-field {
  min-width: 0;
}

.admin-action-controls .button-row {
  grid-column: 2 / span 2;
  align-self: end;
  gap: 0.5rem;
}

.admin-action-controls .button-row button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-width: 0;
  white-space: nowrap;
}

.admin-card .button-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.admin-action-panel {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.12);
}

.action-cell {
  display: grid;
  align-content: start;
  gap: 7px;
  min-height: 104px;
  padding: 13px;
  background: rgba(9, 13, 11, 0.7);
}

.action-cell:only-child {
  grid-column: 1 / -1;
}

.action-cell span {
  color: rgba(198, 221, 192, 0.86);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.action-cell strong {
  color: var(--home-ink);
  font-size: 20px;
  line-height: 1.12;
  font-variant-numeric: tabular-nums;
}

.action-cell small {
  color: rgba(246, 243, 232, 0.74);
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.action-cell.is-ok strong {
  color: var(--home-acid);
}

.action-cell.is-warn strong,
.action-cell.is-error strong {
  color: #ffb86b;
}

.action-cell.is-waiting strong {
  color: var(--home-celadon);
}

.admin-card button[data-admin-action$="dry-run"] {
  border-color: rgba(143, 216, 189, 0.36);
  background: rgba(143, 216, 189, 0.1);
  color: var(--home-ink);
}

.admin-card button[data-admin-action$="process"] {
  border-color: rgba(255, 184, 107, 0.62);
  background: rgba(255, 184, 107, 0.12);
  color: #ffe1bd;
}

.admin-card button[data-admin-action$="dry-run"]:hover,
.admin-card button[data-admin-action$="process"]:hover {
  transform: translateY(-1px);
}

.admin-action-help {
  display: block;
  color: rgba(246, 243, 232, 0.72);
  font-size: 13px;
  line-height: 1.55;
}

.admin-ops-panel pre,
.admin-card pre {
  min-height: 190px;
  max-height: 360px;
  margin: 0;
  padding: 16px;
  box-sizing: border-box;
  overflow: auto;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.24);
  font-size: 13px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.admin-ops-panel pre {
  min-height: 150px;
}

.admin-readiness-panel {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.12);
}

.readiness-cell {
  display: grid;
  align-content: start;
  gap: 7px;
  min-height: 112px;
  padding: 13px;
  background: rgba(9, 13, 11, 0.74);
}

.readiness-cell:only-child {
  grid-column: 1 / -1;
}

.readiness-cell span {
  color: rgba(198, 221, 192, 0.86);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.readiness-cell strong {
  color: var(--home-ink);
  font-size: 18px;
  line-height: 1.15;
}

.readiness-cell small {
  color: rgba(246, 243, 232, 0.74);
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.readiness-cell.is-ok strong {
  color: var(--home-acid);
}

.readiness-cell.is-warn strong,
.readiness-cell.is-error strong {
  color: #ffb86b;
}

.readiness-cell.is-waiting strong {
  color: var(--home-celadon);
}

.admin-inline-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.admin-check-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  justify-content: flex-end;
}

.member-shell {
  padding-bottom: 64px;
}

.member-page {
  color-scheme: dark;
  --surface: rgba(23, 26, 22, 0.84);
  --surface-strong: rgba(246, 243, 232, 0.07);
  --ink: #f6f3e8;
  --muted: rgba(246, 243, 232, 0.78);
  --line: rgba(246, 243, 232, 0.16);
  --accent: #8fd8bd;
  --accent-strong: #d7ff3f;
  --gain: #ff5a3d;
  --loss: #6bb7ff;
  --warn: #c79a3a;
  --shadow: 0 28px 80px rgba(0, 0, 0, 0.28);
  --home-bg: #10130f;
  --home-ink: #f6f3e8;
  --home-panel: #171a16;
  --home-panel-2: #22251f;
  --home-line: rgba(246, 243, 232, 0.16);
  --home-celadon: #8fd8bd;
  --home-acid: #d7ff3f;
  --home-vermilion: #ff5a3d;
  --home-brass: #c79a3a;
  background:
    radial-gradient(circle at 74% 8%, rgba(215, 255, 63, 0.12), transparent 28%),
    radial-gradient(circle at 11% 35%, rgba(143, 216, 189, 0.15), transparent 32%),
    linear-gradient(180deg, #10130f 0%, #171a16 48%, #11140f 100%);
  color: var(--ink);
  overflow-x: clip;
}

.member-page::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: -1;
  background:
    linear-gradient(90deg, rgba(246, 243, 232, 0.045) 1px, transparent 1px),
    linear-gradient(rgba(246, 243, 232, 0.032) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: linear-gradient(180deg, #000 0 72%, transparent 100%);
}

.member-page .topbar {
  border-bottom-color: rgba(246, 243, 232, 0.12);
  background: rgba(16, 19, 15, 0.84);
  color: var(--ink);
}

.member-page .brand-mark {
  background: var(--home-acid);
  color: #10130f;
}

.member-page .top-links {
  color: rgba(246, 243, 232, 0.68);
}

.member-page .top-links a:hover {
  background: rgba(246, 243, 232, 0.08);
  color: var(--ink);
}

.member-page .top-links a[aria-current="page"] {
  border-color: rgba(215, 255, 63, 0.46);
  background: rgba(215, 255, 63, 0.12);
  color: var(--ink);
}

.member-page .top-links .top-auth-link,
.member-page .top-links .top-dashboard-link,
.member-page .top-links .top-admin-link {
  border: 1px solid rgba(246, 243, 232, 0.2);
  color: var(--ink);
}

.member-page .top-links .top-join-link {
  border: 1px solid var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
}

.member-session-gate {
  display: grid;
  align-content: center;
  min-height: min(620px, calc(100svh - 132px));
  padding: clamp(52px, 8vw, 96px) 0;
}

.member-session-gate h1 {
  max-width: 780px;
  margin: 0;
  color: var(--ink);
  font-size: clamp(44px, 6.2vw, 82px);
  line-height: 0.98;
  text-wrap: balance;
}

.member-session-gate p:not(.eyebrow) {
  max-width: 620px;
  margin: 18px 0 0;
  color: var(--muted);
  font-size: clamp(16px, 2vw, 20px);
  line-height: 1.62;
}

.member-session-meter {
  position: relative;
  width: min(520px, 100%);
  height: 8px;
  margin-top: 34px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-radius: 999px;
  background: rgba(246, 243, 232, 0.08);
}

.member-session-meter span {
  position: absolute;
  inset: 0 auto 0 0;
  width: 42%;
  border-radius: inherit;
  background: var(--home-acid);
  animation: memberSessionSweep 1.4s ease-in-out infinite;
}

.member-page:not(.is-member-checking) .member-session-gate {
  display: none;
}

.member-page.is-member-checking .member-auth-landing,
.member-page.is-member-checking .member-workspace {
  display: none;
}

@keyframes memberSessionSweep {
  0% {
    transform: translateX(-110%);
  }

  50% {
    transform: translateX(80%);
  }

  100% {
    transform: translateX(240%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .member-session-meter span {
    animation: none;
    width: 100%;
  }
}

.member-auth-landing {
  display: grid;
  grid-template-columns: minmax(0, 0.96fr) minmax(360px, 0.58fr);
  gap: clamp(28px, 5vw, 72px);
  align-items: start;
  padding: clamp(56px, 8vw, 96px) 0 80px;
}

.member-auth-copy {
  display: grid;
  gap: 22px;
  max-width: 760px;
}

.member-auth-copy h1 {
  max-width: 720px;
  margin: 0;
  color: var(--ink);
  font-size: clamp(48px, 7vw, 88px);
  line-height: 0.96;
  letter-spacing: 0;
  text-wrap: balance;
}

.member-auth-lead {
  max-width: 620px;
  margin: 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-size: clamp(17px, 2vw, 21px);
  line-height: 1.72;
  text-wrap: pretty;
}

.member-auth-points {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.12);
}

.member-auth-points article {
  display: grid;
  gap: 10px;
  min-height: 156px;
  padding: 18px;
  background: rgba(15, 22, 18, 0.74);
}

.member-auth-points span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 800;
}

.member-auth-points strong {
  font-size: 17px;
}

.member-auth-points small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-size: 13px;
  line-height: 1.55;
}

.auth-panel {
  position: sticky;
  top: 92px;
  box-shadow: 0 28px 70px rgba(20, 31, 28, 0.12);
}

.auth-heading {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line);
}

.auth-form {
  gap: 14px;
  margin-top: 20px;
}

.auth-form input {
  height: 46px;
  padding: 0 13px;
}

.member-page .auth-form input {
  height: 46px;
}

.button-row.auth-button-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  align-items: center;
}

.member-page .auth-form .auth-button-row button {
  height: 46px;
  border-radius: 8px;
}

.member-page .auth-form .auth-button-row [data-auth-action="signin"] {
  border-color: var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
}

.member-page .auth-form .auth-button-row [data-auth-action="signin"]:hover {
  background: #ecff72;
}

.member-page .auth-form .auth-button-row [data-auth-action="signup"] {
  border-color: rgba(246, 243, 232, 0.24);
  background: rgba(246, 243, 232, 0.055);
  color: var(--ink);
}

.member-page .auth-form .auth-button-row [data-auth-action="signup"]:hover {
  border-color: rgba(215, 255, 63, 0.38);
  background: rgba(246, 243, 232, 0.095);
}

.auth-form-note {
  margin: -8px 0 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-size: 12px;
  line-height: 1.45;
  letter-spacing: -0.02em;
  opacity: 0.6;
}

.auth-status {
  min-height: 46px;
  padding: 12px 14px;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.045);
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  letter-spacing: -0.02em;
}

.member-workspace {
  display: grid;
  gap: 16px;
  padding-top: 26px;
}

.member-summary-band {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 0.44fr) minmax(180px, 0.28fr);
  align-items: stretch;
}

.member-workspace-lede {
  max-width: 620px;
  margin: 12px 0 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-size: 14px;
  line-height: 1.55;
}

.member-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.member-overview-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.12);
}

.member-overview-strip article {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 15px;
  background: rgba(15, 22, 18, 0.78);
}

.member-overview-strip span,
.member-form-block > strong {
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.member-form-hint {
  display: block;
  margin-top: 6px;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-size: 12px;
  line-height: 1.45;
}

.member-request-hint {
  margin: 10px 0 0;
}

.member-overview-strip strong {
  color: var(--ink);
  font-family: var(--app-font-stack);
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.member-overview-strip small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
}

.member-home-state-note {
  margin: 0;
  padding: 11px 14px;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.04);
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.82));
  font-size: 13px;
  line-height: 1.55;
}

.member-home-panel {
  display: grid;
  gap: 14px;
}

.member-home-panel > .panel-heading {
  align-items: flex-end;
  justify-content: space-between;
}

.member-home-panel > .panel-heading > div {
  min-width: 0;
}

.member-home-panel > .panel-heading .status-pill {
  flex: 0 0 auto;
}

.member-primary-action {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  padding: 18px;
  border: 1px solid rgba(215, 255, 63, 0.22);
  border-left: 3px solid var(--home-acid);
  border-radius: 8px;
  background: linear-gradient(90deg, rgba(215, 255, 63, 0.1), rgba(246, 243, 232, 0.035));
}

.member-primary-action div {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.member-primary-action span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0;
}

.member-primary-action strong {
  color: var(--ink);
  font-size: clamp(22px, 2vw, 28px);
  line-height: 1.15;
}

.member-primary-action small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  line-height: 1.55;
}

.member-primary-action .home-primary-link {
  min-width: 154px;
  border: 1px solid rgba(215, 255, 63, 0.92);
  background: var(--home-acid);
  color: #10130f;
  cursor: pointer;
  font-weight: 950;
  text-shadow: none;
  box-shadow: 0 12px 30px rgba(215, 255, 63, 0.14);
}

.member-primary-action .home-primary-link:hover {
  border-color: #e7ff66;
  background: #e7ff66;
  color: #10130f;
}

.member-home-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
}

.member-home-card {
  display: grid;
  grid-template-rows: auto auto minmax(44px, 1fr) auto;
  gap: 10px;
  min-height: 168px;
  padding: 16px;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-left: 3px solid rgba(215, 255, 63, 0.68);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.045);
}

.member-home-card span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  justify-self: start;
  min-width: 32px;
  height: 22px;
  border: 1px solid rgba(220, 252, 19, 0.42);
  border-radius: 999px;
  background: rgba(220, 252, 19, 0.12);
  box-shadow: inset 0 0 0 1px rgba(220, 252, 19, 0.1);
  color: #dcfc13;
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 950;
  letter-spacing: -0.02em;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.member-home-card strong {
  color: var(--ink);
  font-size: 18px;
}

.member-home-card small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  line-height: 1.55;
}

.member-home-card .ghost-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  justify-self: start;
  align-self: end;
  min-height: 38px;
  text-decoration: none;
}

.member-paper-card {
  border-left-color: var(--home-celadon);
}

.paper-simulation-flow {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 0 0 12px;
  padding: 0;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.12);
  list-style: none;
}

.paper-simulation-flow li {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 12px;
  background: rgba(15, 22, 18, 0.78);
}

.paper-simulation-flow span {
  color: var(--home-celadon);
  font-size: 11px;
  font-weight: 900;
}

.paper-simulation-flow strong {
  color: var(--ink);
  font-size: 16px;
}

.paper-simulation-flow small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  line-height: 1.4;
}

.paper-learning-note {
  display: grid;
  gap: 6px;
  padding: 14px;
  border: 1px solid rgba(143, 216, 189, 0.22);
  border-left: 3px solid var(--home-celadon);
  border-radius: 8px;
  background: rgba(143, 216, 189, 0.07);
}

.paper-learning-note span {
  color: var(--home-celadon);
  font-size: 11px;
  font-weight: 900;
}

.paper-learning-note strong {
  color: var(--ink);
  font-size: 18px;
}

.paper-learning-note small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  line-height: 1.45;
}

.paper-learning-buckets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.paper-learning-buckets span {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 4px 8px;
  border: 1px solid rgba(143, 216, 189, 0.2);
  border-radius: 999px;
  color: rgba(246, 243, 232, 0.84);
  background: rgba(246, 243, 232, 0.06);
  font-size: 11px;
  font-weight: 800;
  line-height: 1.2;
}

.paper-event-section {
  display: grid;
  gap: 10px;
}

.paper-event-section-heading {
  display: grid;
  gap: 4px;
  padding-top: 6px;
}

.paper-event-section-heading strong {
  color: var(--ink);
  font-size: 16px;
}

.paper-event-section-heading small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
}

.member-home-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid rgba(246, 243, 232, 0.08);
}

.member-home-links a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 800;
  text-decoration: none;
  transition: border-color 160ms ease, background 160ms ease, color 160ms ease;
}

.member-admin-link,
.member-report-link {
  border: 1px solid var(--home-celadon);
  background: rgba(143, 216, 189, 0.16);
  color: var(--ink);
}

.member-home-links a:hover {
  border-color: var(--home-acid);
  background: rgba(215, 255, 63, 0.13);
  color: var(--home-acid);
}

.member-panel {
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.auth-panel.member-panel {
  border-color: rgba(143, 216, 189, 0.28);
  background:
    linear-gradient(145deg, rgba(246, 243, 232, 0.1), rgba(143, 216, 189, 0.055)),
    var(--surface);
}

.member-panel h2 {
  margin: 4px 0 0;
  font-size: 20px;
}

.panel-copy {
  max-width: 58ch;
  margin: 6px 0 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-size: 13px;
  line-height: 1.45;
}

.member-form {
  --member-form-control-height: 44px;
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.member-form-stack {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}

.member-form-block {
  min-width: 0;
  padding: 12px;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.035);
}

.member-form-block .member-form {
  margin-top: 10px;
}

.member-form label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
}

.member-form input,
.member-form select {
  min-width: 0;
  width: 100%;
  height: var(--member-form-control-height);
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  line-height: 1;
  box-sizing: border-box;
}

.member-page .member-form input,
.member-page .member-form select,
.member-page .member-action-item input {
  background: rgba(246, 243, 232, 0.06);
  color: var(--ink);
}

.member-page .member-form select {
  color-scheme: dark;
}

.member-page .member-form select option,
.member-page .member-form select optgroup {
  background: #121812;
  color: var(--ink);
}

.member-page .member-form select option:checked {
  background: #d2ff2f;
  color: #10140f;
}

.member-page .member-form input::placeholder,
.member-page .member-action-item input::placeholder {
  color: rgba(246, 243, 232, 0.42);
}

.member-form input:disabled,
.member-form select:disabled,
.member-form button:disabled,
.member-action-item input:disabled,
.member-action-item button:disabled,
.watchlist-rename-form input:disabled,
.watchlist-rename-form button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.member-form.is-busy button[type="submit"],
.member-action-item button[aria-busy="true"],
.watchlist-rename-form button[aria-busy="true"] {
  opacity: 0.78;
}

.password-row {
  position: relative;
  display: block;
}

.auth-form .password-row {
  position: relative;
}

.member-form .password-row input {
  min-width: 0;
}

.auth-form .password-row input {
  padding-right: 118px;
}

.password-toggle {
  height: 40px;
}

.member-page .auth-form .password-toggle {
  position: absolute;
  top: 50%;
  right: 12px;
  width: auto;
  min-width: 0;
  height: auto;
  min-height: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  color: rgba(246, 243, 232, 0.64);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: -0.02em;
  line-height: 1;
  transform: translateY(-50%);
}

.member-page .auth-form .password-toggle:hover {
  background: transparent;
  color: var(--home-acid);
}

.compact-form {
  grid-template-columns: minmax(0, 1fr) auto;
}

.member-page #portfolioForm {
  display: flex;
  align-items: stretch;
  gap: 0.5rem;
}

.member-page #portfolioForm input {
  flex: 1 1 auto;
  min-height: var(--member-form-control-height);
}

.member-page #portfolioForm button {
  flex: 0 0 96px;
  align-self: stretch;
  min-height: var(--member-form-control-height);
}

.member-page #watchlistForm {
  display: flex;
  align-items: stretch;
  gap: 0.5rem;
}

.member-page #watchlistForm input {
  flex: 1 1 auto;
  min-height: var(--member-form-control-height);
}

.member-page #watchlistForm button {
  flex: 0 0 128px;
  align-self: stretch;
  min-height: var(--member-form-control-height);
}

.member-page #watchlistItemForm {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: stretch;
  gap: 0.75rem;
}

.member-page #watchlistItemForm select,
.member-page #watchlistItemForm input,
.member-page #watchlistItemForm button {
  height: var(--member-form-control-height);
}

.member-page #watchlistItemForm button {
  width: 100%;
}

.compact-form input:nth-last-child(2) {
  grid-column: auto;
}

.trade-form {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: center;
}

.trade-form button {
  grid-column: span 4 / span 4;
  width: 100%;
}

.target-form {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: center;
}

.target-form input[name="memo"] {
  grid-column: span 3 / span 3;
}

.target-form button {
  grid-column: span 1 / span 1;
  align-self: center;
  height: var(--member-form-control-height);
  width: 100%;
}

.analysis-request-form {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: center;
}

.analysis-request-form #analysisWatchlistTickerSelect {
  grid-column: span 1 / span 1;
}

.analysis-request-form input[name="ticker"] {
  grid-column: span 2 / span 2;
}

.analysis-request-form input[name="requested_trade_date"] {
  grid-column: span 1 / span 1;
}

.analysis-request-form input[name="reason"] {
  grid-column: span 3 / span 3;
}

.analysis-request-form button {
  grid-column: span 1 / span 1;
  align-self: center;
  height: var(--member-form-control-height);
  width: 100%;
}

.button-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.member-form button,
.ghost-button {
  height: var(--member-form-control-height, 40px);
  padding: 0 14px;
  border: 0;
  border-radius: 6px;
  background: var(--ink);
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font: inherit;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  box-sizing: border-box;
}

.member-page .member-form button {
  border: 1px solid var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
}

.member-page .member-form button:hover {
  background: #ecff72;
}

.member-form button.auth-suggested {
  background: var(--accent);
}

.member-page .member-form button.auth-suggested {
  border-color: var(--home-celadon);
  background: var(--home-celadon);
  color: #10130f;
}

.ghost-button {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink);
}

.member-page .ghost-button {
  border-color: rgba(246, 243, 232, 0.18);
  background: rgba(246, 243, 232, 0.06);
  color: var(--ink);
}

.member-page .ghost-button:hover {
  border-color: rgba(215, 255, 63, 0.42);
  background: rgba(246, 243, 232, 0.1);
}

.auth-panel.is-signed-in .member-form {
  display: none;
}

.auth-panel:not(.is-signed-in) #signOutButton {
  display: none;
}

.member-signed-in {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-strong);
}

.member-signed-in strong {
  font-size: 18px;
  overflow-wrap: anywhere;
}

.member-signed-in small {
  color: var(--muted);
  line-height: 1.5;
}

.member-signed-in .ghost-button {
  justify-self: start;
  margin-top: 2px;
}

.member-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.member-page #analysisRequestList {
  margin-top: 8px;
}

.member-item {
  display: grid;
  gap: 6px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-strong);
}

.member-item strong {
  font-size: 15px;
}

.member-card-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
}

.member-card-header > div {
  min-width: 0;
}

.member-card-header strong,
.member-card-header small {
  display: block;
}

.member-card-header small {
  margin-top: 4px;
  line-height: 1.4;
}

.member-metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 4px;
}

.member-metric-grid div {
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.045);
}

.member-metric-grid small,
.member-metric-grid span {
  display: block;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.35;
}

.member-metric-grid strong {
  display: block;
  margin: 4px 0 0;
  color: var(--ink);
  font-family: var(--app-font-stack);
  font-size: 15px;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.analysis-queue-overview {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid rgba(143, 216, 189, 0.22);
  border-left: 4px solid var(--home-celadon);
  border-radius: 8px;
  background: rgba(143, 216, 189, 0.075);
}

.analysis-queue-meters {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.analysis-queue-meters div {
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.06);
}

.analysis-queue-meters small,
.analysis-queue-meters span {
  display: block;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.35;
}

.analysis-queue-meters strong {
  display: block;
  margin: 3px 0;
  color: var(--ink);
  font-family: var(--app-font-stack);
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}

.analysis-queue-note {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.analysis-request-item {
  gap: 10px;
  background: rgba(246, 243, 232, 0.055);
}

.analysis-request-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
}

.analysis-request-header > div {
  min-width: 0;
}

.analysis-request-header strong,
.analysis-request-header small {
  display: block;
}

.analysis-request-header small {
  margin-top: 4px;
  line-height: 1.4;
}

.analysis-request-header .status-pill {
  justify-self: end;
  white-space: nowrap;
}

.analysis-request-hint {
  margin: 0;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.5;
}

.analysis-request-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 2px;
}

.member-inline-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  height: auto;
  padding: 8px 12px;
  text-decoration: none;
}

.member-item small,
.member-empty {
  color: var(--muted);
  font-size: 13px;
}

.member-sublist {
  display: grid;
  gap: 6px;
  margin: 10px 0 0;
  padding: 10px 0 0;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
  list-style: none;
  overflow-wrap: anywhere;
}

.member-sublist-label {
  color: var(--ink);
  font-weight: 800;
}

.member-action-list {
  display: grid;
  gap: 8px;
  margin: 10px 0 0;
  padding: 10px 0 0;
  border-top: 1px solid var(--line);
}

.watchlist-rename-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  margin-top: 6px;
}

.watchlist-rename-form label {
  display: grid;
  gap: 5px;
  min-width: 0;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.watchlist-rename-form input {
  min-width: 0;
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.06);
  color: var(--ink);
  font: inherit;
}

.watchlist-rename-form button {
  height: 36px;
  padding: 0 12px;
}

.member-action-item {
  display: grid;
  grid-template-columns: minmax(90px, 1fr) minmax(96px, 0.8fr) minmax(120px, 1fr) auto auto;
  gap: 8px;
  align-items: center;
}

.member-action-item strong,
.member-action-item a,
.member-action-item small {
  min-width: 0;
}

.member-action-item a {
  color: var(--home-acid);
  font-weight: 900;
}

.member-action-item small {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
}

.member-action-item input {
  min-width: 0;
  height: 34px;
  padding: 0 9px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
}

.member-action-item button {
  height: 34px;
  padding: 0 10px;
}

.member-action-item .danger-button {
  border: 1px solid var(--gain);
  background: rgba(255, 90, 61, 0.08);
  color: var(--gain);
}

.member-status-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.member-status-strip .status-pill {
  min-height: 24px;
  font-size: 12px;
}

.analysis-status-queued,
.analysis-status-running {
  border-color: rgba(199, 154, 58, 0.72);
  color: var(--warn);
}

.analysis-status-completed {
  border-color: rgba(143, 216, 189, 0.64);
  color: var(--home-celadon);
}

.analysis-status-failed {
  border-color: var(--gain);
  color: var(--gain);
}

.member-empty {
  padding: 12px;
  border: 1px dashed var(--line);
  border-radius: 8px;
}

.member-empty-action {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px dashed rgba(215, 255, 63, 0.34);
  border-radius: 8px;
  background: rgba(215, 255, 63, 0.045);
}

.member-empty-action strong {
  color: var(--ink);
  font-size: 15px;
}

.member-empty-action small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  line-height: 1.55;
}

.member-empty-action .ghost-button {
  justify-self: start;
  letter-spacing: -0.02em;
}

.member-error {
  color: var(--gain);
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
  .workspace,
  .home-search-band {
    grid-template-columns: minmax(0, 1fr);
  }

  .data-source-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .home-hero,
  .home-section-heading,
  .home-analysis-zone,
  .home-ops-strip,
  .feature-hero,
  .feature-journey,
  .policy-hero,
  .policy-next-actions,
  .admin-hero,
  .member-auth-landing,
  .member-summary-band {
    grid-template-columns: minmax(0, 1fr);
  }

  .auth-panel,
  .feature-diagram,
  .policy-stamp {
    position: static;
  }

  .home-hero {
    min-height: 0;
    gap: 32px;
    padding-top: 28px;
  }

  .home-hero-copy {
    max-width: none;
  }

  .home-hero-visual {
    min-height: 440px;
  }

  .home-section-heading .home-primary-link {
    justify-self: start;
  }

  .home-section-copy {
    position: static;
  }

  .home-analysis-grid {
    grid-template-columns: 1fr 1fr;
  }

  .member-auth-points {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .summary-band {
    display: grid;
  }

  .decision-box {
    min-width: 0;
  }

  .lens-grid,
  .outcome-grid,
  .report-grid {
    grid-template-columns: 1fr 1fr;
  }

  .analysis-feed-grid,
  .outcome-feed-grid,
  .analysis-summary-grid,
  .analysis-track-grid,
  .analysis-reader-guide-grid,
  .analysis-pipeline-strip,
  .policy-card-grid,
  .feature-card-grid,
  .feature-index-grid,
  .home-service-grid,
  .admin-grid {
    grid-template-columns: 1fr 1fr;
  }

  .member-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .member-overview-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .member-home-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .trade-form,
  .target-form {
    grid-template-columns: 1fr 1fr;
  }

  .target-form input[name="memo"] {
    grid-column: auto;
  }

  .trade-form button {
    grid-column: auto;
  }

  .member-action-item {
    grid-template-columns: 1fr 1fr;
  }

  .analysis-queue-meters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .paper-simulation-flow {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .member-metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .member-action-item strong,
  .member-action-item a,
  .member-action-item small,
  .member-action-item input {
    grid-column: 1 / -1;
  }
}

@media (max-width: 640px) {
  .topbar {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
    padding: 10px 12px;
  }

  .brand {
    max-width: 100%;
  }

  .top-links {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
    gap: 5px;
  }

  .top-links a {
    display: grid;
    min-height: 34px;
    place-items: center;
    padding: 6px 5px;
    min-width: 0;
    font-size: 12px;
    text-align: center;
    white-space: normal;
  }

  .ticker-search {
    width: 100%;
  }

  .ticker-search input,
  .ticker-search button {
    height: 36px;
  }

  .ticker-search button {
    min-width: 58px;
    padding: 0 10px;
  }

  .chart-toolbar,
  .chart-tools,
  .chart-heading-meta {
    align-items: flex-start;
    flex-direction: column;
  }

  .chart-tabs,
  .chart-tool-group {
    width: 100%;
  }

  .chart-tab,
  .chart-tool-button,
  .chart-setting-field {
    flex: 1 1 auto;
    justify-content: center;
  }

  .chart-setting-field input {
    width: 48px;
  }

  .data-source-strip,
  .analysis-panel .data-source-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .shell {
    width: calc(100% - 24px);
    max-width: 1280px;
    padding-top: 18px;
  }

  .home-shell {
    width: calc(100% - 24px);
    max-width: 1440px;
    padding-top: 14px;
  }

  .feature-shell,
  .admin-shell {
    padding-top: 36px;
  }

  .feature-copy h1,
  .policy-copy h1,
  .admin-hero h1 {
    max-width: 100%;
    font-size: 36px;
    line-height: 1.04;
    overflow-wrap: anywhere;
    word-break: break-word;
    text-wrap: balance;
  }

  .member-auth-copy h1 {
    max-width: 100%;
    font-size: 38px;
    line-height: 1.02;
    overflow-wrap: anywhere;
    word-break: break-word;
    text-wrap: balance;
  }

  .feature-copy > p,
  .policy-copy > p,
  .admin-hero > div > p,
  .member-auth-lead {
    max-width: 100%;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .feature-diagram {
    width: 100%;
    min-width: 0;
    min-height: auto;
    padding: 18px;
    overflow: hidden;
  }

  .feature-step-track {
    grid-template-columns: minmax(0, 1fr);
  }

  .feature-signal-card {
    padding: 18px;
  }

  .feature-signal-card strong {
    font-size: 34px;
    overflow-wrap: anywhere;
  }

  .home-hero {
    gap: 22px;
    padding: 22px 0 28px;
  }

  .home-hero h1 {
    font-size: 40px;
  }

  .home-lede {
    margin-bottom: 18px;
    font-size: 15px;
    line-height: 1.55;
  }

  .home-member-preview ul,
  .home-trust-panel {
    grid-template-columns: minmax(0, 1fr);
  }

  .home-trust-panel div {
    border-right: 0;
    border-bottom: 1px solid rgba(246, 243, 232, 0.12);
  }

  .home-trust-panel div:last-child {
    border-bottom: 0;
  }

  .home-hero-search {
    align-items: stretch;
    flex-direction: column;
    padding: 8px;
  }

  .home-proof-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    margin-top: 20px;
    padding-top: 14px;
  }

  .home-proof-row dt {
    font-size: 10px;
  }

  .home-proof-row dd {
    font-size: 12px;
    overflow-wrap: anywhere;
  }

  .home-console-grid,
  .home-pipeline {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .member-auth-points {
    grid-template-columns: minmax(0, 1fr);
  }

  .home-hero-visual {
    min-height: 130px;
  }

  .home-radar {
    right: -70px;
    width: 280px;
  }

  .home-console,
  .home-pipeline {
    left: 16px;
    right: 16px;
  }

  .home-console {
    top: 12px;
    bottom: auto;
  }

  .home-console-top {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .home-console-top span:first-child {
    grid-column: auto;
  }

  .home-console-top span:last-child {
    white-space: nowrap;
  }

  .home-pipeline {
    display: none;
  }

  .home-console-focus {
    padding: 10px 16px 12px;
  }

  .home-console-focus span,
  .home-console-focus small {
    font-size: 11px;
  }

  .home-sparkline {
    display: none;
  }

  .home-console-grid {
    display: none;
  }

  .home-console-grid div,
  .home-pipeline span {
    border-bottom: 1px solid rgba(243, 245, 239, 0.12);
  }

  .home-console-grid div:nth-child(2n),
  .home-pipeline span:nth-child(2n) {
    border-right: 0;
  }

  .home-console-grid div:nth-last-child(-n + 2),
  .home-pipeline span:nth-last-child(-n + 2) {
    border-bottom: 0;
  }

  .home-console-focus strong {
    font-size: 18px;
  }

  .home-console-focus small {
    display: none;
  }

  .home-band,
  .home-analysis-zone {
    padding: 22px 0 34px;
  }

  .home-section-copy h2 {
    font-size: 28px;
  }

  .home-flow-list article {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .metric-grid,
  .simulation-grid,
  .lens-grid,
  .outcome-grid,
  .report-grid,
  .home-analysis-grid,
  .analysis-feed-grid,
  .outcome-feed-grid,
  .analysis-summary-grid,
  .analysis-track-grid,
  .analysis-reader-guide-grid,
  .analysis-pipeline-strip,
  .policy-card-grid,
  .policy-callout-grid,
  .policy-next-action-grid,
  .feature-card-grid,
  .feature-index-grid,
  .feature-journey-grid,
  .feature-step-track,
  .admin-grid,
  .member-grid,
  .compact-form,
  .trade-form,
  .target-form,
  .analysis-request-form {
    grid-template-columns: minmax(0, 1fr);
  }

  .chart-wrap {
    height: min(72vw, 340px);
    min-height: 260px;
    aspect-ratio: auto;
  }

  .member-action-item {
    grid-template-columns: minmax(0, 1fr);
  }

  .watchlist-rename-form {
    grid-template-columns: minmax(0, 1fr);
  }

  .member-overview-strip,
  .member-home-grid,
  .paper-simulation-flow,
  .member-metric-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .member-primary-action {
    align-items: stretch;
    grid-template-columns: minmax(0, 1fr);
  }

  .member-primary-action .home-primary-link {
    width: 100%;
  }

  .analysis-request-header {
    grid-template-columns: minmax(0, 1fr);
  }

  .analysis-request-header .status-pill {
    justify-self: start;
  }

  .member-action-item strong,
  .member-action-item a,
  .member-action-item small,
  .member-action-item input {
    grid-column: auto;
  }

  .analysis-request-form #analysisWatchlistTickerSelect,
  .analysis-request-form input[name="ticker"],
  .analysis-request-form input[name="requested_trade_date"],
  .analysis-request-form input[name="reason"],
  .analysis-request-form button {
    grid-column: auto;
  }
}

.public-home {
  color-scheme: dark;
  accent-color: var(--home-acid);
  --home-bg: #10130f;
  --home-ink: #f6f3e8;
  --home-paper: #fbfaf4;
  --home-panel: #171a16;
  --home-panel-2: #22251f;
  --home-line: rgba(246, 243, 232, 0.16);
  --home-muted: #a6ada2;
  --home-readable: rgba(246, 243, 232, 0.84);
  --home-muted-readable: rgba(246, 243, 232, 0.8);
  --home-celadon: #8fd8bd;
  --home-acid: #d7ff3f;
  --home-vermilion: #ff5a3d;
  --home-brass: #c79a3a;
  background:
    radial-gradient(circle at 72% 8%, rgba(215, 255, 63, 0.14), transparent 28%),
    radial-gradient(circle at 12% 34%, rgba(143, 216, 189, 0.13), transparent 31%),
    linear-gradient(180deg, #10130f 0%, #171a16 48%, #11140f 100%);
  color: var(--home-ink);
  letter-spacing: -0.03em;
  overflow-x: clip;
}

.public-home::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: -1;
  background:
    linear-gradient(90deg, rgba(246, 243, 232, 0.045) 1px, transparent 1px),
    linear-gradient(rgba(246, 243, 232, 0.032) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: linear-gradient(180deg, #000 0 72%, transparent 100%);
}

.public-home .topbar {
  border-bottom-color: rgba(246, 243, 232, 0.12);
  background: rgba(16, 19, 15, 0.84);
  color: var(--home-ink);
}

.public-home .brand-mark {
  background: var(--home-acid);
  color: #10130f;
}

.public-home .top-links {
  color: rgba(246, 243, 232, 0.68);
  gap: 10px;
}

.public-home .top-links a:hover {
  background: rgba(246, 243, 232, 0.08);
  color: var(--home-ink);
}

.public-home .top-links a[aria-current="page"] {
  border-color: rgba(215, 255, 63, 0.46);
  background: rgba(215, 255, 63, 0.12);
  color: var(--home-ink);
}

.public-home .top-links .top-dashboard-link,
.public-home .top-links .top-admin-link {
  border-color: rgba(246, 243, 232, 0.2);
  color: var(--home-ink);
}

.public-home .top-links .top-auth-link {
  padding-inline: 4px;
  border-color: transparent;
  background: transparent;
  color: rgba(246, 243, 232, 0.62);
}

.public-home .top-links .top-auth-link:hover {
  background: transparent;
  color: var(--home-ink);
}

.public-home .top-links .top-join-link {
  padding-inline: 16px;
  border-color: var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
  box-shadow: 0 0 18px rgba(220, 252, 19, 0.22);
}

.public-home .top-links .top-join-link:hover {
  background: #ecff72;
  color: #10130f;
  box-shadow: 0 0 24px rgba(220, 252, 19, 0.32);
}

.home-shell-art {
  width: min(100% - clamp(24px, 5vw, 72px), 1440px);
  padding: 0 0 72px;
}

.home-hero-artboard {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 0.82fr) minmax(0, 0.9fr);
  gap: clamp(28px, 5vw, 72px);
  align-items: start;
  min-height: min(720px, calc(100svh - 88px));
  padding: clamp(36px, 6vh, 72px) 0 clamp(24px, 3vw, 42px);
  border-bottom: 1px solid var(--home-line);
}

.home-hero-artboard > * {
  min-width: 0;
}

.home-hero-artboard::after {
  content: "TA-KR / SIGNAL MAP";
  position: absolute;
  left: 0;
  bottom: 16px;
  color: rgba(246, 243, 232, 0.28);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.home-hero-content {
  max-width: 760px;
}

.home-kicker {
  margin: 0 0 18px;
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.home-hero-artboard h1 {
  max-width: 640px;
  margin-bottom: 18px;
  color: var(--home-ink);
  font-size: clamp(42px, 5vw, 72px);
  font-weight: 900;
  line-height: 0.98;
  letter-spacing: 0;
  text-wrap: balance;
  word-break: keep-all;
}

.home-hero-artboard .home-lede {
  max-width: 670px;
  margin-bottom: 22px;
  color: rgba(246, 243, 232, 0.76);
  font-size: clamp(15px, 1.25vw, 18px);
  line-height: 1.62;
}

.home-command-search {
  width: min(100%, 650px);
  padding: 7px;
  border: 1px solid rgba(246, 243, 232, 0.18);
  border-radius: 6px;
  background: rgba(23, 26, 22, 0.84);
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.28);
  transition: border-color 180ms ease, box-shadow 180ms ease, background 180ms ease;
}

.home-command-search:hover,
.home-command-search:focus-within {
  border-color: rgba(220, 252, 19, 0.68);
  background: rgba(24, 29, 20, 0.94);
  box-shadow: 0 0 10px rgba(220, 252, 19, 0.3), 0 28px 80px rgba(0, 0, 0, 0.32);
}

.home-command-search input {
  border-color: rgba(246, 243, 232, 0.16);
  background: rgba(251, 250, 244, 0.06);
  color: var(--home-ink);
}

.home-command-search input::placeholder {
  color: rgba(246, 243, 232, 0.48);
}

.home-command-search button,
.public-home .home-primary-link {
  border-color: var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
}

.public-home .home-secondary-link {
  border-color: rgba(246, 243, 232, 0.22);
  background: rgba(246, 243, 232, 0.06);
  color: var(--home-ink);
}

.home-action-row {
  margin-top: 14px;
}

.home-sample-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 15px;
  border: 1px solid rgba(246, 243, 232, 0.22);
  border-radius: 999px;
  background: rgba(246, 243, 232, 0.075);
  color: rgba(246, 243, 232, 0.88);
  font-size: 14px;
  font-weight: 850;
  letter-spacing: -0.03em;
  transition: transform 180ms ease, border-color 180ms ease, background 180ms ease, box-shadow 180ms ease;
}

.home-sample-pill:hover {
  transform: translateY(-1px);
  border-color: rgba(220, 252, 19, 0.48);
  background: rgba(246, 243, 232, 0.12);
  box-shadow: 0 0 14px rgba(220, 252, 19, 0.12);
}

.home-sample-pill:active {
  transform: translateY(1px);
}

.home-member-preview {
  display: grid;
  gap: 10px;
  width: min(100%, 650px);
  margin-top: 12px;
  padding: 12px;
  border: 1px solid rgba(143, 216, 189, 0.22);
  border-left: 3px solid var(--home-celadon);
  border-radius: 8px;
  background: rgba(143, 216, 189, 0.07);
}

.home-member-preview > strong {
  color: var(--home-ink);
  font-size: 14px;
}

.home-member-preview ul {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.1);
}

.home-member-preview li {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 10px 11px;
  background: rgba(15, 22, 18, 0.74);
}

.home-member-preview span {
  color: var(--home-acid);
  font-size: 12px;
  font-weight: 900;
}

.home-member-preview small {
  color: var(--home-readable);
  font-size: 12px;
  line-height: 1.45;
}

.home-trust-panel {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  width: min(100%, 650px);
  margin-top: 18px;
  border: 1px solid rgba(246, 243, 232, 0.16);
  background:
    linear-gradient(90deg, rgba(215, 255, 63, 0.08), transparent 28%),
    rgba(251, 250, 244, 0.045);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.home-trust-panel div {
  min-width: 0;
  padding: 14px 16px;
  border-right: 1px solid rgba(246, 243, 232, 0.12);
}

.home-trust-panel div:last-child {
  border-right: 0;
}

.home-trust-panel span {
  display: block;
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.home-trust-panel strong {
  display: block;
  margin-top: 7px;
  color: var(--home-ink);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.34;
  word-break: keep-all;
}

.home-trust-panel + .home-command-search {
  margin-top: 18px;
}

.home-signal-strip {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  max-width: 710px;
  margin-top: 34px;
  padding-top: 0;
  border-top: 0;
}

.home-signal-strip div {
  padding: 14px 0;
  border-top: 1px solid rgba(246, 243, 232, 0.16);
}

.home-signal-strip dt {
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
}

.home-signal-strip dd {
  color: var(--home-ink);
}

.home-start-strip {
  display: grid;
  grid-template-columns: minmax(0, 0.62fr) minmax(300px, 0.38fr);
  gap: 16px;
  align-items: stretch;
  padding: 18px 0;
  border-bottom: 1px solid var(--home-line);
}

.home-start-strip .home-trust-panel {
  width: 100%;
  margin-top: 0;
}

.home-start-strip .home-signal-strip {
  width: 100%;
  max-width: none;
  margin: 0;
  padding: 0 16px;
  border: 1px solid rgba(246, 243, 232, 0.16);
  background: rgba(246, 243, 232, 0.045);
}

.home-start-strip .home-signal-strip div {
  display: grid;
  align-content: center;
  padding: 12px 0;
  border-top: 0;
}

.home-signal-art {
  position: relative;
  max-width: 100%;
  margin-top: clamp(8px, 2vh, 28px);
  min-height: clamp(360px, 38vw, 560px);
  aspect-ratio: 1.06 / 1;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  background:
    linear-gradient(90deg, rgba(215, 255, 63, 0.1) 1px, transparent 1px),
    linear-gradient(rgba(143, 216, 189, 0.08) 1px, transparent 1px),
    radial-gradient(circle at 72% 28%, rgba(215, 255, 63, 0.18), transparent 28%),
    linear-gradient(135deg, #11130f, #1c201a 58%, #0f110e);
  background-size: 28px 28px, 28px 28px, auto, auto;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 34px 90px rgba(0, 0, 0, 0.34);
}

.home-analyst-window-caption {
  position: absolute;
  left: 20px;
  right: 20px;
  top: 16px;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 28px;
  padding: 0 12px;
  border: 1px solid rgba(246, 243, 232, 0.1);
  border-radius: 6px;
  background: rgba(16, 19, 15, 0.72);
  color: rgba(246, 243, 232, 0.72);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
  backdrop-filter: blur(10px);
}

.home-analyst-window-caption small {
  color: var(--home-acid);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  white-space: nowrap;
}

.home-signal-art::after {
  content: "";
  position: absolute;
  inset: -28%;
  z-index: 1;
  pointer-events: none;
  background:
    conic-gradient(from 40deg at 50% 50%, transparent 0deg, rgba(215, 255, 63, 0.14) 38deg, transparent 72deg, rgba(143, 216, 189, 0.1) 138deg, transparent 194deg, rgba(199, 154, 58, 0.1) 250deg, transparent 320deg),
    radial-gradient(circle at 50% 50%, transparent 0 36%, rgba(246, 243, 232, 0.1) 36.5%, transparent 37.5%);
  opacity: 0.56;
  transform: rotate(0deg);
}

.home-signal-canvas,
.home-market-field {
  position: absolute;
  inset: 0;
}

.home-signal-canvas {
  width: 100%;
  height: 100%;
}

.home-market-field {
  z-index: 1;
  pointer-events: none;
  mix-blend-mode: screen;
}

.home-signal-canvas {
  z-index: 1;
}

.home-market-field::before,
.home-market-field::after {
  content: "";
  position: absolute;
  inset: 10%;
  border: 1px solid rgba(143, 216, 189, 0.18);
  transform: skewX(-18deg) rotate(-10deg);
}

.home-market-field::after {
  inset: 23% 4% 18% 36%;
  border-color: rgba(215, 255, 63, 0.18);
  transform: skewX(22deg) rotate(16deg);
}

.home-scanline {
  position: absolute;
  top: -20%;
  bottom: -20%;
  left: 18%;
  width: 1px;
  background: linear-gradient(transparent, rgba(215, 255, 63, 0.85), transparent);
  transform: rotate(18deg);
}

.home-index-map {
  position: absolute;
  right: -8%;
  top: 12%;
  width: 58%;
  aspect-ratio: 1;
  border: 1px solid rgba(143, 216, 189, 0.22);
  border-radius: 50%;
}

.home-index-map::before,
.home-index-map::after {
  content: "";
  position: absolute;
  inset: 18%;
  border: 1px solid rgba(143, 216, 189, 0.16);
  border-radius: 50%;
}

.home-index-map::after {
  inset: 37%;
  background: rgba(143, 216, 189, 0.1);
}

.home-signal-thread {
  position: absolute;
  left: 7%;
  right: 7%;
  bottom: 18%;
  height: 18%;
  clip-path: polygon(0 72%, 12% 58%, 20% 64%, 30% 22%, 42% 44%, 52% 34%, 62% 70%, 72% 30%, 84% 50%, 100% 18%, 100% 100%, 0 100%);
  background: linear-gradient(90deg, rgba(215, 255, 63, 0.82), rgba(143, 216, 189, 0.34));
  opacity: 0.36;
}

.signal-flow-row {
  position: absolute;
  left: 34px;
  right: 34px;
  top: 58px;
  z-index: 2;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  border: 1px solid rgba(246, 243, 232, 0.14);
  background: rgba(16, 19, 15, 0.5);
}

.signal-flow-row span {
  min-width: 0;
  padding: 12px 10px;
  border-right: 1px solid rgba(246, 243, 232, 0.14);
  color: rgba(246, 243, 232, 0.66);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-align: center;
}

.signal-flow-row span:last-child {
  border-right: 0;
  color: var(--home-acid);
}

.home-live-tape {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 4;
  overflow: hidden;
  border-top: 1px solid rgba(246, 243, 232, 0.14);
  background: rgba(16, 19, 15, 0.72);
}

.home-live-tape-track {
  display: flex;
  width: max-content;
  min-width: 100%;
}

.home-live-tape span {
  flex: 0 0 auto;
  padding: 10px 18px;
  border-right: 1px solid rgba(246, 243, 232, 0.1);
  color: rgba(246, 243, 232, 0.72);
  font-family: var(--app-font-stack);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.signal-stock-card {
  left: 44px;
  right: 44px;
  bottom: 44px;
  z-index: 3;
  border-color: rgba(246, 243, 232, 0.18);
  border-radius: 0;
  background: rgba(16, 19, 15, 0.76);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 28px 60px rgba(0, 0, 0, 0.24);
}

.signal-stock-card .home-console-top {
  border-bottom-color: rgba(246, 243, 232, 0.12);
}

.signal-stock-card .home-console-top span:first-child,
.signal-stock-card .home-console-focus span {
  color: var(--home-celadon);
}

.signal-stock-card .home-console-focus strong {
  color: var(--home-ink);
  font-size: clamp(36px, 4vw, 58px);
  overflow-wrap: anywhere;
}

.signal-stock-card .home-console-focus {
  padding: 22px 22px 14px;
}

.signal-stock-card .home-console-focus small {
  color: rgba(246, 243, 232, 0.64);
  overflow-wrap: anywhere;
}

.signal-vector-row {
  border-top-color: rgba(246, 243, 232, 0.12);
}

.signal-vector-row div {
  border-right-color: rgba(246, 243, 232, 0.12);
}

.signal-vector-row span {
  color: rgba(246, 243, 232, 0.56);
}

.signal-vector-row strong {
  color: var(--home-ink);
}

.signal-stock-card .home-sparkline {
  border-bottom-color: rgba(246, 243, 232, 0.14);
  gap: 5px;
  height: 70px;
  margin: 0 22px 14px;
}

.signal-stock-card .home-sparkline i {
  background: linear-gradient(var(--home-acid), var(--home-celadon));
}

.home-lens-band,
.home-service-map,
.public-home .home-band,
.public-home .home-analysis-zone,
.public-home .home-ops-strip {
  border-bottom: 1px solid var(--home-line);
}

.home-service-map {
  padding: clamp(46px, 7vw, 92px) 0;
}

.home-service-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.14);
}

.home-service-grid article {
  display: grid;
  align-content: start;
  gap: 14px;
  min-height: 260px;
  padding: clamp(18px, 2.2vw, 26px);
  background:
    linear-gradient(145deg, rgba(246, 243, 232, 0.07), rgba(143, 216, 189, 0.035)),
    rgba(15, 22, 18, 0.82);
}

.home-service-grid span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 900;
}

.home-service-grid strong {
  color: var(--home-ink);
  font-size: clamp(22px, 2.4vw, 30px);
  line-height: 1.08;
}

.home-service-grid p {
  margin: 0;
  color: var(--home-muted-readable);
  line-height: 1.65;
}

.home-service-grid a {
  align-self: end;
  justify-self: start;
  display: inline-grid;
  min-height: 38px;
  place-items: center;
  border: 1px solid rgba(215, 255, 63, 0.34);
  border-radius: 6px;
  color: var(--home-acid);
  padding: 0 12px;
  font-weight: 900;
}

.home-lens-band {
  padding: clamp(48px, 7vw, 96px) 0;
}

.public-home .home-section-heading {
  align-items: start;
}

.public-home .home-section-heading h2,
.public-home .home-section-copy h2,
.public-home .home-ops-strip h2 {
  color: var(--home-ink);
  font-size: clamp(28px, 4vw, 54px);
  font-weight: 900;
  line-height: 0.98;
  text-wrap: balance;
}

.public-home .feature-boundary {
  margin-bottom: clamp(28px, 5vw, 56px);
  padding-block: clamp(18px, 2.4vw, 28px);
}

.public-home .feature-boundary h2 {
  line-height: 1.25;
  letter-spacing: -0.03em;
}

.public-home .home-section-heading p,
.public-home .home-section-copy p,
.public-home .home-flow-list p,
.public-home .home-ops-strip li {
  color: var(--home-muted-readable);
}

.public-home .home-ops-strip a {
  color: var(--home-acid);
}

.home-lens-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(160px, 1fr));
  gap: 0;
  margin-top: 28px;
  border-top: 1px solid var(--home-line);
}

.home-lens-grid article {
  min-height: 220px;
  padding: 22px 18px;
  border-right: 1px solid var(--home-line);
}

.home-lens-grid article:last-child {
  border-right: 0;
}

.home-lens-grid span,
.home-flow-list .home-flow-icon {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
}

.home-lens-grid strong {
  display: block;
  margin: 36px 0 12px;
  color: var(--home-ink);
  font-size: 22px;
}

.home-lens-grid p {
  margin: 0;
  color: rgba(246, 243, 232, 0.62);
  line-height: 1.6;
}

.home-recent-intel {
  padding: clamp(52px, 8vw, 110px) 0;
}

.public-home .analysis-feed-card {
  border-color: rgba(246, 243, 232, 0.14);
  border-radius: 0;
  background: rgba(251, 250, 244, 0.055);
  color: var(--home-ink);
}

.public-home .analysis-feed-card span {
  color: var(--home-celadon);
}

.public-home .analysis-feed-card p,
.public-home .analysis-feed-card small,
.public-home .analysis-feed-card dt {
  color: var(--home-muted-readable);
}

.public-home .analysis-feed-card dl div {
  border-top-color: rgba(246, 243, 232, 0.12);
}

.public-home .analysis-feed-actions {
  border-top-color: rgba(246, 243, 232, 0.13);
}

.public-home .analysis-feed-actions a {
  border-color: rgba(246, 243, 232, 0.24);
  background: rgba(246, 243, 232, 0.075);
  color: rgba(246, 243, 232, 0.92);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.public-home .analysis-feed-actions a:hover {
  border-color: rgba(220, 252, 19, 0.48);
  background: rgba(220, 252, 19, 0.1);
  color: var(--home-acid);
}

.public-home .analysis-feed-actions a:first-child {
  border-color: var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
}

.home-analysis-grid .analysis-feed-card:first-child:not(.empty) {
  background: rgba(251, 250, 244, 0.09);
  border-top: 4px solid var(--home-acid);
}

.home-stock-jump {
  padding: clamp(42px, 6vw, 76px) 0;
}

.home-ticker-rail .analysis-feed-card {
  border-left: 3px solid var(--home-acid);
  background: transparent;
}

.home-ticker-rail .quick-ticker-card {
  gap: 10px;
  min-height: 138px;
  padding: 14px 15px 15px;
  border-top: 1px solid rgba(246, 243, 232, 0.12);
  border-left: 2px solid rgba(215, 255, 63, 0.76);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(215, 255, 63, 0.07), transparent 44%),
    rgba(251, 250, 244, 0.045);
}

.quick-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.quick-card-head > span {
  margin: 0;
}

.quick-card-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-radius: 999px;
  background: rgba(246, 243, 232, 0.06);
  color: rgba(246, 243, 232, 0.72);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: -0.02em;
  white-space: nowrap;
  transition: border-color 180ms ease, color 180ms ease, background 180ms ease;
}

.quick-card-action:hover {
  border-color: rgba(220, 252, 19, 0.42);
  background: rgba(220, 252, 19, 0.1);
  color: var(--home-acid);
}

.home-ticker-rail .quick-ticker-card h3 {
  margin: 2px 0 0;
  line-height: 1.1;
}

.home-ticker-rail .quick-ticker-card p {
  max-width: 16rem;
  color: rgba(246, 243, 232, 0.58);
  font-size: 13px;
}

.public-home .home-ops-strip {
  color: var(--home-ink);
}

.public-home .home-ops-strip li {
  border-top-color: rgba(246, 243, 232, 0.14);
}

.public-home .home-flow-list {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  border-top: 0;
}

.public-home .home-flow-list article {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-content: start;
  gap: 12px;
  min-height: 210px;
  padding: 20px;
  border: 1px solid rgba(246, 243, 232, 0.13);
  border-left: 3px solid rgba(215, 255, 63, 0.72);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(215, 255, 63, 0.075), transparent 42%),
    rgba(32, 35, 30, 0.82);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.045);
}

.public-home .home-flow-list strong {
  color: var(--home-ink);
  font-size: clamp(20px, 2vw, 26px);
  line-height: 1.12;
}

.public-home .home-flow-list .home-flow-icon {
  display: inline-grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid rgba(215, 255, 63, 0.38);
  border-radius: 6px;
  background: rgba(215, 255, 63, 0.1);
  color: var(--home-acid);
  font-size: 17px;
  line-height: 1;
}

.public-home .home-flow-list .home-flow-icon svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.public-home .home-flow-list p {
  max-width: 31rem;
  font-size: 14px;
}

.home-readonly-banner {
  margin-top: clamp(22px, 4vw, 44px);
  padding: 18px 20px;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 8px;
  background: rgba(49, 53, 46, 0.56);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.public-home .home-readonly-banner h2 {
  font-size: clamp(18px, 2vw, 24px);
  line-height: 1.18;
  letter-spacing: -0.03em;
}

.home-readonly-banner ul {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.public-home .home-readonly-banner li {
  padding-top: 0;
  border-top: 0;
  color: rgba(246, 243, 232, 0.76);
  font-size: 13px;
  line-height: 1.5;
  letter-spacing: -0.02em;
  opacity: 0.6;
}

.public-home .home-readonly-banner a {
  color: rgba(246, 243, 232, 0.92);
  letter-spacing: -0.02em;
}

@media (prefers-reduced-motion: no-preference) {
  .home-signal-art::after {
    animation: homeRadarSweep 18s linear infinite;
  }

  .home-scanline {
    animation: homeScan 15s linear infinite;
  }

  .home-signal-thread {
    animation: homeThread 7s steps(9) infinite;
  }

  .home-sparkline i {
    animation: homePulse 2.8s ease-in-out infinite;
    animation-delay: calc(var(--i, 0) * 120ms);
  }

  .home-live-tape-track {
    animation: homeTickerTape 26s linear infinite;
  }
}

@keyframes homeRadarSweep {
  from {
    transform: rotate(0deg) scale(1);
  }

  to {
    transform: rotate(360deg) scale(1);
  }
}

@keyframes homeScan {
  from {
    transform: translateX(-42%) rotate(18deg);
  }

  to {
    transform: translateX(520%) rotate(18deg);
  }
}

@keyframes homeThread {
  0%,
  100% {
    opacity: 0.22;
  }

  50% {
    opacity: 0.48;
  }
}

@keyframes homePulse {
  0%,
  100% {
    opacity: 0.55;
    transform: scaleY(0.84);
  }

  50% {
    opacity: 0.95;
    transform: scaleY(1);
  }
}

@keyframes homeTickerTape {
  from {
    transform: translateX(0);
  }

  to {
    transform: translateX(-50%);
  }
}

@media (max-width: 1180px) {
  .home-hero-artboard {
    grid-template-columns: minmax(0, 1fr);
    min-height: auto;
  }

  .home-signal-art {
    margin-top: 0;
    aspect-ratio: 16 / 10;
    min-height: 380px;
  }

  .home-lens-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .home-service-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .home-start-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .home-lens-grid article {
    border-bottom: 1px solid var(--home-line);
  }
}

@media (max-width: 640px) {
  .home-shell-art {
    width: calc(100% - 24px);
    max-width: 1440px;
  }

  .home-hero-artboard {
    padding: 20px 0 0;
    overflow: hidden;
  }

  .home-kicker {
    margin-bottom: 10px;
    font-size: 10px;
  }

  .home-hero-content {
    max-width: 100%;
  }

  .home-hero-artboard h1 {
    max-width: 100%;
    margin-bottom: 12px;
    font-size: clamp(30px, 9vw, 40px);
    line-height: 1.04;
    overflow-wrap: anywhere;
    word-break: break-word;
    text-wrap: balance;
  }

  .home-hero-artboard .home-lede {
    max-width: 100%;
    margin-bottom: 14px;
    font-size: 14px;
    line-height: 1.52;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .home-action-row {
    margin-top: 10px;
  }

  .home-action-row a {
    justify-content: center;
    width: 100%;
  }

  .home-action-row a:nth-child(3) {
    display: none;
  }

  .home-command-search {
    flex-direction: row;
    padding: 6px;
  }

  .home-member-preview {
    gap: 8px;
    margin-top: 10px;
    padding: 10px;
  }

  .home-member-preview > strong {
    font-size: 12px;
  }

  .home-member-preview ul {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .home-member-preview li {
    min-height: 42px;
    place-content: center;
    padding: 8px 6px;
    text-align: center;
  }

  .home-member-preview small {
    display: none;
  }

  .home-service-grid,
  .home-lens-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .home-start-strip {
    gap: 10px;
    padding: 12px 0;
  }

  .home-signal-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    margin-top: 22px;
  }

  .home-signal-strip div {
    padding: 10px 0;
  }

  .home-signal-strip dt {
    font-size: 10px;
  }

  .home-signal-strip dd {
    font-size: 11px;
    overflow-wrap: anywhere;
  }

  .home-trust-panel {
    grid-template-columns: minmax(0, 1fr);
  }

  .home-trust-panel div {
    border-right: 0;
    border-bottom: 1px solid rgba(246, 243, 232, 0.12);
  }

  .home-trust-panel div:last-child {
    border-bottom: 0;
  }

  .home-signal-art {
    min-height: 180px;
    aspect-ratio: 16 / 9;
  }

  .home-analyst-window-caption {
    left: 12px;
    right: 12px;
    top: 10px;
    min-height: 24px;
    padding: 0 8px;
    font-size: 9px;
  }

  .home-analyst-window-caption small {
    font-size: 8px;
  }

  .signal-flow-row {
    left: 16px;
    right: 16px;
    top: 42px;
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }

  .signal-flow-row span {
    padding: 10px 4px;
    font-size: 9px;
  }

  .signal-stock-card {
    left: 16px;
    right: 16px;
    top: auto;
    bottom: 16px;
  }

  .signal-stock-card .home-console-focus {
    padding: 12px;
  }

  .signal-stock-card .home-console-grid,
  .home-live-tape {
    display: none;
  }

  .signal-stock-card .home-console-focus strong {
    font-size: clamp(24px, 8vw, 30px);
    line-height: 0.98;
  }

  .signal-vector-row {
    display: none;
  }

  .signal-stock-card .home-sparkline {
    display: flex;
    height: 52px;
    margin: 0 16px 16px;
  }

  .home-lens-grid,
  .home-analysis-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .public-home .home-flow-list,
  .home-readonly-banner ul {
    grid-template-columns: minmax(0, 1fr);
  }

  .public-home .home-flow-list article {
    min-height: 0;
  }

  .home-readonly-banner {
    grid-template-columns: minmax(0, 1fr);
    padding: 16px;
  }

  .home-lens-grid article {
    min-height: 0;
    border-right: 0;
  }
}

@media (max-width: 560px) {
  .topbar {
    overflow-x: hidden;
  }

  .brand,
  .top-links {
    width: min(100%, 366px);
  }

  .top-links {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .stock-page .top-links a[href^="/features/"] {
    display: none;
  }

  .analysis-detail-page .top-links a[href^="/features/"],
  .analysis-detail-page .top-links a[href="/outcomes"] {
    display: none;
  }

  .home-shell-art,
  .member-shell,
  .market-shell {
    margin-left: 12px;
    margin-right: auto;
    width: min(calc(100% - 24px), 366px);
  }

  .home-lede,
  .member-auth-lead,
  .analysis-filter-panel p,
  .analysis-feed-card,
  .analysis-detail-report-card,
  .analysis-rationale-card {
    overflow-wrap: anywhere;
    word-break: break-word;
  }
}

html {
  scroll-behavior: smooth;
}

.skip-link {
  position: fixed;
  left: 16px;
  top: 12px;
  z-index: 100;
  transform: translateY(-140%);
  border: 1px solid var(--home-acid, var(--accent));
  border-radius: 6px;
  background: var(--home-acid, var(--ink));
  color: #10130f;
  padding: 10px 12px;
  font-weight: 900;
}

.skip-link:focus {
  transform: translateY(0);
}

a:focus-visible,
button:focus-visible,
input:focus-visible,
select:focus-visible {
  outline: 2px solid var(--home-acid, var(--accent));
  outline-offset: 3px;
}

button,
.top-links a,
.chart-tab,
.analysis-filter-form a,
.analysis-feed-card,
.member-item,
.admin-card {
  transition: transform 180ms ease, border-color 180ms ease, background 180ms ease, color 180ms ease, opacity 180ms ease;
}

button:hover,
.analysis-filter-form a:hover {
  transform: translateY(-1px);
}

button:active,
.analysis-filter-form a:active {
  transform: translateY(1px);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.64;
}

.market-shell {
  width: min(1440px, calc(100% - clamp(24px, 5vw, 72px)));
  padding: clamp(32px, 5vw, 64px) 0 78px;
}

.market-page .topbar .ticker-search {
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.05);
  padding: 4px;
}

.market-page .ticker-search input {
  border-color: rgba(246, 243, 232, 0.14);
  background: rgba(251, 250, 244, 0.06);
  color: var(--home-ink);
}

.market-page .ticker-search input::placeholder {
  color: rgba(246, 243, 232, 0.48);
}

.market-page .ticker-search button {
  background: var(--home-acid);
  color: #10130f;
}

.market-page .summary-band {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 0.28fr);
  align-items: stretch;
  gap: clamp(18px, 3vw, 34px);
  padding: clamp(28px, 5vw, 66px) 0 clamp(22px, 4vw, 42px);
  border-bottom: 1px solid var(--home-line);
}

.market-page .summary-band h1 {
  max-width: 880px;
  color: var(--home-ink);
  font-size: clamp(42px, 6vw, 86px);
  font-weight: 900;
  line-height: 0.96;
  text-wrap: balance;
}

.outcome-page .summary-band h1 {
  max-width: 760px;
  text-wrap: normal;
  word-break: keep-all;
}

.outcome-title-line {
  display: inline-block;
  color: inherit;
  font-family: inherit;
  font-size: inherit;
}

.market-page .summary-band h1 span:not(.outcome-title-line) {
  color: rgba(246, 243, 232, 0.58);
  font-family: var(--app-font-stack);
  font-size: clamp(20px, 2.2vw, 34px);
}

.stock-hero-copy {
  max-width: 64ch;
  margin: 14px 0 0;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  font-size: clamp(15px, 1.3vw, 18px);
  line-height: 1.72;
  text-wrap: pretty;
}

.stock-hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
}

.stock-hero-actions a {
  display: inline-grid;
  min-height: 42px;
  place-items: center;
  border: 1px solid rgba(246, 243, 232, 0.18);
  border-radius: 6px;
  color: var(--home-ink);
  padding: 0 14px;
  font-weight: 900;
  transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
}

.stock-hero-actions a:first-child {
  border-color: var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
}

.stock-hero-actions a:hover {
  transform: translateY(-1px);
  border-color: rgba(215, 255, 63, 0.42);
}

.stock-mobile-jumpbar {
  display: none;
}

.stock-hero-stack {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
}

.stock-signal-card {
  display: grid;
  align-content: end;
  gap: 12px;
  min-height: 206px;
  padding: 20px;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-left: 4px solid var(--home-celadon);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(143, 216, 189, 0.12), rgba(246, 243, 232, 0.04)),
    rgba(15, 22, 18, 0.78);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.045);
}

.stock-signal-card span,
.stock-signal-card dt {
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.stock-signal-card strong {
  color: var(--home-ink);
  font-size: clamp(28px, 4vw, 46px);
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.stock-signal-card small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-weight: 800;
  line-height: 1.4;
}

.stock-signal-card dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin: 6px 0 0;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.12);
}

.stock-signal-card dl div {
  min-width: 0;
  padding: 10px;
  background: rgba(9, 13, 11, 0.42);
}

.stock-signal-card dd {
  margin: 5px 0 0;
  color: var(--home-ink);
  font-weight: 900;
  overflow-wrap: anywhere;
}

.stock-reading-guide {
  display: grid;
  grid-template-columns: minmax(240px, 0.74fr) minmax(0, 1.26fr);
  gap: 18px;
  align-items: stretch;
  margin-top: 18px;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  padding: 18px;
  background:
    linear-gradient(135deg, rgba(215, 255, 63, 0.07), rgba(143, 216, 189, 0.04)),
    rgba(15, 22, 18, 0.72);
}

.stock-reading-guide h2 {
  max-width: 14ch;
  color: var(--home-ink);
  font-size: 34px;
  line-height: 1;
  text-wrap: balance;
  word-break: keep-all;
}

.stock-reading-guide p:not(.eyebrow) {
  max-width: 62ch;
  margin: 14px 0 0;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  line-height: 1.7;
  text-wrap: pretty;
}

.stock-reading-nav {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.12);
}

.stock-reading-nav a {
  display: grid;
  gap: 8px;
  min-height: 118px;
  padding: 14px;
  background: rgba(9, 13, 11, 0.46);
  color: var(--home-ink);
  transition: background 180ms ease, transform 180ms ease;
}

.stock-reading-nav a:hover {
  transform: translateY(-1px);
  background: rgba(215, 255, 63, 0.1);
}

.stock-reading-nav span {
  color: var(--home-acid);
  font-size: 11px;
  font-weight: 900;
}

.stock-reading-nav strong {
  font-size: 16px;
  line-height: 1.1;
}

.stock-reading-nav small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  line-height: 1.45;
}

.stock-reading-more {
  border-left: 2px solid rgba(215, 255, 63, 0.54);
}

.stock-report-actions {
  margin-top: 16px;
}

.outcome-section-copy {
  max-width: 72ch;
  margin: 8px 0 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  line-height: 1.6;
}

.market-page .eyebrow {
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 11px;
  letter-spacing: 0.12em;
}

.market-page .asof,
.market-page .chart-caption,
.market-page .analysis-panel p,
.market-page .simulation-preview p,
.market-page .report-card p,
.market-page .analysis-feed-card p,
.market-page .analysis-feed-card small,
.market-page .analysis-feed-card dt,
.market-page .analysis-summary-grid span,
.market-page .analysis-summary-grid small,
.market-page .analysis-track-grid span,
.market-page .analysis-track-grid small,
.market-page .lens-card p,
.market-page .outcome-card p,
.market-page .outcome-card dt {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.74));
}

.market-page .decision-box,
.market-page .chart-panel,
.market-page .analysis-panel,
.market-page .simulation-panel,
.market-page .report-section,
.market-page .metric-grid article,
.market-page .report-card,
.market-page .analysis-summary-grid article,
.market-page .analysis-track-grid article,
.market-page .analysis-feed-card,
.market-page .analysis-pipeline-strip article,
.market-page .analysis-provenance-grid article,
.market-page .analysis-rationale-card,
.market-page .analysis-detail-report-card,
.market-page .lens-card,
.market-page .outcome-card,
.analysis-filter-panel {
  border-color: rgba(246, 243, 232, 0.14);
  background:
    linear-gradient(135deg, rgba(246, 243, 232, 0.072), rgba(246, 243, 232, 0.032)),
    rgba(15, 22, 18, 0.78);
  color: var(--home-ink);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.045);
}

.market-page .decision-box {
  min-width: 0;
  border-top: 4px solid var(--home-acid);
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.26);
}

.market-page .decision-label,
.market-page .status-pill {
  color: rgba(246, 243, 232, 0.74);
}

.market-page .decision-box span:last-child,
.market-page .report-card span,
.market-page .analysis-feed-card span {
  color: var(--home-celadon);
}

.outcome-page .decision-box span:last-child {
  letter-spacing: -0.02em;
  opacity: 0.8;
}

.market-page .analysis-empty-plan {
  border-color: rgba(246, 243, 232, 0.13);
  background: rgba(246, 243, 232, 0.13);
}

.market-page .analysis-empty-plan div {
  background: rgba(9, 13, 11, 0.48);
}

.market-page .analysis-empty-plan strong {
  background: var(--home-acid);
  color: #10130f;
}

.market-page .analysis-empty-plan span {
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
}

.market-page .analysis-feed-card .analysis-feed-signal-row span {
  border-color: rgba(215, 255, 63, 0.22);
  background: rgba(215, 255, 63, 0.08);
  color: var(--home-ink);
}

.market-page .analysis-pipeline-strip {
  border-color: rgba(246, 243, 232, 0.14);
  background: rgba(246, 243, 232, 0.13);
}

.market-page .analysis-pipeline-strip span {
  color: var(--home-acid);
}

.market-page .analysis-pipeline-strip strong {
  color: var(--home-ink);
}

.market-page .analysis-pipeline-strip small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.74));
}

.market-page .analysis-feed-card.is-positive-alpha {
  border-top-color: var(--home-celadon);
}

.market-page .analysis-feed-card.is-negative-alpha {
  border-top-color: var(--home-vermilion);
}

.market-page .analysis-feed-card.is-neutral-alpha {
  border-top-color: var(--home-brass);
}

.market-page .decision-box strong,
.market-page h2,
.market-page h3,
.market-page .metric-grid strong,
.market-page .analysis-summary-grid strong,
.market-page .analysis-track-grid strong,
.market-page .analysis-feed-card dd,
.market-page .analysis-provenance-grid strong,
.market-page .analysis-rationale-card dd,
.market-page .lens-card h3,
.market-page .outcome-card h3,
.market-page .outcome-card dd {
  color: var(--home-ink);
}

.market-page .workspace {
  gap: 16px;
  margin-top: 20px;
}

.market-page .chart-panel,
.market-page .report-section {
  padding: clamp(16px, 2vw, 24px);
}

.market-page .chart-wrap {
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-radius: 6px;
  background:
    linear-gradient(90deg, rgba(246, 243, 232, 0.035) 1px, transparent 1px),
    linear-gradient(0deg, rgba(246, 243, 232, 0.035) 1px, transparent 1px),
    #111711;
  background-size: 40px 40px;
}

.market-page .status-pill,
.market-page .data-pill,
.market-page .chart-tab,
.market-page .chart-tool-button,
.market-page .chart-setting-field,
.market-page .chart-legend span {
  border-color: rgba(246, 243, 232, 0.16);
  background: rgba(246, 243, 232, 0.07);
  color: rgba(246, 243, 232, 0.72);
}

.market-page .chart-setting-field input {
  border-color: rgba(246, 243, 232, 0.16);
  background: rgba(9, 13, 11, 0.44);
  color: var(--home-ink);
}

.market-page .chart-tools {
  border-color: rgba(246, 243, 232, 0.13);
  background: rgba(246, 243, 232, 0.05);
}

.market-page .chart-tool-group > span,
.market-page .chart-tools small,
.market-page .chart-control-block > span {
  color: rgba(198, 221, 192, 0.78);
}

.market-page .chart-legend span {
  background: rgba(9, 13, 11, 0.76);
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  backdrop-filter: blur(8px);
}

.market-page .chart-tooltip {
  border-color: rgba(215, 255, 63, 0.28);
  background: rgba(9, 13, 11, 0.92);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.32);
  color: var(--home-ink);
}

.market-page .chart-tooltip span {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
}

.market-page .data-source-strip {
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  border-color: rgba(246, 243, 232, 0.13);
  background: rgba(246, 243, 232, 0.13);
}

.market-page .data-source-strip div {
  background: rgba(9, 13, 11, 0.42);
}

.market-page .data-source-strip dt {
  color: rgba(198, 221, 192, 0.74);
}

.market-page .data-source-strip dd {
  color: var(--home-ink);
}

.market-page .analysis-confidence-panel {
  border-color: rgba(246, 243, 232, 0.14);
  background: rgba(246, 243, 232, 0.06);
}

.market-page .analysis-confidence-panel span {
  color: rgba(198, 221, 192, 0.74);
}

.market-page .analysis-confidence-panel strong {
  color: var(--home-ink);
}

.market-page .analysis-confidence-panel p,
.market-page .analysis-confidence-panel ul {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.74));
}

.market-page .simulation-grid {
  border-color: rgba(246, 243, 232, 0.13);
  background: rgba(246, 243, 232, 0.13);
}

.market-page .simulation-grid div {
  background: rgba(9, 13, 11, 0.42);
}

.market-page .simulation-grid span {
  color: rgba(198, 221, 192, 0.74);
}

.market-page .simulation-grid strong {
  color: var(--home-ink);
}

.market-page .chart-tab:hover,
.market-page .chart-tab.is-active,
.market-page .chart-tool-button:hover,
.market-page .chart-tool-button.is-active {
  border-color: rgba(215, 255, 63, 0.58);
  background: rgba(215, 255, 63, 0.12);
  color: var(--home-acid);
}

.market-page .chart-tab.is-disabled,
.market-page .chart-tab.is-disabled:hover {
  border-color: rgba(246, 243, 232, 0.13);
  background: rgba(246, 243, 232, 0.045);
  color: rgba(246, 243, 232, 0.46);
}

.market-page .chart-tab.is-active {
  box-shadow: inset 0 0 0 1px rgba(215, 255, 63, 0.18);
}

.market-page .chart-drawing-layer line {
  stroke: var(--home-acid);
  filter: drop-shadow(0 0 7px rgba(215, 255, 63, 0.32));
}

.market-page .metric-grid article {
  border-left: 3px solid rgba(215, 255, 63, 0.56);
}

.market-page .metric-grid span {
  color: rgba(246, 243, 232, 0.68);
}

.market-page .lens-card {
  border-left-color: rgba(246, 243, 232, 0.22);
}

.market-page .lens-positive {
  border-left-color: #ff6b4d;
}

.market-page .lens-caution {
  border-left-color: #6da4ff;
}

.market-page .lens-card span,
.market-page .outcome-card span {
  background: rgba(246, 243, 232, 0.08);
  color: rgba(246, 243, 232, 0.76);
}

.market-page .outcome-card dl div {
  background: rgba(246, 243, 232, 0.07);
}

.market-page .analysis-feed-card:hover,
.market-page .report-card:hover,
.market-page .analysis-detail-report-card:hover,
.market-page .lens-card:hover,
.market-page .outcome-card:hover {
  transform: translateY(-2px);
  border-color: rgba(215, 255, 63, 0.28);
}

.market-page .analysis-feed-card a {
  color: inherit;
}

.market-page .analysis-feed-card dl div {
  border-top-color: rgba(246, 243, 232, 0.13);
}

.market-page .analysis-feed-actions {
  border-top-color: rgba(246, 243, 232, 0.13);
}

.market-page .analysis-feed-actions a {
  border-color: rgba(246, 243, 232, 0.16);
  background: rgba(246, 243, 232, 0.055);
  color: rgba(246, 243, 232, 0.9);
}

.market-page .analysis-feed-actions a:first-child {
  border-color: var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
}

.analysis-filter-panel {
  display: grid;
  grid-template-columns: minmax(0, 0.58fr) minmax(260px, 0.42fr);
  gap: 18px;
  align-items: center;
  margin-top: 18px;
  padding: 16px;
  border-radius: 8px;
}

.analysis-filter-stack {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.outcome-filter-panel .analysis-filter-stack {
  gap: 4px;
}

.analysis-filter-panel p {
  margin: 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.74));
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.analysis-filter-state,
.analysis-feed-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.analysis-filter-state span,
.analysis-filter-state a,
.analysis-feed-toolbar span {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-radius: 999px;
  padding: 0 10px;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  font-size: 12px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.analysis-filter-state a {
  border-color: rgba(215, 255, 63, 0.28);
  color: var(--home-acid);
}

.outcome-filter-state {
  align-items: center;
  margin-top: -2px;
}

.analysis-feed-toolbar {
  align-items: center;
  gap: 0.5rem;
  margin: -2px 0 14px;
  padding: 10px 0;
  border-top: 1px solid rgba(246, 243, 232, 0.1);
  border-bottom: 1px solid rgba(246, 243, 232, 0.1);
}

.analysis-feed-toolbar small {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.76));
  letter-spacing: -0.02em;
  line-height: 1.45;
}

.outcome-feed-toolbar {
  align-items: center;
  gap: 0.5rem;
}

.outcome-feed-toolbar small {
  align-self: center;
}

.analysis-reader-guide {
  display: grid;
  grid-template-columns: minmax(260px, 0.72fr) minmax(0, 1.28fr);
  gap: 18px;
  align-items: stretch;
  margin-top: 16px;
  padding: 18px;
  border: 1px solid rgba(215, 255, 63, 0.2);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(215, 255, 63, 0.055), rgba(143, 216, 189, 0.035)),
    rgba(15, 22, 18, 0.72);
}

.analysis-reader-guide h2 {
  max-width: 24ch;
  margin: 0;
  color: var(--home-ink);
  font-size: clamp(28px, 3vw, 44px);
  line-height: 1.04;
  text-wrap: balance;
}

.analysis-reader-guide p:not(.eyebrow) {
  max-width: 60ch;
  margin: 12px 0 0;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  line-height: 1.68;
}

.analysis-reader-guide-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.13);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.13);
}

.analysis-reader-guide-grid article {
  display: grid;
  align-content: start;
  gap: 9px;
  min-height: 150px;
  padding: 16px;
  background: rgba(9, 13, 11, 0.5);
}

.analysis-reader-guide-grid span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

.analysis-reader-guide-grid strong {
  color: var(--home-ink);
  font-size: 18px;
  line-height: 1.15;
}

.analysis-reader-guide-grid small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  line-height: 1.5;
}

.analysis-filter-form {
  display: grid;
  grid-template-columns: auto minmax(120px, 1fr) auto auto;
  gap: 8px;
  align-items: center;
}

.analysis-filter-form label {
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.analysis-filter-form input,
.analysis-filter-form select {
  min-width: 0;
  height: 42px;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-radius: 6px;
  background: rgba(251, 250, 244, 0.06);
  color: var(--home-ink);
  padding: 0 12px;
  font: inherit;
  font-variant-numeric: tabular-nums;
}

.analysis-filter-form select {
  appearance: none;
  background:
    linear-gradient(45deg, transparent 50%, rgba(246, 243, 232, 0.68) 50%) right 14px center / 6px 6px no-repeat,
    linear-gradient(135deg, rgba(246, 243, 232, 0.68) 50%, transparent 50%) right 10px center / 6px 6px no-repeat,
    rgba(251, 250, 244, 0.06);
  padding-right: 32px;
}

.analysis-filter-form select option {
  background: #111711;
  color: var(--home-ink);
}

.outcome-filter-form {
  grid-template-columns: auto minmax(100px, 1fr) auto minmax(120px, 0.8fr) auto auto;
  align-items: center;
}

.outcome-filter-form > * {
  align-self: center;
}

.outcome-cadence-strip {
  grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
}

.analysis-filter-form button,
.analysis-filter-form a {
  display: inline-grid;
  min-height: 42px;
  place-items: center;
  border-radius: 6px;
  padding: 0 14px;
  font-weight: 900;
  white-space: nowrap;
}

.analysis-filter-form button {
  border: 1px solid var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
  transition: all 0.2s ease;
}

.analysis-filter-form button:hover {
  background: #ecff72;
  border-color: #ecff72;
  transform: translateY(-1px);
  box-shadow: 0 0 18px rgba(220, 252, 19, 0.22);
}

.analysis-filter-form button:active {
  transform: translateY(1px);
}

.analysis-filter-form a {
  border: 1px solid rgba(246, 243, 232, 0.18);
  color: var(--home-ink);
}

.analysis-page .report-section {
  border-radius: 12px;
}

.analysis-page .analysis-feed-card.empty {
  padding: clamp(18px, 2.4vw, 28px);
  background:
    linear-gradient(135deg, rgba(215, 255, 63, 0.045), transparent 40%),
    rgba(251, 250, 244, 0.055);
}

.analysis-page .analysis-feed-card.empty > span {
  color: var(--home-celadon);
  letter-spacing: 0.08em;
}

.analysis-page .analysis-feed-card.empty h3 {
  max-width: 48rem;
  color: var(--home-ink);
  font-size: clamp(22px, 2.15vw, 32px);
  line-height: 1.14;
  text-wrap: balance;
  word-break: keep-all;
}

.analysis-page .analysis-feed-card.empty p {
  max-width: 76ch;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  line-height: 1.72;
}

.analysis-page .analysis-empty-cta-row {
  grid-template-columns: minmax(260px, 1.4fr) repeat(2, minmax(132px, 0.7fr));
  gap: 10px;
  padding-top: 12px;
}

.analysis-page .analysis-empty-cta-row a {
  min-height: 42px;
  border-radius: 7px;
}

.analysis-page .analysis-empty-cta-row a:first-child {
  font-size: 14px;
  letter-spacing: -0.03em;
  box-shadow: 0 0 20px rgba(220, 252, 19, 0.18);
}

.outcome-page .outcome-feed-card.empty {
  padding: clamp(18px, 2.4vw, 28px);
  background:
    linear-gradient(135deg, rgba(215, 255, 63, 0.045), transparent 40%),
    rgba(251, 250, 244, 0.055);
}

.outcome-page .outcome-feed-card.empty > span {
  color: var(--home-celadon);
  letter-spacing: 0.08em;
}

.outcome-page .outcome-feed-card.empty h3 {
  max-width: 52rem;
  color: var(--home-ink);
  font-size: clamp(22px, 2.15vw, 32px);
  line-height: 1.14;
  text-wrap: balance;
  word-break: keep-all;
}

.outcome-page .outcome-feed-card.empty p {
  max-width: 80ch;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  line-height: 1.72;
}

.outcome-page .outcome-empty-cta-row {
  grid-template-columns: minmax(280px, 1.5fr) repeat(3, minmax(112px, 0.6fr));
  gap: 10px;
  padding-top: 12px;
}

.outcome-page .outcome-empty-cta-row a {
  min-height: 42px;
  border-radius: 7px;
}

.outcome-page .outcome-empty-cta-row a:first-child {
  font-size: 14px;
  letter-spacing: -0.03em;
  box-shadow: 0 0 20px rgba(220, 252, 19, 0.18);
}

.analysis-detail-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 0.32fr);
  gap: clamp(18px, 3vw, 34px);
  align-items: stretch;
  padding: clamp(30px, 5vw, 72px) 0 clamp(22px, 4vw, 42px);
  border-bottom: 1px solid var(--home-line);
}

.analysis-detail-hero h1 {
  max-width: 920px;
  color: var(--home-ink);
  font-size: clamp(38px, 5.2vw, 78px);
  font-weight: 900;
  line-height: 1;
  text-wrap: balance;
  word-break: keep-all;
  overflow-wrap: anywhere;
}

.analysis-detail-lede {
  max-width: 74ch;
  margin: 18px 0 0;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  font-size: 17px;
  line-height: 1.72;
  text-wrap: pretty;
}

.analysis-detail-meta-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.analysis-detail-meta-strip span {
  display: inline-grid;
  min-height: 32px;
  place-items: center;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-radius: 6px;
  background: rgba(10, 16, 13, 0.54);
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  padding: 0 10px;
  font-size: 12px;
  font-weight: 800;
}

.analysis-detail-meta-strip span:last-child {
  border-color: rgba(143, 216, 189, 0.34);
  color: var(--home-celadon);
}

.analysis-detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
}

.analysis-detail-actions a {
  display: inline-grid;
  min-height: 42px;
  place-items: center;
  border: 1px solid rgba(246, 243, 232, 0.18);
  border-radius: 6px;
  color: var(--home-ink);
  padding: 0 14px;
  font-weight: 900;
  transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
}

.analysis-detail-actions a:first-child {
  border-color: var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
}

.analysis-detail-actions a:hover {
  transform: translateY(-1px);
  border-color: rgba(215, 255, 63, 0.42);
}

.analysis-detail-decision {
  align-self: stretch;
}

.analysis-detail-map {
  display: grid;
  gap: 14px;
  margin-top: 18px;
  padding: 18px;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(215, 255, 63, 0.08), rgba(143, 216, 189, 0.05)),
    rgba(15, 22, 18, 0.72);
}

.analysis-detail-map-heading {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 18px;
}

.analysis-detail-map-heading h2 {
  color: var(--home-ink);
  font-size: clamp(24px, 3vw, 38px);
  line-height: 1;
}

.analysis-map-copy {
  max-width: 68ch;
  margin: 10px 0 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  line-height: 1.6;
  text-wrap: pretty;
}

.analysis-detail-map-heading nav {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.analysis-detail-map-heading a {
  display: inline-grid;
  min-height: 34px;
  place-items: center;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-radius: 6px;
  color: var(--home-ink);
  padding: 0 11px;
  font-size: 13px;
  font-weight: 900;
  transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
}

.analysis-detail-map-heading a:hover {
  transform: translateY(-1px);
  border-color: rgba(215, 255, 63, 0.42);
  background: rgba(215, 255, 63, 0.1);
}

.analysis-detail-map-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.12);
}

.analysis-detail-map-grid article {
  display: grid;
  gap: 9px;
  min-height: 132px;
  padding: 16px;
  background: rgba(9, 13, 11, 0.44);
}

.analysis-detail-map-grid span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
}

.analysis-detail-map-grid strong {
  color: var(--home-ink);
  font-size: 18px;
  line-height: 1.1;
}

.analysis-detail-map-grid small,
.analysis-detail-map-grid em {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-style: normal;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.analysis-provenance-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.analysis-provenance-grid article {
  min-height: 132px;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  padding: 16px;
  overflow-wrap: anywhere;
}

.analysis-provenance-grid span,
.analysis-rationale-card span,
.analysis-detail-report-card span {
  display: block;
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

.analysis-provenance-grid strong {
  display: block;
  margin-top: 26px;
  font-size: clamp(18px, 2.2vw, 28px);
  line-height: 1.05;
}

.analysis-provenance-grid small {
  display: block;
  margin-top: 8px;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  line-height: 1.45;
}

.analysis-rationale-section {
  margin-top: 18px;
}

.analysis-rationale-card {
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-left: 4px solid var(--home-acid);
  border-radius: 8px;
  padding: clamp(18px, 3vw, 28px);
}

.analysis-rationale-card h2 {
  margin-top: 20px;
  font-size: clamp(26px, 4vw, 46px);
  line-height: 1;
}

.analysis-rationale-card p {
  max-width: 82ch;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  line-height: 1.72;
}

.analysis-rationale-card dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 22px 0 0;
}

.analysis-rationale-card dl div {
  border-top: 1px solid rgba(246, 243, 232, 0.12);
  padding-top: 10px;
}

.analysis-rationale-card dt {
  color: rgba(246, 243, 232, 0.58);
  font-size: 12px;
}

.analysis-rationale-card dd {
  margin: 4px 0 0;
  font-weight: 900;
}

.analysis-detail-reports {
  margin-top: 18px;
}

.analysis-report-stack {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.analysis-detail-report-card {
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  padding: clamp(18px, 3vw, 28px);
}

.analysis-detail-report-card h3 {
  margin-top: 16px;
  font-size: clamp(22px, 3vw, 36px);
  line-height: 1.04;
}

.analysis-report-excerpt-label {
  display: inline-block;
  margin-top: 8px;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  font-size: 12px;
  font-weight: 800;
}

.analysis-quality-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: baseline;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(246, 243, 232, 0.12);
}

.analysis-quality-strip strong {
  color: var(--home-ink);
  font-size: 13px;
}

.analysis-quality-strip small {
  color: rgba(246, 243, 232, 0.58);
  font-size: 12px;
}

.analysis-quality-strip.risk-low strong {
  color: var(--home-celadon);
}

.analysis-quality-strip.risk-medium strong {
  color: var(--home-brass);
}

.analysis-quality-strip.risk-high strong {
  color: var(--home-vermilion);
}

.analysis-quality-list {
  display: grid;
  gap: 8px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}

.analysis-quality-list li {
  display: grid;
  gap: 3px;
  border-left: 2px solid rgba(246, 243, 232, 0.16);
  padding-left: 10px;
}

.analysis-quality-list strong {
  color: var(--home-ink);
  font-size: 12px;
}

.analysis-quality-list small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  font-size: 12px;
  line-height: 1.45;
}

.analysis-detail-report-body {
  display: grid;
  gap: 12px;
  max-width: 78ch;
  margin-top: 16px;
}

.analysis-detail-report-body p {
  margin: 0;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  line-height: 1.74;
  text-wrap: pretty;
}

.analysis-report-note {
  max-width: 78ch;
  margin: 14px 0 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  font-size: 13px;
  line-height: 1.6;
}

.analysis-empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.analysis-empty-actions a {
  display: inline-grid;
  min-height: 36px;
  place-items: center;
  border: 1px solid rgba(246, 243, 232, 0.16);
  border-radius: 6px;
  color: var(--home-ink);
  padding: 0 11px;
  font-size: 13px;
  font-weight: 900;
  transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
}

.analysis-empty-actions a:hover {
  transform: translateY(-1px);
  border-color: rgba(215, 255, 63, 0.42);
  background: rgba(215, 255, 63, 0.08);
}

.analysis-next-actions {
  display: grid;
  grid-template-columns: minmax(260px, 0.38fr) minmax(0, 1fr);
  gap: 18px;
  margin-top: 18px;
  padding: clamp(18px, 3vw, 28px);
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(143, 216, 189, 0.08), rgba(215, 255, 63, 0.04)),
    rgba(12, 18, 15, 0.74);
}

.analysis-next-actions h2 {
  max-width: 10ch;
  margin-top: 8px;
  color: var(--home-ink);
  font-size: clamp(26px, 4vw, 44px);
  line-height: 1;
  text-wrap: balance;
}

.analysis-next-actions p {
  max-width: 54ch;
  margin-top: 14px;
  color: var(--home-readable, rgba(246, 243, 232, 0.84));
  line-height: 1.68;
}

.analysis-next-action-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.12);
}

.analysis-next-action-grid a {
  display: grid;
  align-content: start;
  gap: 9px;
  min-height: 150px;
  padding: 16px;
  background: rgba(8, 13, 11, 0.64);
  color: var(--home-ink);
  transition: background 180ms ease, transform 180ms ease;
}

.analysis-next-action-grid a:hover {
  background: rgba(215, 255, 63, 0.09);
}

.analysis-next-action-grid span {
  color: var(--home-acid);
  font-size: 11px;
  font-weight: 900;
}

.analysis-next-action-grid strong {
  font-size: 18px;
  line-height: 1.1;
}

.analysis-next-action-grid small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.78));
  line-height: 1.5;
}

.market-page .notice-strip {
  border-color: rgba(199, 154, 58, 0.28);
  background: rgba(199, 154, 58, 0.08);
}

.market-page .notice-strip ul {
  color: rgba(246, 243, 232, 0.72);
}

.analysis-page .notice-strip ul {
  color: rgba(246, 243, 232, 0.72);
  letter-spacing: -0.02em;
  opacity: 0.5;
}

.member-page .notice-strip {
  border-color: rgba(199, 154, 58, 0.28);
  background: rgba(199, 154, 58, 0.08);
}

.member-page .notice-strip ul {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
}

.market-page .positive {
  color: #ff6b4d;
}

.market-page .negative {
  color: #6da4ff;
}

.market-page .neutral {
  color: var(--home-ink);
}

.admin-health-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin-top: clamp(34px, 5vw, 62px);
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.14);
}

.admin-health-strip article {
  display: grid;
  gap: 8px;
  min-height: 148px;
  padding: 18px;
  background: rgba(15, 22, 18, 0.78);
}

.admin-health-strip span {
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.admin-health-strip strong {
  color: var(--home-ink);
  font-size: 21px;
}

.admin-health-strip small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  line-height: 1.5;
}

.admin-workflow-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.14);
}

.admin-workflow-strip article {
  display: grid;
  gap: 9px;
  min-height: 132px;
  padding: 18px;
  background: rgba(15, 22, 18, 0.76);
}

.admin-workflow-strip span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 900;
}

.admin-workflow-strip strong {
  color: var(--home-ink);
  font-size: 18px;
}

.admin-workflow-strip small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));
  line-height: 1.5;
}

.admin-ops-panel {
  display: grid;
  gap: 16px;
  margin-top: 18px;
  padding: clamp(18px, 3vw, 26px);
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(246, 243, 232, 0.072), rgba(246, 243, 232, 0.032)),
    rgba(15, 22, 18, 0.78);
  color: var(--home-ink);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.045);
}

.admin-ops-panel .panel-copy {
  max-width: 720px;
  margin: 6px 0 0;
  color: var(--home-muted-readable);
  line-height: 1.55;
}

.admin-ops-panel .panel-heading > div {
  min-width: 0;
}

.admin-ops-panel [data-admin-ops-summary] {
  flex: 0 0 auto;
  min-width: 132px;
  white-space: nowrap;
}

.admin-ops-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.14);
}

.ops-cell {
  display: grid;
  align-content: start;
  gap: 8px;
  min-height: 128px;
  padding: 16px;
  background: rgba(9, 13, 11, 0.48);
}

.ops-cell span,
.admin-recent-list span {
  color: var(--home-celadon);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ops-cell strong {
  color: var(--home-ink);
  font-size: clamp(22px, 2.6vw, 32px);
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.ops-cell small {
  color: var(--home-muted-readable);
  line-height: 1.45;
}

.ops-cell.is-ok {
  border-top: 3px solid var(--home-celadon);
}

.ops-cell.is-warn {
  border-top: 3px solid var(--home-brass);
}

.ops-cell.is-error {
  border-top: 3px solid var(--home-vermilion);
}

.admin-recent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
}

.admin-recent-list {
  display: grid;
  gap: 10px;
  align-content: start;
  min-height: 150px;
  padding: 16px;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(9, 13, 11, 0.42);
}

.admin-recent-list strong {
  color: var(--home-ink);
  font-size: 18px;
}

.admin-recent-list ul {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.admin-recent-list li {
  display: grid;
  gap: 2px;
  border-top: 1px solid rgba(246, 243, 232, 0.12);
  padding-top: 8px;
  color: var(--home-muted-readable);
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.admin-recent-list a {
  color: var(--home-acid);
  font-weight: 900;
  text-decoration: none;
}

.admin-recent-list a:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.member-tab-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  align-items: center;
  gap: 8px;
  margin: 0 0 16px;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.06);
}

.member-tab-strip a {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  min-height: 42px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--muted);
  font-weight: 900;
  line-height: 1;
  text-align: center;
}

.member-tab-strip a span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 24px;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 999px;
  background: rgba(246, 243, 232, 0.06);
  color: rgba(246, 243, 232, 0.72);
  font-family: var(--app-font-stack);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.member-tab-strip a:hover {
  border-color: rgba(215, 255, 63, 0.34);
  background: var(--surface-strong);
  color: var(--ink);
}

.member-tab-strip a[aria-selected="true"] {
  border-color: rgba(215, 255, 63, 0.46);
  background: rgba(215, 255, 63, 0.12);
  color: var(--home-acid);
}

.member-tab-strip a[aria-selected="true"] span {
  border-color: rgba(215, 255, 63, 0.34);
  background: var(--home-acid);
  color: #10130f;
}

.member-panel:target {
  border-color: rgba(215, 255, 63, 0.42);
  box-shadow: 0 0 0 3px rgba(215, 255, 63, 0.12);
}

@media (max-width: 980px) {
  .market-page .summary-band,
  .analysis-detail-hero,
  .analysis-provenance-grid,
  .analysis-detail-map-grid,
  .analysis-next-actions,
  .analysis-filter-panel,
  .analysis-reader-guide,
  .analysis-reader-guide-grid,
  .analysis-empty-plan,
  .stock-reading-guide,
  .stock-reading-nav,
  .admin-readiness-panel,
  .admin-action-panel,
  .admin-ops-grid,
  .admin-recent-grid,
  .admin-health-strip,
  .admin-workflow-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .admin-health-strip {
    gap: 1px;
  }

  .analysis-page .analysis-empty-cta-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .outcome-page .outcome-empty-cta-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .admin-ops-panel .panel-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .admin-ops-panel [data-admin-ops-summary] {
    width: 100%;
  }

  .admin-token-panel,
  .admin-action-controls {
    grid-template-columns: minmax(0, 1fr);
  }

  .admin-token-actions,
  .admin-action-controls .button-row,
  .admin-limit-hint {
    grid-column: 1 / -1;
  }

  .member-tab-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .market-shell {
    width: calc(100% - 24px);
    max-width: 1440px;
    padding-top: 22px;
  }

  .market-page .topbar .ticker-search {
    width: 100%;
  }

  .market-page .ticker-search input {
    min-width: 0;
  }

  .market-page .summary-band h1 {
    font-size: 42px;
    line-height: 1.02;
    overflow-wrap: anywhere;
  }

  .outcome-page .summary-band h1 {
    font-size: 40px;
  }

  .outcome-title-line {
    display: block;
  }

  .analysis-detail-hero h1 {
    font-size: 40px;
    line-height: 1.04;
    overflow-wrap: anywhere;
  }

  .stock-hero-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .stock-hero-actions a {
    width: 100%;
  }

  .stock-mobile-jumpbar {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    margin-top: 12px;
  }

  .stock-mobile-jumpbar a {
    display: grid;
    min-height: 40px;
    place-items: center;
    border: 1px solid rgba(215, 255, 63, 0.3);
    border-radius: 6px;
    background: rgba(215, 255, 63, 0.08);
    color: var(--home-acid);
    font-size: 13px;
    font-weight: 900;
    text-align: center;
    text-decoration: none;
  }

  .stock-signal-card dl {
    grid-template-columns: minmax(0, 1fr);
  }

  .analysis-detail-map-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .analysis-detail-map-heading nav {
    justify-content: stretch;
  }

  .analysis-detail-map-heading a {
    flex: 1 1 128px;
  }

  .analysis-rationale-card dl {
    grid-template-columns: minmax(0, 1fr);
  }

  .analysis-next-action-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .analysis-reader-guide-grid article,
  .analysis-empty-plan div {
    min-height: auto;
  }

  .analysis-filter-form,
  .member-tab-strip {
    grid-template-columns: minmax(0, 1fr);
  }
}
"""


PAGE_JS = """
(() => {
  const memberAccessTokenKey = "tradingagents.member.access_token";
  const memberRefreshTokenKey = "tradingagents.member.refresh_token";
  const searchForm = document.querySelector(".ticker-search");
  const searchInput = document.getElementById("ticker");
  const suggestions = document.getElementById("tickerSuggestions");
  const tickerLookupInputs = Array.from(document.querySelectorAll("[data-ticker-lookup]"));
  let lastSearchController = null;
  const topNavLabels = {
    "/": "종목 검색",
    "/features/methodology": "분석 기준",
    "/analyses": "AI 리포트",
    "/outcomes": "사후 결과",
    "/member": "로그인",
    "/member?mode=signup": "내 공간 만들기",
    "/mypage": "내 공간",
    "/admin": "운영 콘솔"
  };

  function memberStorageGet(key) {
    try {
      return localStorage.getItem(key) || sessionStorage.getItem(key) || "";
    } catch (_) {
      try {
        return sessionStorage.getItem(key) || "";
      } catch (__) {
        return "";
      }
    }
  }

  function currentNavKey() {
    const path = window.location.pathname;
    const params = new URLSearchParams(window.location.search);
    if (path === "/" || path.startsWith("/stocks")) return "/";
    if (path === "/member" && params.get("mode") === "signup") return "/member?mode=signup";
    if (path === "/member") return "/member";
    if (path === "/mypage") return "/mypage";
    if (path === "/admin") return "/admin";
    if (path === "/features/methodology") return "/features/methodology";
    if (path === "/analyses" || path.startsWith("/analyses/")) return "/analyses";
    if (path === "/outcomes") return "/outcomes";
    return "";
  }

  function syncTopNavigationState() {
    const current = currentNavKey();
    document.querySelectorAll(".top-links a[href]").forEach((link) => {
      const href = link.getAttribute("href") || "";
      const target = href.split("#")[0];
      const label = topNavLabels[target];
      if (label && link.textContent.trim() !== label) link.textContent = label;
      const isCurrent = Boolean(current && target === current);
      if (isCurrent) {
        link.setAttribute("aria-current", "page");
      } else if (link.getAttribute("aria-current") === "page" && target !== "/admin") {
        link.removeAttribute("aria-current");
      }
    });
  }

  function syncTopAuthLinks() {
    const signedIn = Boolean(
      memberStorageGet(memberAccessTokenKey)
      || memberStorageGet(memberRefreshTokenKey)
    );
    const adminVisible = signedIn
      || Boolean(memberStorageGet("tradingagents.admin.worker_token"))
      || window.location.pathname === "/admin";
    document.querySelectorAll('[data-auth-visible="signed-out"]').forEach((node) => {
      node.hidden = signedIn;
    });
    document.querySelectorAll('[data-auth-visible="signed-in"]').forEach((node) => {
      node.hidden = !signedIn;
    });
    document.querySelectorAll('[data-auth-visible="admin"]').forEach((node) => {
      node.hidden = !adminVisible;
    });
    syncTopNavigationState();
  }

  syncTopAuthLinks();
  window.addEventListener("storage", syncTopAuthLinks);
  window.addEventListener("tradingagents:admin-token", syncTopAuthLinks);

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

  function renderTickerOptions(target, items) {
    if (!target) return;
    target.replaceChildren(...items.map((item) => {
      const option = document.createElement("option");
      option.value = item.code;
      option.label = `${item.name} / ${item.market}`;
      return option;
    }));
  }

  function tickerDatalistFor(input) {
    const listId = input?.getAttribute("list") || "";
    return listId ? document.getElementById(listId) : null;
  }

  function bindTickerLookup(input) {
    const datalist = tickerDatalistFor(input);
    if (!datalist) return;
    input.addEventListener("input", async () => {
      const query = input.value.trim();
      input.setCustomValidity("");
      if (query.length < 2) {
        datalist.replaceChildren();
        return;
      }
      try {
        renderTickerOptions(datalist, await searchTickers(query));
      } catch (error) {
        if (error.name !== "AbortError") datalist.replaceChildren();
      }
    });
  }

  async function resolveTickerInput(input) {
    const query = input.value.trim();
    input.setCustomValidity("");
    if (!query || /^\\d{6}$/.test(query)) return query;
    const items = await searchTickers(query);
    if (!items.length) {
      input.setCustomValidity("종목명 또는 6자리 종목코드를 확인해 주세요.");
      input.reportValidity();
      return "";
    }
    input.value = items[0].code;
    return items[0].code;
  }

  tickerLookupInputs.forEach(bindTickerLookup);

  document.querySelectorAll("form").forEach((form) => {
    const tickerInput = form.querySelector("[data-ticker-submit]");
    if (!tickerInput) return;
    form.addEventListener("submit", async (event) => {
      if (form.dataset.tickerResolved === "true") {
        form.dataset.tickerResolved = "false";
        return;
      }
      const query = tickerInput.value.trim();
      if (!query || /^\\d{6}$/.test(query)) return;
      event.preventDefault();
      try {
        const code = await resolveTickerInput(tickerInput);
        if (!code) return;
        form.dataset.tickerResolved = "true";
        form.submit();
      } catch (error) {
        if (error.name !== "AbortError") {
          tickerInput.setCustomValidity("종목명 또는 6자리 종목코드를 확인해 주세요.");
          tickerInput.reportValidity();
        }
      }
    });
  });

  if (searchInput && suggestions) {
    searchInput.addEventListener("input", async () => {
      const query = searchInput.value.trim();
      if (query.length < 2) {
        suggestions.replaceChildren();
        return;
      }
      try {
        renderTickerOptions(suggestions, await searchTickers(query));
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

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const signalTicker = document.getElementById("homeSignalTicker");
  const signalDecision = document.getElementById("homeSignalDecision");
  const signalMeta = document.getElementById("homeSignalMeta");
  const signalStates = [
    {
      ticker: "005930 / 삼성전자",
      decision: "보유 관찰",
      meta: "KRX 가격 + DART 공시 + 시장 대비"
    },
    {
      ticker: "000660 / SK하이닉스",
      decision: "위험 점검",
      meta: "변동성 방어 + 뉴스 반응 + 20일 기록"
    },
    {
      ticker: "035420 / NAVER",
      decision: "뉴스 추적",
      meta: "Naver 뉴스 묶음 + 공시 확인"
    },
    {
      ticker: "086520 / 에코프로",
      decision: "데이터 검토",
      meta: "KOSDAQ 흐름 + 주문 없는 투자자 보호"
    }
  ];

  if (signalTicker && signalDecision && signalMeta) {
    let signalIndex = 0;
    const renderSignalState = (index) => {
      const state = signalStates[index % signalStates.length];
      signalTicker.textContent = state.ticker;
      signalDecision.textContent = state.decision;
      signalMeta.textContent = state.meta;
    };
    renderSignalState(signalIndex);
    if (!prefersReducedMotion) {
      window.setInterval(() => {
        signalIndex = (signalIndex + 1) % signalStates.length;
        renderSignalState(signalIndex);
      }, 3200);
    }
  }

  const homeCanvas = document.getElementById("homeSignalCanvas");
  if (homeCanvas) {
    const homeCtx = homeCanvas.getContext("2d");
    const reducedMotion = prefersReducedMotion;
    const nodes = [
      { x: 0.14, y: 0.68, label: "KRX", tone: "#d7ff3f" },
      { x: 0.3, y: 0.38, label: "DART", tone: "#8fd8bd" },
      { x: 0.52, y: 0.58, label: "NEWS", tone: "#c79a3a" },
      { x: 0.7, y: 0.28, label: "AGENTS", tone: "#8fd8bd" },
      { x: 0.86, y: 0.5, label: "REPORT", tone: "#d7ff3f" }
    ];
    let homeFrameId = null;
    let homePaused = false;

    function fitHomeCanvas() {
      const rect = homeCanvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      homeCanvas.width = Math.max(1, Math.floor(rect.width * ratio));
      homeCanvas.height = Math.max(1, Math.floor(rect.height * ratio));
      homeCtx.setTransform(ratio, 0, 0, ratio, 0, 0);
      return rect;
    }

    let homeCanvasRect = fitHomeCanvas();

    function drawHomeSignal(time = 0) {
      homeFrameId = null;
      if (homePaused && !reducedMotion) return;
      const width = homeCanvasRect.width;
      const height = homeCanvasRect.height;
      homeCtx.clearRect(0, 0, width, height);
      homeCtx.save();
      homeCtx.globalCompositeOperation = "screen";

      const pulse = reducedMotion ? 0.5 : (Math.sin(time / 1100) + 1) / 2;
      homeCtx.lineWidth = 1;
      homeCtx.strokeStyle = `rgba(215, 255, 63, ${0.18 + pulse * 0.16})`;
      homeCtx.beginPath();
      nodes.forEach((node, index) => {
        const x = node.x * width;
        const y = node.y * height;
        if (index === 0) homeCtx.moveTo(x, y);
        else homeCtx.lineTo(x, y);
      });
      homeCtx.stroke();

      for (let packetIndex = 0; packetIndex < 3; packetIndex += 1) {
        const phase = reducedMotion ? 0.22 + packetIndex * 0.24 : ((time / 2800) + packetIndex * 0.34) % 1;
        const scaled = phase * (nodes.length - 1);
        const segment = Math.min(nodes.length - 2, Math.floor(scaled));
        const local = scaled - segment;
        const from = nodes[segment];
        const to = nodes[segment + 1];
        const x = (from.x + (to.x - from.x) * local) * width;
        const y = (from.y + (to.y - from.y) * local) * height;
        const angle = Math.atan2((to.y - from.y) * height, (to.x - from.x) * width);
        homeCtx.save();
        homeCtx.translate(x, y);
        homeCtx.rotate(angle);
        homeCtx.fillStyle = packetIndex === 1 ? "rgba(143, 216, 189, 0.78)" : "rgba(215, 255, 63, 0.82)";
        homeCtx.fillRect(-13, -2, 26, 4);
        homeCtx.globalAlpha = 0.28;
        homeCtx.fillRect(-30, -1, 16, 2);
        homeCtx.restore();
      }

      nodes.forEach((node, index) => {
        const x = node.x * width;
        const y = node.y * height;
        const radius = 4 + ((index + pulse * 3) % 4);
        homeCtx.fillStyle = node.tone;
        homeCtx.globalAlpha = 0.75;
        homeCtx.beginPath();
        homeCtx.arc(x, y, radius, 0, Math.PI * 2);
        homeCtx.fill();
        homeCtx.globalAlpha = 0.22;
        homeCtx.beginPath();
        homeCtx.arc(x, y, radius * 4.2, 0, Math.PI * 2);
        homeCtx.strokeStyle = node.tone;
        homeCtx.stroke();
        homeCtx.globalAlpha = 0.72;
        homeCtx.font = '700 11px Geist, "Geist Fallback", "Noto Sans KR", "Noto Sans KR Fallback", -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
        homeCtx.fillText(node.label, x + 10, y - 10);
      });

      for (let index = 0; index < 9; index += 1) {
        const y = height * (0.2 + index * 0.075);
        const offset = reducedMotion ? 0 : (time / 60 + index * 23) % width;
        homeCtx.strokeStyle = `rgba(143, 216, 189, ${0.06 + index * 0.008})`;
        homeCtx.beginPath();
        homeCtx.moveTo(-width * 0.2 + offset, y);
        homeCtx.lineTo(width * 0.18 + offset, y - height * 0.13);
        homeCtx.stroke();
      }

      homeCtx.restore();
      if (!reducedMotion && !homePaused) homeFrameId = window.requestAnimationFrame(drawHomeSignal);
    }

    function startHomeSignal() {
      if (reducedMotion || homeFrameId !== null) return;
      homePaused = false;
      homeFrameId = window.requestAnimationFrame(drawHomeSignal);
    }

    function stopHomeSignal() {
      homePaused = true;
      if (homeFrameId !== null) {
        window.cancelAnimationFrame(homeFrameId);
        homeFrameId = null;
      }
    }

    drawHomeSignal();
    new ResizeObserver(() => {
      homeCanvasRect = fitHomeCanvas();
      if (reducedMotion) drawHomeSignal();
    }).observe(homeCanvas);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopHomeSignal();
      else {
        homePaused = false;
        if (reducedMotion) drawHomeSignal();
        else startHomeSignal();
      }
    });
  }

  const node = document.getElementById("stock-payload");
  const chartNode = document.getElementById("priceChart");
  const canvas = document.getElementById("priceChartCanvas");
  const drawingLayer = document.getElementById("chartDrawingLayer");
  const legend = document.getElementById("chartLegend");
  const fallback = document.getElementById("chartFallback");
  const tooltip = document.getElementById("chartTooltip");
  if (!node || !chartNode) return;

  const payload = JSON.parse(node.textContent || "{}");
  const chart = payload.chart || {};
  const points = (payload.chart?.points || []).filter((point) => Number.isFinite(point.close));
  const money = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
  const compact = new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 });
  const chartIndicatorStorageKey = "tradingagents.chart.indicators.v1";
  const chartSettingsStorageKey = "tradingagents.chart.settings.v1";
  const chartTrendStorageKey = `tradingagents.chart.trends.v1.${payload.code || chart.ticker_code || "stock"}.${chart.interval || "1d"}`;

  function showFallbackMessage(message) {
    if (chartNode) chartNode.hidden = true;
    if (canvas) canvas.hidden = true;
    if (fallback) {
      fallback.textContent = message;
      fallback.hidden = false;
    }
  }

  if (points.length < 1) {
    showFallbackMessage(chart.error ? `차트 데이터를 불러오지 못했습니다: ${chart.error}` : "차트 데이터가 부족합니다.");
    return;
  }

  function chartTime(value) {
    const text = String(value || "");
    if (text.includes("T") || text.includes(" ")) {
      const normalized = text.includes("T") ? text : text.replace(" ", "T");
      const parsed = Date.parse(normalized);
      return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : text.slice(0, 10);
    }
    return text.slice(0, 10);
  }

  function displayTime(value) {
    const text = String(value || "");
    if (!(text.includes("T") || text.includes(" "))) return text.slice(0, 10);
    const parsed = new Date(text.includes("T") ? text : text.replace(" ", "T"));
    if (Number.isNaN(parsed.getTime())) return text.replace("T", " ").slice(0, 16);
    const datePart = new Intl.DateTimeFormat("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).format(parsed);
    return datePart.replace(/\\. /g, "-").replace(".", "").replace(" ", " ");
  }

  function readChartIndicatorState(defaultState) {
    try {
      const saved = JSON.parse(window.localStorage.getItem(chartIndicatorStorageKey) || "{}");
      return Object.keys(defaultState).reduce((next, key) => {
        next[key] = typeof saved[key] === "boolean" ? saved[key] : defaultState[key];
        return next;
      }, {});
    } catch (_) {
      return { ...defaultState };
    }
  }

  function saveChartIndicatorState(state) {
    try {
      window.localStorage.setItem(chartIndicatorStorageKey, JSON.stringify(state));
    } catch (_) {}
  }

  function boundedNumber(value, fallback, min, max, step = 1) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    const clamped = Math.min(max, Math.max(min, parsed));
    return step === 1 ? Math.round(clamped) : Math.round(clamped / step) * step;
  }

  function normalizeChartSettings(raw = {}) {
    return {
      maFast: boundedNumber(raw.maFast, 5, 2, 60),
      maBase: boundedNumber(raw.maBase, 20, 5, 120),
      bollingerPeriod: boundedNumber(raw.bollingerPeriod, 20, 5, 80),
      bollingerDeviation: boundedNumber(raw.bollingerDeviation, 2, 1, 4, 0.5)
    };
  }

  function readChartSettings() {
    try {
      return normalizeChartSettings(JSON.parse(window.localStorage.getItem(chartSettingsStorageKey) || "{}"));
    } catch (_) {
      return normalizeChartSettings();
    }
  }

  function saveChartSettings(settings) {
    try {
      window.localStorage.setItem(chartSettingsStorageKey, JSON.stringify(settings));
    } catch (_) {}
  }

  const bars = points.map((point) => ({
    date: String(point.date || ""),
    time: chartTime(point.date),
    label: displayTime(point.date),
    open: Number.isFinite(point.open) ? Number(point.open) : Number(point.close),
    high: Number.isFinite(point.high) ? Number(point.high) : Number(point.close),
    low: Number.isFinite(point.low) ? Number(point.low) : Number(point.close),
    close: Number(point.close),
    volume: Number.isFinite(point.volume) ? Number(point.volume) : 0
  }));
  const dates = bars.map((point) => point.label);
  const closes = bars.map((point) => point.close);
  const barByTime = new Map(bars.map((bar) => [String(bar.time), bar]));
  const barByDay = new Map();
  bars.forEach((bar) => {
    const day = String(bar.date).slice(0, 10);
    if (!barByDay.has(day)) barByDay.set(day, bar);
  });
  const firstClose = closes[0];
  const lastClose = closes[closes.length - 1];
  const periodReturn = firstClose ? (lastClose - firstClose) / firstClose : null;
  const periodHigh = Math.max(...bars.map((bar) => bar.high));
  const periodLow = Math.min(...bars.map((bar) => bar.low));
  const indicatorState = readChartIndicatorState({
    ma5: true,
    ma20: true,
    ma60: false,
    ma120: false,
    bollinger: false,
    volume: true
  });
  const indicatorSettings = readChartSettings();

  function movingAverage(values, windowSize) {
    return values.map((_, index) => {
      if (index + 1 < windowSize) return null;
      const slice = values.slice(index + 1 - windowSize, index + 1);
      return slice.reduce((total, value) => total + value, 0) / windowSize;
    });
  }

  function bollingerBands(values, period, deviationMultiplier) {
    const baseAverage = movingAverage(values, period);
    return values.map((_, index) => {
      if (index + 1 < period) return null;
      const slice = values.slice(index + 1 - period, index + 1);
      const avg = baseAverage[index];
      const variance = slice.reduce((total, value) => total + ((value - avg) ** 2), 0) / slice.length;
      const deviation = Math.sqrt(variance);
      return {
        mid: avg,
        upper: avg + deviation * deviationMultiplier,
        lower: avg - deviation * deviationMultiplier
      };
    });
  }

  let ma5 = [];
  let ma20 = [];
  let ma60 = [];
  let ma120 = [];
  let ma5ByTime = new Map();
  let ma20ByTime = new Map();
  let ma60ByTime = new Map();
  let ma120ByTime = new Map();
  let bollinger = [];
  function recalculateIndicators() {
    ma5 = movingAverage(closes, indicatorSettings.maFast);
    ma20 = movingAverage(closes, indicatorSettings.maBase);
    ma60 = movingAverage(closes, 60);
    ma120 = movingAverage(closes, 120);
    ma5ByTime = new Map(bars.map((bar, index) => [String(bar.time), ma5[index]]));
    ma20ByTime = new Map(bars.map((bar, index) => [String(bar.time), ma20[index]]));
    ma60ByTime = new Map(bars.map((bar, index) => [String(bar.time), ma60[index]]));
    ma120ByTime = new Map(bars.map((bar, index) => [String(bar.time), ma120[index]]));
    bollinger = bollingerBands(closes, indicatorSettings.bollingerPeriod, indicatorSettings.bollingerDeviation);
  }
  recalculateIndicators();
  let applySimulationMarkers = () => {};
  let refreshChartIndicators = () => {};
  function isStoredTrendPoint(point) {
    return point && "time" in point && Number.isFinite(Number(point.price));
  }

  function readStoredTrendLines() {
    try {
      const saved = JSON.parse(window.localStorage.getItem(chartTrendStorageKey) || "[]");
      if (!Array.isArray(saved)) return [];
      return saved
        .filter((line) => isStoredTrendPoint(line?.start) && isStoredTrendPoint(line?.end))
        .slice(-20);
    } catch (_) {
      return [];
    }
  }

  function saveTrendLines() {
    try {
      window.localStorage.setItem(chartTrendStorageKey, JSON.stringify(trendLines.slice(-20)));
    } catch (_) {}
  }

  const trendLines = readStoredTrendLines();
  let pendingTrendPoint = null;
  let trendDrawMode = false;
  const isIntradayChart = /m$|h$/i.test(String(chart.interval || ""));

  function legendChip(label) {
    const node = document.createElement("span");
    node.textContent = label;
    return node;
  }

  function periodReturnLabel(value) {
    return Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%` : "-";
  }

  function drawLegend(bar = bars[bars.length - 1]) {
    if (!legend || !bar) return;
    const key = String(bar.time);
    const latestMa5 = ma5ByTime.get(key);
    const latestMa20 = ma20ByTime.get(key);
    const latestMa60 = ma60ByTime.get(key);
    const latestMa120 = ma120ByTime.get(key);
    const chips = [
      `기간 ${periodReturnLabel(periodReturn)}`,
      `종가 ${money.format(bar.close)}원`,
      indicatorState.volume ? `거래량 ${compact.format(bar.volume)}` : "",
      `고저 ${money.format(periodHigh)} / ${money.format(periodLow)}`,
      indicatorState.ma5 && latestMa5 ? `MA${indicatorSettings.maFast} ${money.format(latestMa5)}` : "",
      indicatorState.ma20 && latestMa20 ? `MA${indicatorSettings.maBase} ${money.format(latestMa20)}` : "",
      indicatorState.ma60 && latestMa60 ? `MA60 ${money.format(latestMa60)}` : "",
      indicatorState.ma120 && latestMa120 ? `MA120 ${money.format(latestMa120)}` : "",
      indicatorState.bollinger ? `볼린저 ${indicatorSettings.bollingerPeriod}/${indicatorSettings.bollingerDeviation}` : ""
    ];
    legend.replaceChildren(...chips.filter(Boolean).map(legendChip));
  }

  function timeKey(value) {
    if (typeof value === "string") return value;
    if (value && typeof value === "object" && "year" in value) {
      return `${value.year}-${String(value.month).padStart(2, "0")}-${String(value.day).padStart(2, "0")}`;
    }
    return String(value || "");
  }

  function markerDate(value) {
    const key = String(value || "").slice(0, 10);
    const exact = barByTime.get(String(value || ""));
    if (exact) return exact.time;
    return barByDay.get(key)?.time || "";
  }

  function baseAnalysisMarkers() {
    const tradeDate = markerDate(payload.analysis?.run?.trade_date);
    if (!tradeDate) return [];
    return [{
      time: tradeDate,
      position: "aboveBar",
      color: "#d7ff3f",
      shape: "circle",
      text: "분석"
    }];
  }

  function chartSimulationMarkers(simulationPayload) {
    const status = simulationPayload?.status || "";
    const simulation = simulationPayload?.simulation || {};
    if (status !== "available" || !simulation) return [];

    const entryDate = markerDate(simulation.entry_date);
    const exitDate = markerDate(simulation.exit_date);
    const markers = [];
    if (entryDate) {
      markers.push({
        time: entryDate,
        position: "belowBar",
        color: "#8fd8bd",
        shape: "arrowUp",
        text: "가상 매수"
      });
    }
    if (exitDate) {
      const reason = simulation.exit_reason || simulation.status;
      const isStop = reason === "stop_loss";
      markers.push({
        time: exitDate,
        position: "aboveBar",
        color: isStop ? "#ff6b4d" : "#d7ff3f",
        shape: "arrowDown",
        text: `가상 ${simulationLabel(reason)}`
      });
    }
    return markers.sort((left, right) => String(left.time).localeCompare(String(right.time)));
  }

  function updateHtmlTooltip(bar, point) {
    if (!tooltip || !bar || !point) {
      if (tooltip) tooltip.hidden = true;
      return;
    }
    const change = bar.open ? ((bar.close - bar.open) / bar.open) * 100 : 0;
    const title = document.createElement("strong");
    title.textContent = bar.label;
    const ohlc = document.createElement("span");
    ohlc.textContent = `시 ${money.format(bar.open)} / 고 ${money.format(bar.high)} / 저 ${money.format(bar.low)} / 종 ${money.format(bar.close)}`;
    const volume = document.createElement("span");
    volume.textContent = `거래량 ${compact.format(bar.volume)} / 당일 ${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
    const averages = document.createElement("span");
    const latestMa5 = ma5ByTime.get(String(bar.time));
    const latestMa20 = ma20ByTime.get(String(bar.time));
    const latestMa60 = ma60ByTime.get(String(bar.time));
    const latestMa120 = ma120ByTime.get(String(bar.time));
    averages.textContent = [
      `MA${indicatorSettings.maFast} ${latestMa5 ? money.format(latestMa5) : "-"}`,
      `MA${indicatorSettings.maBase} ${latestMa20 ? money.format(latestMa20) : "-"}`,
      `MA60 ${latestMa60 ? money.format(latestMa60) : "-"}`,
      `MA120 ${latestMa120 ? money.format(latestMa120) : "-"}`
    ].join(" / ");
    tooltip.replaceChildren(title, ohlc, volume, averages);
    tooltip.hidden = false;

    const rect = chartNode.getBoundingClientRect();
    const tooltipWidth = Math.min(320, Math.max(220, tooltip.offsetWidth || 220));
    const tooltipHeight = tooltip.offsetHeight || 92;
    const left = Math.min(rect.width - tooltipWidth - 12, Math.max(12, point.x - tooltipWidth / 2));
    const top = Math.min(rect.height - tooltipHeight - 12, Math.max(12, point.y + 12));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function setChartToolState(message) {
    const node = document.getElementById("chartToolState");
    if (node) node.textContent = message;
  }

  function updateIndicatorButtonLabels() {
    const labels = {
      ma5: `MA${indicatorSettings.maFast}`,
      ma20: `MA${indicatorSettings.maBase}`,
      ma60: "MA60",
      ma120: "MA120",
      bollinger: `볼린저 ${indicatorSettings.bollingerPeriod}/${indicatorSettings.bollingerDeviation}`,
      volume: "거래량"
    };
    Object.entries(labels).forEach(([key, label]) => {
      const button = document.querySelector(`[data-chart-indicator="${key}"]`);
      if (button) button.textContent = label;
    });
  }

  function bindIndicatorControls() {
    updateIndicatorButtonLabels();
    document.querySelectorAll("[data-chart-indicator]").forEach((button) => {
      const key = button.getAttribute("data-chart-indicator");
      if (!key || !(key in indicatorState)) return;
      button.classList.toggle("is-active", indicatorState[key]);
      button.setAttribute("aria-pressed", indicatorState[key] ? "true" : "false");
      button.addEventListener("click", () => {
        indicatorState[key] = !indicatorState[key];
        button.classList.toggle("is-active", indicatorState[key]);
        button.setAttribute("aria-pressed", indicatorState[key] ? "true" : "false");
        saveChartIndicatorState(indicatorState);
        refreshChartIndicators();
      });
    });
  }

  function bindChartSettingControls() {
    const inputs = Array.from(document.querySelectorAll("[data-chart-setting]"));
    if (!inputs.length) return;
    inputs.forEach((input) => {
      const key = input.getAttribute("data-chart-setting");
      if (key && key in indicatorSettings) input.value = String(indicatorSettings[key]);
    });
    const applyButton = document.querySelector("[data-chart-apply-settings]");
    const applySettings = () => {
      inputs.forEach((input) => {
        const key = input.getAttribute("data-chart-setting");
        if (!key || !(key in indicatorSettings)) return;
        const min = Number(input.getAttribute("min"));
        const max = Number(input.getAttribute("max"));
        const step = Number(input.getAttribute("step")) || 1;
        indicatorSettings[key] = boundedNumber(input.value, indicatorSettings[key], min, max, step);
        input.value = String(indicatorSettings[key]);
      });
      saveChartSettings(indicatorSettings);
      recalculateIndicators();
      updateIndicatorButtonLabels();
      refreshChartIndicators();
      setChartToolState(`지표 설정을 반영했습니다. MA${indicatorSettings.maFast}, MA${indicatorSettings.maBase}, 볼린저 ${indicatorSettings.bollingerPeriod}/${indicatorSettings.bollingerDeviation}`);
    };
    applyButton?.addEventListener("click", applySettings);
    inputs.forEach((input) => {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") applySettings();
      });
    });
  }

  function updateTrendLayer(chartApi, candleSeries) {
    if (!drawingLayer || !chartApi || !candleSeries) return;
    const rect = chartNode.getBoundingClientRect();
    drawingLayer.setAttribute("viewBox", `0 0 ${Math.max(1, rect.width)} ${Math.max(1, rect.height)}`);
    drawingLayer.replaceChildren(...trendLines.map((line) => {
      const x1 = chartApi.timeScale().timeToCoordinate(line.start.time);
      const y1 = candleSeries.priceToCoordinate(line.start.price);
      const x2 = chartApi.timeScale().timeToCoordinate(line.end.time);
      const y2 = candleSeries.priceToCoordinate(line.end.price);
      if (![x1, y1, x2, y2].every((value) => Number.isFinite(value))) return null;
      const node = document.createElementNS("http://www.w3.org/2000/svg", "line");
      node.setAttribute("x1", String(x1));
      node.setAttribute("y1", String(y1));
      node.setAttribute("x2", String(x2));
      node.setAttribute("y2", String(y2));
      return node;
    }).filter(Boolean));
  }

  function setupTrendDrawing(chartApi, candleSeries) {
    const drawButton = document.querySelector("[data-chart-draw-trend]");
    const clearButton = document.querySelector("[data-chart-clear-trends]");
    if (!drawButton || !chartApi || !candleSeries) return;
    drawButton.addEventListener("click", () => {
      trendDrawMode = !trendDrawMode;
      pendingTrendPoint = null;
      drawButton.classList.toggle("is-active", trendDrawMode);
      drawButton.setAttribute("aria-pressed", trendDrawMode ? "true" : "false");
      chartNode.classList.toggle("is-drawing-trend", trendDrawMode);
      setChartToolState(trendDrawMode ? "추세선 시작점을 클릭하세요." : "추세선은 시작점과 끝점을 차례로 클릭해 그립니다.");
    });
    clearButton?.addEventListener("click", () => {
      trendLines.splice(0, trendLines.length);
      pendingTrendPoint = null;
      saveTrendLines();
      updateTrendLayer(chartApi, candleSeries);
      setChartToolState("추세선을 모두 지웠습니다.");
    });
    chartNode.addEventListener("pointerdown", (event) => {
      if (!trendDrawMode) return;
      const rect = chartNode.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const time = chartApi.timeScale().coordinateToTime(x);
      const price = candleSeries.coordinateToPrice(y);
      if (!time || !Number.isFinite(price)) return;
      event.preventDefault();
      const point = { time, price };
      if (!pendingTrendPoint) {
        pendingTrendPoint = point;
        setChartToolState("추세선 끝점을 클릭하세요.");
        return;
      }
      trendLines.push({ start: pendingTrendPoint, end: point });
      pendingTrendPoint = null;
      trendDrawMode = false;
      drawButton.classList.remove("is-active");
      drawButton.setAttribute("aria-pressed", "false");
      chartNode.classList.remove("is-drawing-trend");
      saveTrendLines();
      updateTrendLayer(chartApi, candleSeries);
      setChartToolState("추세선을 추가했습니다.");
    });
    if (typeof chartApi.timeScale().subscribeVisibleTimeRangeChange === "function") {
      chartApi.timeScale().subscribeVisibleTimeRangeChange(() => updateTrendLayer(chartApi, candleSeries));
    }
    if (trendLines.length) {
      setChartToolState(`저장된 추세선 ${trendLines.length}개를 불러왔습니다.`);
      updateTrendLayer(chartApi, candleSeries);
    }
  }

  function setupChartFitControl(chartApi, candleSeries) {
    const fitButton = document.querySelector("[data-chart-fit]");
    if (!fitButton || !chartApi) return;
    fitButton.addEventListener("click", () => {
      chartApi.timeScale().fitContent();
      updateTrendLayer(chartApi, candleSeries);
      setChartToolState("전체 기간을 화면에 맞췄습니다.");
    });
  }

  function renderTradingViewChart() {
    const TV = window.LightweightCharts;
    if (!TV || typeof TV.createChart !== "function") return false;
    if (fallback) fallback.hidden = true;
    if (canvas) canvas.hidden = true;
    chartNode.hidden = false;

    const rect = chartNode.getBoundingClientRect();
    const chartApi = TV.createChart(chartNode, {
      width: Math.max(320, Math.floor(rect.width || chartNode.clientWidth || 720)),
      height: Math.max(260, Math.floor(rect.height || chartNode.clientHeight || 420)),
      layout: {
        background: { type: TV.ColorType?.Solid || "solid", color: "transparent" },
        textColor: "rgba(246, 243, 232, 0.72)",
        fontFamily: 'Geist, "Geist Fallback", "Noto Sans KR", "Noto Sans KR Fallback", -apple-system, BlinkMacSystemFont, system-ui, sans-serif'
      },
      grid: {
        vertLines: { color: "rgba(246, 243, 232, 0.06)" },
        horzLines: { color: "rgba(246, 243, 232, 0.09)" }
      },
      crosshair: {
        mode: TV.CrosshairMode?.Normal ?? 0,
        vertLine: {
          color: "rgba(215, 255, 63, 0.38)",
          labelBackgroundColor: "#1f2a15"
        },
        horzLine: {
          color: "rgba(143, 216, 189, 0.42)",
          labelBackgroundColor: "#1a2a22"
        }
      },
      localization: {
        priceFormatter: (price) => `${money.format(price)}원`
      },
      rightPriceScale: {
        borderColor: "rgba(246, 243, 232, 0.14)",
        scaleMargins: { top: 0.08, bottom: 0.3 }
      },
      timeScale: {
        borderColor: "rgba(246, 243, 232, 0.14)",
        fixLeftEdge: true,
        fixRightEdge: true,
        timeVisible: isIntradayChart,
        secondsVisible: false
      }
    });

    const candleSeries = chartApi.addSeries(TV.CandlestickSeries, {
      upColor: "#ff6b4d",
      downColor: "#6da4ff",
      borderUpColor: "#ff6b4d",
      borderDownColor: "#6da4ff",
      wickUpColor: "#ff9b86",
      wickDownColor: "#9cc3ff",
      priceLineColor: "#d7ff3f"
    });
    candleSeries.setData(bars.map((bar) => ({
      time: bar.time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close
    })));

    const volumeSeries = chartApi.addSeries(TV.HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      priceLineVisible: false,
      lastValueVisible: false
    });
    volumeSeries.setData(bars.map((bar) => ({
      time: bar.time,
      value: bar.volume,
      color: bar.close >= bar.open ? "rgba(255, 107, 77, 0.28)" : "rgba(109, 164, 255, 0.24)"
    })));

    function indicatorLineData(values) {
      return bars
        .map((bar, index) => (Number.isFinite(values[index]) ? { time: bar.time, value: values[index] } : null))
        .filter(Boolean);
    }

    function bollingerLineData(edge) {
      return bars
        .map((bar, index) => (bollinger[index] ? { time: bar.time, value: bollinger[index][edge] } : null))
        .filter(Boolean);
    }

    const ma5Series = chartApi.addSeries(TV.LineSeries, {
      color: "#d7ff3f",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false
    });
    ma5Series.setData([]);

    const ma20Series = chartApi.addSeries(TV.LineSeries, {
      color: "#c79a3a",
      lineWidth: 2,
      lineStyle: TV.LineStyle?.Dashed ?? 2,
      priceLineVisible: false,
      lastValueVisible: false
    });
    ma20Series.setData([]);

    const ma60Series = chartApi.addSeries(TV.LineSeries, {
      color: "#8fd8bd",
      lineWidth: 2,
      lineStyle: TV.LineStyle?.Dotted ?? 1,
      priceLineVisible: false,
      lastValueVisible: false
    });
    ma60Series.setData([]);

    const ma120Series = chartApi.addSeries(TV.LineSeries, {
      color: "#b6a6ff",
      lineWidth: 2,
      lineStyle: TV.LineStyle?.Dotted ?? 1,
      priceLineVisible: false,
      lastValueVisible: false
    });
    ma120Series.setData([]);

    const bollUpperSeries = chartApi.addSeries(TV.LineSeries, {
      color: "rgba(143, 216, 189, 0.62)",
      lineWidth: 1,
      lineStyle: TV.LineStyle?.Dashed ?? 2,
      priceLineVisible: false,
      lastValueVisible: false
    });
    const bollLowerSeries = chartApi.addSeries(TV.LineSeries, {
      color: "rgba(143, 216, 189, 0.62)",
      lineWidth: 1,
      lineStyle: TV.LineStyle?.Dashed ?? 2,
      priceLineVisible: false,
      lastValueVisible: false
    });
    bollUpperSeries.setData([]);
    bollLowerSeries.setData([]);

    const volumeData = bars.map((bar) => ({
      time: bar.time,
      value: bar.volume,
      color: bar.close >= bar.open ? "rgba(255, 107, 77, 0.28)" : "rgba(109, 164, 255, 0.24)"
    }));
    refreshChartIndicators = () => {
      ma5Series.setData(indicatorState.ma5 ? indicatorLineData(ma5) : []);
      ma20Series.setData(indicatorState.ma20 ? indicatorLineData(ma20) : []);
      ma60Series.setData(indicatorState.ma60 ? indicatorLineData(ma60) : []);
      ma120Series.setData(indicatorState.ma120 ? indicatorLineData(ma120) : []);
      bollUpperSeries.setData(indicatorState.bollinger ? bollingerLineData("upper") : []);
      bollLowerSeries.setData(indicatorState.bollinger ? bollingerLineData("lower") : []);
      volumeSeries.setData(indicatorState.volume ? volumeData : []);
      drawLegend();
    };
    refreshChartIndicators();

    chartApi.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.3 } });
    chartApi.priceScale("volume").applyOptions({ scaleMargins: { top: 0.76, bottom: 0 } });

    const latest = bars[bars.length - 1];
    candleSeries.createPriceLine({
      price: latest.close,
      color: "#d7ff3f",
      lineWidth: 1,
      lineStyle: TV.LineStyle?.Dashed ?? 2,
      axisLabelVisible: true,
      title: "최근"
    });

    let markerApi = null;
    function setChartMarkers(markers) {
      if (typeof TV.createSeriesMarkers !== "function") return;
      if (markerApi && typeof markerApi.setMarkers === "function") {
        markerApi.setMarkers(markers);
        return;
      }
      markerApi = TV.createSeriesMarkers(candleSeries, markers);
    }
    applySimulationMarkers = (simulationPayload) => {
      const markers = [...baseAnalysisMarkers(), ...chartSimulationMarkers(simulationPayload)]
        .sort((left, right) => String(left.time).localeCompare(String(right.time)));
      setChartMarkers(markers);
    };
    applySimulationMarkers(null);

    chartApi.subscribeCrosshairMove((param) => {
      if (!param?.point || !param.time) {
        updateHtmlTooltip(null);
        drawLegend();
        return;
      }
      const key = timeKey(param.time);
      const bar = barByTime.get(key);
      updateHtmlTooltip(bar, param.point);
      drawLegend(bar);
    });

    setupTrendDrawing(chartApi, candleSeries);
    setupChartFitControl(chartApi, candleSeries);

    const resize = () => {
      const nextRect = chartNode.getBoundingClientRect();
      chartApi.applyOptions({
        width: Math.max(320, Math.floor(nextRect.width || 720)),
        height: Math.max(260, Math.floor(nextRect.height || 420))
      });
      chartApi.timeScale().fitContent();
      updateTrendLayer(chartApi, candleSeries);
    };
    if ("ResizeObserver" in window) {
      new ResizeObserver(resize).observe(chartNode);
    } else {
      window.addEventListener("resize", resize);
    }
    resize();
    drawLegend();
    return true;
  }

  function renderCanvasFallback() {
    if (!canvas) return false;
    if (fallback) fallback.hidden = true;
    chartNode.hidden = true;
    canvas.hidden = false;
    const ctx = canvas.getContext("2d");
    const priceValues = bars.flatMap((point) => [point.open, point.high, point.low, point.close]);
    const min = Math.min(...priceValues);
    const max = Math.max(...priceValues);
    const maxVolume = Math.max(...bars.map((point) => point.volume), 1);
    const pad = Math.max((max - min) * 0.12, max * 0.01, 1);
    const yMin = min - pad;
    const yMax = max + pad;
    let hoverIndex = null;

    function fitCanvas() {
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      return rect;
    }

    function xAt(index, width, left, right) {
      if (bars.length === 1) return left;
      return left + (index / (bars.length - 1)) * (width - left - right);
    }

    function yAt(value, top, bottom) {
      return top + ((yMax - value) / (yMax - yMin)) * (bottom - top);
    }

    function drawLine(values, width, left, right, top, bottom, color, dash = []) {
      ctx.beginPath();
      let started = false;
      values.forEach((value, index) => {
        if (!Number.isFinite(value)) return;
        const x = xAt(index, width, left, right);
        const y = yAt(value, top, bottom);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      });
      if (!started) return;
      ctx.save();
      ctx.setLineDash(dash);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.8;
      ctx.stroke();
      ctx.restore();
    }

    function chartLayout(width, height) {
      const left = width < 520 ? 48 : 62;
      const right = width < 520 ? 12 : 24;
      const top = 34;
      const bottom = 42;
      const volumeHeight = Math.min(92, Math.max(52, height * 0.22));
      const priceBottom = height - bottom - volumeHeight - 18;
      const volumeTop = priceBottom + 12;
      const volumeBottom = height - bottom;
      const slot = (width - left - right) / Math.max(bars.length - 1, 1);
      const candleWidth = Math.max(3, Math.min(12, slot * 0.58));
      return { left, right, top, bottom, volumeHeight, priceBottom, volumeTop, volumeBottom, slot, candleWidth };
    }

    function nearestIndex(mouseX, width, left, right) {
      const span = Math.max(1, width - left - right);
      const ratio = Math.min(1, Math.max(0, (mouseX - left) / span));
      return Math.min(bars.length - 1, Math.max(0, Math.round(ratio * (bars.length - 1))));
    }

    function updateCanvasTooltip(index, rect, layout) {
      if (index === null || index === undefined) {
        updateHtmlTooltip(null);
        return;
      }
      const bar = bars[index];
      const x = xAt(index, rect.width, layout.left, layout.right);
      updateHtmlTooltip(bar, { x, y: 18 });
    }

    function draw() {
      const rect = fitCanvas();
      const width = rect.width;
      const height = rect.height;
      const layout = chartLayout(width, height);
      const { left, right, top, priceBottom, volumeTop, volumeBottom, candleWidth } = layout;

      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#111711";
      ctx.fillRect(0, 0, width, height);

      ctx.strokeStyle = "rgba(246, 243, 232, 0.13)";
      ctx.lineWidth = 1;
      ctx.fillStyle = "rgba(246, 243, 232, 0.68)";
      ctx.font = '12px Geist, "Geist Fallback", "Noto Sans KR", "Noto Sans KR Fallback", -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
      ctx.textBaseline = "middle";

      for (let i = 0; i <= 4; i += 1) {
        const y = top + (i / 4) * (priceBottom - top);
        const value = yMax - (i / 4) * (yMax - yMin);
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(width - right, y);
        ctx.stroke();
        ctx.fillText(money.format(value), 0, y);
      }

      ctx.strokeStyle = "rgba(246, 243, 232, 0.16)";
      ctx.beginPath();
      ctx.moveTo(left, volumeTop);
      ctx.lineTo(width - right, volumeTop);
      ctx.stroke();

      bars.forEach((bar, index) => {
        const x = xAt(index, width, left, right);
        const isUp = bar.close >= bar.open;
        const color = isUp ? "#ff6b4d" : "#6da4ff";
        const volumeY = volumeBottom - (bar.volume / maxVolume) * (volumeBottom - volumeTop);
        if (indicatorState.volume) {
          ctx.fillStyle = isUp ? "rgba(255, 107, 77, 0.22)" : "rgba(109, 164, 255, 0.2)";
          ctx.fillRect(x - candleWidth / 2, volumeY, candleWidth, Math.max(1, volumeBottom - volumeY));
        }
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1.2;
        const highY = yAt(bar.high, top, priceBottom);
        const lowY = yAt(bar.low, top, priceBottom);
        const openY = yAt(bar.open, top, priceBottom);
        const closeY = yAt(bar.close, top, priceBottom);
        ctx.beginPath();
        ctx.moveTo(x, highY);
        ctx.lineTo(x, lowY);
        ctx.stroke();
        const bodyTop = Math.min(openY, closeY);
        const bodyHeight = Math.max(1.5, Math.abs(closeY - openY));
        ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
      });

      drawLine(closes, width, left, right, top, priceBottom, "rgba(143, 216, 189, 0.9)");
      if (indicatorState.ma5) drawLine(ma5, width, left, right, top, priceBottom, "#d7ff3f");
      if (indicatorState.ma20) drawLine(ma20, width, left, right, top, priceBottom, "#c79a3a", [4, 4]);
      if (indicatorState.ma60) drawLine(ma60, width, left, right, top, priceBottom, "#8fd8bd", [2, 4]);
      if (indicatorState.ma120) drawLine(ma120, width, left, right, top, priceBottom, "#b6a6ff", [2, 5]);
      if (indicatorState.bollinger) {
        drawLine(bollinger.map((item) => item?.upper ?? null), width, left, right, top, priceBottom, "rgba(143, 216, 189, 0.7)", [5, 5]);
        drawLine(bollinger.map((item) => item?.lower ?? null), width, left, right, top, priceBottom, "rgba(143, 216, 189, 0.7)", [5, 5]);
      }

      const lastClose = closes[closes.length - 1];
      const lastX = xAt(bars.length - 1, width, left, right);
      const lastY = yAt(lastClose, top, priceBottom);
      ctx.fillStyle = "#d7ff3f";
      ctx.beginPath();
      ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
      ctx.fill();

      if (hoverIndex !== null) {
        const hovered = bars[hoverIndex];
        const hoverX = xAt(hoverIndex, width, left, right);
        const hoverY = yAt(hovered.close, top, priceBottom);
        ctx.save();
        ctx.strokeStyle = "rgba(246, 243, 232, 0.32)";
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(hoverX, top);
        ctx.lineTo(hoverX, volumeBottom);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#f6f3e8";
        ctx.beginPath();
        ctx.arc(hoverX, hoverY, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      ctx.fillStyle = "rgba(246, 243, 232, 0.68)";
      ctx.textBaseline = "alphabetic";
      ctx.fillText(dates[0], left, height - 12);
      ctx.textAlign = "right";
      ctx.fillText(dates[dates.length - 1], width - right, height - 12);
      ctx.textAlign = "left";
      drawLegend();
    }

    draw();
    window.addEventListener("resize", draw);
    canvas.addEventListener("pointermove", (event) => {
      const rect = canvas.getBoundingClientRect();
      const layout = chartLayout(rect.width, rect.height);
      hoverIndex = nearestIndex(event.clientX - rect.left, rect.width, layout.left, layout.right);
      updateCanvasTooltip(hoverIndex, rect, layout);
      draw();
    });
    canvas.addEventListener("pointerleave", () => {
      hoverIndex = null;
      updateHtmlTooltip(null);
      draw();
    });
    refreshChartIndicators = draw;
    drawLegend();
    return true;
  }

  async function bootStockPageChart() {
    let chartRendered = false;
    try {
      chartRendered = renderTradingViewChart();
    } catch (error) {
      chartRendered = false;
    }
    if (!chartRendered) renderCanvasFallback();
    bindIndicatorControls();
    bindChartSettingControls();

    const simulationNode = document.getElementById("simulationPreview");
    if (simulationNode) {
      loadSimulationPreview(simulationNode);
    }
  }

  bootStockPageChart();

  function pct(value) {
    if (!Number.isFinite(value)) return "-";
    return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
  }

  function simulationLabel(value) {
    const labels = {
      take_profit: "익절",
      stop_loss: "손절",
      max_holding_days: "기간 만료",
      no_completed_analysis: "리포트 필요",
      no_decision: "의견 없음",
      insufficient_price_data: "가격 부족",
      not_configured: "준비 중",
      skipped: "대기",
      open: "가상 보유",
      closed: "청산 완료",
      paper_position_open: "가상 보유",
      paper_position_closed: "청산 완료"
    };
    return labels[value] || String(value || "-");
  }

  function renderSimulationState(node, payload) {
    applySimulationMarkers(payload);
    const status = payload?.status || "unavailable";
    const simulation = payload?.simulation || {};
    if (status !== "available") {
      const pill = document.createElement("span");
      pill.className = "status-pill";
      pill.textContent = simulationLabel(status);
      const copy = document.createElement("p");
      copy.textContent = status === "no_completed_analysis"
        ? "분석 리포트가 완료되면 가상 매수·매도 기록을 계산합니다."
        : "AI 가상매매 기록을 아직 만들 수 없습니다.";
      node.replaceChildren(pill, copy);
      return;
    }

    const pill = document.createElement("span");
    pill.className = "status-pill";
    pill.textContent = simulationLabel(simulation.status);
    const grid = document.createElement("div");
    grid.className = "simulation-grid";
    const rows = [
      ["가상 매수", simulation.entry_date || "-"],
      ["가상 청산", simulation.exit_date || "-"],
      ["수익률", simulation.status === "open" ? pct(Number(simulation.unrealized_return)) : pct(Number(simulation.portfolio_return))],
      ["기준", simulationLabel(simulation.exit_reason || simulation.message)]
    ];
    rows.forEach(([label, value]) => {
      const cell = document.createElement("div");
      const name = document.createElement("span");
      name.textContent = label;
      const metric = document.createElement("strong");
      metric.textContent = value;
      cell.replaceChildren(name, metric);
      grid.append(cell);
    });
    node.replaceChildren(pill, grid);
  }

  async function loadSimulationPreview(node) {
    const url = node.dataset.simulationUrl;
    if (!url) return;
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("simulation_preview_failed");
      renderSimulationState(node, await response.json());
    } catch (error) {
      renderSimulationState(node, { status: "not_configured" });
    }
  }
})();
"""


ADMIN_PAGE_JS = """
(() => {
  const tokenKey = "tradingagents.admin.worker_token";
  const tokenForm = document.getElementById("adminTokenForm");
  const tokenInput = document.getElementById("adminWorkerToken");
  const tokenClearButton = document.querySelector("[data-admin-token-clear]");
  const tokenState = document.getElementById("adminTokenState");
  const readinessOutput = document.getElementById("adminReadinessOutput");
  const readinessPanel = document.getElementById("adminReadinessPanel");
  const opsOutput = document.getElementById("adminOpsOutput");
  const opsSummary = document.getElementById("adminOpsSummary");
  const recentPanel = document.getElementById("adminRecentPanel");
  const requestsOutput = document.getElementById("adminRequestsOutput");
  const outcomesOutput = document.getElementById("adminOutcomesOutput");
  const paperSimulationOutput = document.getElementById("adminPaperSimulationOutput");
  const requestsPanel = document.getElementById("adminRequestsPanel");
  const outcomesPanel = document.getElementById("adminOutcomesPanel");
  const paperSimulationPanel = document.getElementById("adminPaperSimulationPanel");
  const requestLimit = document.getElementById("adminRequestLimit");
  const outcomeLimit = document.getElementById("adminOutcomeLimit");
  const paperSimulationLimit = document.getElementById("adminPaperSimulationLimit");
  const requestLimitHint = document.getElementById("adminRequestLimitHint");
  const outcomeLimitHint = document.getElementById("adminOutcomeLimitHint");
  const paperSimulationLimitHint = document.getElementById("adminPaperSimulationLimitHint");
  const probeKrx = document.getElementById("adminProbeKrx");
  const probeVendors = document.getElementById("adminProbeVendors");
  const dryRunReadyMs = 10 * 60 * 1000;
  const lastDryRunAt = {
    requests: 0,
    outcomes: 0,
    paper: 0
  };

  function savedToken() {
    return sessionStorage.getItem(tokenKey) || "";
  }

  function currentToken() {
    return (tokenInput?.value || "").trim() || savedToken();
  }

  function requiresOperationToken(button) {
    return Boolean(button?.matches("[data-admin-action], [data-admin-ops-summary]"));
  }

  function syncAdminAccessControls() {
    const hasToken = Boolean(currentToken());
    document.querySelectorAll("[data-admin-action], [data-admin-ops-summary]").forEach((button) => {
      if (button.getAttribute("aria-busy") === "true") return;
      button.disabled = !hasToken;
      button.title = hasToken ? "" : "운영 토큰을 먼저 입력하세요.";
    });
    [requestLimit, outcomeLimit, paperSimulationLimit].forEach((control) => {
      if (control) control.disabled = !hasToken;
    });
    document.body.classList.toggle("admin-token-ready", hasToken);
    if (tokenState && !hasToken) {
      tokenState.textContent = "운영 토큰을 입력하면 대기열 조회와 작업 실행 버튼이 활성화됩니다.";
    }
  }

  function clearSavedToken(message = "저장된 운영 토큰을 지웠습니다.") {
    sessionStorage.removeItem(tokenKey);
    if (tokenInput) tokenInput.value = "";
    if (tokenState) tokenState.textContent = message;
    window.dispatchEvent(new Event("tradingagents:admin-token"));
    syncAdminAccessControls();
  }

  function setOutput(node, payload) {
    if (!node) return;
    node.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  }

  function setBusy(button, isBusy) {
    if (!button) return;
    button.setAttribute("aria-busy", isBusy ? "true" : "false");
    button.disabled = isBusy || (requiresOperationToken(button) && !currentToken());
  }

  function positiveInt(value, fallback = 1) {
    const number = Math.floor(Number(value));
    return Number.isFinite(number) && number > 0 ? number : fallback;
  }

  function syncLimitControl(control, hint, maxValue) {
    if (!control) return;
    const max = positiveInt(maxValue, positiveInt(control.max, 1));
    control.max = String(max);
    const current = positiveInt(control.value, max);
    if (current > max) control.value = String(max);
    if (hint) hint.textContent = `현재 최대 ${max}건`;
  }

  function syncWorkerLimits(limits = {}) {
    syncLimitControl(requestLimit, requestLimitHint, limits.analysis_worker_max);
    syncLimitControl(outcomeLimit, outcomeLimitHint, limits.outcome_worker_max);
    syncLimitControl(paperSimulationLimit, paperSimulationLimitHint, limits.paper_simulation_worker_max);
  }

  function limitFromControl(control) {
    if (!control) return 1;
    const max = positiveInt(control.max, 1);
    const requested = positiveInt(control.value, 1);
    const limit = Math.min(requested, max);
    if (String(limit) !== String(control.value)) control.value = String(limit);
    return limit;
  }

  function readinessText(value) {
    return value ? "OK" : "확인 필요";
  }

  function quotaSignalText(probe) {
    if (!probe) return "요청 제한 확인 대기";
    if (probe.quota_signal === "headers_present") return "요청 제한 헤더 감지";
    if (probe.quota_signal === "wrapper_no_headers") return "요청 제한 헤더 없음";
    return "요청 제한 헤더 미제공";
  }

  function probeSummary(probe, fallback = "probe 대기") {
    if (!probe) return fallback;
    const status = probe.status || "unknown";
    const elapsed = `${probe.elapsed_ms || 0}ms`;
    const requests = probe.request_count ? `req ${probe.request_count}` : "req 1";
    const count = probe.row_count !== undefined
      ? `rows ${probe.row_count || 0}`
      : probe.item_count !== undefined
        ? `items ${probe.item_count || 0}`
        : "";
    return [status, elapsed, requests, count, quotaSignalText(probe)].filter(Boolean).join(" · ");
  }

  function appendReadinessCell(fragment, label, value, note, state = "is-waiting") {
    const cell = document.createElement("div");
    cell.className = `readiness-cell ${state}`;

    const labelNode = document.createElement("span");
    labelNode.textContent = label;
    cell.appendChild(labelNode);

    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    cell.appendChild(valueNode);

    const noteNode = document.createElement("small");
    noteNode.textContent = note;
    cell.appendChild(noteNode);

    fragment.appendChild(cell);
  }

  function appendOpsCell(fragment, label, value, note, state = "is-waiting") {
    const cell = document.createElement("div");
    cell.className = `ops-cell ${state}`;

    const labelNode = document.createElement("span");
    labelNode.textContent = label;
    cell.appendChild(labelNode);

    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    cell.appendChild(valueNode);

    const noteNode = document.createElement("small");
    noteNode.textContent = note;
    cell.appendChild(noteNode);

    fragment.appendChild(cell);
  }

  function appendActionCell(fragment, label, value, note, state = "is-waiting") {
    const cell = document.createElement("div");
    cell.className = `action-cell ${state}`;

    const labelNode = document.createElement("span");
    labelNode.textContent = label;
    cell.appendChild(labelNode);

    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    cell.appendChild(valueNode);

    const noteNode = document.createElement("small");
    noteNode.textContent = note;
    cell.appendChild(noteNode);

    fragment.appendChild(cell);
  }

  function percentLabel(value) {
    if (value === null || value === undefined || value === "") return "-";
    const number = Number(value);
    return Number.isFinite(number) ? `${(number * 100).toFixed(2)}%` : "-";
  }

  function countByStatus(rows) {
    return (Array.isArray(rows) ? rows : []).reduce((acc, row) => {
      const status = row?.status || "unknown";
      acc[status] = (acc[status] || 0) + 1;
      return acc;
    }, {});
  }

  function opsStatusLabel(value) {
    return {
      queued: "대기",
      running: "처리 중",
      completed: "완료",
      failed: "실패",
      pending: "보류",
      unavailable: "데이터 없음",
      skipped: "건너뜀",
      dry_run: "실행 전 확인"
    }[value] || value || "-";
  }

  function opsReasonLabel(value) {
    return {
      already_completed: "이미 처리됨",
      insufficient_holding_days: "확인 기간 부족",
      return_data_unavailable: "수익률 데이터 없음",
      no_completed_public_analysis: "완료된 공개 리포트 없음",
      simulation_only_no_orders: "가상매매 전용"
    }[value] || value || "다음 자동 처리에서 재확인";
  }

  function actionErrorNote(rows) {
    const errors = (Array.isArray(rows) ? rows : [])
      .filter((row) => row?.error && row.error !== "already_completed")
      .slice(0, 2)
      .map((row) => {
        const ticker = row.ticker_code || row.request_id || row.analysis_run_id || "항목";
        const horizon = row.horizon_days ? ` ${row.horizon_days}일` : "";
        return `${ticker}${horizon}: ${opsReasonLabel(row.error)}`;
      });
    return errors.length ? errors.join(" · ") : "실패 로그 없음";
  }

  function requestLabel(item) {
    if (!item) return "항목 없음";
    const ticker = [item.ticker_name, item.ticker_code].filter(Boolean).join(" ");
    const date = item.requested_trade_date || item.created_at || "-";
    return `${ticker || item.id || "request"} / ${item.status || "-"} / ${date}`;
  }

  function outcomeLabel(item) {
    if (!item) return "항목 없음";
    const ticker = [item.ticker_name, item.ticker_code].filter(Boolean).join(" ");
    const horizon = item.horizon_days ? `${item.horizon_days}일` : "리포트";
    const alpha = item.alpha_return === null || item.alpha_return === undefined
      ? "시장 대비 -"
      : `시장 대비 ${(Number(item.alpha_return) * 100).toFixed(2)}%`;
    return `${ticker || item.id || "outcome"} / ${horizon} / ${alpha}`;
  }

  function outcomeIssueLabel(item) {
    if (!item) return "항목 없음";
    const ticker = [item.ticker_name, item.ticker_code].filter(Boolean).join(" ");
    const horizon = item.horizon_days ? `${item.horizon_days}일` : "리포트";
    const status = opsStatusLabel(item.status);
    const reason = opsReasonLabel(item.error || item.evaluated_at);
    return `${ticker || item.id || "사후 결과"} / ${horizon} / ${status} / ${reason}`;
  }

  function runLabel(item) {
    if (!item) return "항목 없음";
    const ticker = [item.ticker_name, item.ticker_code].filter(Boolean).join(" ");
    return `${ticker || item.id || "리포트"} / ${item.trade_date || "-"} / ${opsStatusLabel(item.status)}`;
  }

  function paperCandidateLabel(item) {
    if (!item) return "항목 없음";
    const ticker = [item.ticker_name, item.ticker_code].filter(Boolean).join(" ");
    const decision = [item.decision_rating, item.decision_action].filter(Boolean).join("/");
    return `${ticker || item.analysis_run_id || "run"} / ${item.trade_date || "-"} / ${decision || "AI"}`;
  }

  function paperOpenLabel(item) {
    if (!item) return "항목 없음";
    const ticker = [item.ticker_name, item.ticker_code].filter(Boolean).join(" ");
    return `${ticker || item.id || "position"} / 진입 ${item.entry_date || "-"} / ${percentLabel(item.unrealized_return)}`;
  }

  function renderRecentList(title, label, items, formatter) {
    const section = document.createElement("section");
    section.className = "admin-recent-list";
    const eyebrow = document.createElement("span");
    eyebrow.textContent = label;
    section.appendChild(eyebrow);
    const heading = document.createElement("strong");
    heading.textContent = title;
    section.appendChild(heading);
    const list = document.createElement("ul");
    const rows = Array.isArray(items) ? items.slice(0, 4) : [];
    if (!rows.length) {
      const empty = document.createElement("li");
      empty.textContent = "표시할 항목이 없습니다.";
      list.appendChild(empty);
    } else {
      rows.forEach((item) => {
        const row = document.createElement("li");
        const link = item.report_path ? document.createElement("a") : null;
        if (link) {
          link.href = item.report_path;
          link.textContent = formatter(item);
          row.appendChild(link);
        } else {
          row.textContent = formatter(item);
        }
        list.appendChild(row);
      });
    }
    section.appendChild(list);
    return section;
  }

  function renderOpsSummaryPending(message) {
    if (!opsSummary) return;
    opsSummary.textContent = "";
    recentPanel && (recentPanel.textContent = "");
    const fragment = document.createDocumentFragment();
    appendOpsCell(fragment, "운영", "확인 중", message, "is-waiting");
    opsSummary.appendChild(fragment);
  }

  function renderOpsSummaryError(message) {
    if (!opsSummary) return;
    opsSummary.textContent = "";
    recentPanel && (recentPanel.textContent = "");
    const fragment = document.createDocumentFragment();
    appendOpsCell(fragment, "운영", "오류", message, "is-error");
    opsSummary.appendChild(fragment);
  }

  function renderOpsSummary(payload) {
    if (!opsSummary) return;
    const requests = payload?.analysis_requests || {};
    const counts = requests.counts || {};
    const recent = requests.recent || {};
    const outcomes = payload?.outcomes || {};
    const paper = payload?.paper_simulations || {};
    const limits = payload?.limits || {};
    const fragment = document.createDocumentFragment();
    opsSummary.textContent = "";
    syncWorkerLimits(limits);

    const active = Number(requests.active_count || 0);
    const failed = Number(requests.failed_count || 0);
    const candidates = Array.isArray(outcomes.candidate_runs) ? outcomes.candidate_runs.length : 0;
    const completedOutcomes = Array.isArray(outcomes.recent_completed) ? outcomes.recent_completed.length : 0;
    const paperCandidates = Array.isArray(paper.candidate_runs) ? paper.candidate_runs.length : 0;
    const openPaperPositions = Array.isArray(paper.open_positions) ? paper.open_positions.length : 0;
    appendOpsCell(fragment, "처리 중 요청", String(active), `대기 ${counts.queued || 0} · 처리 중 ${counts.running || 0}`, active ? "is-warn" : "is-ok");
    appendOpsCell(fragment, "완료", String(counts.completed || 0), "완료된 분석 요청 누적", "is-ok");
    appendOpsCell(fragment, "실패", String(failed), "최근 실패 목록은 아래에서 확인", failed ? "is-error" : "is-ok");
    appendOpsCell(fragment, "기록 후보", String(candidates), `확인 한도 ${limits.outcome_worker_max || "-"}`, candidates ? "is-warn" : "is-ok");
    appendOpsCell(fragment, "최근 기록", String(completedOutcomes), `대기 샘플 ${outcomes.pending_sample_count || 0} · 데이터 없음 샘플 ${outcomes.unavailable_sample_count || 0}`, "is-ok");
    appendOpsCell(fragment, "AI 가상매매", String(paperCandidates + openPaperPositions), `대기 ${paperCandidates} · 가상 보유 ${paper.open_count || 0} · 청산 ${paper.closed_count || 0}`, (paperCandidates + openPaperPositions) ? "is-warn" : "is-ok");
    opsSummary.appendChild(fragment);

    if (recentPanel) {
      recentPanel.textContent = "";
      recentPanel.appendChild(renderRecentList("대기/처리 중", "대기열", [...(recent.queued || []), ...(recent.running || [])], requestLabel));
      recentPanel.appendChild(renderRecentList("최근 실패", "실패", recent.failed || [], requestLabel));
      recentPanel.appendChild(renderRecentList("기록 후보", "사후 결과", outcomes.candidate_runs || [], runLabel));
      recentPanel.appendChild(renderRecentList("최근 완료 기록", "결과", outcomes.recent_completed || [], outcomeLabel));
      recentPanel.appendChild(renderRecentList("보류/데이터 없음", "확인 필요", [...(outcomes.recent_pending || []), ...(outcomes.recent_unavailable || [])], outcomeIssueLabel));
      recentPanel.appendChild(renderRecentList("AI 가상매매 대기", "가상매매", paper.candidate_runs || [], paperCandidateLabel));
      recentPanel.appendChild(renderRecentList("가상 보유 재평가", "보유 중", paper.open_positions || [], paperOpenLabel));
    }
  }

  function renderActionSummaryPending(panel, label, message) {
    if (!panel) return;
    panel.textContent = "";
    const fragment = document.createDocumentFragment();
    appendActionCell(fragment, label, "확인 중", message, "is-waiting");
    panel.appendChild(fragment);
  }

  function renderActionSummaryError(panel, label, message) {
    if (!panel) return;
    panel.textContent = "";
    const fragment = document.createDocumentFragment();
    appendActionCell(fragment, label, "오류", message, "is-error");
    panel.appendChild(fragment);
  }

  function renderAdminActionSummary(panel, payload, isOutcome, isDryRun, isPaper = false) {
    if (!panel) return;
    panel.textContent = "";
    const fragment = document.createDocumentFragment();
    if (isPaper) {
      if (isDryRun || payload?.status === "dry_run") {
        const rows = Array.isArray(payload?.items) ? payload.items : [];
        const openRows = Array.isArray(payload?.open_positions) ? payload.open_positions : [];
        const limitNote = payload?.notice || "완료된 분석 리포트 중 아직 가상매매 기록이 없는 항목입니다.";
        appendActionCell(fragment, "새 가상매매", String(payload?.candidate_count ?? rows.length), limitNote, rows.length ? "is-warn" : "is-ok");
        appendActionCell(fragment, "보유 재평가", String(payload?.open_position_count ?? openRows.length), "가상 보유 중인 기록을 최신 가격으로 다시 확인합니다.", openRows.length ? "is-warn" : "is-ok");
        appendActionCell(fragment, "실행 경계", "가상매매", "실제 주문 없이, 분석 리포트 기준의 가상매매 기록만 저장합니다.", "is-ok");
      } else {
        const summary = payload?.summary || {};
        const results = Array.isArray(payload?.results) ? payload.results : [];
        appendActionCell(fragment, "처리 결과", String(payload?.item_count || results.length || 0), "AI 가상매매 기록 생성 결과입니다.", "is-ok");
        appendActionCell(fragment, "새 기록", String(summary.created_count || 0), `평균 실현 수익률 ${percentLabel(summary.average_realized_return)}`, "is-ok");
        appendActionCell(fragment, "청산 완료", String(summary.closed_count || 0), `가상 보유 ${summary.still_open_count || 0}건 유지`, summary.closed_count ? "is-ok" : "is-waiting");
        appendActionCell(fragment, "보류", String(summary.unavailable_count || 0), "가격 데이터가 부족한 항목입니다.", summary.unavailable_count ? "is-warn" : "is-ok");
        appendActionCell(fragment, "실패", String(summary.failed_count || 0), actionErrorNote(results), summary.failed_count ? "is-error" : "is-ok");
      }
    } else if (isOutcome) {
      const horizons = Array.isArray(payload?.horizons) && payload.horizons.length
        ? payload.horizons.map((value) => `${value}D`).join(" / ")
        : "5D / 20D";
      if (isDryRun || payload?.status === "dry_run") {
        const runCount = Number(payload?.run_count || payload?.item_count || 0);
        const estimated = Number(payload?.estimated_outcome_count || 0);
        const limitNote = payload?.notice || `검증 구간 ${horizons}`;
        appendActionCell(fragment, "대상 리포트", String(runCount), limitNote, runCount ? "is-warn" : "is-ok");
        appendActionCell(fragment, "예상 작업", String(estimated), "이미 완료된 구간은 실행 시 건너뜁니다.", estimated ? "is-warn" : "is-ok");
        appendActionCell(fragment, "확인 경로", payload?.inspect_path || "/api/analysis-outcomes", "공개 사후 결과 API로 결과를 재확인합니다.", "is-waiting");
      } else {
        const summary = payload?.summary || {};
        const results = Array.isArray(payload?.results) ? payload.results : [];
        const warningCount = Number(summary.pending_count || 0) + Number(summary.unavailable_count || 0);
        appendActionCell(fragment, "처리 결과", String(payload?.item_count || results.length || 0), `검증 구간 ${horizons}`, "is-ok");
        appendActionCell(fragment, "완료", String(summary.completed_count || 0), `평균 시장 대비 ${percentLabel(summary.average_alpha_return)}`, "is-ok");
        appendActionCell(fragment, "보류/데이터 없음", String(warningCount), `대기 ${summary.pending_count || 0} · 데이터 없음 ${summary.unavailable_count || 0}`, warningCount ? "is-warn" : "is-ok");
        appendActionCell(fragment, "건너뜀", String(summary.skipped_count || 0), "이미 완료된 5일/20일 기록입니다.", summary.skipped_count ? "is-waiting" : "is-ok");
        appendActionCell(fragment, "실패/보류 로그", String(results.filter((row) => row?.error && row.error !== "already_completed").length), actionErrorNote(results), warningCount ? "is-warn" : "is-ok");
      }
    } else if (isDryRun || payload?.status === "dry_run") {
      const rows = Array.isArray(payload?.items) ? payload.items : [];
      const limitNote = payload?.notice || "실행하면 이 대상부터 처리합니다.";
      appendActionCell(fragment, "대기 요청", String(payload?.item_count || rows.length || 0), limitNote, rows.length ? "is-warn" : "is-ok");
      appendActionCell(fragment, "실행 경계", "주문 없음", "분석 리포트 생성 대기열만 처리하고 주문 기능은 없습니다.", "is-ok");
    } else {
      const results = Array.isArray(payload?.results) ? payload.results : [];
      const counts = countByStatus(results);
      appendActionCell(fragment, "처리 결과", String(payload?.item_count || results.length || 0), "분석 리포트 생성 결과입니다.", "is-ok");
      appendActionCell(fragment, "완료", String(counts.completed || 0), "완료 리포트는 AI 리포트에서 확인합니다.", "is-ok");
      appendActionCell(fragment, "실패", String(counts.failed || 0), actionErrorNote(results), counts.failed ? "is-error" : "is-ok");
    }
    panel.appendChild(fragment);
  }

  function renderReadinessPending(message) {
    if (!readinessPanel) return;
    readinessPanel.textContent = "";
    const fragment = document.createDocumentFragment();
    appendReadinessCell(fragment, "상태", "확인 중", message, "is-waiting");
    readinessPanel.appendChild(fragment);
  }

  function renderReadinessError(message) {
    if (!readinessPanel) return;
    readinessPanel.textContent = "";
    const fragment = document.createDocumentFragment();
    appendReadinessCell(fragment, "Status", "오류", message, "is-error");
    readinessPanel.appendChild(fragment);
  }

  function deploymentTraceLabel(deployment) {
    const sourceLabels = {
      git_sha: "SHA",
      deployment_id: "Deploy",
      vercel_url: "URL"
    };
    const traceId = deployment.trace_id || deployment.git_sha || deployment.deployment_id || deployment.vercel_url;
    if (!traceId) return "배포 식별자 없음";
    const traceSource = deployment.trace_source || (deployment.git_sha ? "git_sha" : "deployment");
    return `${sourceLabels[traceSource] || "Trace"} ${traceId}`;
  }

  function renderReadinessPanel(payload) {
    if (!readinessPanel) return;
    const checks = payload?.checks || {};
    const deployment = payload?.deployment || {};
    const errors = payload?.configuration_errors || {};
    const diagnostics = payload?.diagnostics || {};
    const vendorProbes = diagnostics.vendor_probes || {};
    const krxProbe = diagnostics.krx_probe || vendorProbes.krx || null;
    const fragment = document.createDocumentFragment();
    readinessPanel.textContent = "";

    const isOk = payload?.status === "ok";
    appendReadinessCell(fragment, "상태", isOk ? "정상" : "점검 필요", deploymentTraceLabel(deployment), isOk ? "is-ok" : "is-warn");

    const storageOk = Boolean(checks.storage_online && checks.storage_schema_ready);
    const storageValue = storageOk ? "온라인" : checks.storage_configured ? "점검 필요" : "미설정";
    const storageNote = errors.storage_online || errors.storage_schema_ready
      || `storage ${readinessText(checks.storage_online)} · schema ${readinessText(checks.storage_schema_ready)}`;
    appendReadinessCell(fragment, "저장소", storageValue, storageNote, storageOk ? "is-ok" : "is-warn");

    const hasKrxProbe = Object.prototype.hasOwnProperty.call(checks, "krx_online");
    let krxValue = checks.krx_configured ? "설정됨" : "미설정";
    let krxNote = checks.krx_configured ? "KRX 응답 점검 체크박스로 온라인 응답을 확인할 수 있습니다." : "KRX_API_KEY 또는 KRX_OPENAPI_KEY가 필요합니다.";
    let krxState = checks.krx_configured ? "is-ok" : "is-warn";
    if (hasKrxProbe) {
      krxValue = checks.krx_online ? "온라인" : "점검 실패";
      krxState = checks.krx_online ? "is-ok" : "is-warn";
      if (krxProbe) {
        krxNote = krxProbe.status === "ok"
          ? `${krxProbe.ticker || "ticker"} · ${krxProbe.date || "date"} · ${probeSummary(krxProbe)}`
          : `${krxProbe.error_type || "KRX"} · ${krxProbe.message || krxProbe.error || "probe failed"}`;
      }
    }
    appendReadinessCell(fragment, "KRX", krxValue, krxNote, krxState);

    const vendorCount = [checks.dart_configured, checks.naver_configured, checks.openai_configured].filter(Boolean).length;
    let vendorValue = `${vendorCount}/3 설정`;
    let vendorNote = `DART ${readinessText(checks.dart_configured)} · Naver ${readinessText(checks.naver_configured)} · OpenAI ${readinessText(checks.openai_configured)}`;
    let vendorState = vendorCount === 3 ? "is-ok" : "is-warn";
    if (vendorProbes.dart || vendorProbes.naver) {
      const vendorProbeRows = [
        `DART ${probeSummary(vendorProbes.dart)}`,
        `Naver ${probeSummary(vendorProbes.naver)}`
      ];
      const onlineCount = [vendorProbes.dart, vendorProbes.naver].filter((probe) => probe?.status === "ok").length;
      vendorValue = `${onlineCount}/2 온라인`;
      vendorNote = vendorProbeRows.join(" · ");
      vendorState = onlineCount === 2 ? "is-ok" : "is-warn";
    }
    appendReadinessCell(fragment, "외부 데이터", vendorValue, vendorNote, vendorState);

    appendReadinessCell(
      fragment,
      "실행 경계",
      checks.live_trading_disabled ? "주문 없음" : "확인 필요",
      checks.live_trading_disabled ? "실거래 주문 경로는 비활성 상태입니다." : "TRADINGAGENTS_LIVE_TRADING 설정을 확인하세요.",
      checks.live_trading_disabled ? "is-ok" : "is-warn"
    );

    const authWorkerOk = Boolean(checks.supabase_auth_configured && checks.worker_token_configured);
    const authWorkerNote = `회원 인증 ${readinessText(checks.supabase_auth_configured)} · 운영 키 ${readinessText(checks.worker_token_configured)}`;
    appendReadinessCell(fragment, "접근", authWorkerOk ? "준비됨" : "점검 필요", authWorkerNote, authWorkerOk ? "is-ok" : "is-warn");

    appendReadinessCell(
      fragment,
      "사이트 URL",
      checks.site_base_url_configured ? "설정됨" : "미설정",
      checks.site_base_url_configured ? "canonical, sitemap, redirect 기준 URL이 설정되어 있습니다." : "TRADINGAGENTS_SITE_BASE_URL 설정을 확인하세요.",
      checks.site_base_url_configured ? "is-ok" : "is-warn"
    );

    appendReadinessCell(
      fragment,
      "광고",
      checks.ads_configured ? "설정됨" : "보류",
      checks.ads_configured ? "ads.txt 또는 publisher id가 설정되어 있습니다." : "AdSense 키가 준비되기 전까지는 운영 보류 항목입니다.",
      checks.ads_configured ? "is-ok" : "is-waiting"
    );

    const securityOk = Boolean(checks.api_docs_disabled && checks.trusted_member_user_header_disabled && checks.https_request);
    const securityNote = `문서 ${readinessText(checks.api_docs_disabled)} · 신뢰 헤더 ${readinessText(checks.trusted_member_user_header_disabled)} · HTTPS ${readinessText(checks.https_request)}`;
    appendReadinessCell(fragment, "보안", securityOk ? "잠김" : "점검 필요", securityNote, securityOk ? "is-ok" : "is-warn");

    readinessPanel.appendChild(fragment);
  }

  async function fetchJson(path, options = {}, requireToken = false) {
    const headers = {
      "Accept": "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {})
    };
    if (requireToken) {
      const token = currentToken();
      if (!token) throw new Error("운영 토큰을 입력하세요.");
      headers["X-TradingAgents-Worker-Token"] = token;
    }
    const response = await fetch(path, { ...options, headers });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || payload.error || `요청 실패 (HTTP ${response.status})`);
    }
    return payload;
  }

  if (tokenInput) tokenInput.value = savedToken();
  if (savedToken() && tokenState) tokenState.textContent = "세션에 저장된 운영 토큰을 사용합니다.";
  syncAdminAccessControls();

  tokenForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const token = (tokenInput?.value || "").trim();
    if (!token) {
      clearSavedToken();
      return;
    }
    sessionStorage.setItem(tokenKey, token);
    if (tokenState) tokenState.textContent = "운영 토큰을 이 브라우저 세션에 저장했습니다.";
    window.dispatchEvent(new Event("tradingagents:admin-token"));
    syncAdminAccessControls();
  });

  tokenInput?.addEventListener("input", () => {
    syncAdminAccessControls();
  });

  tokenClearButton?.addEventListener("click", () => {
    clearSavedToken("세션에 저장된 운영 토큰을 지웠습니다.");
  });

  const readinessButton = document.querySelector("[data-admin-readiness]");
  const opsButton = document.querySelector("[data-admin-ops-summary]");

  readinessButton?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    try {
      setBusy(button, true);
      setOutput(readinessOutput, "확인 중");
      renderReadinessPending("배포, 저장소, 외부 데이터, 주문 차단 경계를 조회하고 있습니다.");
      const params = new URLSearchParams();
      if (probeKrx?.checked) params.set("probe_krx", "true");
      if (probeVendors?.checked) params.set("probe_vendors", "true");
      const suffix = params.toString() ? `?${params.toString()}` : "";
      const payload = await fetchJson(`/api/readiness${suffix}`);
      renderReadinessPanel(payload);
      setOutput(readinessOutput, payload);
    } catch (error) {
      const message = error.message || "상태 점검 실패";
      renderReadinessError(message);
      setOutput(readinessOutput, message);
    } finally {
      setBusy(button, false);
    }
  });

  opsButton?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    try {
      setBusy(button, true);
      setOutput(opsOutput, "운영 요약 확인 중");
      renderOpsSummaryPending("운영 토큰으로 대기열 현황과 최근 처리 결과를 조회합니다.");
      const payload = await fetchJson("/api/admin/ops-summary", { method: "GET" }, true);
      renderOpsSummary(payload);
      setOutput(opsOutput, payload);
    } catch (error) {
      const message = error.message || "운영 요약 조회 실패";
      renderOpsSummaryError(message);
      setOutput(opsOutput, message);
    } finally {
      setBusy(button, false);
    }
  });

  window.setTimeout(() => {
    if (readinessButton && !readinessButton.disabled) readinessButton.click();
  }, 120);

  async function runAdminAction(action, button) {
    const isDryRun = action.endsWith("dry-run");
    const isOutcome = action.startsWith("outcomes");
    const isPaper = action.startsWith("paper");
    const actionGroup = isPaper ? "paper" : isOutcome ? "outcomes" : "requests";
    const output = isPaper ? paperSimulationOutput : isOutcome ? outcomesOutput : requestsOutput;
    const summaryPanel = isPaper ? paperSimulationPanel : isOutcome ? outcomesPanel : requestsPanel;
    const originalLabel = button.dataset.originalLabel || button.textContent;
    button.dataset.originalLabel = originalLabel;
    const limitControl = isPaper ? paperSimulationLimit : isOutcome ? outcomeLimit : requestLimit;
    const limit = limitFromControl(limitControl);
    const path = isPaper
      ? "/api/admin/paper-simulations/process"
      : isOutcome
        ? "/api/admin/analysis-outcomes/process"
        : "/api/admin/analysis-requests/process";
    const body = isOutcome
      ? { limit, dry_run: isDryRun, horizons: [5, 20] }
      : { limit, dry_run: isDryRun };
    const actionLabel = isPaper ? "AI 가상매매 기록" : isOutcome ? "사후 결과 계산" : "AI 리포트 생성";
    if (!isDryRun && Date.now() - (lastDryRunAt[actionGroup] || 0) > dryRunReadyMs) {
      const message = "먼저 실행 전 확인을 눌러 이번 실행 후보를 확인하세요. 확인 후 10분 동안 실행할 수 있습니다.";
      setOutput(output, message);
      renderActionSummaryPending(summaryPanel, actionLabel, message);
      return;
    }
    try {
      setBusy(button, true);
      setOutput(output, isDryRun ? "실행 전 확인 중" : "작업 실행 중");
      renderActionSummaryPending(summaryPanel, actionLabel, isDryRun ? "저장 없이 이번 실행 후보를 확인하고 있습니다." : "선택한 대기열 작업을 저장하고 있습니다.");
      const payload = await fetchJson(path, { method: "POST", body: JSON.stringify(body) }, true);
      renderAdminActionSummary(summaryPanel, payload, isOutcome, isDryRun, isPaper);
      setOutput(output, payload);
      if (isDryRun) lastDryRunAt[actionGroup] = Date.now();
      button.textContent = originalLabel;
      if (opsButton && !opsButton.disabled) opsButton.click();
    } catch (error) {
      const message = error.message || "관리 작업 실패";
      renderActionSummaryError(summaryPanel, actionLabel, message);
      setOutput(output, message);
    } finally {
      if (!isDryRun) {
        button.textContent = originalLabel;
      }
      setBusy(button, false);
    }
  }

  document.querySelectorAll("[data-admin-action]").forEach((button) => {
    button.addEventListener("click", () => runAdminAction(button.dataset.adminAction || "", button));
  });
})();
"""


MEMBER_PAGE_JS = """
(() => {
  const configNode = document.getElementById("member-config");
  const config = JSON.parse(configNode?.textContent || "{}");
  const statusNode = document.getElementById("memberStatus");
  const authStatusNode = document.getElementById("authStatus");
  const authForm = document.getElementById("authForm");
  const authPanel = document.querySelector(".auth-panel");
  const signedInPanel = document.getElementById("memberSignedIn");
  const signedInState = document.getElementById("memberSignedInState");
  const signedInUser = document.getElementById("memberSignedInUser");
  const signedInMeta = document.getElementById("memberSignedInMeta");
  const authButtons = Array.from(document.querySelectorAll("[data-auth-action]"));
  const passwordToggle = document.getElementById("passwordToggle");
  const signOutButton = document.getElementById("signOutButton");
  const refreshButton = document.getElementById("refreshMemberData");
  const portfolioForm = document.getElementById("portfolioForm");
  const tradeForm = document.getElementById("tradeForm");
  const targetForm = document.getElementById("targetForm");
  const watchlistForm = document.getElementById("watchlistForm");
  const watchlistItemForm = document.getElementById("watchlistItemForm");
  const analysisRequestForm = document.getElementById("analysisRequestForm");
  const portfolioList = document.getElementById("portfolioList");
  const watchlistList = document.getElementById("watchlistList");
  const analysisRequestList = document.getElementById("analysisRequestList");
  const paperSimulationList = document.getElementById("paperSimulationList");
  const memberTabLinks = Array.from(document.querySelectorAll("[data-member-tab]"));
  const memberPanels = Array.from(document.querySelectorAll("[data-member-panel]"));
  const memberJumpButtons = Array.from(document.querySelectorAll("[data-member-jump]"));
  const memberHomeStatus = document.getElementById("memberHomeStatus");
  const portfolioTabCount = document.getElementById("portfolioTabCount");
  const watchlistTabCount = document.getElementById("watchlistTabCount");
  const analysisTabCount = document.getElementById("analysisTabCount");
  const paperSimulationTabCount = document.getElementById("paperSimulationTabCount");
  const overviewPortfolios = document.getElementById("memberOverviewPortfolios");
  const overviewWatchlists = document.getElementById("memberOverviewWatchlists");
  const overviewActiveRequests = document.getElementById("memberOverviewActiveRequests");
  const overviewCompletedReports = document.getElementById("memberOverviewCompletedReports");
  const overviewPaperSimulations = document.getElementById("memberOverviewPaperSimulations");
  const memberHomeStateNote = document.getElementById("memberHomeStateNote");
  const memberPrimaryAction = document.getElementById("memberPrimaryAction");
  const memberPrimaryActionTitle = document.getElementById("memberPrimaryActionTitle");
  const memberPrimaryActionCopy = document.getElementById("memberPrimaryActionCopy");
  const memberPrimaryActionButton = document.getElementById("memberPrimaryActionButton");
  const portfolioSelect = tradeForm?.elements?.portfolio_id;
  const targetPortfolioSelect = targetForm?.elements?.portfolio_id;
  const watchlistSelect = watchlistItemForm?.elements?.watchlist_id;
  const analysisWatchlistTickerSelect = document.getElementById("analysisWatchlistTickerSelect");
  const memberTickerInputs = Array.from(document.querySelectorAll("[data-member-ticker-lookup]"));
  const memberTickerSuggestions = document.getElementById("memberTickerSuggestions");
  let memberTickerSearchController = null;
  const accessTokenKey = "tradingagents.member.access_token";
  const refreshTokenKey = "tradingagents.member.refresh_token";
  const expiresAtKey = "tradingagents.member.expires_at";
  const userEmailKey = "tradingagents.member.user_email";
  const userIdKey = "tradingagents.member.user_id";
  const activeTabKey = "tradingagents.member.active_tab";
  const analysisScheduleText = "평일 18:10 자동 실행 또는 운영 콘솔 실행 때 처리됩니다.";
  let memberDataPollTimer = null;
  const tabHashes = {
    home: "#member-home-section",
    portfolio: "#portfolio-section",
    watchlist: "#watchlist-section",
    analysis: "#analysis-request-section",
    paper: "#paper-simulation-section"
  };
  const memberTopNavLabels = {
    "/": "종목 검색",
    "/features/methodology": "분석 기준",
    "/analyses": "AI 리포트",
    "/outcomes": "사후 결과",
    "/member": "로그인",
    "/member?mode=signup": "내 공간 만들기",
    "/mypage": "내 공간",
    "/admin": "운영 콘솔"
  };
  const memberSearchParams = new URLSearchParams(window.location.search);
  const requestedAuthMode = memberSearchParams.get("mode");
  const requestedMemberTab = memberSearchParams.get("tab");
  const memberBody = document.body;
  const sessionGate = document.getElementById("memberSessionGate");
  const sessionTitle = document.getElementById("memberSessionTitle");
  const sessionMessage = document.getElementById("memberSessionMessage");
  const authLanding = document.getElementById("memberAuthLanding");
  const memberWorkspace = document.getElementById("memberWorkspace");
  const signedOutNavItems = Array.from(document.querySelectorAll('[data-auth-visible="signed-out"]'));
  const signedInNavItems = Array.from(document.querySelectorAll('[data-auth-visible="signed-in"]'));
  const adminNavItems = Array.from(document.querySelectorAll('[data-auth-visible="admin"]'));
  const sessionKeys = [accessTokenKey, refreshTokenKey, expiresAtKey, userEmailKey, userIdKey];

  function storageAreaGet(area, key) {
    try {
      return area?.getItem(key) || "";
    } catch (_) {
      return "";
    }
  }

  function sessionSnapshot(area) {
    const values = Object.fromEntries(sessionKeys.map((key) => [key, storageAreaGet(area, key)]));
    const expiresAt = Number(values[expiresAtKey] || 0);
    const hasSession = Boolean(values[accessTokenKey] || values[refreshTokenKey]);
    const score = (Number.isFinite(expiresAt) ? expiresAt : 0)
      + (values[accessTokenKey] ? 10 : 0)
      + (values[refreshTokenKey] ? 5 : 0);
    return { values, expiresAt, hasSession, score };
  }

  function preferredSessionSnapshot() {
    const persistent = sessionSnapshot(window.localStorage);
    const volatile = sessionSnapshot(window.sessionStorage);
    if (!persistent.hasSession) return volatile;
    if (!volatile.hasSession) return persistent;
    return volatile.score > persistent.score ? volatile : persistent;
  }

  function storageGet(key) {
    if (sessionKeys.includes(key)) {
      return preferredSessionSnapshot().values[key] || "";
    }
    return storageAreaGet(window.localStorage, key) || storageAreaGet(window.sessionStorage, key);
  }

  function storageSet(key, value) {
    const text = String(value || "");
    try {
      window.localStorage.setItem(key, text);
    } catch (_) {}
    try {
      window.sessionStorage.setItem(key, text);
    } catch (_) {}
  }

  function storageRemove(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (_) {}
    try {
      window.sessionStorage.removeItem(key);
    } catch (_) {}
  }

  function migrateSessionStorage() {
    const preferred = preferredSessionSnapshot();
    if (!preferred.hasSession) return;
    sessionKeys.forEach((key) => {
      const value = preferred.values[key];
      if (value) storageSet(key, value);
    });
  }

  function tabFromHash() {
    const panelId = String(window.location.hash || "").replace("#", "");
    const panel = memberPanels.find((node) => node.id === panelId);
    return panel?.dataset?.memberPanel || "";
  }

  function validTab(tabKey) {
    return memberPanels.some((panel) => panel.dataset.memberPanel === tabKey) ? tabKey : "";
  }

  function initialMemberTab() {
    return validTab(tabFromHash()) || validTab(requestedMemberTab) || validTab(storageGet(activeTabKey)) || "home";
  }

  function activateMemberTab(tabKey, updateHash = true) {
    const next = validTab(tabKey) || "home";
    memberTabLinks.forEach((link) => {
      const isActive = link.dataset.memberTab === next;
      link.classList.toggle("is-active", isActive);
      link.setAttribute("aria-selected", isActive ? "true" : "false");
      link.tabIndex = isActive ? 0 : -1;
    });
    memberPanels.forEach((panel) => {
      panel.hidden = panel.dataset.memberPanel !== next;
    });
    storageSet(activeTabKey, next);
    if (updateHash) {
      const nextHash = tabHashes[next] || "#member-home-section";
      const nextUrl = `${window.location.pathname}${window.location.search}${nextHash}`;
      if (window.location.hash !== nextHash) window.history.replaceState(null, "", nextUrl);
    }
  }

  function setupMemberTabs() {
    activateMemberTab(initialMemberTab(), false);
    memberTabLinks.forEach((link, index) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        activateMemberTab(link.dataset.memberTab || "portfolio");
      });
      link.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
        event.preventDefault();
        const step = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
        const nextIndex = (index + step + memberTabLinks.length) % memberTabLinks.length;
        const nextLink = memberTabLinks[nextIndex];
        activateMemberTab(nextLink.dataset.memberTab || "home");
        nextLink.focus();
      });
    });
    memberJumpButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const tab = button.dataset.memberJump || "home";
        activateMemberTab(tab);
        const target = memberTabLinks.find((link) => link.dataset.memberTab === tab);
        target?.focus();
      });
    });
    window.addEventListener("hashchange", () => {
      const tab = tabFromHash();
      if (tab) activateMemberTab(tab, false);
    });
  }

  function currentMemberNavKey(isSignedIn) {
    const path = window.location.pathname;
    if (path === "/member" && requestedAuthMode === "signup" && !isSignedIn) return "/member?mode=signup";
    if (path === "/member" || path === "/mypage") return isSignedIn ? "/mypage" : "/member";
    if (path === "/features/methodology") return "/features/methodology";
    if (path === "/analyses" || path.startsWith("/analyses/")) return "/analyses";
    if (path === "/outcomes") return "/outcomes";
    return "";
  }

  function syncMemberTopNavigationState(isSignedIn) {
    const current = currentMemberNavKey(Boolean(isSignedIn));
    document.querySelectorAll(".top-links a[href]").forEach((link) => {
      const target = (link.getAttribute("href") || "").split("#")[0];
      const label = memberTopNavLabels[target];
      if (label && link.textContent.trim() !== label) link.textContent = label;
      if (current && target === current) {
        link.setAttribute("aria-current", "page");
      } else if (link.getAttribute("aria-current") === "page") {
        link.removeAttribute("aria-current");
      }
    });
  }

  function setSessionCheckingState(
    label = "세션을 확인하고 있습니다",
    message = "로그인 상태가 남아 있으면 바로 내 공간으로 이동하고, 없으면 로그인/가입 화면을 엽니다."
  ) {
    memberBody?.classList.add("is-member-checking");
    memberBody?.classList.remove("is-member-signed-in", "is-member-signed-out");
    if (sessionGate) sessionGate.hidden = false;
    if (sessionTitle) sessionTitle.textContent = label;
    if (sessionMessage) sessionMessage.textContent = message;
    if (authLanding) authLanding.hidden = true;
    if (memberWorkspace) memberWorkspace.hidden = true;
    signedOutNavItems.forEach((node) => {
      node.hidden = true;
    });
    signedInNavItems.forEach((node) => {
      node.hidden = true;
    });
    adminNavItems.forEach((node) => {
      node.hidden = !(storageGet("tradingagents.admin.worker_token") || window.location.pathname === "/admin");
    });
    syncMemberTopNavigationState(false);
  }

  function setAuthUiState(isSignedIn) {
    const signedIn = Boolean(isSignedIn);
    memberBody?.classList.remove("is-member-checking");
    memberBody?.classList.toggle("is-member-signed-in", signedIn);
    memberBody?.classList.toggle("is-member-signed-out", !signedIn);
    if (sessionGate) sessionGate.hidden = true;
    if (authLanding) authLanding.hidden = signedIn;
    if (memberWorkspace) memberWorkspace.hidden = !signedIn;
    signedOutNavItems.forEach((node) => {
      node.hidden = signedIn;
    });
    signedInNavItems.forEach((node) => {
      node.hidden = !signedIn;
    });
    adminNavItems.forEach((node) => {
      node.hidden = !(signedIn || storageGet("tradingagents.admin.worker_token") || window.location.pathname === "/admin");
    });
    syncMemberTopNavigationState(signedIn);
  }

  function setStatus(message, isError = false) {
    if (statusNode) {
      statusNode.textContent = message;
      statusNode.classList.toggle("member-error", isError);
    }
    if (authStatusNode) {
      authStatusNode.textContent = message;
      authStatusNode.classList.toggle("member-error", isError);
    }
  }

  function renderMemberTickerOptions(items) {
    if (!memberTickerSuggestions) return;
    memberTickerSuggestions.replaceChildren(...items.map((item) => {
      const option = document.createElement("option");
      option.value = item.code;
      option.label = `${item.name} / ${item.market}`;
      return option;
    }));
  }

  async function memberSearchTickers(query) {
    const trimmed = String(query || "").trim();
    if (!trimmed) return [];
    if (memberTickerSearchController) memberTickerSearchController.abort();
    memberTickerSearchController = new AbortController();
    const response = await fetch(`/api/tickers/search?q=${encodeURIComponent(trimmed)}&limit=8`, {
      signal: memberTickerSearchController.signal,
      headers: { "Accept": "application/json" }
    });
    if (!response.ok) return [];
    const payload = await response.json();
    return payload.items || [];
  }

  function setupMemberTickerLookup() {
    if (!memberTickerSuggestions) return;
    memberTickerInputs.forEach((input) => {
      input.addEventListener("input", async () => {
        const query = input.value.trim();
        input.setCustomValidity("");
        if (query.length < 2) {
          memberTickerSuggestions.replaceChildren();
          return;
        }
        try {
          renderMemberTickerOptions(await memberSearchTickers(query));
        } catch (error) {
          if (error.name !== "AbortError") memberTickerSuggestions.replaceChildren();
        }
      });
    });
  }

  async function normalizeMemberTickerValue(value) {
    const query = String(value || "").trim();
    if (!query || /^\\d{6}$/.test(query)) return query;
    const items = await memberSearchTickers(query);
    if (!items.length) throw new Error("종목명 또는 6자리 종목코드를 확인해 주세요.");
    return items[0].code;
  }

  async function tickerFromForm(form, name) {
    const input = form?.elements?.[name];
    if (input) input.setCustomValidity("");
    try {
      const code = await normalizeMemberTickerValue(input?.value || "");
      if (input && code) input.value = code;
      return code;
    } catch (error) {
      if (input) {
        input.setCustomValidity(error.message || "종목명 또는 6자리 종목코드를 확인해 주세요.");
        input.reportValidity();
      }
      throw error;
    }
  }

  function setAuthBusy(isBusy) {
    authButtons.forEach((button) => {
      button.disabled = isBusy;
      button.setAttribute("aria-busy", isBusy ? "true" : "false");
    });
  }

  function setButtonBusy(button, isBusy, pendingLabel = "처리 중") {
    if (!button) return;
    if (isBusy) {
      button.dataset.originalLabel = button.dataset.originalLabel || button.textContent;
      button.textContent = pendingLabel;
    } else if (button.dataset.originalLabel) {
      button.textContent = button.dataset.originalLabel;
    }
    button.disabled = Boolean(isBusy);
    button.setAttribute("aria-busy", isBusy ? "true" : "false");
  }

  function setFormBusy(form, isBusy, pendingLabel = "저장 중") {
    if (!form) return;
    form.classList.toggle("is-busy", Boolean(isBusy));
    const submitButton = form.querySelector('button[type="submit"]');
    setButtonBusy(submitButton, isBusy, pendingLabel);
  }

  function applyRequestedAuthMode() {
    if (requestedAuthMode !== "signup") return;
    const signupButton = authButtons.find((button) => button.dataset.authAction === "signup");
    signupButton?.classList.add("auth-suggested");
    if (!accessToken() && !refreshToken()) {
      setStatus("가입하려면 이메일과 비밀번호를 입력한 뒤 가입하기를 선택하세요.");
      authForm?.elements?.email?.focus({ preventScroll: true });
    }
  }

  function setSignedInState(isSignedIn, options = {}) {
    setAuthUiState(Boolean(isSignedIn));
    authPanel?.classList.toggle("is-signed-in", Boolean(isSignedIn));
    if (signedInPanel) signedInPanel.hidden = !isSignedIn;
    if (!isSignedIn) return;
    const label = options.label || "대시보드 확인 중";
    const user = options.user || storageGet(userEmailKey) || storageGet(userIdKey) || "회원 세션";
    const meta = options.meta || "세션을 확인하고 있습니다.";
    if (signedInState) {
      signedInState.textContent = label;
      signedInState.classList.toggle("member-error", Boolean(options.isError));
    }
    if (signedInUser) signedInUser.textContent = user;
    if (signedInMeta) {
      signedInMeta.textContent = meta;
      signedInMeta.classList.toggle("member-error", Boolean(options.isError));
    }
  }

  function accessToken() {
    return storageGet(accessTokenKey) || "";
  }

  function refreshToken() {
    return storageGet(refreshTokenKey) || "";
  }

  function sessionExpiresAt() {
    return Number(storageGet(expiresAtKey) || 0);
  }

  function clearMemberDataPoll() {
    if (memberDataPollTimer) {
      window.clearTimeout(memberDataPollTimer);
      memberDataPollTimer = null;
    }
  }

  function activeAnalysisRequestCount(requests) {
    const summaryCount = Number(requests?.summary?.active_count ?? NaN);
    if (Number.isFinite(summaryCount)) return summaryCount;
    return (requests?.items || []).filter((row) => (
      row?.is_active || ["queued", "running"].includes(String(row?.status || ""))
    )).length;
  }

  function scheduleMemberDataPoll(requests) {
    clearMemberDataPoll();
    if (document.hidden || activeAnalysisRequestCount(requests) <= 0) return;
    memberDataPollTimer = window.setTimeout(() => {
      memberDataPollTimer = null;
      loadMemberData().catch((error) => setStatus(error.message, true));
    }, 30_000);
  }

  function clearSession() {
    clearMemberDataPoll();
    sessionKeys.forEach((key) => storageRemove(key));
    setSignedInState(false);
  }

  function setSession(payload) {
    const session = payload?.session || payload || {};
    const user = session.user || payload?.user || {};
    const token = session.access_token || "";
    const refresh = session.refresh_token || "";
    const expiresAt = session.expires_at
      ? Number(session.expires_at) * 1000
      : Date.now() + Math.max(Number(session.expires_in || 3600) - 30, 60) * 1000;
    if (!token) return false;
    storageSet(accessTokenKey, token);
    if (refresh) storageSet(refreshTokenKey, refresh);
    if (Number.isFinite(expiresAt)) storageSet(expiresAtKey, String(expiresAt));
    if (user.email) storageSet(userEmailKey, String(user.email));
    if (user.id) storageSet(userIdKey, String(user.id));
    setSignedInState(true, { label: "세션 확인 중", user: user.email || user.id || "", meta: "대시보드 권한을 확인하고 있습니다." });
    return true;
  }

  function tokenNeedsRefresh() {
    const expiresAt = sessionExpiresAt();
    return Boolean(refreshToken() && (!accessToken() || !expiresAt || Date.now() > expiresAt - 60_000));
  }

  function requireConfig() {
    if (config.configured) return true;
    setStatus("Supabase 공개 인증 설정 대기 중", true);
    return false;
  }

  function memberRedirectUrl() {
    const url = new URL("/member", window.location.origin);
    const tab = validTab(tabFromHash()) || validTab(storageGet(activeTabKey));
    if (tab && tab !== "home") url.searchParams.set("tab", tab);
    return url.toString();
  }

  function supabaseAuthUrl(path, params = {}) {
    const url = new URL(path, config.supabase_url);
    Object.entries(params).forEach(([key, value]) => {
      if (value) url.searchParams.set(key, value);
    });
    return url.toString();
  }

  function consumeRedirectSession() {
    const searchParams = new URLSearchParams(window.location.search);
    if (!window.location.hash && searchParams.has("code")) {
      searchParams.delete("code");
      const cleaned = searchParams.toString();
      window.history.replaceState(null, "", `${window.location.pathname}${cleaned ? `?${cleaned}` : ""}${window.location.hash}`);
      setStatus("이메일 확인 완료. 로그인해 주세요.");
      return { shouldLoad: Boolean(accessToken() || refreshToken()) };
    }
    if (!window.location.hash) return { shouldLoad: true };
    const params = new URLSearchParams(window.location.hash.slice(1));
    const isAuthRedirect = params.has("access_token")
      || params.has("refresh_token")
      || params.has("error")
      || params.has("type");
    if (!isAuthRedirect) return { shouldLoad: true };

    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    const errorMessage = params.get("error_description") || params.get("error");
    if (errorMessage) {
      setStatus(errorMessage, true);
      return { shouldLoad: false };
    }

    const token = params.get("access_token");
    if (!token) {
      setStatus("이메일 확인 완료. 로그인해 주세요.");
      return { shouldLoad: false };
    }

    setSession({
      access_token: token,
      refresh_token: params.get("refresh_token") || "",
      expires_in: Number(params.get("expires_in") || 3600)
    });
    setStatus("이메일 확인 완료. 대시보드 확인 중");
    return { shouldLoad: true };
  }

  async function supabaseAuth(path, body, params = {}) {
    if (!requireConfig()) throw new Error("Supabase 공개 인증 설정 대기 중");
    const response = await fetch(supabaseAuthUrl(path, params), {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "apikey": config.supabase_anon_key,
        "Authorization": `Bearer ${config.supabase_anon_key}`
      },
      body: JSON.stringify(body)
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error_description || payload.msg || payload.error || "인증 요청에 실패했습니다.");
    }
    return payload;
  }

  async function refreshSession() {
    if (!refreshToken()) return false;
    const payload = await supabaseAuth(
      "/auth/v1/token?grant_type=refresh_token",
      { refresh_token: refreshToken() }
    );
    return setSession(payload);
  }

  async function ensureAccessToken() {
    if (tokenNeedsRefresh()) {
      try {
        await refreshSession();
      } catch (_) {
        clearSession();
      }
    }
    return accessToken();
  }

  async function supabaseLogout() {
    if (!requireConfig() || !accessToken()) return;
    await fetch(supabaseAuthUrl("/auth/v1/logout"), {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "apikey": config.supabase_anon_key,
        "Authorization": `Bearer ${accessToken()}`
      }
    }).catch(() => {});
  }

  function apiErrorMessage(payload) {
    const detail = payload?.detail;
    if (!detail) return payload?.error || "요청 처리에 실패했습니다.";
    if (typeof detail === "string") return detail;
    if (typeof detail === "object") return detail.message || detail.error || JSON.stringify(detail);
    return String(detail);
  }

  async function memberApi(path, options = {}, retry = true) {
    const token = await ensureAccessToken();
    if (!token) throw new Error("로그인이 필요합니다");
    const response = await fetch(path, {
      ...options,
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`,
        ...(options.headers || {})
      }
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401 && retry && refreshToken()) {
      try {
        if (await refreshSession()) return memberApi(path, options, false);
      } catch (_) {
        clearSession();
      }
    }
    if (response.status === 401) {
      clearSession();
      throw new Error("로그인 세션이 만료되었습니다. 다시 로그인해 주세요.");
    }
    if (!response.ok) throw new Error(apiErrorMessage(payload));
    return payload;
  }

  async function safeMemberApi(path, options = {}) {
    try {
      return { ok: true, payload: await memberApi(path, options) };
    } catch (error) {
      return { ok: false, error: error.message || "요청 처리에 실패했습니다." };
    }
  }

  function itemCard(title, meta, children = []) {
    const node = document.createElement("article");
    node.className = "member-item";
    const strong = document.createElement("strong");
    strong.textContent = title;
    const small = document.createElement("small");
    small.textContent = meta;
    node.append(strong, small);
    children.forEach((child) => node.append(child));
    return node;
  }

  function smallButton(label, className = "ghost-button") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    return button;
  }

  function emptyNode(message) {
    const node = document.createElement("div");
    node.className = "member-empty";
    node.textContent = message;
    return node;
  }

  function emptyActionNode(title, message, actionLabel = "", onAction = null) {
    const node = document.createElement("div");
    node.className = "member-empty-action";
    const strong = document.createElement("strong");
    const small = document.createElement("small");
    strong.textContent = title;
    small.textContent = message;
    node.append(strong, small);
    if (actionLabel && typeof onAction === "function") {
      const button = smallButton(actionLabel);
      button.addEventListener("click", onAction);
      node.append(button);
    }
    return node;
  }

  function focusField(form, name) {
    const input = form?.elements?.[name];
    if (!input) return;
    input.focus({ preventScroll: false });
  }

  function money(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(Number(value))}원`;
  }

  function signedMoney(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    const number = Number(value);
    const sign = number > 0 ? "+" : "";
    return `${sign}${money(number)}`;
  }

  function signedPercent(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    const number = Number(value) * 100;
    const sign = number > 0 ? "+" : "";
    return `${sign}${number.toFixed(2)}%`;
  }

  function optionalDecimal(value) {
    const text = String(value || "").trim();
    return text || null;
  }

  function shortDate(value) {
    const raw = String(value || "");
    return raw ? raw.slice(0, 10) : "-";
  }

  function shortDateTime(value) {
    const raw = String(value || "");
    return raw ? raw.replace("T", " ").slice(0, 16) : "-";
  }

  function compactId(value) {
    const raw = String(value || "");
    return raw ? raw.slice(0, 8) : "-";
  }

  function inlineLink(label, path) {
    const link = document.createElement("a");
    link.className = "ghost-button member-inline-link";
    link.href = path;
    link.textContent = label;
    return link;
  }

  function miniList(lines, emptyMessage, label = "") {
    const list = document.createElement("ul");
    list.className = "member-sublist";
    if (label) {
      const heading = document.createElement("li");
      heading.className = "member-sublist-label";
      heading.textContent = label;
      list.append(heading);
    }
    const rendered = lines.length ? lines : [emptyMessage];
    rendered.forEach((line) => {
      const item = document.createElement("li");
      item.textContent = line;
      list.append(item);
    });
    return list;
  }

  function metricGrid(entries) {
    const grid = document.createElement("div");
    grid.className = "member-metric-grid";
    entries.forEach(([label, value, hint = ""]) => {
      const item = document.createElement("div");
      const small = document.createElement("small");
      const strong = document.createElement("strong");
      small.textContent = label;
      strong.textContent = value;
      item.append(small, strong);
      if (hint) {
        const span = document.createElement("span");
        span.textContent = hint;
        item.append(span);
      }
      grid.append(item);
    });
    return grid;
  }

  function cardHeader(title, meta, pillText = "") {
    const header = document.createElement("div");
    header.className = "member-card-header";
    const text = document.createElement("div");
    const strong = document.createElement("strong");
    const small = document.createElement("small");
    strong.textContent = title;
    small.textContent = meta;
    text.append(strong, small);
    header.append(text);
    if (pillText) {
      const pill = document.createElement("span");
      pill.className = "status-pill";
      pill.textContent = pillText;
      header.append(pill);
    }
    return header;
  }

  function riskText(position) {
    const parts = [];
    if (position.target_price !== null && position.target_price !== undefined) {
      const gap = position.target_gap_rate === null || position.target_gap_rate === undefined
        ? ""
        : ` / 목표까지 ${signedPercent(position.target_gap_rate)}`;
      parts.push(`목표 ${money(position.target_price)}${position.target_hit ? " 도달" : gap}`);
    }
    if (position.stop_price !== null && position.stop_price !== undefined) {
      const gap = position.stop_gap_rate === null || position.stop_gap_rate === undefined
        ? ""
        : ` / 손절 여유 ${signedPercent(position.stop_gap_rate)}`;
      parts.push(`손절 ${money(position.stop_price)}${position.stop_hit ? " 도달" : gap}`);
    }
    if (position.target_memo) parts.push(position.target_memo);
    return parts.length ? parts.join(" / ") : "목표·손절 미설정";
  }

  function portfolioLines(detail) {
    return (detail?.positions || []).slice(0, 4).map((position) => {
      const quantity = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 4 }).format(Number(position.quantity || 0));
      const pnl = signedMoney(position.total_pnl ?? position.unrealized_pnl ?? position.realized_pnl);
      const pnlRate = signedPercent(position.unrealized_pnl_rate);
      return `${position.ticker_name || position.ticker_code} ${quantity}주 / 평단 ${money(position.average_cost)} / 손익 ${pnl} (${pnlRate}) / ${riskText(position)}`;
    });
  }

  function tradeLines(detail) {
    return (detail?.trades || []).slice(0, 5).map((trade) => {
      const side = trade.side === "sell" ? "매도" : "매수";
      const quantity = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 4 }).format(Number(trade.quantity || 0));
      const costs = Number(trade.fee || 0) + Number(trade.tax || 0);
      const costText = costs > 0 ? ` / 비용 ${money(costs)}` : "";
      return `${trade.trade_date} ${side} ${trade.ticker_name || trade.ticker_code} ${quantity}주 @ ${money(trade.price)}${costText}`;
    });
  }

  function watchlistLines(detail) {
    return (detail?.items || []).slice(0, 5).map((item) => {
      const price = item.current_price === null || item.current_price === undefined ? "가격 대기" : money(item.current_price);
      const memo = item.memo ? ` / ${item.memo}` : "";
      const page = item.public_stock_path ? ` / 상세 ${item.public_stock_path}` : "";
      return `${item.ticker_name || item.ticker_code} ${item.ticker_code} / ${price}${memo}${page}`;
    });
  }

  function watchlistActionList(detail) {
    const list = document.createElement("div");
    list.className = "member-action-list";
    const items = detail?.items || [];
    if (!items.length) {
      list.append(emptyNode("이 그룹에 담긴 종목이 없습니다. 위 입력란에서 종목명이나 6자리 코드를 넣어 저장하세요."));
      return list;
    }
    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "member-action-item";
      const title = document.createElement(item.public_stock_path ? "a" : "strong");
      if (item.public_stock_path) title.href = item.public_stock_path;
      title.textContent = `${item.ticker_name || item.ticker_code} ${item.ticker_code}`;
      const meta = document.createElement("small");
      const price = item.current_price === null || item.current_price === undefined ? "가격 대기" : money(item.current_price);
      meta.textContent = `${item.market || "KR"} / ${price}`;
      const memo = document.createElement("input");
      memo.type = "text";
      memo.maxLength = 500;
      memo.value = item.memo || "";
      memo.placeholder = "메모";
      memo.setAttribute("aria-label", `${item.ticker_code} 메모`);
      const save = smallButton("메모 저장");
      save.addEventListener("click", async () => {
        try {
          setButtonBusy(save, true, "저장 중");
          setStatus("관심그룹 메모를 저장하는 중입니다.");
          memo.disabled = true;
          await memberApi(`/api/watchlists/${encodeURIComponent(detail.watchlist.id)}/items`, {
            method: "POST",
            body: JSON.stringify({ ticker_code: item.ticker_code, memo: memo.value || null })
          });
          await loadMemberData();
          setStatus("관심그룹 메모를 저장했습니다.");
        } catch (error) {
          setStatus(error.message, true);
        } finally {
          memo.disabled = false;
          setButtonBusy(save, false);
        }
      });
      const remove = smallButton("종목 삭제", "ghost-button danger-button");
      remove.addEventListener("click", async () => {
        try {
          setButtonBusy(remove, true, "삭제 중");
          setStatus("관심그룹에서 종목을 삭제하는 중입니다.");
          save.disabled = true;
          memo.disabled = true;
          await memberApi(`/api/watchlists/${encodeURIComponent(detail.watchlist.id)}/items/${encodeURIComponent(item.ticker_code)}`, {
            method: "DELETE"
          });
          await loadMemberData();
          setStatus("관심그룹에서 종목을 삭제했습니다.");
        } catch (error) {
          setStatus(error.message, true);
        } finally {
          save.disabled = false;
          memo.disabled = false;
          setButtonBusy(remove, false);
        }
      });
      row.append(title, meta, memo, save, remove);
      list.append(row);
    });
    return list;
  }

  function watchlistRenameForm(row) {
    const form = document.createElement("form");
    form.className = "watchlist-rename-form";
    const label = document.createElement("label");
    const labelText = document.createElement("span");
    const input = document.createElement("input");
    const button = smallButton("이름 저장");
    labelText.textContent = "그룹 이름 수정";
    input.type = "text";
    input.maxLength = 80;
    input.value = row.name || "";
    input.placeholder = "관심그룹 이름";
    input.setAttribute("aria-label", `${row.name || "관심그룹"} 이름 수정`);
    button.type = "submit";
    label.append(labelText, input);
    form.append(label, button);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = input.value.trim();
      if (!name) {
        input.setCustomValidity("관심그룹 이름을 입력해 주세요.");
        input.reportValidity();
        return;
      }
      input.setCustomValidity("");
      if (name === row.name) {
        setStatus("변경할 이름이 없습니다.");
        return;
      }
      try {
        setButtonBusy(button, true, "저장 중");
        setStatus("관심그룹 이름을 저장하는 중입니다.");
        input.disabled = true;
        await memberApi(`/api/watchlists/${encodeURIComponent(row.id)}`, {
          method: "PATCH",
          body: JSON.stringify({ name })
        });
        await loadMemberData();
        setStatus("관심그룹 이름을 바꿨습니다.");
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        input.disabled = false;
        setButtonBusy(button, false);
      }
    });
    return form;
  }

  function portfolioCard(row, detail) {
    const totals = detail?.totals || {};
    const tradeCount = detail?.trade_count || 0;
    const positionCount = (detail?.positions || []).length;
    const node = document.createElement("article");
    node.className = "member-item portfolio-card";
    const meta = detail
      ? `${row.base_currency || "KRW"} / ${positionCount}종목`
      : `${row.base_currency || "KRW"} / 상세 계산 대기`;
    node.append(
      cardHeader(row.name, meta, `거래 ${tradeCount}건`),
      metricGrid([
        ["평가", money(totals.market_value), "시장가 기준"],
        ["손익", signedMoney(totals.total_pnl), signedPercent(totals.total_pnl_rate)],
        ["보유", `${positionCount}종목`, "목표·손절 포함"],
        ["최근 거래", `${tradeCount}건`, detail?.pricing_status || "기록 기준"]
      ]),
      miniList(portfolioLines(detail), "아직 보유 종목이 없습니다", "보유"),
      miniList(tradeLines(detail), "아직 거래 내역이 없습니다", "최근 거래")
    );
    return node;
  }

  function watchlistCard(row, detail) {
    const summary = detail?.summary || {};
    const itemCount = detail?.item_count || 0;
    const pricedCount = detail?.priced_item_count || 0;
    const node = document.createElement("article");
    node.className = "member-item watchlist-card";
    node.append(
      cardHeader(row.name, detail ? `${detail.pricing_status || "가격 확인"} / 가격 ${pricedCount}/${itemCount}` : "가격 확인 대기", `종목 ${itemCount}개`),
      watchlistRenameForm(row),
      metricGrid([
        ["종목", `${itemCount}개`, "담긴 항목"],
        ["가격", `${pricedCount}개`, "현재가 확인"],
        ["메모", `${summary.memo_item_count || 0}개`, "검토 노트"],
        ["시장", row.market || "KR", "한국 종목"]
      ]),
      miniList(watchlistLines(detail), "아직 관심 종목이 없습니다", "요약"),
      watchlistActionList(detail)
    );
    return node;
  }

  function statusLabel(status) {
    return {
      queued: "대기",
      running: "처리 중",
      completed: "완료",
      failed: "실패",
      skipped: "건너뜀"
    }[status] || status || "미확인";
  }

  function analysisRequestSummary(summary = {}) {
    const counts = summary.status_counts || {};
    const policy = summary.quota_policy || {};
    const activeLimit = policy.active_limit || "-";
    const dailyLimit = policy.daily_limit || "-";
    const windowHours = policy.window_hours || 24;
    const node = document.createElement("div");
    node.className = "analysis-queue-overview";

    const meters = document.createElement("div");
    meters.className = "analysis-queue-meters";
    [
      ["대기 중 요청", `${policy.active_used ?? summary.active_count ?? 0}/${activeLimit}`, "대기+처리 중"],
      [`${windowHours}시간`, `${policy.daily_used ?? "-"}/${dailyLimit}`, "요청 제한"],
      ["완료", summary.completed_count || 0, "저장된 리포트"],
      ["실패", summary.failed_count || 0, "확인 필요"]
    ].forEach(([label, value, hint]) => {
      const meter = document.createElement("div");
      const small = document.createElement("small");
      const strong = document.createElement("strong");
      const span = document.createElement("span");
      small.textContent = label;
      strong.textContent = value;
      span.textContent = hint;
      meter.append(small, strong, span);
      meters.append(meter);
    });

    const strip = document.createElement("div");
    strip.className = "member-status-strip";
    [
      ["queued", "대기"],
      ["running", "처리 중"],
      ["completed", "완료"],
      ["failed", "실패"]
    ].forEach(([key, label]) => {
      const pill = document.createElement("span");
      pill.className = `status-pill analysis-status-${key}`;
      pill.textContent = `${label} ${counts[key] || 0}`;
      strip.append(pill);
    });

    const note = document.createElement("p");
    note.className = "analysis-queue-note";
    note.textContent = `대기 요청은 ${analysisScheduleText} 같은 종목과 기준일의 중복 요청은 기존 대기열에 합쳐집니다.`;
    node.append(meters, strip, note);
    return node;
  }

  function prefillAnalysisRequest(row) {
    if (!analysisRequestForm || !row) return;
    activateMemberTab("analysis");
    const elements = analysisRequestForm.elements || {};
    if (elements.ticker) elements.ticker.value = row.ticker_code || "";
    if (elements.requested_trade_date) elements.requested_trade_date.value = String(row.requested_trade_date || "").slice(0, 10);
    if (elements.reason) elements.reason.value = row.request_reason || "";
    const title = `${row.ticker_name || row.ticker_code || "분석 요청"}`.trim();
    setStatus(`${title} 재요청 내용을 입력했습니다. 확인 후 요청을 누르세요.`);
    elements.ticker?.focus();
  }

  function failureReasonLabel(value) {
    const text = String(value || "").trim();
    if (!text) return "실패 사유 확인 필요";
    if (text.includes("Read-only file system")) {
      return "서버 임시 저장 경로 문제로 실패했습니다. 다시 요청하면 수정된 처리 경로로 진행됩니다.";
    }
    return text.length > 180 ? `${text.slice(0, 177)}...` : text;
  }

  function analysisRequestCard(row) {
    const title = `${row.ticker_name || row.ticker_code || "한국 종목"} ${row.ticker_code || ""}`.trim();
    const status = row.status || "unknown";
    const node = document.createElement("article");
    node.className = "member-item analysis-request-item";

    const header = document.createElement("div");
    header.className = "analysis-request-header";
    const heading = document.createElement("div");
    const strong = document.createElement("strong");
    const small = document.createElement("small");
    const pill = document.createElement("span");
    strong.textContent = title;
    small.textContent = [
      `${row.market || "KR"} / 기준일 ${shortDate(row.requested_trade_date)}`,
      row.member_queue_position ? `${row.queue_scope_label || "내 대기열"} ${row.member_queue_position}번째` : null,
      `요청 ${shortDateTime(row.created_at)}`,
      `업데이트 ${shortDateTime(row.updated_at || row.created_at)}`
    ].filter(Boolean).join(" / ");
    pill.className = `status-pill analysis-status-${status}`;
    pill.textContent = row.status_label || statusLabel(status);
    heading.append(strong, small);
    header.append(heading, pill);

    const hint = document.createElement("p");
    hint.className = "analysis-request-hint";
    hint.textContent = row.status_hint || "분석 요청 상태를 확인하고 있습니다.";

    const details = [];
    if (row.request_reason) details.push(`요청 메모 ${row.request_reason}`);
    if (status === "queued") details.push("처리 전 대기");
    if (status === "running") details.push("리포트 생성 중");
    if (status === "failed") details.push(`실패 사유 ${failureReasonLabel(row.failure_reason || row.reason)}`);
    if (row.member_queue_position) details.push(`${row.queue_scope_label || "내 활성 요청 기준"} ${row.member_queue_position}번째`);
    if (row.analysis_run_id) details.push(`리포트 ID ${compactId(row.analysis_run_id)}`);
    if (row.public_stock_path) details.push(`종목 페이지 ${row.public_stock_path}`);
    details.push(`다음 행동 ${row.next_action_label || "상태 확인"}`);

    const actions = document.createElement("div");
    actions.className = "analysis-request-actions";
    if (status === "failed") {
      const retry = smallButton("다시 요청");
      retry.addEventListener("click", () => prefillAnalysisRequest(row));
      actions.append(retry);
    }
    if (row.is_active) {
      const refresh = smallButton(row.next_action_label || "상태 새로고침");
      refresh.addEventListener("click", () => loadMemberData());
      actions.append(refresh);
    }
    if (row.public_stock_path) actions.append(inlineLink("종목", row.public_stock_path));
    if (row.report_path) actions.append(inlineLink(row.next_action_label || "리포트", row.report_path));
    if (!row.report_path && row.next_action_path && !row.public_stock_path) {
      actions.append(inlineLink(row.next_action_label || "확인", row.next_action_path));
    }

    node.append(header, hint, miniList(details, "상세 상태 대기", "요청 상세"));
    if (actions.childElementCount) node.append(actions);
    return node;
  }

  function paperStatusLabel(status) {
    return {
      open: "가상 보유",
      closed: "청산 완료"
    }[status] || status || "대기";
  }

  function exitReasonLabel(reason) {
    return {
      take_profit: "익절",
      stop_loss: "손절",
      max_holding_days: "기간 종료"
    }[reason] || reason || "-";
  }

  function decisionLabel(row) {
    return [row.decision_rating, row.decision_action].filter(Boolean).join(" / ") || "AI";
  }

  function paperEventSideLabel(row = {}) {
    const key = String(row.side || row.event_type || "").toLowerCase();
    return {
      buy: "가상 매수",
      entry: "가상 매수",
      sell: "가상 매도",
      exit: "가상 청산"
    }[key] || "가상 이벤트";
  }

  function paperEventReasonLabel(reason) {
    return {
      entry_signal: "AI 분석 진입",
      take_profit: "목표가 도달",
      stop_loss: "손절 기준 도달",
      max_holding_days: "보유 기간 종료",
      manual_refresh: "가상 포지션 갱신"
    }[reason] || exitReasonLabel(reason);
  }

  function paperSimulationLines(row) {
    const lines = [];
    if (row.metadata?.pattern_label) lines.push(`진입 패턴 ${row.metadata.pattern_label}`);
    if (row.metadata?.entry_reason?.summary) lines.push(`진입 이유 ${row.metadata.entry_reason.summary}`);
    if (row.entry_date) lines.push(`가상 매수 ${shortDate(row.entry_date)} @ ${money(row.entry_price)}`);
    if (row.exit_date) lines.push(`가상 청산 ${shortDate(row.exit_date)} @ ${money(row.exit_price)} / ${exitReasonLabel(row.exit_reason)}`);
    if (row.metadata?.exit_reason_detail?.detail) lines.push(`청산 이유 ${row.metadata.exit_reason_detail.detail}`);
    if (row.metadata?.post_trade_evaluation?.summary) lines.push(`사후 평가 ${row.metadata.post_trade_evaluation.summary}`);
    (row.metadata?.post_trade_evaluation?.notes || []).slice(0, 2).forEach((note) => {
      if (note) lines.push(note);
    });
    if (!row.exit_date && row.metadata?.mark_date) lines.push(`최근 평가 ${shortDate(row.metadata.mark_date)} @ ${money(row.metadata.mark_price)} / ${signedPercent(row.metadata.unrealized_return)}`);
    if (row.target_price || row.stop_price) {
      lines.push(`목표 ${money(row.target_price)} / 손절 ${money(row.stop_price)}`);
    }
    if (row.metadata?.price_basis) lines.push(`가격 기준 ${row.metadata.price_basis}`);
    return lines;
  }

  function paperSimulationCard(row) {
    const title = `${row.ticker_name || row.ticker_code || "한국 종목"} ${row.ticker_code || ""}`.trim();
    const status = row.status || "open";
    const node = document.createElement("article");
    node.className = "member-item paper-simulation-card";
    const meta = `${row.market || "KR"} / ${paperStatusLabel(status)} / ${decisionLabel(row)}`;
    const actions = document.createElement("div");
    actions.className = "analysis-request-actions";
    if (row.stock_path) actions.append(inlineLink("종목", row.stock_path));
    if (row.report_path) actions.append(inlineLink("리포트", row.report_path));
    const currentPrice = row.exit_price || row.metadata?.mark_price;
    const currentDate = row.exit_date || row.metadata?.mark_date;
    const patternLabel = row.metadata?.pattern_label || "";
    const evaluation = row.metadata?.post_trade_evaluation || {};
    node.append(
      cardHeader(title, meta, paperStatusLabel(status)),
      metricGrid([
        ["진입가", money(row.entry_price), shortDate(row.entry_date)],
        ["청산/평가", currentPrice ? money(currentPrice) : "-", currentDate ? shortDate(currentDate) : "보유 중"],
        ["손익", row.status === "open" ? signedPercent(row.metadata?.unrealized_return) : signedMoney(row.realized_pnl), row.status === "open" ? "평가 기준" : signedPercent(row.realized_return)],
        ["사후 평가", evaluation.outcome_label || patternLabel || exitReasonLabel(row.exit_reason), evaluation.summary || (patternLabel ? "진입 시점" : "가상 기준")]
      ]),
      miniList(paperSimulationLines(row), "AI 가상매매 상세 대기", "기록")
    );
    if (actions.childElementCount) node.append(actions);
    return node;
  }

  function paperSimulationEventCard(row) {
    const title = `${row.ticker_code || "한국 종목"} · ${paperEventSideLabel(row)}`;
    const node = document.createElement("article");
    node.className = "member-item paper-simulation-event-card";
    const actions = document.createElement("div");
    actions.className = "analysis-request-actions";
    if (row.ticker_code) actions.append(inlineLink("종목", `/stocks/${encodeURIComponent(row.ticker_code)}`));
    if (row.analysis_run_id) actions.append(inlineLink("리포트", `/analyses/${encodeURIComponent(row.analysis_run_id)}`));
    node.append(
      cardHeader(title, `${shortDate(row.event_date)} / ${paperEventReasonLabel(row.reason)}`, paperEventSideLabel(row)),
      metricGrid([
        ["가격", money(row.price), "가상 체결가"],
        ["수량", String(row.quantity || "-"), "가상 수량"],
        ["금액", money(row.notional), "수수료·세금 전"],
        ["사유", paperEventReasonLabel(row.reason), row.event_type || "기록"]
      ]),
      miniList([
        row.commission ? `수수료 ${money(row.commission)}` : "",
        row.transaction_tax ? `세금 ${money(row.transaction_tax)}` : "",
        row.metadata?.reason_summary ? `기록 사유 ${row.metadata.reason_summary}` : (row.reason ? `기록 사유 ${paperEventReasonLabel(row.reason)}` : ""),
        row.metadata?.reason_detail ? `판정 기준 ${row.metadata.reason_detail}` : "",
        row.metadata?.evaluation_summary ? `사후 평가 ${row.metadata.evaluation_summary}` : ""
      ].filter(Boolean), "이벤트 상세 대기", "이벤트")
    );
    if (actions.childElementCount) node.append(actions);
    return node;
  }

  function paperSimulationEventSection(events = []) {
    const section = document.createElement("section");
    section.className = "paper-event-section";
    const heading = document.createElement("div");
    heading.className = "paper-event-section-heading";
    const title = document.createElement("strong");
    const copy = document.createElement("small");
    title.textContent = "최근 가상 매매 이벤트";
    copy.textContent = "AI가 만든 가상 매수·매도 시점과 기록 사유입니다.";
    heading.append(title, copy);
    section.append(heading, ...events.slice(0, 6).map((row) => paperSimulationEventCard(row)));
    return section;
  }

  function paperLearningNote(summary = {}) {
    const learning = summary.learning || {};
    const best = learning.best_bucket || null;
    const buckets = Array.isArray(learning.buckets) ? learning.buckets.slice(0, 3) : [];
    const node = document.createElement("div");
    node.className = "paper-learning-note";
    const label = document.createElement("span");
    label.textContent = "복기 요약";
    const title = document.createElement("strong");
    const copy = document.createElement("small");
    if (best) {
      title.textContent = `${best.label} · 승률 ${signedPercent(best.win_rate).replace("+", "")}`;
      copy.textContent = `청산 ${best.trade_count || 0}건 · 평균 수익률 ${signedPercent(best.average_return)} · 누적 손익 ${signedMoney(best.total_realized_pnl)}`;
    } else {
      title.textContent = "청산 기록 대기";
      copy.textContent = "가상 청산이 쌓이면 AI 의견별 승률과 평균 수익률을 보여줍니다.";
    }
    const bucketList = document.createElement("div");
    bucketList.className = "paper-learning-buckets";
    buckets.forEach((bucket) => {
      const item = document.createElement("span");
      const labelText = bucket.label || "패턴 미분류";
      const winRate = signedPercent(bucket.win_rate).replace("+", "");
      item.textContent = `${labelText} · ${bucket.trade_count || 0}건 · 승률 ${winRate}`;
      bucketList.append(item);
    });
    node.replaceChildren(
      label,
      title,
      copy,
      ...(bucketList.childElementCount ? [bucketList] : [])
    );
    return node;
  }

  function fillSelect(select, rows, labelKey, emptyLabel = "항목을 먼저 추가하세요") {
    if (!select) return;
    if (!rows.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = emptyLabel;
      option.disabled = true;
      option.selected = true;
      select.replaceChildren(option);
      return;
    }
    select.replaceChildren(...rows.map((row) => {
      const option = document.createElement("option");
      option.value = row.id;
      option.textContent = row[labelKey] || row.id;
      return option;
    }));
  }

  function setFormControlsDisabled(form, disabled) {
    if (!form) return;
    Array.from(form.elements || []).forEach((control) => {
      control.disabled = Boolean(disabled);
    });
  }

  function fillPortfolioSelects(rows) {
    fillSelect(portfolioSelect, rows, "name", "매매 일지를 먼저 추가하세요");
    fillSelect(targetPortfolioSelect, rows, "name", "매매 일지를 먼저 추가하세요");
  }

  function watchlistTickerOptions(rows = [], details = {}) {
    const options = [];
    rows.forEach((row) => {
      const groupName = row.name || "관심그룹";
      const items = details?.[row.id]?.items || [];
      items.forEach((item) => {
        const tickerCode = String(item.ticker_code || "").trim();
        if (!tickerCode) return;
        const tickerName = item.ticker_name || tickerCode;
        options.push({
          code: tickerCode,
          label: `${groupName} · ${tickerName} ${tickerCode}`
        });
      });
    });
    return options;
  }

  function fillAnalysisWatchlistTickerSelect(rows = [], details = {}) {
    if (!analysisWatchlistTickerSelect) return;
    const placeholder = document.createElement("option");
    placeholder.value = "";
    const options = watchlistTickerOptions(rows, details);
    if (!options.length) {
      placeholder.textContent = "관심그룹에 종목을 먼저 담으세요";
      placeholder.selected = true;
      analysisWatchlistTickerSelect.replaceChildren(placeholder);
      analysisWatchlistTickerSelect.disabled = true;
      return;
    }
    placeholder.textContent = "관심그룹 종목 선택";
    placeholder.selected = true;
    analysisWatchlistTickerSelect.disabled = false;
    analysisWatchlistTickerSelect.replaceChildren(
      placeholder,
      ...options.map((item) => {
        const option = document.createElement("option");
        option.value = item.code;
        option.textContent = item.label;
        return option;
      })
    );
  }

  function renderPortfolios(payload, details = {}, error = "") {
    if (error) {
      fillPortfolioSelects([]);
      setFormControlsDisabled(tradeForm, true);
      setFormControlsDisabled(targetForm, true);
      portfolioList.replaceChildren(emptyNode(`매매 일지를 불러오지 못했습니다: ${error}`));
      return;
    }
    const rows = payload.items || [];
    fillPortfolioSelects(rows);
    setFormControlsDisabled(tradeForm, !rows.length);
    setFormControlsDisabled(targetForm, !rows.length);
    portfolioList.replaceChildren(
      ...(rows.length ? rows.map((row) => portfolioCard(row, details[row.id])) : [
        emptyActionNode(
          "아직 매매 일지가 없습니다",
          "실제 계좌가 아닌 매매 일지입니다. 먼저 이름을 만들고 종목, 평단, 목표가를 직접 남겨보세요.",
          "매매 일지 이름 입력",
          () => focusField(portfolioForm, "name")
        )
      ])
    );
  }

  function renderWatchlists(payload, details = {}, error = "") {
    if (error) {
      fillSelect(watchlistSelect, [], "name", "관심그룹을 먼저 만드세요");
      fillAnalysisWatchlistTickerSelect([], {});
      setFormControlsDisabled(watchlistItemForm, true);
      watchlistList.replaceChildren(emptyNode(`관심그룹을 불러오지 못했습니다: ${error}`));
      return;
    }
    const rows = payload.items || [];
    fillSelect(watchlistSelect, rows, "name", "관심그룹을 먼저 만드세요");
    fillAnalysisWatchlistTickerSelect(rows, details);
    setFormControlsDisabled(watchlistItemForm, !rows.length);
    watchlistList.replaceChildren(
      ...(rows.length ? rows.map((row) => watchlistCard(row, details[row.id])) : [
        emptyActionNode(
          "아직 관심그룹이 없습니다",
          "자주 확인할 종목을 담을 그룹을 먼저 만드세요.",
          "새 관심그룹 생성 가동",
          () => focusField(watchlistForm, "name")
        )
      ])
    );
  }

  function renderAnalysisRequests(payload, error = "") {
    if (error) {
      analysisRequestList.replaceChildren(emptyNode(`분석 요청을 불러오지 못했습니다: ${error}`));
      return;
    }
    const rows = payload.items || [];
    analysisRequestList.replaceChildren(
      analysisRequestSummary(payload.summary),
      ...(rows.length ? rows.map((row) => analysisRequestCard(row)) : [
        emptyActionNode(
          "아직 분석 요청이 없습니다",
          "종목명이나 6자리 코드를 입력하면 요청 대기열에 올라갑니다. 완료 후 AI 리포트 링크를 보여줍니다.",
          "새로운 종목 분석 대기열 가동",
          () => focusField(analysisRequestForm, "ticker")
        )
      ])
    );
  }

  function renderPaperSimulations(payload, error = "") {
    if (!paperSimulationList) return;
    if (error) {
      paperSimulationList.replaceChildren(emptyNode(`AI 가상매매 기록을 불러오지 못했습니다: ${error}`));
      return;
    }
    const rows = payload.positions || [];
    const events = payload.events || [];
    const summary = payload.summary || {};
    const overview = metricGrid([
      ["가상 보유", `${summary.open_count || 0}건`, "보유 중"],
      ["청산", `${summary.closed_count || 0}건`, "완료 기록"],
      ["승률", summary.win_rate === null || summary.win_rate === undefined ? "-" : signedPercent(summary.win_rate).replace("+", ""), "청산 기준"],
      ["누적 손익", signedMoney(summary.total_realized_pnl), "가상 손익"]
    ]);
    overview.classList.add("paper-simulation-overview");
    paperSimulationList.replaceChildren(
      overview,
      paperLearningNote(summary),
      ...(rows.length ? rows.map((row) => paperSimulationCard(row)) : [
        emptyActionNode(
          "아직 AI 가상매매 기록이 없습니다",
          "완료된 AI 리포트를 바탕으로 가상 매수·매도 기록이 쌓입니다.",
          "분석 요청 열기",
          () => activateMemberTab("analysis")
        )
      ]),
      ...(events.length ? [paperSimulationEventSection(events)] : [])
    );
  }

  function setText(node, value) {
    if (node) node.textContent = String(value);
  }

  function paperPositionCount(paperPayload = {}) {
    return (paperPayload.positions || []).length;
  }

  function dashboardStatusMeta(portfoliosPayload = {}, watchlistsPayload = {}, requestsPayload = {}, paperPayload = {}) {
    const portfolioCount = (portfoliosPayload.items || []).length;
    const watchlistCount = (watchlistsPayload.items || []).length;
    const requestRows = requestsPayload.items || [];
    const paperCount = paperPositionCount(paperPayload);
    const summary = requestsPayload.summary || {};
    const activeCount = summary.active_count ?? requestRows.filter((row) => row.is_active).length;
    const completedCount = summary.completed_count ?? requestRows.filter((row) => row.status === "completed").length;
    const parts = [];
    if (portfolioCount) parts.push(`매매 일지 ${portfolioCount}개`);
    if (watchlistCount) parts.push(`관심그룹 ${watchlistCount}개`);
    if (activeCount) parts.push(`진행 중 요청 ${activeCount}건`);
    if (completedCount) parts.push(`완료 리포트 ${completedCount}건`);
    if (paperCount) parts.push(`AI 가상매매 ${paperCount}건`);
    if (!parts.length) {
      return "아직 저장된 항목이 없습니다. 매매 일지나 관심그룹부터 시작해 보세요.";
    }
    return `저장된 항목: ${parts.join(" / ")}`;
  }

  function dashboardSignedInMeta(portfoliosPayload = {}, watchlistsPayload = {}, requestsPayload = {}, paperPayload = {}) {
    const meta = dashboardStatusMeta(portfoliosPayload, watchlistsPayload, requestsPayload, paperPayload);
    if (meta === "아직 저장된 항목이 없습니다. 매매 일지나 관심그룹부터 시작해 보세요.") {
      return "내 리서치 공간이 활성화되었습니다. 아래 흐름을 따라 투자 기록과 분석 요청을 이어가세요.";
    }
    return meta;
  }

  function setMemberHomeNote(text) {
    setText(memberHomeStateNote, text);
  }

  function setMemberPrimaryAction(tab, title, copy, label) {
    if (memberPrimaryAction) memberPrimaryAction.dataset.memberPrimaryAction = tab;
    setText(memberPrimaryActionTitle, title);
    setText(memberPrimaryActionCopy, copy);
    if (memberPrimaryActionButton) {
      memberPrimaryActionButton.dataset.memberJump = tab;
      memberPrimaryActionButton.textContent = label;
    }
  }

  function updateMemberOverview(portfoliosPayload = {}, watchlistsPayload = {}, requestsPayload = {}, paperPayload = {}) {
    const portfolioCount = (portfoliosPayload.items || []).length;
    const watchlistCount = (watchlistsPayload.items || []).length;
    const requestRows = requestsPayload.items || [];
    const paperCount = paperPositionCount(paperPayload);
    const summary = requestsPayload.summary || {};
    const activeCount = summary.active_count ?? requestRows.filter((row) => row.is_active).length;
    const completedCount = summary.completed_count ?? requestRows.filter((row) => row.status === "completed").length;
    const savedCount = portfolioCount + watchlistCount + requestRows.length + paperCount;
    const homeStatus = activeCount ? `진행 ${activeCount}` : completedCount ? `완료 ${completedCount}` : savedCount ? "정리됨" : "비어 있음";
    setText(memberHomeStatus, homeStatus);
    setText(portfolioTabCount, portfolioCount);
    setText(watchlistTabCount, watchlistCount);
    setText(analysisTabCount, activeCount);
    setText(paperSimulationTabCount, paperCount);
    setText(overviewPortfolios, portfolioCount);
    setText(overviewWatchlists, watchlistCount);
    setText(overviewActiveRequests, activeCount);
    setText(overviewCompletedReports, completedCount);
    setText(overviewPaperSimulations, paperCount);
    setMemberHomeNote(dashboardStatusMeta(portfoliosPayload, watchlistsPayload, requestsPayload, paperPayload));
    if (activeCount) {
      setMemberPrimaryAction(
        "analysis",
        "진행 중인 분석을 확인하세요",
        "대기열 위치와 처리 상태를 확인하세요.",
        "요청 상태 보기"
      );
    } else if (paperCount) {
      setMemberPrimaryAction(
        "paper",
        "AI 가상매매 기록을 확인하세요",
        "가상 매수와 매도 이유를 리포트와 이어서 볼 수 있습니다.",
        "AI 가상매매 보기"
      );
    } else if (!portfolioCount) {
      setMemberPrimaryAction(
        "portfolio",
        "첫 매매 일지를 만들어 보세요",
        "실제 계좌 주문과 연결되지 않는 조회 전용 기록 공간입니다. 평단, 목표가, 손절선을 직접 남겨 투자 시나리오를 점검하세요.",
        "매매 일지 시작"
      );
    } else if (!watchlistCount) {
      setMemberPrimaryAction(
        "watchlist",
        "관심그룹을 추가하세요",
        "자주 보는 종목을 묶어두면 분석 요청과 리포트를 이어서 보기 쉽습니다.",
        "관심그룹 추가"
      );
    } else {
      setMemberPrimaryAction(
        "analysis",
        completedCount ? "완료 리포트를 확인하세요" : "새 분석을 요청해보세요",
        completedCount
          ? "완료된 리포트가 있으면 공개 목록과 종목 페이지에서 확인합니다."
          : "궁금한 종목을 분석 요청 대기열에 올려보세요.",
        completedCount ? "리포트 보기" : "분석 요청하기"
      );
    }
  }

  function flattenErrorCount(errors) {
    return Object.values(errors || {}).reduce((count, value) => {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        return count + Math.max(Object.keys(value).length, 1);
      }
      return count + 1;
    }, 0);
  }

  function errorText(errors, key) {
    const value = errors?.[key];
    if (!value) return "";
    if (typeof value === "string") return value;
    if (value && typeof value === "object") {
      return Object.values(value).filter(Boolean).join(", ");
    }
    return String(value);
  }

  function errorSummary(errors) {
    return Object.entries(errors || {})
      .map(([key]) => {
        const text = errorText(errors, key);
        return text ? `${key}: ${text}` : key;
      })
      .filter(Boolean)
      .join(" / ");
  }

  function renderDashboard(payload) {
    const errors = payload?.errors || {};
    const member = payload?.member || {};
    const userId = member.user_id || storageGet(userIdKey) || "";
    if (userId) storageSet(userIdKey, String(userId));
    const userLabel = storageGet(userEmailKey) || userId || "회원 세션";
    const portfolios = payload?.portfolios || { items: [] };
    const watchlists = payload?.watchlists || { items: [] };
    const requests = payload?.analysis_requests || { items: [] };
    const paperSimulations = payload?.paper_simulations || { positions: [] };
    updateMemberOverview(
      portfolios,
      watchlists,
      requests,
      paperSimulations
    );
    renderPortfolios(
      portfolios,
      payload?.portfolio_details || {},
      errorText(errors, "portfolios")
    );
    renderWatchlists(
      watchlists,
      payload?.watchlist_details || {},
      errorText(errors, "watchlists")
    );
    renderAnalysisRequests(
      requests,
      errorText(errors, "analysis_requests")
    );
    scheduleMemberDataPoll(requests);
    renderPaperSimulations(
      paperSimulations,
      errorText(errors, "paper_simulations")
    );
    const errorCount = flattenErrorCount(errors);
    const status = payload?.status || (errorCount ? "partial" : "available");
    if (status === "available" && !errorCount) {
      setSignedInState(true, {
        label: "대시보드 준비 완료",
        user: userLabel,
        meta: dashboardSignedInMeta(portfolios, watchlists, requests, paperSimulations)
      });
      setStatus("대시보드 준비 완료");
      return;
    }
    const summary = errorSummary(errors) || "일부 영역을 불러오지 못했습니다.";
    setSignedInState(true, {
      label: "부분 연결",
      user: userLabel,
      meta: `확인 필요: ${summary}`,
      isError: true
    });
    setStatus(`로그인됨 / 대시보드 ${Math.max(errorCount, 1)}개 영역 확인 필요`, true);
  }

  async function loadMemberData() {
    if (!accessToken() && !refreshToken()) {
      clearMemberDataPoll();
      setSignedInState(false);
      setStatus(config.configured ? "내 공간 진입을 위해 인증이 필요합니다." : "Supabase 공개 인증 설정 대기 중", !config.configured);
      return;
    }
    if (!accessToken() && refreshToken()) {
      setSessionCheckingState(
        "세션 복구 중",
        "저장된 로그인 정보를 확인하고 있습니다. 확인이 끝나면 내 공간이 열립니다."
      );
      setStatus("저장된 세션으로 로그인 상태를 확인하고 있습니다.");
      const restoredToken = await ensureAccessToken();
      if (!restoredToken) {
        clearMemberDataPoll();
        setSignedInState(false);
        setStatus("로그인 세션이 만료되었습니다. 다시 로그인해 주세요.", true);
        return;
      }
    }
    setSignedInState(true, { label: "세션 확인 중", meta: "대시보드를 불러오고 있습니다." });
    setStatus("대시보드 불러오는 중");
    const dashboardResult = await safeMemberApi("/api/member/dashboard?include_latest_prices=true");
    if (dashboardResult.ok) {
      renderDashboard(dashboardResult.payload);
      return;
    }
    if (!accessToken() && !refreshToken()) {
      clearMemberDataPoll();
      setSignedInState(false);
      setStatus(dashboardResult.error, true);
      return;
    }
    await loadLegacyMemberData(dashboardResult.error);
  }

  async function loadLegacyMemberData(dashboardError = "") {
    const [portfoliosResult, watchlistsResult, requestsResult, paperResult] = await Promise.all([
      safeMemberApi("/api/portfolios"),
      safeMemberApi("/api/watchlists"),
      safeMemberApi("/api/analysis-requests?limit=20"),
      safeMemberApi("/api/member/paper-simulations?limit=20")
    ]);
    const portfolios = portfoliosResult.payload || { items: [] };
    const watchlists = watchlistsResult.payload || { items: [] };
    const requests = requestsResult.payload || { items: [] };
    const paperSimulations = paperResult.payload || { positions: [] };
    const [portfolioDetails, watchlistDetails] = await Promise.all([
      portfoliosResult.ok
        ? detailMap((portfolios.items || []).slice(0, 6), (row) => `/api/portfolio/${encodeURIComponent(row.id)}?include_latest_prices=true`)
        : Promise.resolve({}),
      watchlistsResult.ok
        ? detailMap((watchlists.items || []).slice(0, 6), (row) => `/api/watchlists/${encodeURIComponent(row.id)}?include_latest_prices=true`)
        : Promise.resolve({})
    ]);
    renderPortfolios(portfolios, portfolioDetails, portfoliosResult.error);
    renderWatchlists(watchlists, watchlistDetails, watchlistsResult.error);
    renderAnalysisRequests(requests, requestsResult.error);
    scheduleMemberDataPoll(requests);
    renderPaperSimulations(paperSimulations, paperResult.error);
    updateMemberOverview(portfolios, watchlists, requests, paperSimulations);
    const errors = [portfoliosResult, watchlistsResult, requestsResult, paperResult].filter((result) => !result.ok).length
      + (dashboardError ? 1 : 0);
    const userLabel = storageGet(userEmailKey) || storageGet(userIdKey) || "회원 세션";
    if (errors) {
      const fallbackErrors = [
        dashboardError ? `dashboard: ${dashboardError}` : "",
        portfoliosResult.ok ? "" : `portfolios: ${portfoliosResult.error}`,
        watchlistsResult.ok ? "" : `watchlists: ${watchlistsResult.error}`,
        requestsResult.ok ? "" : `analysis_requests: ${requestsResult.error}`,
        paperResult.ok ? "" : `paper_simulations: ${paperResult.error}`
      ].filter(Boolean).join(" / ");
      setSignedInState(true, {
        label: "기본 화면으로 표시 중",
        user: userLabel,
        meta: fallbackErrors ? `확인 필요: ${fallbackErrors}` : "대시보드 일부 영역을 확인해야 합니다.",
        isError: true
      });
      setStatus(`로그인됨 / ${errors}개 영역 확인 필요`, true);
      return;
    }
    setSignedInState(true, {
      label: "기본 화면 준비 완료",
      user: userLabel,
      meta: dashboardSignedInMeta(portfolios, watchlists, requests, paperSimulations)
    });
    setStatus("대시보드 준비 완료");
  }

  async function detailMap(rows, pathForRow) {
    const entries = await Promise.all(rows.map(async (row) => {
      try {
        return [row.id, await memberApi(pathForRow(row))];
      } catch (_) {
        return [row.id, null];
      }
    }));
    return Object.fromEntries(entries.filter(([, value]) => value));
  }

  async function handleAuth(action) {
    if (!authForm?.reportValidity()) return;
    const form = new FormData(authForm);
    const email = String(form.get("email") || "");
    const password = String(form.get("password") || "");
    try {
      setAuthBusy(true);
      setStatus(action === "signup" ? "가입 처리 중" : "로그인 중");
      const payload = action === "signup"
        ? await supabaseAuth("/auth/v1/signup", { email, password }, { redirect_to: memberRedirectUrl() })
        : await supabaseAuth("/auth/v1/token?grant_type=password", { email, password });
      if (!setSession(payload)) {
        setStatus("가입 요청을 보냈습니다. 메일이 오지 않으면 이미 가입된 이메일일 수 있으니 로그인해 보세요.");
        return;
      }
      await loadMemberData();
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      setAuthBusy(false);
    }
  }

  async function submitJson(form, path, buildBody, options = {}) {
    try {
      const formValues = new FormData(form);
      const pendingMessage = options.pendingMessage || "저장 중";
      setFormBusy(form, true, pendingMessage);
      setStatus(`${pendingMessage}입니다.`);
      const resolvedPath = typeof path === "function" ? await path(formValues) : path;
      const body = await buildBody(formValues);
      const payload = await memberApi(resolvedPath, { method: options.method || "POST", body: JSON.stringify(body) });
      form.reset();
      setFormBusy(form, false);
      await loadMemberData();
      if (payload?.status === "already_queued") {
        setStatus(`이미 대기 중인 분석 요청이 있어 기존 대기열 항목을 유지했습니다. ${analysisScheduleText}`);
      } else if (payload?.status === "queued") {
        const quota = payload?.quota;
        const suffix = quota ? ` (${quota.daily_used}/${quota.daily_limit}, 최근 ${quota.window_hours}시간)` : "";
        setStatus(`분석 요청을 대기열에 등록했습니다${suffix}. ${analysisScheduleText}`);
      } else if (options.successMessage) {
        setStatus(options.successMessage);
      }
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      setFormBusy(form, false);
    }
  }

  authForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    handleAuth("signin");
  });

  authButtons.forEach((button) => {
    button.addEventListener("click", () => handleAuth(button.dataset.authAction || "signin"));
  });

  passwordToggle?.addEventListener("click", () => {
    const input = authForm?.elements?.password;
    if (!input) return;
    const showing = input.type === "text";
    input.type = showing ? "password" : "text";
    const label = showing ? "비밀번호 표시" : "비밀번호 숨김";
    passwordToggle.textContent = label;
    passwordToggle.setAttribute("aria-label", label);
    passwordToggle.setAttribute("aria-pressed", showing ? "false" : "true");
  });

  signOutButton?.addEventListener("click", async () => {
    await supabaseLogout();
    clearSession();
    fillPortfolioSelects([]);
    fillSelect(watchlistSelect, [], "name", "관심그룹을 먼저 만드세요");
    fillAnalysisWatchlistTickerSelect([], {});
    setFormControlsDisabled(tradeForm, true);
    setFormControlsDisabled(targetForm, true);
    setFormControlsDisabled(watchlistItemForm, true);
    portfolioList?.replaceChildren(emptyNode("로그인 후 매매 일지가 표시됩니다"));
    watchlistList?.replaceChildren(emptyNode("로그인 후 관심그룹이 표시됩니다"));
    analysisRequestList?.replaceChildren(emptyNode("로그인 후 분석 요청이 표시됩니다"));
    paperSimulationList?.replaceChildren(emptyNode("로그인 후 AI 가상매매 기록이 표시됩니다"));
    updateMemberOverview({ items: [] }, { items: [] }, { items: [] }, { positions: [] });
    setStatus("로그아웃됨");
  });

  refreshButton?.addEventListener("click", () => {
    loadMemberData().catch((error) => setStatus(error.message, true));
  });

  analysisWatchlistTickerSelect?.addEventListener("change", () => {
    const ticker = analysisWatchlistTickerSelect.value || "";
    const input = analysisRequestForm?.elements?.ticker;
    if (!ticker || !input) return;
    input.value = ticker;
    input.setCustomValidity("");
    setStatus("관심그룹 종목을 분석 요청에 넣었습니다.");
  });

  portfolioForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitJson(portfolioForm, "/api/portfolios", (form) => ({
      name: String(form.get("name") || ""),
      base_currency: "KRW"
    }), { successMessage: "매매 일지를 만들었습니다. 이제 매수·매도 기록이나 목표/손절 메모를 추가할 수 있습니다." });
  });

  tradeForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(tradeForm);
    const portfolioId = String(form.get("portfolio_id") || "");
    submitJson(tradeForm, `/api/portfolio/${encodeURIComponent(portfolioId)}/trades`, async () => ({
      ticker_code: await tickerFromForm(tradeForm, "ticker_code"),
      side: String(form.get("side") || "buy"),
      trade_date: String(form.get("trade_date") || ""),
      price: String(form.get("price") || ""),
      quantity: Number(form.get("quantity") || 0),
      fee: optionalDecimal(form.get("fee")) || "0",
      tax: optionalDecimal(form.get("tax")) || "0"
    }), { successMessage: "매매 일지를 저장했습니다. 이 기록은 주문과 연결되지 않습니다." });
  });

  targetForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(targetForm);
    const portfolioId = String(form.get("portfolio_id") || "");
    submitJson(targetForm, async () => {
      const tickerCode = await tickerFromForm(targetForm, "ticker_code");
      return `/api/portfolio/${encodeURIComponent(portfolioId)}/targets/${encodeURIComponent(tickerCode)}`;
    }, (values) => ({
      target_price: optionalDecimal(values.get("target_price")),
      stop_price: optionalDecimal(values.get("stop_price")),
      memo: String(values.get("memo") || "") || null
    }), { method: "PUT", successMessage: "목표/손절 메모를 저장했습니다. 주문 기능은 열리지 않습니다." });
  });

  watchlistForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitJson(watchlistForm, "/api/watchlists", (form) => ({
      name: String(form.get("name") || "")
    }), { pendingMessage: "그룹 만드는 중", successMessage: "관심그룹을 만들었습니다. 이제 종목을 담아보세요." });
  });

  watchlistItemForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(watchlistItemForm);
    const watchlistId = String(form.get("watchlist_id") || "");
    submitJson(watchlistItemForm, `/api/watchlists/${encodeURIComponent(watchlistId)}/items`, async () => ({
      ticker_code: await tickerFromForm(watchlistItemForm, "ticker_code"),
      memo: String(form.get("memo") || "") || null
    }), { pendingMessage: "종목 담는 중", successMessage: "관심그룹에 종목을 담았습니다." });
  });

  analysisRequestForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitJson(analysisRequestForm, "/api/analysis-requests", async (form) => {
      const requested = String(form.get("requested_trade_date") || "");
      return {
        ticker: await tickerFromForm(analysisRequestForm, "ticker"),
        requested_trade_date: requested || null,
        reason: String(form.get("reason") || "") || null
      };
    });
  });

  async function bootstrapMemberSession() {
    migrateSessionStorage();
    setupMemberTabs();
    setupMemberTickerLookup();
    const redirectSession = consumeRedirectSession();
    const hasStoredSession = Boolean(accessToken() || refreshToken());
    if (hasStoredSession) {
      if (!accessToken() && refreshToken()) {
        setSessionCheckingState(
          "세션 복구 중",
          "저장된 로그인 정보를 확인하고 있습니다. 확인이 끝나면 내 공간이 열립니다."
        );
      } else {
        setSignedInState(true, { label: "세션 확인 중", meta: "저장된 세션으로 대시보드를 불러오고 있습니다." });
      }
    } else {
      setAuthUiState(false);
    }
    applyRequestedAuthMode();
    if (!redirectSession.shouldLoad) return;
    const shouldSkipInitialLoad = requestedAuthMode === "signup" && !accessToken() && !refreshToken();
    if (shouldSkipInitialLoad) return;
    if (accessToken() || refreshToken()) {
      await loadMemberData();
      return;
    }
    setAuthUiState(false);
    setStatus(config.configured ? "내 공간 진입을 위해 인증이 필요합니다." : "Supabase 공개 인증 설정 대기 중", !config.configured);
  }

  bootstrapMemberSession().catch((error) => {
    setAuthUiState(false);
    setStatus(error.message || "세션 확인에 실패했습니다.", true);
  });
})();
"""

"""Server-rendered public pages for the TradingAgents Korea site."""

from __future__ import annotations

import html
import json
import os
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from tradingagents.storage import StorageRepository

from .analysis_api import (
    build_public_analysis_bundle_payload,
    build_public_analysis_feed_payload,
    build_public_analysis_outcomes_payload,
)
from .public_api import build_public_stock_payload
from .seo import canonical_url, stock_canonical_url


def render_public_stock_page(
    ticker: str,
    *,
    repo: StorageRepository | None = None,
    chart_start: str | None = None,
    chart_end: str | None = None,
    as_of_date: str | None = None,
    max_analysis_age_days: int = 1,
    chart_vendor: str | None = None,
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
        chart_vendor=chart_vendor,
    )
    model = _view_model(payload, site_base_url=site_base_url)
    payload_json = _script_json(payload)
    structured_data_json = _script_json(_structured_data(model, payload))
    chart_controls_html = _chart_controls(model)
    reports_html = _report_cards(model["reports"])
    lenses_html = _strategy_lens_cards(payload.get("strategy_lenses") or [])
    outcomes_html = _outcome_cards((payload.get("analysis") or {}).get("outcomes") or [])
    notices_html = "".join(f"<li>{_h(notice)}</li>" for notice in payload.get("notices", []))
    chart_source_html = _data_source_strip(model["chart_source_rows"], label="차트 데이터 출처")
    analysis_source_html = _data_source_strip(model["analysis_source_rows"], label="공개 분석 출처")
    confidence_html = _analysis_confidence_panel(model["analysis_confidence"])
    stock_flow_html = _stock_flow_strip(model)
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
    <nav class="top-links" aria-label="서비스 페이지">
      <a href="/features/research">기능</a>
      <a href="/features/methodology">신뢰 기준</a>
      <a href="/analyses">분석 목록</a>
      <a href="/outcomes">성과</a>
      <a class="top-auth-link" href="/member" data-auth-visible="signed-out">로그인</a>
      <a class="top-join-link" href="/member?mode=signup" data-auth-visible="signed-out">가입하기</a>
      <a class="top-dashboard-link" href="/mypage" data-auth-visible="signed-in" hidden>마이페이지</a>
    </nav>
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
        <div class="stock-hero-actions" aria-label="종목 상세 주요 이동">
          <a href="/analyses?ticker={_h(model["code"])}">공개 분석 이력</a>
          <a href="/member#analysis-request-section">분석 요청</a>
        </div>
      </div>
      <aside class="stock-hero-stack" aria-label="종목 리서치 요약">
        <div class="decision-box">
          <span class="decision-label">AI 판단</span>
          <strong>{_h(model["rating"])}</strong>
          <span>{_h(model["action"])}</span>
        </div>
        {stock_signal_html}
      </aside>
    </section>

    {stock_flow_html}

    <section class="workspace">
      <section class="chart-panel" aria-labelledby="chart-title">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">KRW OHLCV</p>
            <h2 id="chart-title">가격 흐름</h2>
          </div>
          <div class="chart-heading-meta">
            <span class="status-pill">{_h(model["chart_status"])}</span>
            <span class="data-pill">{_h(model["chart_vendor_label"])}</span>
          </div>
        </div>
        {chart_controls_html}
        <p class="chart-caption">{_h(model["chart_caption"])}</p>
        {chart_source_html}
        <div class="chart-wrap">
          <canvas id="priceChart" aria-label="{_h(model["name"])} 가격 차트"></canvas>
          <div class="chart-legend" id="chartLegend" aria-hidden="true"></div>
          <div class="chart-tooltip" id="chartTooltip" hidden></div>
          <p id="chartFallback" class="chart-fallback" hidden>{_h(model["chart_fallback"])}</p>
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
          {analysis_source_html}
          {confidence_html}
        </section>
      </aside>
    </section>

    {lenses_html}

    {outcomes_html}

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
    summary_html = _analysis_summary_cards(model["summary"])
    track_record_html = _analysis_track_record_cards(model["summary"])
    cards_html = _analysis_feed_cards(model["items"])
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
    <nav class="top-links" aria-label="공개 페이지">
      <a href="/features/research">기능</a>
      <a href="/features/methodology">신뢰 기준</a>
      <a href="/analyses">분석 목록</a>
      <a href="/outcomes">성과</a>
      <a class="top-auth-link" href="/member" data-auth-visible="signed-out">로그인</a>
      <a class="top-join-link" href="/member?mode=signup" data-auth-visible="signed-out">가입하기</a>
      <a class="top-dashboard-link" href="/mypage" data-auth-visible="signed-in" hidden>마이페이지</a>
    </nav>
  </header>

  <main id="main-content" class="shell market-shell">
    <section class="summary-band" aria-labelledby="feed-title">
      <div>
        <p class="eyebrow">Public Analysis Feed</p>
        <h1 id="feed-title">공개 분석 목록</h1>
        <p class="asof">{_h(model["subtitle"])}</p>
      </div>
      <div class="decision-box">
        <span class="decision-label">공개 리포트</span>
        <strong>{_h(model["item_count"])}</strong>
        <span>{_h(model["status"])}</span>
      </div>
    </section>

    <section class="analysis-filter-panel" aria-label="공개 분석 필터">
      <form class="analysis-filter-form" action="/analyses" method="get">
        <label for="analysisTicker">종목 필터</label>
        <input id="analysisTicker" name="ticker" maxlength="12" value="{_h(str(model["ticker_code"] or ""))}" placeholder="005930">
        <button type="submit">필터 적용</button>
        <a href="/analyses">전체 보기</a>
      </form>
      <p>저장된 public run만 노출하며, 회원 포트폴리오나 개인 watchlist API는 호출하지 않습니다.</p>
    </section>

    <section class="analysis-pipeline-strip" aria-label="공개 분석 공개 기준">
      <article>
        <span>01</span>
        <strong>Stored Run</strong>
        <small>완료된 public 분석만 목록에 노출합니다.</small>
      </article>
      <article>
        <span>02</span>
        <strong>Agent Evidence</strong>
        <small>에이전트 리포트와 판단 요약을 분리해 제공합니다.</small>
      </article>
      <article>
        <span>03</span>
        <strong>Outcome Check</strong>
        <small>5일/20일 성과 검증이 연결되면 알파를 표시합니다.</small>
      </article>
    </section>

    {summary_html}

    {track_record_html}

    <section class="report-section" aria-labelledby="feed-list-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Completed Runs</p>
          <h2 id="feed-list-title">최근 완료된 분석</h2>
        </div>
        <span class="status-pill">{_h(model["filter_label"])}</span>
      </div>
      <div class="analysis-feed-grid">
        {cards_html}
      </div>
    </section>

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>
        <li>AI analysis is for informational purposes only and is not investment advice.</li>
        <li>Live trading and broker order placement are intentionally not supported.</li>
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
    summary_html = _analysis_outcome_summary_cards(model["summary"])
    cadence_html = _analysis_outcome_cadence_strip(model)
    cards_html = _analysis_outcome_feed_cards(model["items"])
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
    <nav class="top-links" aria-label="공개 페이지">
      <a href="/features/research">기능</a>
      <a href="/features/methodology">신뢰 기준</a>
      <a href="/analyses">분석 목록</a>
      <a href="/outcomes" aria-current="page">성과</a>
      <a class="top-auth-link" href="/member" data-auth-visible="signed-out">로그인</a>
      <a class="top-join-link" href="/member?mode=signup" data-auth-visible="signed-out">가입하기</a>
      <a class="top-dashboard-link" href="/mypage" data-auth-visible="signed-in" hidden>마이페이지</a>
    </nav>
  </header>

  <main id="main-content" class="shell market-shell">
    <section class="summary-band outcome-hero" aria-labelledby="outcomes-title">
      <div>
        <p class="eyebrow">Outcome Verification</p>
        <h1 id="outcomes-title"><span class="outcome-title-line">성과 검증</span> <span class="outcome-title-line">대시보드</span></h1>
        <p class="asof">{_h(model["subtitle"])}</p>
        <div class="analysis-detail-actions">
          <a href="/analyses">공개 분석 보기</a>
          <a href="/features/outcomes">검증 방식</a>
          <a href="/api/analysis-outcomes">JSON</a>
        </div>
      </div>
      <div class="decision-box">
        <span class="decision-label">Outcome Track Record</span>
        <strong>{_h(model["item_count"])}</strong>
        <span>{_h(model["status_label"])}</span>
      </div>
    </section>

    <section class="analysis-filter-panel outcome-filter-panel" aria-label="성과 검증 필터">
      <form class="analysis-filter-form outcome-filter-form" action="/outcomes" method="get">
        <label for="outcomeTicker">종목</label>
        <input id="outcomeTicker" name="ticker" maxlength="12" value="{_h(str(model["ticker_code"] or ""))}" placeholder="005930">
        <label for="outcomeStatus">상태</label>
        <select id="outcomeStatus" name="status">
          {_outcome_status_options(model["filter_status"])}
        </select>
        <button type="submit">필터 적용</button>
        <a href="/outcomes">초기화</a>
      </form>
      <p>완료된 public run의 5일/20일 사후 성과만 공개합니다. 계좌 주문이나 브로커 실행 권한은 연결하지 않습니다.</p>
    </section>

    {summary_html}

    {cadence_html}

    <section class="report-section outcome-feed-section" aria-labelledby="outcome-feed-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Evaluated Runs</p>
          <h2 id="outcome-feed-title">검증된 공개 분석</h2>
        </div>
        <span class="status-pill">{_h(model["filter_label"])}</span>
      </div>
      <div class="outcome-feed-grid">
        {cards_html}
      </div>
    </section>

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>
        <li>성과 검증은 과거 public 분석의 사후 기록이며 미래 수익을 보장하지 않습니다.</li>
        <li>TradingAgents Korea는 실거래 주문과 브로커 주문 placement를 의도적으로 지원하지 않습니다.</li>
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
    reports_html = _analysis_detail_report_cards(model["reports"])
    decision_html = _analysis_detail_decision_card(model["decision"])
    outcomes_html = _outcome_cards(model["outcomes"])
    provenance_html = _analysis_detail_provenance(model)
    detail_map_html = _analysis_detail_map(model)
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
    <nav class="top-links" aria-label="공개 페이지">
      <a href="/features/research">기능</a>
      <a href="/features/methodology">신뢰 기준</a>
      <a href="/analyses">분석 목록</a>
      <a href="/outcomes">성과</a>
      <a href="/stocks/{_h(model["ticker_code"])}">종목</a>
      <a class="top-auth-link" href="/member" data-auth-visible="signed-out">로그인</a>
      <a class="top-join-link" href="/member?mode=signup" data-auth-visible="signed-out">가입하기</a>
      <a class="top-dashboard-link" href="/mypage" data-auth-visible="signed-in" hidden>마이페이지</a>
    </nav>
  </header>

  <main id="main-content" class="shell market-shell">
    <section class="analysis-detail-hero" aria-labelledby="analysis-detail-title">
      <div>
        <p class="eyebrow">Public Analysis Report</p>
        <h1 id="analysis-detail-title">{_h(model["heading"])}</h1>
        <p class="asof">{_h(model["subtitle"])}</p>
        <div class="analysis-detail-actions">
          <a href="/stocks/{_h(model["ticker_code"])}">종목 페이지</a>
          <a href="/analyses">목록</a>
          <a href="/api/analyses/{_h(model["run_id"])}">JSON</a>
        </div>
      </div>
      <aside class="decision-box analysis-detail-decision">
        <span class="decision-label">투자 판단 아님</span>
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
          <p class="eyebrow">Agent Reports</p>
          <h2 id="analysis-reports-title">에이전트 리포트</h2>
        </div>
        <span class="status-pill">{_h(model["report_count_label"])}</span>
      </div>
      <div class="analysis-report-stack">
        {reports_html}
      </div>
    </section>

    {outcomes_html}

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>
        <li>이 공개 리포트는 정보 제공용이며 투자 조언이나 매수/매도 지시가 아닙니다.</li>
        <li>TradingAgents Korea는 실거래 주문과 브로커 주문 placement를 의도적으로 지원하지 않습니다.</li>
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
    <nav class="top-links" aria-label="공개 페이지">
      <a href="/features/research">기능</a>
      <a href="/features/methodology">신뢰 기준</a>
      <a href="/analyses">분석 목록</a>
      <a class="top-auth-link" href="/member" data-auth-visible="signed-out">로그인</a>
      <a class="top-join-link" href="/member?mode=signup" data-auth-visible="signed-out">가입하기</a>
      <a class="top-dashboard-link" href="/mypage" data-auth-visible="signed-in" hidden>마이페이지</a>
    </nav>
  </header>

  <main id="main-content" class="home-shell home-shell-art">
    <section class="home-hero home-hero-artboard" aria-labelledby="home-title">
      <div class="home-hero-copy home-hero-content">
        <p class="home-kicker">KR Market Signal Desk / Read-only AI Research</p>
        <h1 id="home-title">한국 투자자를 위한 AI 리서치 신호망</h1>
        <p class="home-lede">KRX 시세, DART 공시, Naver 뉴스와 공개 리포트를 한 화면에 연결합니다. 5일/20일 사후 성과와 주문 차단 원칙까지 드러내, 투자 판단의 근거를 확인하게 합니다.</p>
        <div class="home-trust-panel" aria-label="신뢰 운영 기준">
          <div>
            <span>공식·공개 데이터</span>
            <strong>KRX / DART / Naver</strong>
          </div>
          <div>
            <span>사후 검증</span>
            <strong>5D / 20D outcome</strong>
          </div>
          <div>
            <span>투자자 보호</span>
            <strong>실거래 주문 기능 차단</strong>
          </div>
        </div>
        <form class="ticker-search home-search home-command-search" action="/stocks" method="get">
          <label class="sr-only" for="ticker">종목코드 또는 종목명</label>
          <input id="ticker" name="ticker" list="tickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" autocomplete="off">
          <datalist id="tickerSuggestions"></datalist>
          <button type="submit">조회</button>
        </form>
        <div class="home-cta-row home-action-row" aria-label="주요 링크">
          <a class="home-primary-link" href="/stocks/005930">샘플 분석 보기</a>
          <a class="home-secondary-link" href="/analyses">최근 공개 분석</a>
          <a class="home-secondary-link" href="/features/research">기능 구조</a>
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
            <dd>읽기 전용</dd>
          </div>
        </dl>
      </div>
      <div class="home-hero-visual home-signal-art" aria-label="한국 주식 AI 분석 신호 아트보드">
        <canvas id="homeSignalCanvas" class="home-signal-canvas" aria-hidden="true"></canvas>
        <div class="home-market-field" aria-hidden="true">
          <span class="home-scanline"></span>
          <span class="home-index-map"></span>
          <span class="home-signal-thread"></span>
        </div>
        <div class="home-console signal-stock-card">
          <div class="home-console-top">
            <span>KRX SIGNAL</span>
            <span>READ-ONLY LAB</span>
          </div>
          <div class="home-console-focus">
            <span id="homeSignalTicker">005930 / 삼성전자</span>
            <strong id="homeSignalDecision">HOLD WATCH</strong>
            <small id="homeSignalMeta">price + disclosure + news + benchmark alpha</small>
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
            <div><span>Price</span><strong>OHLCV</strong></div>
            <div><span>Disclosure</span><strong>DART</strong></div>
            <div><span>News</span><strong>Naver</strong></div>
            <div><span>Outcome</span><strong>5D / 20D</strong></div>
          </div>
        </div>
        <div class="home-pipeline signal-flow-row" aria-hidden="true">
          <span>KRX</span>
          <span>DART</span>
          <span>NEWS</span>
          <span>AGENTS</span>
          <span>REPORT</span>
        </div>
        <div class="home-live-tape" aria-hidden="true">
          <div class="home-live-tape-track">
            <span>005930 삼성전자 / KRX OHLCV / DART event</span>
            <span>000660 SK하이닉스 / benchmark alpha / news impulse</span>
            <span>035420 NAVER / disclosure watch / 20D outcome</span>
            <span>086520 에코프로 / volatility guard / read-only</span>
            <span>005930 삼성전자 / KRX OHLCV / DART event</span>
            <span>000660 SK하이닉스 / benchmark alpha / news impulse</span>
          </div>
        </div>
      </div>
    </section>

    <section class="home-lens-band" aria-labelledby="lens-home-title">
      <div class="home-section-heading">
        <div>
          <p class="eyebrow">Analysis Lenses</p>
          <h2 id="lens-home-title">종목을 다섯 개의 신호로 분해합니다</h2>
        </div>
        <p>차트만 보거나 뉴스만 읽는 화면이 아니라, 가격과 이벤트를 함께 묶어 공개 분석의 맥락을 만듭니다. <a href="/features/research">리서치 구조 보기</a></p>
      </div>
      <div class="home-lens-grid">
        <article><span>01</span><strong>Price</strong><p>KRW OHLCV와 이동평균, 거래량 흐름을 확인합니다.</p></article>
        <article><span>02</span><strong>Disclosure</strong><p>DART 공시와 재무 이벤트를 분석 흐름에 반영합니다.</p></article>
        <article><span>03</span><strong>News</strong><p>Naver 뉴스 신호로 단기 이슈와 시장 반응을 추적합니다.</p></article>
        <article><span>04</span><strong>Agents</strong><p>복수 에이전트 판단을 공개 리포트 구조로 정리합니다.</p></article>
        <article><span>05</span><strong>Outcome</strong><p>5일/20일 성과 검증으로 판단 이후를 기록합니다.</p></article>
      </div>
    </section>

    <section class="home-analysis-zone home-recent-intel" aria-labelledby="recent-title">
      <div class="home-section-copy">
        <p class="eyebrow">Public Intelligence</p>
        <h2 id="recent-title">최근 공개 분석</h2>
        <p>완료된 AI 분석은 종목 페이지와 공개 피드에 누적됩니다. 판단, 모델, 리포트 수, 벤치마크 대비 알파를 빠르게 훑고 원문 JSON까지 확인할 수 있습니다.</p>
        <a class="home-secondary-link" href="/analyses">전체 분석 목록</a>
      </div>
      <div class="home-analysis-grid">
        {recent_html}
      </div>
    </section>

    <section class="home-band home-stock-jump" aria-labelledby="quick-title">
      <div class="home-section-heading">
        <div>
          <p class="eyebrow">Quick Start</p>
          <h2 id="quick-title">주요 종목 바로가기</h2>
        </div>
        <p>삼성전자, SK하이닉스, NAVER처럼 자주 확인하는 종목은 바로 차트와 공개 분석 페이지로 이동합니다.</p>
      </div>
      <div class="home-ticker-rail">
        {quick_html}
      </div>
    </section>

    <section class="home-ops-strip" aria-label="서비스 원칙">
      <div>
        <p class="eyebrow">Operating Boundary</p>
        <h2>조회와 기록에 집중한 READ-ONLY 리서치</h2>
      </div>
      <ul>
        <li>실거래 주문 기능은 의도적으로 지원하지 않습니다.</li>
        <li>AI analysis is informational and is not investment advice.</li>
        <li><a href="/features/methodology">데이터 출처와 한계</a>를 공개 방법론으로 분리해 설명합니다.</li>
      </ul>
    </section>

    <section class="home-band home-member-band" aria-labelledby="member-title">
      <div class="home-section-heading">
        <div>
          <p class="eyebrow">Member Workspace</p>
          <h2 id="member-title">회원은 포트폴리오와 관심종목을 따로 관리합니다</h2>
        </div>
        <a class="home-primary-link" href="/mypage">마이페이지 열기</a>
      </div>
      <div class="home-flow-list">
        <article>
          <span>01</span>
          <strong>수동 포트폴리오</strong>
          <p>매수/매도 기록, 평균단가, 목표가, 손절가를 직접 입력합니다.</p>
        </article>
        <article>
          <span>02</span>
          <strong>관심종목</strong>
          <p>한국 종목코드 기준으로 메모와 함께 watchlist를 관리합니다.</p>
        </article>
        <article>
          <span>03</span>
          <strong>분석 요청 큐</strong>
          <p>원하는 종목을 요청하면 worker가 공개 분석 흐름으로 처리합니다.</p>
        </article>
      </div>
    </section>
  </main>

  <script>{PAGE_JS}</script>
</body>
</html>"""


FEATURE_DETAIL_PAGES: dict[str, dict[str, Any]] = {
    "research": {
        "path": "/features/research",
        "title": "AI 리서치 파이프라인 | TradingAgents Korea",
        "description": "KRX, DART, Naver 뉴스와 TradingAgents 리포트를 연결하는 한국 주식 AI 리서치 흐름입니다.",
        "eyebrow": "Feature / Research Pipeline",
        "heading": "KRX부터 공개 리포트까지 한 화면에 연결",
        "lead": "종목 상세 페이지는 가격, 공시, 뉴스, 에이전트 리포트, 사후 검증을 분리해 불러옵니다. 사용자가 종목을 조회할 때 필요한 공개 데이터만 조합하고 회원 전용 기록은 요청하지 않습니다.",
        "proof": (("공개 페이지", "종목·분석 피드"), ("데이터", "KRX / DART / Naver"), ("주문", "실거래 차단")),
        "cards": (
            ("종목 조회", "6자리 한국 종목코드와 종목명 resolver로 KOSPI/KOSDAQ 종목을 찾습니다."),
            ("차트 payload", "OHLCV 차트, 가격 상태, 데이터 vendor 표기를 종목 화면에만 전달합니다."),
            ("공개 분석", "완료된 public 리포트와 판단, 모델, 리포트 수를 공개 피드와 연결합니다."),
        ),
        "steps": ("Ticker resolver", "KRX OHLCV", "DART disclosure", "Naver news", "Agents report"),
        "cta_label": "샘플 종목 보기",
        "cta_href": "/stocks/005930",
    },
    "member-workspace": {
        "path": "/features/member-workspace",
        "title": "회원 작업공간 | TradingAgents Korea",
        "description": "로그인한 사용자를 위한 수동 포트폴리오, 관심목록, 분석 요청 큐의 구성 방식입니다.",
        "eyebrow": "Feature / Member Workspace",
        "heading": "마이페이지는 로그인 후에만 개인 데이터를 불러옵니다",
        "lead": "회원 화면은 인증 전에는 로그인/가입만 보여주고, 세션 확인 뒤에만 수동 기록과 요청 큐 API를 호출합니다. 공개 페이지와 개인 기록의 데이터 경계를 명확히 나눕니다.",
        "proof": (("인증", "Supabase Auth"), ("저장", "사용자별 private API"), ("범위", "조회/기록 전용")),
        "cards": (
            ("수동 포트폴리오", "매수·매도 기록, 평균단가, 비용, 목표가, 손절가를 직접 관리합니다."),
            ("관심목록", "한국 종목코드 기준 watchlist와 메모를 사용자별로 분리합니다."),
            ("분석 요청 큐", "원하는 종목과 날짜를 큐에 넣고 처리 상태를 확인합니다."),
        ),
        "steps": ("Sign in", "Member dashboard", "Private records", "Request queue", "Read-only guard"),
        "cta_label": "마이페이지 열기",
        "cta_href": "/mypage",
    },
    "outcomes": {
        "path": "/features/outcomes",
        "title": "사후 성과 검증 | TradingAgents Korea",
        "description": "AI 분석 이후 5일/20일 성과와 벤치마크 대비 알파를 공개 검증하는 구조입니다.",
        "eyebrow": "Feature / Outcome Verification",
        "heading": "AI 판단 이후의 결과까지 남깁니다",
        "lead": "공개 분석은 완료 시점에서 끝나지 않습니다. outcome worker가 5일/20일 이후 성과를 계산하고 벤치마크 대비 알파를 남겨, 리포트 품질을 추적할 수 있게 합니다.",
        "proof": (("검증", "5D / 20D"), ("지표", "raw return / alpha"), ("노출", "public feed")),
        "cards": (
            ("성과 저장", "분석 run과 horizon별 outcome을 저장해 공개 리포트와 연결합니다."),
            ("벤치마크 비교", "KOSPI/KOSDAQ 흐름과 비교한 alpha return을 보여줍니다."),
            ("운영 점검", "관리자와 cron worker가 큐를 처리하고 실패 상태를 확인합니다."),
        ),
        "steps": ("Completed run", "Outcome worker", "Benchmark return", "Alpha return", "Public review"),
        "cta_label": "공개 분석 보기",
        "cta_href": "/analyses",
    },
    "methodology": {
        "path": "/features/methodology",
        "title": "방법론과 신뢰 기준 | TradingAgents Korea",
        "description": "TradingAgents Korea의 데이터 출처, AI 분석 한계, outcome 검증, read-only 운영 원칙입니다.",
        "eyebrow": "Trust / Methodology",
        "heading": "데이터 출처와 한계를 함께 공개합니다",
        "lead": "공개 리포트는 종목 판단의 근거를 보여주는 자료입니다. KRX, DART, Naver 뉴스, 에이전트 리포트, 5D/20D outcome을 한 흐름으로 묶되, 투자 실행 권한은 서비스가 갖지 않습니다.",
        "proof": (("출처", "KRX / DART / Naver"), ("검증", "5D / 20D outcome"), ("권한", "주문 차단")),
        "cards": (
            ("데이터 기준", "공개 화면은 기준일, vendor, fallback 여부를 최대한 노출하고 원문 JSON으로 검증할 수 있게 둡니다."),
            ("AI 한계", "리포트는 정보 제공용이며 누락 데이터, 시장 휴장, vendor 장애, 모델 오류 가능성을 전제로 읽어야 합니다."),
            ("사후 검증", "완료된 public run은 outcome worker가 5일/20일 뒤 raw return과 benchmark alpha를 추적합니다."),
            ("회원 경계", "회원 포트폴리오와 관심종목은 개인 기록이며 공개 리포트 feed와 분리해 호출합니다."),
            ("운영 보안", "worker token은 브라우저 세션 입력값으로만 사용하고 HTML, 문서, 커밋에 포함하지 않습니다."),
            ("실행 차단", "KIS 같은 브로커 연동은 read-only 계좌조회 검토까지만 가능하며 주문 placement는 구현하지 않습니다."),
        ),
        "steps": ("Source labels", "Run metadata", "Agent report", "Outcome check", "No order path"),
        "cta_label": "공개 분석 보기",
        "cta_href": "/analyses",
    },
}


def feature_detail_slugs() -> tuple[str, ...]:
    return tuple(FEATURE_DETAIL_PAGES)


def feature_detail_paths() -> tuple[str, ...]:
    return tuple(str(page["path"]) for page in FEATURE_DETAIL_PAGES.values())


def render_feature_detail_page(slug: str, *, site_base_url: str | None = None) -> str:
    """Render a public feature detail page using the landing-page visual language."""

    page = FEATURE_DETAIL_PAGES.get(slug)
    if page is None:
        raise ValueError("Unknown feature page")

    proof_html = "".join(
        f"""<div><dt>{_h(label)}</dt><dd>{_h(value)}</dd></div>"""
        for label, value in page["proof"]
    )
    card_html = "".join(
        f"""<article><span>{index:02d}</span><strong>{_h(title)}</strong><p>{_h(copy)}</p></article>"""
        for index, (title, copy) in enumerate(page["cards"], start=1)
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
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(page["title"])}">
  <meta property="og:description" content="{_h(page["description"])}">
  <meta property="og:url" content="{_h(canonical)}">
  <style>{PAGE_CSS}</style>
</head>
<body class="public-home feature-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    <nav class="top-links" aria-label="공개 페이지">
      <a href="/features/research">기능</a>
      <a href="/features/methodology">신뢰 기준</a>
      <a href="/analyses">분석 목록</a>
      <a class="top-auth-link" href="/member" data-auth-visible="signed-out">로그인</a>
      <a class="top-join-link" href="/member?mode=signup" data-auth-visible="signed-out">가입하기</a>
      <a class="top-dashboard-link" href="/mypage" data-auth-visible="signed-in" hidden>마이페이지</a>
    </nav>
  </header>

  <main id="main-content" class="home-shell feature-shell">
    <section class="feature-hero" aria-labelledby="feature-title">
      <div class="feature-copy">
        <p class="home-kicker">{_h(page["eyebrow"])}</p>
        <h1 id="feature-title">{_h(page["heading"])}</h1>
        <p>{_h(page["lead"])}</p>
        <dl class="home-proof-row feature-proof-row" aria-label="기능 기준">
          {proof_html}
        </dl>
        <div class="home-cta-row">
          <a class="home-primary-link" href="{_h(page["cta_href"])}">{_h(page["cta_label"])}</a>
          <a class="home-secondary-link" href="/features/member-workspace">회원 기능 보기</a>
        </div>
      </div>
      <div class="feature-diagram" aria-label="기능 데이터 흐름">
        <div class="feature-diagram-top">
          <span>TA-KR</span>
          <span>READ-ONLY</span>
        </div>
        <div class="feature-step-track">
          {step_html}
        </div>
        <div class="feature-signal-card">
          <span>{_h(slug.upper())}</span>
          <strong>{_h(page["heading"])}</strong>
          <small>{_h(page["description"])}</small>
        </div>
      </div>
    </section>

    <section class="feature-card-grid" aria-label="기능 세부 구성">
      {card_html}
    </section>

    <section class="home-ops-strip feature-boundary" aria-label="데이터 로딩 경계">
      <div>
        <p class="eyebrow">Loading Boundary</p>
        <h2>페이지 목적에 맞는 데이터만 요청합니다</h2>
      </div>
      <ul>
        <li>공개 상세 페이지는 정적 설명과 인증 상태 네비게이션만 사용합니다.</li>
        <li>회원 API는 로그인 세션 확인 뒤 마이페이지에서만 호출합니다.</li>
      </ul>
    </section>
  </main>

  <script>{PAGE_JS}</script>
</body>
</html>"""


def render_admin_console_page(*, site_base_url: str | None = None) -> str:
    """Render a noindex operator console that never embeds worker secrets."""

    canonical = canonical_url("/admin", site_base_url=site_base_url)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>관리자 콘솔 | TradingAgents Korea</title>
  <meta name="description" content="TradingAgents Korea 운영 큐와 readiness를 점검하는 관리자 콘솔입니다.">
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
    <nav class="top-links" aria-label="관리 페이지">
      <a href="/features/research">기능</a>
      <a href="/features/methodology">신뢰 기준</a>
      <a href="/analyses">분석 목록</a>
      <a class="top-auth-link" href="/member" data-auth-visible="signed-out">로그인</a>
      <a class="top-dashboard-link" href="/mypage" data-auth-visible="signed-in" hidden>마이페이지</a>
    </nav>
  </header>

  <main id="main-content" class="home-shell admin-shell">
    <section class="admin-hero" aria-labelledby="admin-title">
      <div>
        <p class="home-kicker">Operator Console / No Secret Embedded</p>
        <h1 id="admin-title">운영 큐와 readiness만 점검합니다</h1>
        <p>관리자 화면은 worker token을 코드나 HTML에 포함하지 않습니다. 토큰은 브라우저 세션에만 보관되며 기존 admin API 호출 헤더로만 전송됩니다.</p>
      </div>
      <form class="admin-token-panel" id="adminTokenForm">
        <label>
          <span>Worker token</span>
          <input id="adminWorkerToken" name="worker_token" type="password" autocomplete="off" placeholder="TRADINGAGENTS_WORKER_TOKEN">
        </label>
        <button type="submit">세션에 저장</button>
        <small id="adminTokenState">토큰은 서버 렌더 HTML에 저장되지 않습니다.</small>
      </form>
    </section>

    <section class="admin-health-strip" aria-label="운영 기준 요약">
      <article>
        <span>readiness</span>
        <strong>수동 확인</strong>
        <small>배포 SHA, storage, KRX probe를 같은 패널에서 확인합니다.</small>
      </article>
      <article>
        <span>worker</span>
        <strong>토큰 입력형</strong>
        <small>HTML에는 secret을 싣지 않고 세션 스토리지에만 둡니다.</small>
      </article>
      <article>
        <span>queue</span>
        <strong>dry run 우선</strong>
        <small>분석 요청과 outcome 처리는 실행 전 결과를 미리 봅니다.</small>
      </article>
      <article>
        <span>boundary</span>
        <strong>read-only</strong>
        <small>운영 콘솔에도 실거래 주문 경로는 없습니다.</small>
      </article>
    </section>

    <section class="admin-workflow-strip" aria-label="권장 운영 순서">
      <article>
        <span>01</span>
        <strong>Readiness</strong>
        <small>페이지 진입 시 자동 조회하고, 필요할 때 KRX/vendor probe를 추가합니다.</small>
      </article>
      <article>
        <span>02</span>
        <strong>Dry run</strong>
        <small>worker token 입력 후 실행 전 처리 대상과 제한값을 확인합니다.</small>
      </article>
      <article>
        <span>03</span>
        <strong>Process</strong>
        <small>분석 요청 또는 outcome worker를 제한된 건수만큼 실행합니다.</small>
      </article>
      <article>
        <span>04</span>
        <strong>Audit</strong>
        <small>결과 JSON과 readiness panel을 함께 보고 다음 운영 큐를 결정합니다.</small>
      </article>
    </section>

    <section class="admin-grid" aria-label="운영 작업">
      <article class="admin-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Readiness</p>
            <h2>서비스 상태</h2>
          </div>
          <div class="admin-check-row">
            <label class="admin-inline-check"><input id="adminProbeKrx" type="checkbox"> KRX probe</label>
            <label class="admin-inline-check"><input id="adminProbeVendors" type="checkbox"> Vendor probes</label>
          </div>
        </div>
        <button type="button" data-admin-readiness>상태 확인</button>
        <div class="admin-readiness-panel" id="adminReadinessPanel" aria-live="polite">
          <div class="readiness-cell is-waiting">
            <span>Status</span>
            <strong>대기</strong>
            <small>readiness를 실행하면 배포와 vendor 상태를 요약합니다.</small>
          </div>
        </div>
        <pre id="adminReadinessOutput">대기 중</pre>
      </article>

      <article class="admin-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Analysis Queue</p>
            <h2>분석 요청 처리</h2>
          </div>
          <span class="status-pill">admin api</span>
        </div>
        <label class="admin-number-field">Limit <input id="adminRequestLimit" type="number" min="1" max="20" value="5"></label>
        <div class="button-row">
          <button type="button" data-admin-action="requests-dry-run">Dry run</button>
          <button type="button" data-admin-action="requests-process">처리 실행</button>
        </div>
        <pre id="adminRequestsOutput">대기 중</pre>
      </article>

      <article class="admin-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Outcome Worker</p>
            <h2>성과 검증 처리</h2>
          </div>
          <span class="status-pill">5D / 20D</span>
        </div>
        <label class="admin-number-field">Limit <input id="adminOutcomeLimit" type="number" min="1" max="50" value="10"></label>
        <div class="button-row">
          <button type="button" data-admin-action="outcomes-dry-run">Dry run</button>
          <button type="button" data-admin-action="outcomes-process">처리 실행</button>
        </div>
        <pre id="adminOutcomesOutput">대기 중</pre>
      </article>
    </section>
  </main>

  <script>{PAGE_JS}</script>
  <script>{ADMIN_PAGE_JS}</script>
</body>
</html>"""


def render_member_dashboard_page(*, site_base_url: str | None = None, canonical_path: str = "/member") -> str:
    """Render the authenticated member dashboard shell."""

    model = {
        "title": "회원 대시보드 | TradingAgents Korea",
        "description": "수동 포트폴리오, 관심목록, 한국 주식 AI 분석 요청을 관리합니다.",
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
<body class="member-page is-member-signed-out">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    <nav class="top-links" aria-label="서비스 페이지">
      <a href="/features/research">기능</a>
      <a href="/features/methodology">신뢰 기준</a>
      <a href="/analyses">분석 목록</a>
      <a class="top-auth-link" href="/member" data-auth-visible="signed-out">로그인</a>
      <a class="top-join-link" href="/member?mode=signup" data-auth-visible="signed-out">가입하기</a>
      <a class="top-dashboard-link" href="/mypage" data-auth-visible="signed-in" hidden>마이페이지</a>
    </nav>
  </header>

  <main id="main-content" class="shell member-shell">
    <section class="member-auth-landing" id="memberAuthLanding" aria-labelledby="member-auth-title">
      <div class="member-auth-copy">
        <p class="eyebrow">Member Access</p>
        <h1 id="member-auth-title">리서치 노트를 안전하게 보관하세요</h1>
        <p class="member-auth-lead">회원 작업공간은 로그인 후에만 열립니다. TradingAgents Korea는 계좌 주문을 실행하지 않고, 공개 데이터 기반의 판단 근거를 정리합니다.</p>
        <div class="member-auth-points" aria-label="회원 영역 원칙">
          <article>
            <span>01</span>
            <strong>읽기 전용 원칙</strong>
            <small>실거래 주문 기능은 차단하고 기록과 조회 흐름만 제공합니다.</small>
          </article>
          <article>
            <span>02</span>
            <strong>공식 데이터 기준</strong>
            <small>KRX, DART, 공개 뉴스 흐름을 분리해 분석 근거를 남깁니다.</small>
          </article>
          <article>
            <span>03</span>
            <strong>개인 작업공간</strong>
            <small>로그인한 사용자에게만 저장 기록과 검토 큐를 보여줍니다.</small>
          </article>
        </div>
      </div>

      <section class="member-panel auth-panel" aria-labelledby="auth-panel-title">
        <div class="panel-heading auth-heading">
          <div>
            <p class="eyebrow">Secure sign-in</p>
            <h2 id="auth-panel-title">로그인 / 가입</h2>
          </div>
          <span class="status-pill">Read only</span>
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
              <button class="ghost-button password-toggle" id="passwordToggle" type="button" aria-pressed="false">보기</button>
            </span>
          </label>
          <div class="button-row auth-button-row" aria-label="인증 작업">
            <button type="button" data-auth-action="signin">로그인</button>
            <button type="button" data-auth-action="signup">가입하기</button>
          </div>
          <div class="member-empty auth-status" id="authStatus" role="status" aria-live="polite">이메일과 비밀번호를 입력하세요.</div>
        </form>
      </section>
    </section>

    <section class="member-workspace" id="memberWorkspace" hidden>
      <section class="summary-band member-summary-band" aria-labelledby="member-title">
        <div>
          <p class="eyebrow">Member Workspace</p>
          <h1 id="member-title">내 투자 노트</h1>
          <p class="asof" id="memberStatus">로그인 상태 확인 중</p>
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

      <nav class="member-tab-strip" role="tablist" aria-label="마이페이지 섹션">
        <a id="home-tab" class="is-active" href="#member-home-section" role="tab" data-member-tab="home" aria-controls="member-home-section" aria-selected="true">홈 <span id="memberHomeStatus">Ready</span></a>
        <a id="portfolio-tab" href="#portfolio-section" role="tab" data-member-tab="portfolio" aria-controls="portfolio-section" aria-selected="false">포트폴리오 <span id="portfolioTabCount">0</span></a>
        <a id="watchlist-tab" href="#watchlist-section" role="tab" data-member-tab="watchlist" aria-controls="watchlist-section" aria-selected="false">관심종목 <span id="watchlistTabCount">0</span></a>
        <a id="analysis-tab" href="#analysis-request-section" role="tab" data-member-tab="analysis" aria-controls="analysis-request-section" aria-selected="false">분석 요청 <span id="analysisTabCount">0</span></a>
      </nav>

      <section class="member-grid" aria-label="회원 기능">
        <section class="member-panel member-home-panel" id="member-home-section" role="tabpanel" data-member-panel="home" aria-labelledby="home-tab">
          <div class="panel-heading">
            <div>
              <p class="eyebrow">My Page Home</p>
              <h2>마이페이지 홈</h2>
              <p class="panel-copy">내 기록과 공개 리포트 요청 상태를 먼저 확인하고, 필요한 작업만 각 탭에서 이어갑니다.</p>
            </div>
            <span class="status-pill">Read only</span>
          </div>
          <section class="member-overview-strip" id="memberOverview" aria-label="작업공간 요약">
            <article>
              <span>Portfolios</span>
              <strong id="memberOverviewPortfolios">0</strong>
              <small>저장된 노트</small>
            </article>
            <article>
              <span>Watchlist</span>
              <strong id="memberOverviewWatchlists">0</strong>
              <small>관심목록</small>
            </article>
            <article>
              <span>Active Queue</span>
              <strong id="memberOverviewActiveRequests">0</strong>
              <small>대기/처리 중</small>
            </article>
            <article>
              <span>Reports</span>
              <strong id="memberOverviewCompletedReports">0</strong>
              <small>완료 리포트</small>
            </article>
          </section>
          <div class="member-home-grid" aria-label="다음 작업">
            <article class="member-home-card">
              <span>01</span>
              <strong>거래 기록 정리</strong>
              <small>매수·매도 내역, 수수료, 세금, 목표가를 수동으로 남깁니다.</small>
              <button class="ghost-button" type="button" data-member-jump="portfolio">포트폴리오 열기</button>
            </article>
            <article class="member-home-card">
              <span>02</span>
              <strong>관심종목 점검</strong>
              <small>추적할 한국 종목을 묶고 메모와 현재가 상태를 같이 봅니다.</small>
              <button class="ghost-button" type="button" data-member-jump="watchlist">관심종목 열기</button>
            </article>
            <article class="member-home-card">
              <span>03</span>
              <strong>AI 분석 요청</strong>
              <small>worker 큐 제한과 완료 리포트 연결 상태를 확인합니다.</small>
              <button class="ghost-button" type="button" data-member-jump="analysis">분석 요청 열기</button>
            </article>
          </div>
        </section>

        <section class="member-panel" id="portfolio-section" role="tabpanel" data-member-panel="portfolio" aria-labelledby="portfolio-tab" hidden>
          <div class="panel-heading">
            <div>
              <p class="eyebrow">Manual Portfolio</p>
              <h2>수동 매수 기록</h2>
            </div>
            <button class="ghost-button" id="refreshMemberData" type="button">새로고침</button>
          </div>
          <div class="member-form-stack">
            <div class="member-form-block">
              <strong>새 포트폴리오</strong>
              <form class="member-form compact-form" id="portfolioForm">
                <input name="name" maxlength="80" placeholder="포트폴리오 이름" required>
                <button type="submit">추가</button>
              </form>
            </div>
            <div class="member-form-block">
              <strong>매수/매도 기록</strong>
              <form class="member-form trade-form" id="tradeForm">
                <select name="portfolio_id" required></select>
                <input name="ticker_code" maxlength="12" placeholder="005930" required>
                <select name="side" required>
                  <option value="buy">매수</option>
                  <option value="sell">매도</option>
                </select>
                <input name="trade_date" type="date" required>
                <input name="price" type="number" min="1" step="1" placeholder="단가" required>
                <input name="quantity" type="number" min="1" step="1" placeholder="수량" required>
                <input name="fee" type="number" min="0" step="1" placeholder="수수료">
                <input name="tax" type="number" min="0" step="1" placeholder="세금">
                <button type="submit">기록</button>
              </form>
            </div>
            <div class="member-form-block">
              <strong>목표/손절 메모</strong>
              <form class="member-form target-form" id="targetForm">
                <select name="portfolio_id" required></select>
                <input name="ticker_code" maxlength="12" placeholder="005930" required>
                <input name="target_price" type="number" min="1" step="1" placeholder="목표가">
                <input name="stop_price" type="number" min="1" step="1" placeholder="손절가">
                <input name="memo" maxlength="500" placeholder="목표 메모">
                <button type="submit">저장</button>
              </form>
            </div>
          </div>
          <div class="member-list" id="portfolioList"></div>
        </section>

        <section class="member-panel" id="watchlist-section" role="tabpanel" data-member-panel="watchlist" aria-labelledby="watchlist-tab" hidden>
          <div class="panel-heading">
            <div>
              <p class="eyebrow">Watchlist</p>
              <h2>관심종목</h2>
            </div>
            <span class="status-pill">KR</span>
          </div>
          <div class="member-form-stack">
            <div class="member-form-block">
              <strong>관심목록</strong>
              <form class="member-form compact-form" id="watchlistForm">
                <input name="name" maxlength="80" placeholder="관심목록 이름" required>
                <button type="submit">추가</button>
              </form>
            </div>
            <div class="member-form-block">
              <strong>종목 담기</strong>
              <form class="member-form compact-form" id="watchlistItemForm">
                <select name="watchlist_id" required></select>
                <input name="ticker_code" maxlength="12" placeholder="005930" required>
                <input name="memo" maxlength="500" placeholder="메모">
                <button type="submit">담기</button>
              </form>
            </div>
          </div>
          <div class="member-list" id="watchlistList"></div>
        </section>

        <section class="member-panel" id="analysis-request-section" role="tabpanel" data-member-panel="analysis" aria-labelledby="analysis-tab" hidden>
          <div class="panel-heading">
            <div>
              <p class="eyebrow">AI Analysis</p>
              <h2>분석 요청</h2>
              <p class="panel-copy">worker 큐 상태, 제한 사용량, 완료 리포트 연결을 한 곳에서 확인합니다.</p>
            </div>
            <span class="status-pill">Queued</span>
          </div>
          <form class="member-form compact-form" id="analysisRequestForm">
            <input name="ticker" maxlength="12" placeholder="005930" required>
            <input name="requested_trade_date" type="date">
            <input name="reason" maxlength="500" placeholder="요청 메모">
            <button type="submit">요청</button>
          </form>
          <div class="member-list" id="analysisRequestList"></div>
        </section>
      </section>
    </section>
  </main>

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
        "chart_vendor": _chart_vendor_value(chart.get("vendor")),
        "chart_vendor_label": _chart_vendor_label(chart.get("vendor")),
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
    period_options = [
        ("1W", "1주", 7),
        ("1M", "1개월", 30),
        ("3M", "3개월", 90),
        ("6M", "6개월", 180),
    ]
    range_links = []
    for key, label, days in period_options:
        start = end - timedelta(days=days)
        href = _stock_query_href(
            code,
            {
                "chart_start": start.isoformat(),
                "chart_end": end.isoformat(),
            },
        )
        active = _period_is_active(active_days, days)
        range_links.append(
            f'<a class="chart-tab{" is-active" if active else ""}" href="{_h(href)}"'
            f'{" aria-current=\"page\"" if active else ""}>{_h(label)}</a>'
        )

    pykrx_href = _stock_query_href(code, {"chart_vendor": "pykrx"})
    krx_href = _stock_query_href(code, {"chart_vendor": "krx"})
    vendor = model.get("chart_vendor")
    vendor_links = [
        f'<a class="chart-tab{" is-active" if vendor == "pykrx" else ""}" href="{_h(pykrx_href)}">pykrx</a>',
        f'<a class="chart-tab{" is-active" if vendor == "krx" else ""}" href="{_h(krx_href)}">KRX 14D</a>',
    ]

    return (
        '<div class="chart-toolbar">'
        '<nav class="chart-tabs" aria-label="차트 기간">'
        + "".join(range_links)
        + "</nav>"
        '<nav class="chart-tabs chart-vendor-tabs" aria-label="차트 데이터 소스">'
        + "".join(vendor_links)
        + "</nav>"
        "</div>"
    )


def _stock_signal_card(model: dict[str, Any]) -> str:
    confidence = model.get("analysis_confidence") or {}
    return f"""
    <div class="stock-signal-card">
      <span>Read-only signal</span>
      <strong>{_h(model.get("close") or "-")}</strong>
      <small>{_h(model.get("change") or "-")} / {_h(model.get("chart_vendor_label") or "데이터 확인")}</small>
      <dl>
        <div>
          <dt>분석 상태</dt>
          <dd>{_h(model.get("analysis_state") or "-")}</dd>
        </div>
        <div>
          <dt>근거</dt>
          <dd>{_h(confidence.get("label") or "확인 필요")}</dd>
        </div>
      </dl>
    </div>
    """


def _stock_flow_strip(model: dict[str, Any]) -> str:
    confidence = model.get("analysis_confidence") or {}
    items = [
        ("01", "KRX price", model.get("chart_caption") or "가격 데이터를 확인합니다."),
        ("02", "Public report", model.get("refresh_state") or "분석 상태 확인"),
        ("03", "Evidence check", confidence.get("label") or "근거 확인 필요"),
        ("04", "Read-only", "주문 기능 없이 조회와 기록 흐름만 제공합니다."),
    ]
    cards = "".join(
        f"""
        <article>
          <span>{_h(number)}</span>
          <strong>{_h(title)}</strong>
          <small>{_h(str(copy))}</small>
        </article>
        """
        for number, title, copy in items
    )
    return f"""
    <section class="stock-flow-strip" aria-label="종목 상세 리서치 흐름">
      {cards}
    </section>
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
    return [
        ("출처", str(chart.get("data_source_label") or _chart_vendor_label(chart.get("vendor")))),
        ("신선도", f"{chart.get('end_date') or '-'} 기준"),
        ("범위", f"{point_count}거래일"),
        ("vendor", f"요청 {requested} / 응답 {resolved}"),
        ("fallback", "사용" if chart.get("fallback_used") else "없음"),
    ]


def _analysis_source_rows(analysis: dict[str, Any], refresh: dict[str, Any]) -> list[tuple[str, str]]:
    run = analysis.get("run") or {}
    provider = run.get("model_provider") or "AI"
    run_id = str(run.get("id") or "")
    source = f"public run {run_id[:8]}" if run_id else _analysis_status_label(analysis.get("status"))
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
    return f"{prefix} ({reason}{age_label})"


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
        warnings.append("분석 저장소가 연결되지 않아 저장된 리포트를 확인할 수 없습니다.")
    elif status == "unavailable":
        warnings.append("분석 저장소 응답을 확인하지 못했습니다.")
    elif status != "available":
        warnings.append("공개 분석 상태를 확인해야 합니다.")

    if refresh.get("recommended"):
        reason = refresh.get("reason") or "refresh_recommended"
        warnings.append(f"분석 업데이트 권장: {reason}")
    if status == "available" and report_count == 0:
        warnings.append("에이전트 리포트가 저장되지 않았습니다.")
    if status == "available" and not has_decision:
        warnings.append("최종 판단 레코드가 저장되지 않았습니다.")
    if status == "available" and outcome_count == 0:
        warnings.append("5일/20일 사후 성과 검증이 아직 없습니다.")
    if chart.get("status") != "available":
        warnings.append(_chart_fallback_message(chart))
    elif point_count == 0:
        warnings.append("차트 거래일 데이터가 비어 있습니다.")
    return warnings


def _analysis_confidence_summary(*, status: str, score: int, warnings: list[str]) -> str:
    if status != "available":
        return "저장된 공개 분석이 없거나 불완전해 리포트 근거를 제한적으로만 볼 수 있습니다."
    if warnings:
        return "분석은 표시되지만 일부 근거가 비어 있어 JSON과 기준일을 함께 확인해야 합니다."
    return f"분석, 판단, 차트 근거가 함께 있어 현재 공개 화면 기준 신뢰 점수 {score}/7입니다."


def _analysis_confidence_panel(confidence: dict[str, Any]) -> str:
    warnings = confidence.get("warnings") or []
    warning_items = "".join(f"<li>{_h(warning)}</li>" for warning in warnings)
    warning_html = f"<ul>{warning_items}</ul>" if warning_items else "<p>현재 표시된 공개 데이터 블록에서 즉시 드러난 누락 경고는 없습니다.</p>"
    level = str(confidence.get("level") or "low")
    return f"""
    <div class="analysis-confidence-panel confidence-{_h(level)}" aria-label="분석 신뢰도와 누락 데이터 경고">
      <span>분석 신뢰도</span>
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
    if option_days == 7:
        return days <= 10
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
    if selected == "auto":
        return "auto"
    return "vendor 확인"


def _chart_caption(chart: dict[str, Any], points: list[dict[str, Any]]) -> str:
    start = chart.get("start_date") or "-"
    end = chart.get("end_date") or "-"
    vendor = _chart_vendor_label(chart.get("vendor"))
    point_label = f"{len(points):,}개 거래일" if points else "거래일 데이터 없음"
    fallback_note = " / auto fallback" if chart.get("fallback_used") else ""
    return f"{start} - {end} / {vendor} / {point_label}{fallback_note}"


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
    title = "공개 분석 목록 | TradingAgents Korea"
    description = "TradingAgents Korea의 한국 주식 AI 공개 분석 목록입니다."
    summary = payload.get("summary") or {}
    return {
        "title": title,
        "description": description,
        "canonical_url": canonical_url("/analyses", site_base_url=site_base_url),
        "subtitle": "한국 주식 AI 분석이 완료되면 이곳에 공개됩니다.",
        "status": _analysis_feed_status_label(payload.get("status")),
        "ticker_code": ticker_code,
        "filter_label": f"{ticker_code} 필터" if ticker_code else "전체 종목",
        "item_count": str(len(items)),
        "summary": summary,
        "items": items,
    }


def _analysis_outcomes_view_model(payload: dict[str, Any], *, site_base_url: str | None = None) -> dict[str, Any]:
    ticker_code = payload.get("ticker_code")
    filter_status = payload.get("filter_status")
    items = payload.get("items") or []
    filters = []
    if ticker_code:
        filters.append(str(ticker_code))
    if filter_status:
        filters.append(_outcome_status_label(str(filter_status)))
    filter_label = " / ".join(filters) if filters else "전체 성과"
    return {
        "title": "성과 검증 대시보드 | TradingAgents Korea",
        "description": "TradingAgents Korea 공개 분석의 5일/20일 사후 성과와 벤치마크 대비 알파를 확인합니다.",
        "canonical_url": canonical_url("/outcomes", site_base_url=site_base_url),
        "subtitle": "공개 분석의 5일/20일 사후 성과를 검증합니다.",
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
    source_label = str(metadata.get("source") or "stored run")
    currency_label = str(metadata.get("currency") or "KRW")
    language_label = str(metadata.get("output_language") or "ko-KR")
    analyst_label = _metadata_list_label(metadata.get("selected_analysts"), fallback="저장된 agent 목록 없음")
    created_label = _compact_timestamp(run.get("created_at"))
    completed_label = _compact_timestamp(run.get("completed_at"))
    rating = str(summary.get("decision_rating") or decision.get("rating") or "-")
    action = str(summary.get("decision_action") or decision.get("action") or "-")
    model_bits = [provider]
    if deep_model:
        model_bits.append(f"deep {deep_model}")
    if quick_model:
        model_bits.append(f"quick {quick_model}")
    heading = f"{ticker_name} 공개 분석 리포트"
    description = (
        f"{trade_date} 기준 {ticker_name}({ticker_code}) 공개 AI 분석입니다. "
        f"판단 {rating}, 리포트 {len(reports)}개, 사후 성과 검증 {summary.get('completed_outcome_count', 0)}건을 제공합니다."
    )
    return {
        "title": f"{ticker_name} {ticker_code} 공개 분석 리포트 | TradingAgents Korea",
        "description": description,
        "canonical_url": canonical_url(f"/analyses/{run_id}", site_base_url=site_base_url),
        "heading": heading,
        "subtitle": f"{trade_date} 기준 / {market} / run {run_id[:8]}",
        "run": run,
        "run_id": run_id,
        "ticker_code": ticker_code,
        "ticker_name": ticker_name,
        "market": market,
        "trade_date": trade_date,
        "decision": decision,
        "decision_label": f"{rating} / {action}",
        "data_basis": f"{trade_date} 기준, {provider} 공개 분석",
        "reports": reports,
        "outcomes": outcomes,
        "summary": summary,
        "model_label": " / ".join(model_bits),
        "source_label": source_label,
        "currency_label": currency_label,
        "language_label": language_label,
        "analyst_label": analyst_label,
        "timestamp_label": _timestamp_pair_label(created_label, completed_label),
        "metadata_note": f"source {source_label} / currency {currency_label} / language {language_label}",
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
        return f"created {created}"
    if created == "-":
        return f"completed {completed}"
    return f"created {created} / completed {completed}"


def _home_view_model(payload: dict[str, Any], *, site_base_url: str | None = None) -> dict[str, Any]:
    return {
        "title": "TradingAgents Korea | 한국 주식 AI 분석",
        "description": "한국 주식 종목코드와 종목명으로 AI 분석, KRW 차트, 공개 리포트를 탐색합니다.",
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
            <article class="analysis-feed-card">
              <span>{_h(market)}</span>
              <h3><a href="/stocks/{_h(code)}">{_h(name)} <small>{_h(code)}</small></a></h3>
              <p>KRW 차트와 공개 분석 상태를 확인합니다.</p>
              <dl>
                <div><dt>통화</dt><dd>KRW</dd></div>
                <div><dt>페이지</dt><dd>분석 보기</dd></div>
              </dl>
            </article>
            """
        )
    return "\n".join(cards)


def _analysis_summary_cards(summary: dict[str, Any]) -> str:
    latest = summary.get("latest_trade_date") or "-"
    markets = summary.get("market_counts") if isinstance(summary.get("market_counts"), dict) else {}
    providers = summary.get("model_provider_counts") if isinstance(summary.get("model_provider_counts"), dict) else {}
    ratings = summary.get("decision_rating_counts") if isinstance(summary.get("decision_rating_counts"), dict) else {}
    top_market = _top_count_label(markets) or "-"
    top_provider = _top_count_label(providers) or "-"
    top_rating = _top_count_label(ratings) or "-"
    cards = [
        ("완료 리포트", summary.get("completed_count", 0), "현재 목록 기준"),
        ("커버 종목", summary.get("unique_ticker_count", 0), "중복 제외"),
        ("최신 기준일", latest, f"평균 알파 {_percent(summary.get('average_alpha_return'), signed=True)}"),
        ("주요 판단/시장", top_rating, top_market),
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


def _analysis_track_record_cards(summary: dict[str, Any]) -> str:
    completed_outcomes = int(summary.get("completed_outcome_count") or 0)
    outcome_covered = int(summary.get("outcome_covered_count") or 0)
    coverage = _percent(summary.get("outcome_coverage_rate"))
    positive_rate = _percent(summary.get("positive_alpha_rate"))
    average_alpha = _percent(summary.get("average_alpha_return"), signed=True)
    positive_count = int(summary.get("positive_alpha_count") or 0)
    cards = [
        ("검증 완료", f"{completed_outcomes}건", f"성과 연결 run {outcome_covered}개"),
        ("평균 알파", average_alpha, "벤치마크 대비"),
        ("알파 우위", positive_rate, f"양수 알파 {positive_count}건"),
        ("커버리지", coverage, "현재 공개 목록 기준"),
    ]
    if completed_outcomes == 0:
        cards = [
            ("검증 대기", "0건", "outcome worker가 완료하면 채워집니다."),
            ("평균 알파", "-", "성과 데이터 대기"),
            ("알파 우위", "-", "성과 데이터 대기"),
            ("커버리지", "-", "현재 공개 목록 기준"),
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
          <p class="eyebrow">Public Track Record</p>
          <h2 id="track-record-title">성과 검증 스냅샷</h2>
        </div>
        <span class="status-pill">5D / 20D</span>
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
        ("검증 완료", f"{completed}건", "completed outcome"),
        ("평균 알파", average_alpha, f"종목 수익률 {average_raw}"),
        ("알파 우위", positive_rate, f"양수 알파 {positive_alpha}건"),
        ("대기/누락", f"{pending}/{unavailable}", "pending / unavailable"),
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
    <section class="analysis-summary-grid outcome-summary-grid" aria-label="성과 검증 요약">
      {"".join(html_cards)}
    </section>
    """


def _analysis_outcome_cadence_strip(model: dict[str, Any]) -> str:
    filter_label = model.get("filter_label") or "전체 성과"
    return f"""
    <section class="analysis-pipeline-strip outcome-cadence-strip" aria-label="성과 검증 흐름">
      <article>
        <span>01</span>
        <strong>Public Run</strong>
        <small>완료된 public 분석 run만 검증 대상으로 삼습니다.</small>
      </article>
      <article>
        <span>02</span>
        <strong>5D / 20D</strong>
        <small>기준일 이후 충분한 거래일이 쌓이면 horizon별 결과를 저장합니다.</small>
      </article>
      <article>
        <span>03</span>
        <strong>Benchmark Alpha</strong>
        <small>종목 수익률과 한국 시장 benchmark 대비 초과 성과를 나눠 표시합니다.</small>
      </article>
      <article>
        <span>04</span>
        <strong>{_h(str(filter_label))}</strong>
        <small>결과는 공개 기록으로 남기되 투자 실행 권한은 연결하지 않습니다.</small>
      </article>
    </section>
    """


def _analysis_outcome_feed_cards(items: list[dict[str, Any]]) -> str:
    if not items:
        return """
        <article class="analysis-feed-card outcome-feed-card empty">
          <span>waiting</span>
          <h3>성과 검증 대기</h3>
          <p>outcome worker가 public run을 평가하면 이곳에 5일/20일 성과가 누적됩니다.</p>
          <div class="analysis-feed-actions">
            <a href="/analyses">분석 목록</a>
            <a href="/features/outcomes">검증 방식</a>
          </div>
        </article>
        """

    cards = []
    for item in items:
        code = str(item.get("ticker_code") or "")
        name = str(item.get("ticker_name") or code or "공개 분석")
        market = str(item.get("market") or "KR")
        status = str(item.get("status") or "pending")
        run_id = str(item.get("analysis_run_id") or "")
        horizon = item.get("horizon_days") or "-"
        trade_date = item.get("trade_date") or "-"
        evaluated_at = item.get("evaluated_at") or "-"
        raw_return = _percent(item.get("raw_return"), signed=True)
        benchmark_return = _percent(item.get("benchmark_return"), signed=True)
        alpha_return = _percent(item.get("alpha_return"), signed=True)
        decision = item.get("decision_rating") or item.get("decision_action") or "-"
        report_path = f"/analyses/{run_id}" if run_id else "/analyses"
        stock_path = f"/stocks/{code}" if code else "/analyses"
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
                <span>{_h(market)} / {_h(str(horizon))}D</span>
                <small>{_h(str(evaluated_at))}</small>
              </div>
              <h3><a href="{_h(report_path)}">{_h(name)} <small>{_h(code)}</small></a></h3>
              <p>{_h(_outcome_status_label(status))} / 판단 {_h(str(decision))} / 기준일 {_h(str(trade_date))}</p>
              <dl>
                <div><dt>Raw</dt><dd>{_h(raw_return)}</dd></div>
                <div><dt>Benchmark</dt><dd>{_h(benchmark_return)}</dd></div>
                <div><dt>Alpha</dt><dd>{_h(alpha_return)}</dd></div>
                <div><dt>Run</dt><dd>{_h(run_id[:8] or "-")}</dd></div>
              </dl>
              <div class="analysis-feed-actions">
                <a href="{_h(report_path)}">리포트</a>
                <a href="{_h(stock_path)}">종목</a>
                <a href="{_h(api_path)}">JSON</a>
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
        ("unavailable", "누락"),
    ]
    html_options = []
    for value, label in options:
        selected_attr = " selected" if value == selected_value else ""
        html_options.append(f'<option value="{_h(value)}"{selected_attr}>{_h(label)}</option>')
    return "".join(html_options)


def _analysis_feed_cards(items: list[dict[str, Any]]) -> str:
    if not items:
        return """
        <article class="analysis-feed-card empty">
          <span>waiting</span>
          <h3>공개 분석 대기</h3>
          <p>분석 worker가 완료한 public 리포트가 생기면 이 목록에 표시됩니다.</p>
          <div class="analysis-feed-actions">
            <a href="/features/research">리서치 흐름</a>
            <a href="/member">분석 요청</a>
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
        decision = item.get("decision_rating") or item.get("decision_action") or "-"
        alpha = _percent(item.get("alpha_return"), signed=True)
        alpha_raw = item.get("alpha_return")
        try:
            alpha_number = float(alpha_raw) if alpha_raw is not None else None
        except (TypeError, ValueError):
            alpha_number = None
        alpha_class = (
            "is-positive-alpha"
            if alpha_number is not None and alpha_number > 0
            else "is-negative-alpha"
            if alpha_number is not None and alpha_number < 0
            else "is-neutral-alpha"
        )
        report_count = item.get("report_count")
        reports = f"{report_count}개" if report_count is not None else "-"
        run_id = item.get("id")
        report_path = item.get("report_path") or (f"/analyses/{run_id}" if run_id else "/analyses")
        api_path = item.get("api_path") or (f"/api/analyses/{run_id}" if run_id else "/api/analyses")
        cards.append(
            f"""
            <article class="analysis-feed-card {alpha_class}">
              <div class="analysis-feed-card-top">
                <span>{_h(str(market))}</span>
                <small>{_h(str(trade_date))}</small>
              </div>
              <h3><a href="{_h(str(report_path))}">{_h(str(name))} <small>{_h(str(code))}</small></a></h3>
              <p>판단 {_h(str(decision))} / {_h(str(model_provider))} 공개 분석</p>
              <dl>
                <div><dt>상태</dt><dd>{_h(str(item.get("status") or "-"))}</dd></div>
                <div><dt>모델</dt><dd>{_h(str(model_provider))}</dd></div>
                <div><dt>리포트</dt><dd>{_h(reports)}</dd></div>
                <div><dt>알파</dt><dd>{_h(alpha)}</dd></div>
              </dl>
              <div class="analysis-feed-actions">
                <a href="{_h(str(report_path))}">리포트</a>
                <a href="/stocks/{_h(str(code))}">종목</a>
                <a href="{_h(str(api_path))}">JSON</a>
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
        ("01", "Stored run", f"run {run_id[:8] or '-'}", model.get("timestamp_label") or "저장 시각 없음"),
        ("02", "Decision", model.get("decision_label") or "-", model.get("data_basis") or "기준 데이터 확인"),
        ("03", "Agent reports", f"{len(reports)}개", model.get("analyst_label") or "agent 목록 확인"),
        (
            "04",
            "Outcome",
            f"{summary.get('completed_outcome_count', len(outcomes) or 0)}개 완료",
            f"평균 알파 {model.get('average_alpha_label') or '-'}",
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
          <p class="eyebrow">Report Map</p>
          <h2>리포트 읽기 순서</h2>
        </div>
        <nav aria-label="리포트 섹션 바로가기">
          <a href="#analysis-provenance">출처</a>
          <a href="#analysis-decision">판단</a>
          <a href="#analysis-reports">리포트</a>
          <a href="#analysis-outcomes">성과</a>
        </nav>
      </div>
      <div class="analysis-detail-map-grid">
        {card_html}
      </div>
    </section>
    """


def _analysis_detail_report_cards(reports: list[dict[str, Any]]) -> str:
    if not reports:
        return """
        <article class="analysis-detail-report-card empty">
          <span>pending</span>
          <h3>리포트 대기</h3>
          <p>저장된 에이전트 리포트가 아직 없습니다.</p>
        </article>
        """

    cards = []
    for report in reports:
        role = str(report.get("role") or "agent")
        title = str(report.get("title") or role)
        content = _excerpt(str(report.get("content") or ""), limit=1600)
        quality_html = _analysis_quality_html(_report_quality(report))
        cards.append(
            f"""
            <article class="analysis-detail-report-card">
              <span>{_h(role)}</span>
              <h3>{_h(title)}</h3>
              {quality_html}
              <p>{_h(content or "리포트 본문이 비어 있습니다.")}</p>
            </article>
            """
        )
    return "\n".join(cards)


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
        <small>{_h(str(passed))}/{_h(str(total))} checks passed · review {warnings}</small>
      </div>
    """


def _analysis_detail_decision_card(decision: dict[str, Any]) -> str:
    if not decision:
        body = """
        <article class="analysis-rationale-card empty">
          <span>pending</span>
          <h2>최종 판단 대기</h2>
          <p>저장된 최종 판단이 아직 없습니다.</p>
        </article>
        """
    else:
        rating = str(decision.get("rating") or "-")
        action = str(decision.get("action") or "-")
        target_weight = decision.get("target_weight")
        rationale = decision.get("rationale") or decision.get("raw_decision") or "판단 근거가 저장되지 않았습니다."
        body = f"""
        <article class="analysis-rationale-card">
          <span>Decision checkpoint</span>
          <h2>최종 판단: {_h(rating)}</h2>
          <p>{_h(_excerpt(str(rationale), limit=900))}</p>
          <dl>
            <div><dt>Action</dt><dd>{_h(action)}</dd></div>
            <div><dt>Target weight</dt><dd>{_h(_percent(target_weight) if target_weight is not None else "-")}</dd></div>
          </dl>
        </article>
        """
    return f"""
    <section id="analysis-decision" class="analysis-rationale-section" aria-label="최종 판단">
      {body}
    </section>
    """


def _analysis_detail_provenance(model: dict[str, Any]) -> str:
    cells = [
        ("데이터 기준일", model["trade_date"], model["timestamp_label"]),
        ("데이터/vendor", "KRX/DART/Naver", "시세, 공시, 뉴스 adapter 기반. 장애와 누락은 JSON/본문 기준으로 확인합니다."),
        ("Agent coverage", model["analyst_label"], "metadata_json.selected_analysts 기준"),
        ("모델", model["model_label"], model["metadata_note"]),
        ("성과 검증", model["completed_outcome_label"], f"평균 알파 {model['average_alpha_label']}"),
        ("공개 Run ID", model["run_id"], "JSON 원문과 HTML 리포트가 같은 id를 공유"),
        ("검증 경로", "HTML + JSON", f"화면 요약은 저장된 bundle에서 렌더링하며 /api/analyses/{model['run_id']}로 대조합니다."),
        ("한계", "read-only research", "투자 조언/주문 아님. 휴장, vendor 장애, 누락 데이터, 모델 오류 가능성이 있습니다."),
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


def _top_count_label(counts: dict[str, Any]) -> str | None:
    if not counts:
        return None
    key, value = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))[0]
    return f"{key} {value}"


def _analysis_feed_status_label(status: Any) -> str:
    return {
        "available": "분석 사용 가능",
        "not_configured": "저장소 미연결",
    }.get(str(status), "상태 확인")


def _analysis_outcomes_status_label(status: Any) -> str:
    return {
        "available": "성과 사용 가능",
        "not_configured": "저장소 미연결",
        "unavailable": "성과 저장소 확인 필요",
    }.get(str(status), "상태 확인")


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
          <p class="eyebrow">Korean Strategy Lenses</p>
          <h2 id="lens-title">한국형 투자 렌즈</h2>
        </div>
        <span class="status-pill">READ-ONLY</span>
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
          <span>pending</span>
          <h3>검증 대기</h3>
          <p>분석 기준일 이후 충분한 거래일이 쌓이면 5일/20일 성과가 표시됩니다.</p>
        </article>
        """
    else:
        cards = "\n".join(_outcome_card(outcome) for outcome in outcomes[:6])
    return f"""
    <section id="analysis-outcomes" class="outcome-section" aria-labelledby="outcome-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Outcome Track Record</p>
          <h2 id="outcome-title">사후 성과 검증</h2>
        </div>
        <span class="status-pill">ALPHA</span>
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
    title = f"{horizon}일 검증"
    if status == "completed":
        summary = f"종목 수익률 {raw_return}, benchmark alpha {alpha_return}"
    elif status == "pending":
        summary = f"현재 {actual_days or 0}거래일만 관측되어 검증을 기다리는 중입니다."
    else:
        summary = "성과 검증 데이터를 아직 확보하지 못했습니다."
    return f"""
    <article class="outcome-card outcome-{_h(status)}">
      <span>{_h(_outcome_status_label(status))}</span>
      <h3>{_h(title)}</h3>
      <p>{_h(summary)}</p>
      <dl>
        <div><dt>Raw</dt><dd>{_h(raw_return)}</dd></div>
        <div><dt>Alpha</dt><dd>{_h(alpha_return)}</dd></div>
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
        "unavailable": "불가",
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
}

.top-links a:hover {
  background: var(--surface-strong);
  color: var(--ink);
}

.top-links a[hidden] {
  display: none;
}

.top-links .top-auth-link,
.top-links .top-dashboard-link {
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
  flex-wrap: wrap;
  gap: 10px;
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
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  min-width: 0;
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
  min-height: 340px;
  aspect-ratio: 16 / 9;
}

#priceChart {
  display: block;
  width: 100%;
  height: 100%;
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

.analysis-panel {
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

.analysis-feed-card p {
  margin: 0 0 2px;
  color: var(--muted);
}

.analysis-feed-card dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

.analysis-feed-card dl div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid var(--line);
  padding-top: 8px;
}

.analysis-feed-card dt {
  color: var(--muted);
  font-size: 13px;
}

.analysis-feed-card dd {
  margin: 0;
  font-weight: 700;
}

.analysis-feed-card.empty {
  grid-column: 1 / -1;
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

.outcome-page .decision-box {
  width: 100%;
}

.analysis-feed-actions {
  display: flex;
  flex-wrap: wrap;
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

.feature-shell,
.admin-shell {
  padding: clamp(52px, 8vw, 96px) 0 80px;
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
  color: rgba(246, 243, 232, 0.58);
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
  color: var(--home-mint);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 800;
}

.feature-signal-card strong {
  color: var(--home-ink);
  font-size: clamp(28px, 4vw, 54px);
  line-height: 1;
}

.feature-signal-card small {
  color: rgba(246, 243, 232, 0.58);
  line-height: 1.6;
}

.feature-card-grid,
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
.admin-card {
  display: grid;
  gap: 16px;
  min-height: 220px;
  padding: 24px;
  background: rgba(15, 22, 18, 0.76);
}

.feature-card-grid span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 900;
}

.feature-card-grid strong,
.admin-card h2 {
  color: var(--home-ink);
  font-size: 22px;
}

.feature-card-grid p,
.feature-boundary li,
.admin-card label,
.admin-card pre,
.admin-token-panel small {
  color: rgba(246, 243, 232, 0.68);
}

.admin-token-panel,
.admin-card {
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(15, 22, 18, 0.78);
}

.admin-token-panel {
  display: grid;
  gap: 12px;
  padding: 22px;
}

.admin-token-panel label,
.admin-number-field {
  display: grid;
  gap: 8px;
  font-size: 13px;
  font-weight: 800;
}

.admin-token-panel input,
.admin-number-field input {
  width: 100%;
  height: 42px;
  padding: 0 12px;
  border: 1px solid rgba(246, 243, 232, 0.18);
  border-radius: 6px;
  background: rgba(246, 243, 232, 0.06);
  color: var(--home-ink);
  font: inherit;
}

.admin-token-panel button,
.admin-card button {
  height: 42px;
  padding: 0 14px;
  border: 1px solid var(--home-acid);
  border-radius: 6px;
  background: var(--home-acid);
  color: #10130f;
  font: inherit;
  font-weight: 900;
  cursor: pointer;
}

.admin-card .button-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.admin-card pre {
  min-height: 190px;
  max-height: 360px;
  margin: 0;
  padding: 14px;
  overflow: auto;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.2);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
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
  color: rgba(246, 243, 232, 0.62);
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
  --muted: rgba(246, 243, 232, 0.66);
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

.member-page .top-links .top-auth-link,
.member-page .top-links .top-dashboard-link {
  border: 1px solid rgba(246, 243, 232, 0.2);
  color: var(--ink);
}

.member-page .top-links .top-join-link {
  border: 1px solid var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
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
  color: var(--muted);
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
  color: var(--muted);
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

.auth-button-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.auth-status {
  min-height: 44px;
  padding: 12px 14px;
  border: 1px dashed var(--line);
  border-radius: 8px;
  background: var(--surface-strong);
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

.member-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.member-overview-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
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

.member-overview-strip strong {
  color: var(--ink);
  font-family: var(--app-font-stack);
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.member-overview-strip small {
  color: var(--muted);
}

.member-home-panel {
  display: grid;
  gap: 14px;
}

.member-home-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.member-home-card {
  display: grid;
  align-content: space-between;
  gap: 10px;
  min-height: 178px;
  padding: 16px;
  border: 1px solid rgba(246, 243, 232, 0.12);
  border-left: 3px solid rgba(215, 255, 63, 0.68);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.045);
}

.member-home-card span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 900;
}

.member-home-card strong {
  color: var(--ink);
  font-size: 18px;
}

.member-home-card small {
  color: var(--muted);
  line-height: 1.55;
}

.member-home-card .ghost-button {
  justify-self: start;
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
  color: var(--muted);
  font-size: 13px;
  line-height: 1.45;
}

.member-form {
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
  height: 40px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
}

.member-page .member-form input,
.member-page .member-form select,
.member-page .member-action-item input {
  background: rgba(246, 243, 232, 0.06);
  color: var(--ink);
}

.member-page .member-form input::placeholder,
.member-page .member-action-item input::placeholder {
  color: rgba(246, 243, 232, 0.42);
}

.password-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.member-form .password-row input {
  min-width: 0;
}

.password-toggle {
  height: 40px;
}

.compact-form {
  grid-template-columns: minmax(0, 1fr) auto;
}

.compact-form input:nth-last-child(2) {
  grid-column: auto;
}

.trade-form {
  grid-template-columns: minmax(120px, 1.2fr) minmax(88px, 0.8fr) minmax(82px, 0.7fr) minmax(122px, 1fr);
  align-items: end;
}

.trade-form button {
  width: 100%;
}

.target-form {
  grid-template-columns: minmax(120px, 1.2fr) minmax(88px, 0.8fr) minmax(96px, 0.8fr) minmax(96px, 0.8fr);
  align-items: end;
}

.target-form input[name="memo"] {
  grid-column: span 3;
}

.target-form button {
  width: 100%;
}

.button-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.member-form button,
.ghost-button {
  height: 40px;
  padding: 0 14px;
  border: 0;
  border-radius: 6px;
  background: var(--ink);
  color: #ffffff;
  font: inherit;
  font-weight: 800;
  cursor: pointer;
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
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(143, 216, 189, 0.22);
  border-left: 4px solid var(--home-celadon);
  border-radius: 8px;
  background: rgba(143, 216, 189, 0.075);
}

.analysis-queue-meters {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.analysis-queue-meters div {
  min-width: 0;
  padding: 9px 10px;
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
  .admin-hero,
  .member-auth-landing,
  .member-summary-band {
    grid-template-columns: minmax(0, 1fr);
  }

  .auth-panel,
  .feature-diagram {
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
  .analysis-pipeline-strip,
  .feature-card-grid,
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

  .member-action-item {
    grid-template-columns: 1fr 1fr;
  }

  .analysis-queue-meters {
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
  }

  .ticker-search {
    width: 100%;
  }

  .chart-toolbar,
  .chart-heading-meta {
    align-items: flex-start;
    flex-direction: column;
  }

  .chart-tabs {
    width: 100%;
  }

  .chart-tab {
    flex: 1 1 auto;
    justify-content: center;
  }

  .data-source-strip,
  .analysis-panel .data-source-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .shell {
    width: min(100% - 24px, 1280px);
    padding-top: 18px;
  }

  .home-shell {
    width: min(100% - 24px, 1440px);
    padding-top: 14px;
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
  .lens-grid,
  .outcome-grid,
  .report-grid,
  .home-analysis-grid,
  .analysis-feed-grid,
  .outcome-feed-grid,
  .analysis-summary-grid,
  .analysis-track-grid,
  .analysis-pipeline-strip,
  .feature-card-grid,
  .feature-step-track,
  .admin-grid,
  .member-grid,
  .compact-form,
  .trade-form,
  .target-form {
    grid-template-columns: minmax(0, 1fr);
  }

  .chart-wrap {
    height: min(64vw, 260px);
    min-height: 220px;
    aspect-ratio: auto;
  }

  .member-action-item {
    grid-template-columns: minmax(0, 1fr);
  }

  .member-overview-strip,
  .member-home-grid,
  .member-metric-grid {
    grid-template-columns: minmax(0, 1fr);
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
}

.public-home {
  --home-bg: #10130f;
  --home-ink: #f6f3e8;
  --home-paper: #fbfaf4;
  --home-panel: #171a16;
  --home-panel-2: #22251f;
  --home-line: rgba(246, 243, 232, 0.16);
  --home-muted: #a6ada2;
  --home-readable: rgba(246, 243, 232, 0.8);
  --home-muted-readable: rgba(246, 243, 232, 0.74);
  --home-celadon: #8fd8bd;
  --home-acid: #d7ff3f;
  --home-vermilion: #ff5a3d;
  --home-brass: #c79a3a;
  background:
    radial-gradient(circle at 72% 8%, rgba(215, 255, 63, 0.14), transparent 28%),
    radial-gradient(circle at 12% 34%, rgba(143, 216, 189, 0.13), transparent 31%),
    linear-gradient(180deg, #10130f 0%, #171a16 48%, #11140f 100%);
  color: var(--home-ink);
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
}

.public-home .top-links a:hover {
  background: rgba(246, 243, 232, 0.08);
  color: var(--home-ink);
}

.public-home .top-links .top-auth-link,
.public-home .top-links .top-dashboard-link {
  border-color: rgba(246, 243, 232, 0.2);
  color: var(--home-ink);
}

.public-home .top-links .top-join-link {
  border-color: var(--home-acid);
  background: var(--home-acid);
  color: #10130f;
}

.public-home .top-links .top-join-link:hover {
  background: #ecff72;
  color: #10130f;
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
  min-height: min(820px, calc(100svh - 88px));
  padding: clamp(44px, 7vh, 92px) 0 clamp(28px, 4vw, 52px);
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
  margin-bottom: 22px;
  color: var(--home-ink);
  font-size: clamp(44px, 5.6vw, 82px);
  font-weight: 900;
  line-height: 0.96;
  letter-spacing: 0;
  text-wrap: balance;
  word-break: keep-all;
}

.home-hero-artboard .home-lede {
  max-width: 670px;
  margin-bottom: 26px;
  color: rgba(246, 243, 232, 0.76);
  font-size: clamp(16px, 1.4vw, 20px);
  line-height: 1.68;
}

.home-command-search {
  width: min(100%, 650px);
  padding: 7px;
  border: 1px solid rgba(246, 243, 232, 0.18);
  border-radius: 6px;
  background: rgba(23, 26, 22, 0.84);
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.28);
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
  margin-top: 16px;
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

.home-signal-art {
  position: relative;
  max-width: 100%;
  margin-top: clamp(8px, 2vh, 28px);
  min-height: clamp(380px, 42vw, 620px);
  aspect-ratio: 1.06 / 1;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.18);
  border-radius: 0;
  background:
    linear-gradient(90deg, rgba(215, 255, 63, 0.1) 1px, transparent 1px),
    linear-gradient(rgba(143, 216, 189, 0.08) 1px, transparent 1px),
    radial-gradient(circle at 72% 28%, rgba(215, 255, 63, 0.18), transparent 28%),
    linear-gradient(135deg, #11130f, #1c201a 58%, #0f110e);
  background-size: 28px 28px, 28px 28px, auto, auto;
  box-shadow: 0 34px 90px rgba(0, 0, 0, 0.34);
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
  top: 34px;
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
}

.signal-stock-card .home-sparkline i {
  background: linear-gradient(var(--home-acid), var(--home-celadon));
}

.home-lens-band,
.public-home .home-band,
.public-home .home-analysis-zone,
.public-home .home-ops-strip {
  border-bottom: 1px solid var(--home-line);
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
.home-flow-list span {
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

.public-home .home-ops-strip {
  color: var(--home-ink);
}

.public-home .home-ops-strip li {
  border-top-color: rgba(246, 243, 232, 0.14);
}

.public-home .home-flow-list {
  border-top-color: rgba(246, 243, 232, 0.16);
}

.public-home .home-flow-list article {
  border-bottom-color: rgba(246, 243, 232, 0.12);
}

.public-home .home-flow-list strong {
  color: var(--home-ink);
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

  .home-lens-grid article {
    border-bottom: 1px solid var(--home-line);
  }
}

@media (max-width: 640px) {
  .home-shell-art {
    width: min(100% - 24px, 1440px);
  }

  .home-hero-artboard {
    padding: 28px 0 46px;
  }

  .home-hero-artboard h1 {
    font-size: clamp(36px, 12vw, 52px);
  }

  .home-command-search {
    flex-direction: column;
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
    min-height: 360px;
    aspect-ratio: auto;
  }

  .signal-flow-row {
    left: 16px;
    right: 16px;
    top: 16px;
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
    bottom: 48px;
  }

  .signal-stock-card .home-console-focus {
    padding: 16px;
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

  .home-lens-grid article {
    min-height: 0;
    border-right: 0;
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
  color: rgba(246, 243, 232, 0.42);
  font-family: var(--app-font-stack);
  font-size: clamp(20px, 2.2vw, 34px);
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
  color: rgba(246, 243, 232, 0.62);
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

.stock-flow-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 18px 0 0;
  overflow: hidden;
  border: 1px solid rgba(246, 243, 232, 0.14);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.14);
}

.stock-flow-strip article {
  display: grid;
  gap: 9px;
  min-height: 132px;
  padding: 18px;
  background: rgba(15, 22, 18, 0.78);
}

.stock-flow-strip span {
  color: var(--home-acid);
  font-family: var(--app-font-stack);
  font-size: 12px;
  font-weight: 900;
}

.stock-flow-strip strong {
  color: var(--home-ink);
  font-size: 18px;
  line-height: 1.15;
}

.stock-flow-strip small {
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.74));
  line-height: 1.5;
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
  background: #fbfaf4;
}

.market-page .status-pill,
.market-page .data-pill,
.market-page .chart-tab,
.market-page .chart-legend span {
  border-color: rgba(246, 243, 232, 0.16);
  background: rgba(246, 243, 232, 0.07);
  color: rgba(246, 243, 232, 0.72);
}

.market-page .data-source-strip {
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

.market-page .chart-tab:hover,
.market-page .chart-tab.is-active {
  border-color: rgba(215, 255, 63, 0.58);
  background: rgba(215, 255, 63, 0.12);
  color: var(--home-acid);
}

.market-page .chart-tab.is-active {
  box-shadow: inset 0 0 0 1px rgba(215, 255, 63, 0.18);
}

.market-page .metric-grid article {
  border-left: 3px solid rgba(215, 255, 63, 0.56);
}

.market-page .metric-grid span {
  color: rgba(246, 243, 232, 0.54);
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
  color: rgba(246, 243, 232, 0.66);
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

.analysis-filter-panel p {
  margin: 0;
  color: var(--home-muted-readable, rgba(246, 243, 232, 0.74));
  line-height: 1.55;
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
}

.outcome-cadence-strip {
  grid-template-columns: repeat(4, minmax(0, 1fr));
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
}

.analysis-filter-form a {
  border: 1px solid rgba(246, 243, 232, 0.18);
  color: var(--home-ink);
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
  font-size: clamp(42px, 6vw, 88px);
  font-weight: 900;
  line-height: 0.96;
  text-wrap: balance;
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
  color: rgba(246, 243, 232, 0.62);
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
  color: rgba(246, 243, 232, 0.58);
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
  color: rgba(246, 243, 232, 0.68);
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
  color: rgba(246, 243, 232, 0.62);
  font-size: 12px;
  line-height: 1.45;
}

.analysis-detail-report-card p {
  max-width: 96ch;
  color: rgba(246, 243, 232, 0.68);
  line-height: 1.74;
}

.market-page .notice-strip {
  border-color: rgba(199, 154, 58, 0.28);
  background: rgba(199, 154, 58, 0.08);
}

.market-page .notice-strip ul {
  color: rgba(246, 243, 232, 0.72);
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
  color: rgba(246, 243, 232, 0.62);
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
  color: rgba(246, 243, 232, 0.62);
  line-height: 1.5;
}

.member-tab-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 0 0 16px;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(246, 243, 232, 0.06);
}

.member-tab-strip a {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  min-height: 42px;
  align-items: center;
  justify-items: center;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--muted);
  font-weight: 900;
}

.member-tab-strip a span {
  display: inline-grid;
  min-width: 28px;
  height: 24px;
  place-items: center;
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
  .analysis-filter-panel,
  .stock-flow-strip,
  .admin-readiness-panel,
  .admin-health-strip,
  .admin-workflow-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .admin-health-strip {
    gap: 1px;
  }
}

@media (max-width: 640px) {
  .market-shell {
    width: min(100% - 24px, 1440px);
    padding-top: 22px;
  }

  .market-page .topbar .ticker-search {
    width: 100%;
  }

  .market-page .summary-band h1 {
    font-size: clamp(36px, 12vw, 52px);
  }

  .outcome-page .summary-band h1 {
    font-size: clamp(34px, 11vw, 46px);
  }

  .outcome-title-line {
    display: block;
  }

  .analysis-detail-hero h1 {
    font-size: clamp(36px, 12vw, 54px);
  }

  .stock-hero-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .stock-hero-actions a {
    width: 100%;
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
  let lastSearchController = null;

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

  function syncTopAuthLinks() {
    const signedIn = Boolean(
      memberStorageGet(memberAccessTokenKey)
      || memberStorageGet(memberRefreshTokenKey)
    );
    document.querySelectorAll('[data-auth-visible="signed-out"]').forEach((node) => {
      node.hidden = signedIn;
    });
    document.querySelectorAll('[data-auth-visible="signed-in"]').forEach((node) => {
      node.hidden = !signedIn;
    });
  }

  syncTopAuthLinks();
  window.addEventListener("storage", syncTopAuthLinks);

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

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const signalTicker = document.getElementById("homeSignalTicker");
  const signalDecision = document.getElementById("homeSignalDecision");
  const signalMeta = document.getElementById("homeSignalMeta");
  const signalStates = [
    {
      ticker: "005930 / 삼성전자",
      decision: "HOLD WATCH",
      meta: "KRX price + DART disclosure + benchmark alpha"
    },
    {
      ticker: "000660 / SK하이닉스",
      decision: "RISK CHECK",
      meta: "volatility guard + news impulse + 20D outcome"
    },
    {
      ticker: "035420 / NAVER",
      decision: "NEWS TRACE",
      meta: "Naver news cluster + disclosure watch"
    },
    {
      ticker: "086520 / 에코프로",
      decision: "DATA REVIEW",
      meta: "KOSDAQ flow + read-only investor guard"
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
  const canvas = document.getElementById("priceChart");
  const legend = document.getElementById("chartLegend");
  const fallback = document.getElementById("chartFallback");
  const tooltip = document.getElementById("chartTooltip");
  if (!node || !canvas) return;

  const payload = JSON.parse(node.textContent || "{}");
  const chart = payload.chart || {};
  const points = (payload.chart?.points || []).filter((point) => Number.isFinite(point.close));
  if (points.length < 2) {
    if (fallback && chart.error) fallback.textContent = `차트 데이터를 불러오지 못했습니다: ${chart.error}`;
    if (fallback) fallback.hidden = false;
    return;
  }

  const ctx = canvas.getContext("2d");
  const money = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
  const compact = new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 });
  const dates = points.map((point) => point.date);
  const bars = points.map((point) => ({
    date: point.date,
    open: Number.isFinite(point.open) ? Number(point.open) : Number(point.close),
    high: Number.isFinite(point.high) ? Number(point.high) : Number(point.close),
    low: Number.isFinite(point.low) ? Number(point.low) : Number(point.close),
    close: Number(point.close),
    volume: Number.isFinite(point.volume) ? Number(point.volume) : 0
  }));
  const closes = bars.map((point) => point.close);
  const priceValues = bars.flatMap((point) => [point.open, point.high, point.low, point.close]);
  const min = Math.min(...priceValues);
  const max = Math.max(...priceValues);
  const maxVolume = Math.max(...bars.map((point) => point.volume), 1);
  const pad = Math.max((max - min) * 0.12, max * 0.01, 1);
  const yMin = min - pad;
  const yMax = max + pad;
  let hoverIndex = null;

  function movingAverage(values, windowSize) {
    return values.map((_, index) => {
      if (index + 1 < windowSize) return null;
      const slice = values.slice(index + 1 - windowSize, index + 1);
      return slice.reduce((total, value) => total + value, 0) / windowSize;
    });
  }

  const ma5 = movingAverage(closes, 5);
  const ma20 = movingAverage(closes, 20);

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

  function drawLegend() {
    if (!legend) return;
    const latest = bars[bars.length - 1];
    const chips = [
      `종가 ${money.format(latest.close)}원`,
      `거래량 ${compact.format(latest.volume)}`,
      "상승 빨강",
      "하락 파랑",
      ma5[ma5.length - 1] ? `MA5 ${money.format(ma5[ma5.length - 1])}` : "MA5 대기",
      ma20[ma20.length - 1] ? `MA20 ${money.format(ma20[ma20.length - 1])}` : "MA20 대기"
    ];
    legend.replaceChildren(...chips.map((label) => {
      const node = document.createElement("span");
      node.textContent = label;
      return node;
    }));
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

  function updateTooltip(index, rect, layout) {
    if (!tooltip) return;
    if (index === null || index === undefined) {
      tooltip.hidden = true;
      return;
    }
    const bar = bars[index];
    const x = xAt(index, rect.width, layout.left, layout.right);
    const title = document.createElement("strong");
    title.textContent = bar.date;
    const close = document.createElement("span");
    close.textContent = `종가 ${money.format(bar.close)}원`;
    const range = document.createElement("span");
    range.textContent = `고가 ${money.format(bar.high)} / 저가 ${money.format(bar.low)}`;
    const volume = document.createElement("span");
    volume.textContent = `거래량 ${compact.format(bar.volume)}`;
    tooltip.replaceChildren(title, close, range, volume);
    tooltip.hidden = false;
    const tooltipWidth = Math.min(260, Math.max(190, tooltip.offsetWidth || 190));
    const left = Math.min(rect.width - tooltipWidth - 12, Math.max(12, x - tooltipWidth / 2));
    tooltip.style.left = `${left}px`;
  }

  function draw() {
    const rect = fitCanvas();
    const width = rect.width;
    const height = rect.height;
    const layout = chartLayout(width, height);
    const { left, right, top, priceBottom, volumeTop, volumeBottom, candleWidth } = layout;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = "#dce3df";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#66716f";
    ctx.font = "12px system-ui, sans-serif";
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

    ctx.strokeStyle = "#eef2ef";
    ctx.beginPath();
    ctx.moveTo(left, volumeTop);
    ctx.lineTo(width - right, volumeTop);
    ctx.stroke();

    bars.forEach((bar, index) => {
      const x = xAt(index, width, left, right);
      const isUp = bar.close >= bar.open;
      const color = isUp ? "#c0392b" : "#1f5f9f";
      const volumeY = volumeBottom - (bar.volume / maxVolume) * (volumeBottom - volumeTop);
      ctx.fillStyle = isUp ? "rgba(192, 57, 43, 0.24)" : "rgba(31, 95, 159, 0.22)";
      ctx.fillRect(x - candleWidth / 2, volumeY, candleWidth, Math.max(1, volumeBottom - volumeY));
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

    drawLine(closes, width, left, right, top, priceBottom, "rgba(20, 107, 99, 0.72)");
    drawLine(ma5, width, left, right, top, priceBottom, "#d39c1d");
    drawLine(ma20, width, left, right, top, priceBottom, "#5a6acf", [4, 4]);

    const lastClose = closes[closes.length - 1];
    const lastX = xAt(bars.length - 1, width, left, right);
    const lastY = yAt(lastClose, top, priceBottom);
    ctx.fillStyle = "#146b63";
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fill();

    if (hoverIndex !== null) {
      const hovered = bars[hoverIndex];
      const hoverX = xAt(hoverIndex, width, left, right);
      const hoverY = yAt(hovered.close, top, priceBottom);
      ctx.save();
      ctx.strokeStyle = "rgba(23, 32, 31, 0.28)";
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(hoverX, top);
      ctx.lineTo(hoverX, volumeBottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#17201f";
      ctx.beginPath();
      ctx.arc(hoverX, hoverY, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    ctx.fillStyle = "#66716f";
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
    updateTooltip(hoverIndex, rect, layout);
    draw();
  });
  canvas.addEventListener("pointerleave", () => {
    hoverIndex = null;
    updateTooltip(null);
    draw();
  });
})();
"""


ADMIN_PAGE_JS = """
(() => {
  const tokenKey = "tradingagents.admin.worker_token";
  const tokenForm = document.getElementById("adminTokenForm");
  const tokenInput = document.getElementById("adminWorkerToken");
  const tokenState = document.getElementById("adminTokenState");
  const readinessOutput = document.getElementById("adminReadinessOutput");
  const readinessPanel = document.getElementById("adminReadinessPanel");
  const requestsOutput = document.getElementById("adminRequestsOutput");
  const outcomesOutput = document.getElementById("adminOutcomesOutput");
  const requestLimit = document.getElementById("adminRequestLimit");
  const outcomeLimit = document.getElementById("adminOutcomeLimit");
  const probeKrx = document.getElementById("adminProbeKrx");
  const probeVendors = document.getElementById("adminProbeVendors");

  function savedToken() {
    return sessionStorage.getItem(tokenKey) || "";
  }

  function currentToken() {
    return (tokenInput?.value || "").trim() || savedToken();
  }

  function setOutput(node, payload) {
    if (!node) return;
    node.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  }

  function setBusy(button, isBusy) {
    if (!button) return;
    button.disabled = isBusy;
    button.setAttribute("aria-busy", isBusy ? "true" : "false");
  }

  function readinessText(value) {
    return value ? "OK" : "확인 필요";
  }

  function quotaSignalText(probe) {
    if (!probe) return "quota 확인 대기";
    if (probe.quota_signal === "headers_present") return "quota headers 감지";
    if (probe.quota_signal === "wrapper_no_headers") return "quota headers 없음";
    return "quota headers 미제공";
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

  function renderReadinessPending(message) {
    if (!readinessPanel) return;
    readinessPanel.textContent = "";
    const fragment = document.createDocumentFragment();
    appendReadinessCell(fragment, "Status", "확인 중", message, "is-waiting");
    readinessPanel.appendChild(fragment);
  }

  function renderReadinessError(message) {
    if (!readinessPanel) return;
    readinessPanel.textContent = "";
    const fragment = document.createDocumentFragment();
    appendReadinessCell(fragment, "Status", "오류", message, "is-error");
    readinessPanel.appendChild(fragment);
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
    const sha = deployment.git_sha ? `SHA ${deployment.git_sha}` : "deployment SHA 없음";
    appendReadinessCell(fragment, "Status", isOk ? "OK" : "DEGRADED", sha, isOk ? "is-ok" : "is-warn");

    const storageOk = Boolean(checks.storage_online && checks.storage_schema_ready);
    const storageValue = storageOk ? "Online" : checks.storage_configured ? "점검 필요" : "미설정";
    const storageNote = errors.storage_online || errors.storage_schema_ready
      || `storage ${readinessText(checks.storage_online)} · schema ${readinessText(checks.storage_schema_ready)}`;
    appendReadinessCell(fragment, "Storage", storageValue, storageNote, storageOk ? "is-ok" : "is-warn");

    const hasKrxProbe = Object.prototype.hasOwnProperty.call(checks, "krx_online");
    let krxValue = checks.krx_configured ? "Configured" : "미설정";
    let krxNote = checks.krx_configured ? "KRX probe checkbox로 온라인 응답을 확인할 수 있습니다." : "KRX_API_KEY 또는 KRX_OPENAPI_KEY가 필요합니다.";
    let krxState = checks.krx_configured ? "is-ok" : "is-warn";
    if (hasKrxProbe) {
      krxValue = checks.krx_online ? "Online" : "Probe failed";
      krxState = checks.krx_online ? "is-ok" : "is-warn";
      if (krxProbe) {
        krxNote = krxProbe.status === "ok"
          ? `${krxProbe.ticker || "ticker"} · ${krxProbe.date || "date"} · ${probeSummary(krxProbe)}`
          : `${krxProbe.error_type || "KRX"} · ${krxProbe.message || krxProbe.error || "probe failed"}`;
      }
    }
    appendReadinessCell(fragment, "KRX", krxValue, krxNote, krxState);

    const vendorCount = [checks.dart_configured, checks.naver_configured, checks.openai_configured].filter(Boolean).length;
    let vendorValue = `${vendorCount}/3 configured`;
    let vendorNote = `DART ${readinessText(checks.dart_configured)} · Naver ${readinessText(checks.naver_configured)} · OpenAI ${readinessText(checks.openai_configured)}`;
    let vendorState = vendorCount === 3 ? "is-ok" : "is-warn";
    if (vendorProbes.dart || vendorProbes.naver) {
      const vendorProbeRows = [
        `DART ${probeSummary(vendorProbes.dart)}`,
        `Naver ${probeSummary(vendorProbes.naver)}`
      ];
      const onlineCount = [vendorProbes.dart, vendorProbes.naver].filter((probe) => probe?.status === "ok").length;
      vendorValue = `${onlineCount}/2 online`;
      vendorNote = vendorProbeRows.join(" · ");
      vendorState = onlineCount === 2 ? "is-ok" : "is-warn";
    }
    appendReadinessCell(fragment, "Vendors", vendorValue, vendorNote, vendorState);

    appendReadinessCell(
      fragment,
      "Boundary",
      checks.live_trading_disabled ? "Read only" : "확인 필요",
      checks.live_trading_disabled ? "실거래 주문 경로는 비활성 상태입니다." : "TRADINGAGENTS_LIVE_TRADING 설정을 확인하세요.",
      checks.live_trading_disabled ? "is-ok" : "is-warn"
    );

    const authWorkerOk = Boolean(checks.supabase_auth_configured && checks.worker_token_configured);
    const authWorkerNote = `Auth ${readinessText(checks.supabase_auth_configured)} · Worker token ${readinessText(checks.worker_token_configured)}`;
    appendReadinessCell(fragment, "Access", authWorkerOk ? "Ready" : "점검 필요", authWorkerNote, authWorkerOk ? "is-ok" : "is-warn");

    const securityOk = Boolean(checks.api_docs_disabled && checks.trusted_member_user_header_disabled && checks.https_request);
    const securityNote = `Docs ${readinessText(checks.api_docs_disabled)} · Trust header ${readinessText(checks.trusted_member_user_header_disabled)} · HTTPS ${readinessText(checks.https_request)}`;
    appendReadinessCell(fragment, "Security", securityOk ? "Locked" : "점검 필요", securityNote, securityOk ? "is-ok" : "is-warn");

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
      if (!token) throw new Error("Worker token을 입력하세요.");
      headers["X-TradingAgents-Worker-Token"] = token;
    }
    const response = await fetch(path, { ...options, headers });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
    }
    return payload;
  }

  if (tokenInput) tokenInput.value = savedToken();
  if (savedToken() && tokenState) tokenState.textContent = "세션에 저장된 worker token을 사용합니다.";

  tokenForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const token = (tokenInput?.value || "").trim();
    if (!token) {
      sessionStorage.removeItem(tokenKey);
      if (tokenState) tokenState.textContent = "저장된 worker token을 지웠습니다.";
      return;
    }
    sessionStorage.setItem(tokenKey, token);
    if (tokenState) tokenState.textContent = "worker token을 이 브라우저 세션에 저장했습니다.";
  });

  const readinessButton = document.querySelector("[data-admin-readiness]");

  readinessButton?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    try {
      setBusy(button, true);
      setOutput(readinessOutput, "확인 중");
      renderReadinessPending("배포, storage, vendor, read-only boundary를 조회하고 있습니다.");
      const params = new URLSearchParams();
      if (probeKrx?.checked) params.set("probe_krx", "true");
      if (probeVendors?.checked) params.set("probe_vendors", "true");
      const suffix = params.toString() ? `?${params.toString()}` : "";
      const payload = await fetchJson(`/api/readiness${suffix}`);
      renderReadinessPanel(payload);
      setOutput(readinessOutput, payload);
    } catch (error) {
      const message = error.message || "Readiness failed";
      renderReadinessError(message);
      setOutput(readinessOutput, message);
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
    const output = isOutcome ? outcomesOutput : requestsOutput;
    const limit = Math.max(1, Number((isOutcome ? outcomeLimit : requestLimit)?.value || 1));
    const path = isOutcome ? "/api/admin/analysis-outcomes/process" : "/api/admin/analysis-requests/process";
    const body = isOutcome
      ? { limit, dry_run: isDryRun, horizons: [5, 20] }
      : { limit, dry_run: isDryRun };
    try {
      setBusy(button, true);
      setOutput(output, isDryRun ? "dry run 확인 중" : "처리 요청 중");
      setOutput(output, await fetchJson(path, { method: "POST", body: JSON.stringify(body) }, true));
    } catch (error) {
      setOutput(output, error.message || "Admin action failed");
    } finally {
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
  const memberTabLinks = Array.from(document.querySelectorAll("[data-member-tab]"));
  const memberPanels = Array.from(document.querySelectorAll("[data-member-panel]"));
  const memberJumpButtons = Array.from(document.querySelectorAll("[data-member-jump]"));
  const memberHomeStatus = document.getElementById("memberHomeStatus");
  const portfolioTabCount = document.getElementById("portfolioTabCount");
  const watchlistTabCount = document.getElementById("watchlistTabCount");
  const analysisTabCount = document.getElementById("analysisTabCount");
  const overviewPortfolios = document.getElementById("memberOverviewPortfolios");
  const overviewWatchlists = document.getElementById("memberOverviewWatchlists");
  const overviewActiveRequests = document.getElementById("memberOverviewActiveRequests");
  const overviewCompletedReports = document.getElementById("memberOverviewCompletedReports");
  const portfolioSelect = tradeForm?.elements?.portfolio_id;
  const targetPortfolioSelect = targetForm?.elements?.portfolio_id;
  const watchlistSelect = watchlistItemForm?.elements?.watchlist_id;
  const accessTokenKey = "tradingagents.member.access_token";
  const refreshTokenKey = "tradingagents.member.refresh_token";
  const expiresAtKey = "tradingagents.member.expires_at";
  const userEmailKey = "tradingagents.member.user_email";
  const userIdKey = "tradingagents.member.user_id";
  const activeTabKey = "tradingagents.member.active_tab";
  const tabHashes = {
    home: "#member-home-section",
    portfolio: "#portfolio-section",
    watchlist: "#watchlist-section",
    analysis: "#analysis-request-section"
  };
  const requestedAuthMode = new URLSearchParams(window.location.search).get("mode");
  const memberBody = document.body;
  const authLanding = document.getElementById("memberAuthLanding");
  const memberWorkspace = document.getElementById("memberWorkspace");
  const signedOutNavItems = Array.from(document.querySelectorAll('[data-auth-visible="signed-out"]'));
  const signedInNavItems = Array.from(document.querySelectorAll('[data-auth-visible="signed-in"]'));
  const sessionKeys = [accessTokenKey, refreshTokenKey, expiresAtKey, userEmailKey, userIdKey];

  function storageAreaGet(area, key) {
    try {
      return area?.getItem(key) || "";
    } catch (_) {
      return "";
    }
  }

  function storageGet(key) {
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
    sessionKeys.forEach((key) => {
      const persistent = storageAreaGet(window.localStorage, key);
      const volatile = storageAreaGet(window.sessionStorage, key);
      if (!persistent && volatile) storageSet(key, volatile);
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
    return validTab(tabFromHash()) || validTab(storageGet(activeTabKey)) || "home";
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

  function setAuthUiState(isSignedIn) {
    const signedIn = Boolean(isSignedIn);
    memberBody?.classList.toggle("is-member-signed-in", signedIn);
    memberBody?.classList.toggle("is-member-signed-out", !signedIn);
    if (authLanding) authLanding.hidden = signedIn;
    if (memberWorkspace) memberWorkspace.hidden = !signedIn;
    signedOutNavItems.forEach((node) => {
      node.hidden = signedIn;
    });
    signedInNavItems.forEach((node) => {
      node.hidden = !signedIn;
    });
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

  function setAuthBusy(isBusy) {
    authButtons.forEach((button) => {
      button.disabled = isBusy;
      button.setAttribute("aria-busy", isBusy ? "true" : "false");
    });
  }

  function applyRequestedAuthMode() {
    if (requestedAuthMode !== "signup") return;
    const signupButton = authButtons.find((button) => button.dataset.authAction === "signup");
    signupButton?.classList.add("auth-suggested");
    if (!accessToken()) {
      setStatus("가입하려면 이메일과 비밀번호를 입력한 뒤 가입하기를 선택하세요.");
      authForm?.elements?.email?.focus();
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

  function clearSession() {
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
    setStatus("Supabase 공개 Auth 설정 대기 중", true);
    return false;
  }

  function memberRedirectUrl() {
    return new URL("/member", window.location.origin).toString();
  }

  function supabaseAuthUrl(path, params = {}) {
    const url = new URL(path, config.supabase_url);
    Object.entries(params).forEach(([key, value]) => {
      if (value) url.searchParams.set(key, value);
    });
    return url.toString();
  }

  function consumeRedirectSession() {
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
    if (!requireConfig()) throw new Error("Supabase 공개 Auth 설정 대기 중");
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
      throw new Error(payload.error_description || payload.msg || payload.error || "Supabase auth failed");
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
    if (!detail) return payload?.error || "Request failed";
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
      return { ok: false, error: error.message || "Request failed" };
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
      list.append(emptyNode("담긴 관심 종목이 없습니다"));
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
      const save = smallButton("수정");
      save.addEventListener("click", async () => {
        try {
          await memberApi(`/api/watchlists/${encodeURIComponent(detail.watchlist.id)}/items`, {
            method: "POST",
            body: JSON.stringify({ ticker_code: item.ticker_code, memo: memo.value || null })
          });
          await loadMemberData();
        } catch (error) {
          setStatus(error.message, true);
        }
      });
      const remove = smallButton("삭제", "ghost-button danger-button");
      remove.addEventListener("click", async () => {
        try {
          await memberApi(`/api/watchlists/${encodeURIComponent(detail.watchlist.id)}/items/${encodeURIComponent(item.ticker_code)}`, {
            method: "DELETE"
          });
          await loadMemberData();
        } catch (error) {
          setStatus(error.message, true);
        }
      });
      row.append(title, meta, memo, save, remove);
      list.append(row);
    });
    return list;
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
      cardHeader(row.name, detail ? `${detail.pricing_status || "가격 확인"} / ${row.id}` : row.id, `${itemCount}종목`),
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
      ["활성 큐", `${policy.active_used ?? summary.active_count ?? 0}/${activeLimit}`, "대기+처리 중"],
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
    note.textContent = "같은 종목과 기준일의 활성 요청은 기존 큐에 합쳐지며 quota를 다시 사용하지 않습니다.";
    node.append(meters, strip, note);
    return node;
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
      row.member_queue_position ? `${row.queue_scope_label || "내 큐"} ${row.member_queue_position}번째` : null,
      `요청 ${shortDateTime(row.created_at)}`,
      `업데이트 ${shortDateTime(row.updated_at || row.created_at)}`
    ].filter(Boolean).join(" / ");
    pill.className = `status-pill analysis-status-${status}`;
    pill.textContent = row.status_label || statusLabel(status);
    heading.append(strong, small);
    header.append(heading, pill);

    const hint = document.createElement("p");
    hint.className = "analysis-request-hint";
    hint.textContent = row.status_hint || "큐 상태를 확인하고 있습니다.";

    const details = [];
    if (row.reason) details.push(`요청 메모 ${row.reason}`);
    if (row.is_active) details.push("worker 처리 대기 중");
    if (row.member_queue_position) details.push(`${row.queue_scope_label || "내 활성 요청 기준"} ${row.member_queue_position}번째`);
    if (row.analysis_run_id) details.push(`리포트 ID ${compactId(row.analysis_run_id)}`);
    if (row.public_stock_path) details.push(`종목 페이지 ${row.public_stock_path}`);
    details.push(`다음 행동 ${row.next_action_label || "상태 확인"}`);

    const actions = document.createElement("div");
    actions.className = "analysis-request-actions";
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

    node.append(header, hint, miniList(details, "상세 상태 대기", "큐 상세"));
    if (actions.childElementCount) node.append(actions);
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

  function fillPortfolioSelects(rows) {
    fillSelect(portfolioSelect, rows, "name", "포트폴리오를 먼저 추가하세요");
    fillSelect(targetPortfolioSelect, rows, "name", "포트폴리오를 먼저 추가하세요");
  }

  function renderPortfolios(payload, details = {}, error = "") {
    if (error) {
      fillPortfolioSelects([]);
      portfolioList.replaceChildren(emptyNode(`포트폴리오를 불러오지 못했습니다: ${error}`));
      return;
    }
    const rows = payload.items || [];
    fillPortfolioSelects(rows);
    portfolioList.replaceChildren(
      ...(rows.length ? rows.map((row) => portfolioCard(row, details[row.id])) : [emptyNode("저장된 포트폴리오가 없습니다")])
    );
  }

  function renderWatchlists(payload, details = {}, error = "") {
    if (error) {
      fillSelect(watchlistSelect, [], "name");
      watchlistList.replaceChildren(emptyNode(`관심목록을 불러오지 못했습니다: ${error}`));
      return;
    }
    const rows = payload.items || [];
    fillSelect(watchlistSelect, rows, "name", "관심목록을 먼저 추가하세요");
    watchlistList.replaceChildren(
      ...(rows.length ? rows.map((row) => watchlistCard(row, details[row.id])) : [emptyNode("저장된 관심목록이 없습니다")])
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
      ...(rows.length ? rows.map((row) => analysisRequestCard(row)) : [emptyNode("분석 요청 내역이 없습니다")])
    );
  }

  function setText(node, value) {
    if (node) node.textContent = String(value);
  }

  function updateMemberOverview(portfoliosPayload = {}, watchlistsPayload = {}, requestsPayload = {}) {
    const portfolioCount = (portfoliosPayload.items || []).length;
    const watchlistCount = (watchlistsPayload.items || []).length;
    const requestRows = requestsPayload.items || [];
    const summary = requestsPayload.summary || {};
    const activeCount = summary.active_count ?? requestRows.filter((row) => row.is_active).length;
    const completedCount = summary.completed_count ?? requestRows.filter((row) => row.status === "completed").length;
    const homeStatus = activeCount ? `큐 ${activeCount}` : completedCount ? `완료 ${completedCount}` : "Ready";
    setText(memberHomeStatus, homeStatus);
    setText(portfolioTabCount, portfolioCount);
    setText(watchlistTabCount, watchlistCount);
    setText(analysisTabCount, activeCount);
    setText(overviewPortfolios, portfolioCount);
    setText(overviewWatchlists, watchlistCount);
    setText(overviewActiveRequests, activeCount);
    setText(overviewCompletedReports, completedCount);
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
    updateMemberOverview(
      payload?.portfolios || { items: [] },
      payload?.watchlists || { items: [] },
      payload?.analysis_requests || { items: [] }
    );
    renderPortfolios(
      payload?.portfolios || { items: [] },
      payload?.portfolio_details || {},
      errorText(errors, "portfolios")
    );
    renderWatchlists(
      payload?.watchlists || { items: [] },
      payload?.watchlist_details || {},
      errorText(errors, "watchlists")
    );
    renderAnalysisRequests(
      payload?.analysis_requests || { items: [] },
      errorText(errors, "analysis_requests")
    );
    const errorCount = flattenErrorCount(errors);
    const status = payload?.status || (errorCount ? "partial" : "available");
    if (status === "available" && !errorCount) {
      setSignedInState(true, {
        label: "대시보드 준비 완료",
        user: userLabel,
        meta: "포트폴리오, 관심종목, 분석 요청 큐를 불러왔습니다."
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
      setSignedInState(false);
      setStatus(config.configured ? "로그인 필요" : "Supabase 공개 Auth 설정 대기 중", !config.configured);
      return;
    }
    setSignedInState(true, { label: "세션 확인 중", meta: "대시보드를 불러오고 있습니다." });
    setStatus("대시보드 불러오는 중");
    const dashboardResult = await safeMemberApi("/api/member/dashboard?include_latest_prices=true");
    if (dashboardResult.ok) {
      renderDashboard(dashboardResult.payload);
      return;
    }
    if (!accessToken() && !refreshToken()) {
      setSignedInState(false);
      setStatus(dashboardResult.error, true);
      return;
    }
    await loadLegacyMemberData(dashboardResult.error);
  }

  async function loadLegacyMemberData(dashboardError = "") {
    const [portfoliosResult, watchlistsResult, requestsResult] = await Promise.all([
      safeMemberApi("/api/portfolios"),
      safeMemberApi("/api/watchlists"),
      safeMemberApi("/api/analysis-requests?limit=20")
    ]);
    const portfolios = portfoliosResult.payload || { items: [] };
    const watchlists = watchlistsResult.payload || { items: [] };
    const requests = requestsResult.payload || { items: [] };
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
    updateMemberOverview(portfolios, watchlists, requests);
    const errors = [portfoliosResult, watchlistsResult, requestsResult].filter((result) => !result.ok).length
      + (dashboardError ? 1 : 0);
    const userLabel = storageGet(userEmailKey) || storageGet(userIdKey) || "회원 세션";
    if (errors) {
      const fallbackErrors = [
        dashboardError ? `dashboard: ${dashboardError}` : "",
        portfoliosResult.ok ? "" : `portfolios: ${portfoliosResult.error}`,
        watchlistsResult.ok ? "" : `watchlists: ${watchlistsResult.error}`,
        requestsResult.ok ? "" : `analysis_requests: ${requestsResult.error}`
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
      meta: "통합 대시보드 대신 기본 API 응답으로 화면을 구성했습니다."
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
        setStatus("가입 요청 완료. 이메일 확인 후 로그인하세요.");
        return;
      }
      await loadMemberData();
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      setAuthBusy(false);
    }
  }

  async function submitJson(form, path, buildBody) {
    try {
      const body = buildBody(new FormData(form));
      const payload = await memberApi(path, { method: "POST", body: JSON.stringify(body) });
      form.reset();
      await loadMemberData();
      if (payload?.status === "already_queued") {
        setStatus("이미 대기 중인 분석 요청이 있어 기존 큐 항목을 유지했습니다.");
      } else if (payload?.status === "queued") {
        const quota = payload?.quota;
        const suffix = quota ? ` (${quota.daily_used}/${quota.daily_limit}, 최근 ${quota.window_hours}시간)` : "";
        setStatus(`분석 요청을 큐에 등록했습니다${suffix}.`);
      }
    } catch (error) {
      setStatus(error.message, true);
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
    passwordToggle.textContent = showing ? "보기" : "숨김";
    passwordToggle.setAttribute("aria-pressed", showing ? "false" : "true");
  });

  signOutButton?.addEventListener("click", async () => {
    await supabaseLogout();
    clearSession();
    fillPortfolioSelects([]);
    fillSelect(watchlistSelect, [], "name");
    portfolioList?.replaceChildren(emptyNode("로그인 후 포트폴리오가 표시됩니다"));
    watchlistList?.replaceChildren(emptyNode("로그인 후 관심목록이 표시됩니다"));
    analysisRequestList?.replaceChildren(emptyNode("로그인 후 분석 요청이 표시됩니다"));
    updateMemberOverview({ items: [] }, { items: [] }, { items: [] });
    setStatus("로그아웃됨");
  });

  refreshButton?.addEventListener("click", () => {
    loadMemberData().catch((error) => setStatus(error.message, true));
  });

  portfolioForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitJson(portfolioForm, "/api/portfolios", (form) => ({
      name: String(form.get("name") || ""),
      base_currency: "KRW"
    }));
  });

  tradeForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(tradeForm);
    const portfolioId = String(form.get("portfolio_id") || "");
    submitJson(tradeForm, `/api/portfolio/${encodeURIComponent(portfolioId)}/trades`, () => ({
      ticker_code: String(form.get("ticker_code") || ""),
      side: String(form.get("side") || "buy"),
      trade_date: String(form.get("trade_date") || ""),
      price: String(form.get("price") || ""),
      quantity: Number(form.get("quantity") || 0),
      fee: optionalDecimal(form.get("fee")) || "0",
      tax: optionalDecimal(form.get("tax")) || "0"
    }));
  });

  targetForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(targetForm);
    const portfolioId = String(form.get("portfolio_id") || "");
    const tickerCode = String(form.get("ticker_code") || "");
    submitJson(targetForm, `/api/portfolio/${encodeURIComponent(portfolioId)}/targets/${encodeURIComponent(tickerCode)}`, (values) => ({
      target_price: optionalDecimal(values.get("target_price")),
      stop_price: optionalDecimal(values.get("stop_price")),
      memo: String(values.get("memo") || "") || null
    }));
  });

  watchlistForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitJson(watchlistForm, "/api/watchlists", (form) => ({
      name: String(form.get("name") || "")
    }));
  });

  watchlistItemForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(watchlistItemForm);
    const watchlistId = String(form.get("watchlist_id") || "");
    submitJson(watchlistItemForm, `/api/watchlists/${encodeURIComponent(watchlistId)}/items`, () => ({
      ticker_code: String(form.get("ticker_code") || ""),
      memo: String(form.get("memo") || "") || null
    }));
  });

  analysisRequestForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitJson(analysisRequestForm, "/api/analysis-requests", (form) => {
      const requested = String(form.get("requested_trade_date") || "");
      return {
        ticker: String(form.get("ticker") || ""),
        requested_trade_date: requested || null,
        reason: String(form.get("reason") || "") || null
      };
    });
  });

  migrateSessionStorage();
  setupMemberTabs();
  setAuthUiState(Boolean(accessToken() || refreshToken()));
  applyRequestedAuthMode();
  const redirectSession = consumeRedirectSession();
  if (redirectSession.shouldLoad) {
    const shouldSkipInitialLoad = requestedAuthMode === "signup" && !accessToken() && !refreshToken();
    if (!shouldSkipInitialLoad) {
      loadMemberData().catch((error) => setStatus(error.message, true));
    }
  }
})();
"""

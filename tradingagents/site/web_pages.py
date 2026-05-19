"""Server-rendered public pages for the TradingAgents Korea site."""

from __future__ import annotations

import html
import json
import os
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from tradingagents.storage import StorageRepository

from .analysis_api import build_public_analysis_feed_payload
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
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    <nav class="top-links" aria-label="서비스 페이지">
      <a href="/analyses">분석 목록</a>
      <a href="/member">대시보드</a>
    </nav>
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
          <div class="chart-heading-meta">
            <span class="status-pill">{_h(model["chart_status"])}</span>
            <span class="data-pill">{_h(model["chart_vendor_label"])}</span>
          </div>
        </div>
        {chart_controls_html}
        <p class="chart-caption">{_h(model["chart_caption"])}</p>
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
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    <nav class="top-links" aria-label="공개 페이지">
      <a href="/analyses">분석 목록</a>
      <a href="/stocks/005930">삼성전자</a>
      <a href="/member">대시보드</a>
    </nav>
  </header>

  <main class="shell">
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

    {summary_html}

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
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    <nav class="top-links" aria-label="공개 페이지">
      <a href="/analyses">분석 목록</a>
      <a href="/stocks/005930">삼성전자</a>
      <a href="/member">대시보드</a>
    </nav>
  </header>

  <main class="home-shell home-shell-art">
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
        <p>차트만 보거나 뉴스만 읽는 화면이 아니라, 가격과 이벤트를 함께 묶어 공개 분석의 맥락을 만듭니다.</p>
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
      </ul>
    </section>

    <section class="home-band home-member-band" aria-labelledby="member-title">
      <div class="home-section-heading">
        <div>
          <p class="eyebrow">Member Workspace</p>
          <h2 id="member-title">회원은 포트폴리오와 관심종목을 따로 관리합니다</h2>
        </div>
        <a class="home-primary-link" href="/member">대시보드 열기</a>
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


def render_member_dashboard_page(*, site_base_url: str | None = None) -> str:
    """Render the authenticated member dashboard shell."""

    model = {
        "title": "회원 대시보드 | TradingAgents Korea",
        "description": "수동 포트폴리오, 관심목록, 한국 주식 AI 분석 요청을 관리합니다.",
        "canonical_url": canonical_url("/member", site_base_url=site_base_url),
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
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    <nav class="top-links" aria-label="서비스 페이지">
      <a href="/analyses">분석 목록</a>
      <a href="/stocks/005930">삼성전자</a>
      <a href="/member">대시보드</a>
    </nav>
  </header>

  <main class="shell member-shell">
    <section class="summary-band" aria-labelledby="member-title">
      <div>
        <p class="eyebrow">Member Workspace</p>
        <h1 id="member-title">내 투자 노트</h1>
        <p class="asof" id="memberStatus">로그인 상태 확인 중</p>
      </div>
      <div class="decision-box">
        <span class="decision-label">거래 기능</span>
        <strong>OFF</strong>
        <span>조회/기록 전용</span>
      </div>
    </section>

    <section class="member-grid" aria-label="회원 기능">
      <section class="member-panel auth-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Supabase Auth</p>
            <h2>로그인</h2>
          </div>
          <button class="ghost-button" id="signOutButton" type="button">나가기</button>
        </div>
        <form class="member-form" id="authForm">
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
          <div class="button-row">
            <button type="button" data-auth-action="signin">로그인</button>
            <button type="button" data-auth-action="signup">가입</button>
          </div>
          <div class="member-empty auth-status" id="authStatus" role="status" aria-live="polite">이메일과 비밀번호를 입력하세요.</div>
        </form>
        <div class="member-signed-in" id="memberSignedIn" hidden>
          <span class="status-pill" id="memberSignedInState">대시보드 확인 중</span>
          <strong id="memberSignedInUser">회원 세션</strong>
          <small id="memberSignedInMeta">대시보드를 불러오고 있습니다.</small>
        </div>
      </section>

      <section class="member-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Manual Portfolio</p>
            <h2>수동 매수 기록</h2>
          </div>
          <button class="ghost-button" id="refreshMemberData" type="button">새로고침</button>
        </div>
        <form class="member-form compact-form" id="portfolioForm">
          <input name="name" maxlength="80" placeholder="포트폴리오 이름" required>
          <button type="submit">추가</button>
        </form>
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
        <form class="member-form target-form" id="targetForm">
          <select name="portfolio_id" required></select>
          <input name="ticker_code" maxlength="12" placeholder="005930" required>
          <input name="target_price" type="number" min="1" step="1" placeholder="목표가">
          <input name="stop_price" type="number" min="1" step="1" placeholder="손절가">
          <input name="memo" maxlength="500" placeholder="목표 메모">
          <button type="submit">저장</button>
        </form>
        <div class="member-list" id="portfolioList"></div>
      </section>

      <section class="member-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Watchlist</p>
            <h2>관심종목</h2>
          </div>
          <span class="status-pill">KR</span>
        </div>
        <form class="member-form compact-form" id="watchlistForm">
          <input name="name" maxlength="80" placeholder="관심목록 이름" required>
          <button type="submit">추가</button>
        </form>
        <form class="member-form compact-form" id="watchlistItemForm">
          <select name="watchlist_id" required></select>
          <input name="ticker_code" maxlength="12" placeholder="005930" required>
          <input name="memo" maxlength="500" placeholder="메모">
          <button type="submit">담기</button>
        </form>
        <div class="member-list" id="watchlistList"></div>
      </section>

      <section class="member-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">AI Analysis</p>
            <h2>분석 요청</h2>
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
        "chart_caption": _chart_caption(chart, points),
        "chart_fallback": _chart_fallback_message(chart),
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


def _stock_query_href(code: str, params: dict[str, str]) -> str:
    query = urlencode({key: value for key, value in params.items() if value})
    return f"/stocks/{code}?{query}" if query else f"/stocks/{code}"


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
    return f"{start} - {end} / {vendor} / {point_label}"


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
        "filter_label": f"{ticker_code} 필터" if ticker_code else "전체 종목",
        "item_count": str(len(items)),
        "summary": summary,
        "items": items,
    }


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


def _analysis_feed_cards(items: list[dict[str, Any]]) -> str:
    if not items:
        return """
        <article class="analysis-feed-card empty">
          <span>waiting</span>
          <h3>공개 분석 대기</h3>
          <p>분석 worker가 완료한 public 리포트가 생기면 이 목록에 표시됩니다.</p>
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
        report_count = item.get("report_count")
        reports = f"{report_count}개" if report_count is not None else "-"
        api_path = item.get("api_path") or f"/api/analyses/{item.get('id')}"
        cards.append(
            f"""
            <article class="analysis-feed-card">
              <span>{_h(str(market))}</span>
              <h3><a href="/stocks/{_h(str(code))}">{_h(str(name))} <small>{_h(str(code))}</small></a></h3>
              <p>{_h(str(trade_date))} 기준 공개 분석 / 판단 {_h(str(decision))}</p>
              <dl>
                <div><dt>상태</dt><dd>{_h(str(item.get("status") or "-"))}</dd></div>
                <div><dt>모델</dt><dd>{_h(str(model_provider))}</dd></div>
                <div><dt>리포트</dt><dd>{_h(reports)}</dd></div>
                <div><dt>알파</dt><dd>{_h(alpha)}</dd></div>
                <div><dt>원문</dt><dd><a href="{_h(str(api_path))}">JSON</a></dd></div>
              </dl>
            </article>
            """
        )
    return "\n".join(cards)


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
    <section class="outcome-section" aria-labelledby="outcome-title">
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
  font-family: Pretendard, Geist, Satoshi, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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

.analysis-feed-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.analysis-feed-card {
  min-height: 178px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
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
  margin-bottom: 14px;
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

.member-shell {
  padding-bottom: 64px;
}

.member-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.member-panel {
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.member-panel h2 {
  margin: 4px 0 0;
  font-size: 20px;
}

.member-form {
  display: grid;
  gap: 10px;
  margin-top: 14px;
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

.ghost-button {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink);
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
.member-action-item small {
  min-width: 0;
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
  background: var(--surface);
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
  border-color: #d6a73b;
  color: var(--warn);
}

.analysis-status-completed {
  border-color: #87b391;
  color: #23633a;
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

  .home-hero,
  .home-section-heading,
  .home-analysis-zone,
  .home-ops-strip {
    grid-template-columns: minmax(0, 1fr);
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
  .analysis-summary-grid,
  .member-grid {
    grid-template-columns: 1fr 1fr;
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

  .member-action-item strong,
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
  .analysis-summary-grid,
  .member-grid,
  .compact-form,
  .trade-form,
  .target-form {
    grid-template-columns: minmax(0, 1fr);
  }

  .chart-wrap {
    min-height: 260px;
    aspect-ratio: 4 / 3;
  }

  .member-action-item {
    grid-template-columns: minmax(0, 1fr);
  }

  .member-action-item strong,
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  color: rgba(246, 243, 232, 0.66);
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
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
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
  color: rgba(246, 243, 232, 0.6);
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
        homeCtx.font = "700 11px JetBrains Mono, Consolas, monospace";
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
  const portfolioSelect = tradeForm?.elements?.portfolio_id;
  const targetPortfolioSelect = targetForm?.elements?.portfolio_id;
  const watchlistSelect = watchlistItemForm?.elements?.watchlist_id;
  const accessTokenKey = "tradingagents.member.access_token";
  const refreshTokenKey = "tradingagents.member.refresh_token";
  const expiresAtKey = "tradingagents.member.expires_at";
  const userEmailKey = "tradingagents.member.user_email";
  const userIdKey = "tradingagents.member.user_id";

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

  function setSignedInState(isSignedIn, options = {}) {
    authPanel?.classList.toggle("is-signed-in", Boolean(isSignedIn));
    if (signedInPanel) signedInPanel.hidden = !isSignedIn;
    if (!isSignedIn) return;
    const label = options.label || "대시보드 확인 중";
    const user = options.user || sessionStorage.getItem(userEmailKey) || sessionStorage.getItem(userIdKey) || "회원 세션";
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
    return sessionStorage.getItem(accessTokenKey) || "";
  }

  function refreshToken() {
    return sessionStorage.getItem(refreshTokenKey) || "";
  }

  function sessionExpiresAt() {
    return Number(sessionStorage.getItem(expiresAtKey) || 0);
  }

  function clearSession() {
    sessionStorage.removeItem(accessTokenKey);
    sessionStorage.removeItem(refreshTokenKey);
    sessionStorage.removeItem(expiresAtKey);
    sessionStorage.removeItem(userEmailKey);
    sessionStorage.removeItem(userIdKey);
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
    sessionStorage.setItem(accessTokenKey, token);
    if (refresh) sessionStorage.setItem(refreshTokenKey, refresh);
    if (Number.isFinite(expiresAt)) sessionStorage.setItem(expiresAtKey, String(expiresAt));
    if (user.email) sessionStorage.setItem(userEmailKey, String(user.email));
    if (user.id) sessionStorage.setItem(userIdKey, String(user.id));
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
    if (!response.ok) throw new Error(payload.detail || "Request failed");
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

  function optionalDecimal(value) {
    const text = String(value || "").trim();
    return text || null;
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

  function riskText(position) {
    const parts = [];
    if (position.target_price !== null && position.target_price !== undefined) {
      parts.push(`목표 ${money(position.target_price)}${position.target_hit ? " 도달" : ""}`);
    }
    if (position.stop_price !== null && position.stop_price !== undefined) {
      parts.push(`손절 ${money(position.stop_price)}${position.stop_hit ? " 도달" : ""}`);
    }
    if (position.target_memo) parts.push(position.target_memo);
    return parts.length ? parts.join(" / ") : "목표·손절 미설정";
  }

  function portfolioLines(detail) {
    return (detail?.positions || []).slice(0, 4).map((position) => {
      const quantity = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 4 }).format(Number(position.quantity || 0));
      const pnl = signedMoney(position.total_pnl ?? position.unrealized_pnl ?? position.realized_pnl);
      return `${position.ticker_name || position.ticker_code} ${quantity}주 / 평단 ${money(position.average_cost)} / 손익 ${pnl} / ${riskText(position)}`;
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
      return `${item.ticker_name || item.ticker_code} ${item.ticker_code} / ${price}${memo}`;
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
      const title = document.createElement("strong");
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
    return strip;
  }

  function analysisRequestCard(row) {
    const title = `${row.ticker_name || row.ticker_code} ${row.ticker_code}`;
    const meta = `${statusLabel(row.status)} / ${row.requested_trade_date}`;
    const details = [];
    if (row.reason) details.push(`메모 ${row.reason}`);
    if (row.analysis_run_id) details.push(`리포트 ${row.analysis_run_id.slice(0, 8)}`);
    details.push(`업데이트 ${String(row.updated_at || row.created_at || "").slice(0, 10) || "-"}`);
    return itemCard(title, meta, [miniList(details, "상세 상태 대기", "큐 상태")]);
  }

  function fillSelect(select, rows, labelKey) {
    if (!select) return;
    select.replaceChildren(...rows.map((row) => {
      const option = document.createElement("option");
      option.value = row.id;
      option.textContent = row[labelKey] || row.id;
      return option;
    }));
  }

  function fillPortfolioSelects(rows) {
    fillSelect(portfolioSelect, rows, "name");
    fillSelect(targetPortfolioSelect, rows, "name");
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
      ...(rows.length ? rows.map((row) => {
        const detail = details[row.id];
        const totals = detail?.totals || {};
        const meta = detail
          ? `${row.base_currency || "KRW"} / 평가 ${money(totals.market_value)} / 손익 ${signedMoney(totals.total_pnl)} / 거래 ${detail.trade_count || 0}건`
          : `${row.base_currency || "KRW"} / ${row.id}`;
        return itemCard(row.name, meta, [
          miniList(portfolioLines(detail), "아직 보유 종목이 없습니다", "보유"),
          miniList(tradeLines(detail), "아직 거래 내역이 없습니다", "최근 거래")
        ]);
      }) : [emptyNode("저장된 포트폴리오가 없습니다")])
    );
  }

  function renderWatchlists(payload, details = {}, error = "") {
    if (error) {
      fillSelect(watchlistSelect, [], "name");
      watchlistList.replaceChildren(emptyNode(`관심목록을 불러오지 못했습니다: ${error}`));
      return;
    }
    const rows = payload.items || [];
    fillSelect(watchlistSelect, rows, "name");
    watchlistList.replaceChildren(
      ...(rows.length ? rows.map((row) => {
        const detail = details[row.id];
        const meta = detail
          ? `${detail.item_count}종목 / 가격 ${detail.priced_item_count}개 / ${detail.market_price_source?.vendor || "수동"}`
          : row.id;
        return itemCard(row.name, meta, [
          miniList(watchlistLines(detail), "아직 관심 종목이 없습니다", "요약"),
          watchlistActionList(detail)
        ]);
      }) : [emptyNode("저장된 관심목록이 없습니다")])
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
    const userId = member.user_id || sessionStorage.getItem(userIdKey) || "";
    if (userId) sessionStorage.setItem(userIdKey, String(userId));
    const userLabel = sessionStorage.getItem(userEmailKey) || userId || "회원 세션";
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
    const errors = [portfoliosResult, watchlistsResult, requestsResult].filter((result) => !result.ok).length
      + (dashboardError ? 1 : 0);
    const userLabel = sessionStorage.getItem(userEmailKey) || sessionStorage.getItem(userIdKey) || "회원 세션";
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
      await memberApi(path, { method: "POST", body: JSON.stringify(body) });
      form.reset();
      await loadMemberData();
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

  const redirectSession = consumeRedirectSession();
  if (redirectSession.shouldLoad) {
    loadMemberData().catch((error) => setStatus(error.message, true));
  }
})();
"""

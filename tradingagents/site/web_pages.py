"""Server-rendered public pages for the TradingAgents Korea site."""

from __future__ import annotations

import html
import json
import os
from typing import Any

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
    structured_data_json = _script_json(_structured_data(model, payload))
    reports_html = _report_cards(model["reports"])
    lenses_html = _strategy_lens_cards(payload.get("strategy_lenses") or [])
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
          <span class="status-pill">{_h(model["chart_status"])}</span>
        </div>
        <div class="chart-wrap">
          <canvas id="priceChart" aria-label="{_h(model["name"])} 가격 차트"></canvas>
          <div class="chart-legend" id="chartLegend" aria-hidden="true"></div>
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

    {lenses_html}

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
    """Render the public analysis explorer home page."""

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
    <section class="home-search-band" aria-labelledby="home-title">
      <div>
        <p class="eyebrow">Korean Stock AI Analysis</p>
        <h1 id="home-title">한국 주식 AI 분석</h1>
        <p class="asof">6자리 종목코드나 종목명으로 바로 분석 페이지를 열 수 있습니다.</p>
      </div>
      <form class="ticker-search home-search" action="/stocks" method="get">
        <label class="sr-only" for="ticker">종목코드 또는 종목명</label>
        <input id="ticker" name="ticker" list="tickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" autocomplete="off">
        <datalist id="tickerSuggestions"></datalist>
        <button type="submit">조회</button>
      </form>
    </section>

    <section class="report-section" aria-labelledby="quick-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Quick Start</p>
          <h2 id="quick-title">주요 종목 바로가기</h2>
        </div>
        <span class="status-pill">KRW</span>
      </div>
      <div class="analysis-feed-grid">
        {quick_html}
      </div>
    </section>

    <section class="report-section" aria-labelledby="recent-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Recent Analyses</p>
          <h2 id="recent-title">최근 공개 분석</h2>
        </div>
        <a class="status-pill" href="/analyses">전체 보기</a>
      </div>
      <div class="analysis-feed-grid">
        {recent_html}
      </div>
    </section>

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>
        <li>AI analysis is for informational purposes only and is not investment advice.</li>
        <li>Live trading and broker order placement are intentionally not supported.</li>
      </ul>
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
            <input name="password" type="password" autocomplete="current-password" required>
          </label>
          <div class="button-row">
            <button type="button" data-auth-action="signin">로그인</button>
            <button type="button" data-auth-action="signup">가입</button>
          </div>
          <div class="member-empty auth-status" id="authStatus" role="status">이메일과 비밀번호를 입력하세요.</div>
        </form>
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
          <button type="submit">기록</button>
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
    }


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
        }
    return build_public_analysis_feed_payload(repo, ticker=ticker, limit=limit, max_limit=max_limit)


def _analysis_feed_view_model(payload: dict[str, Any], *, site_base_url: str | None = None) -> dict[str, Any]:
    ticker_code = payload.get("ticker_code")
    items = payload.get("items") or []
    title = "공개 분석 목록 | TradingAgents Korea"
    description = "TradingAgents Korea의 한국 주식 AI 공개 분석 목록입니다."
    return {
        "title": title,
        "description": description,
        "canonical_url": canonical_url("/analyses", site_base_url=site_base_url),
        "subtitle": "한국 주식 AI 분석이 완료되면 이곳에 공개됩니다.",
        "status": _analysis_feed_status_label(payload.get("status")),
        "filter_label": f"{ticker_code} 필터" if ticker_code else "전체 종목",
        "item_count": str(len(items)),
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
        cards.append(
            f"""
            <article class="analysis-feed-card">
              <span>{_h(str(market))}</span>
              <h3><a href="/stocks/{_h(str(code))}">{_h(str(name))} <small>{_h(str(code))}</small></a></h3>
              <p>{_h(str(trade_date))} 기준 공개 분석</p>
              <dl>
                <div><dt>상태</dt><dd>{_h(str(item.get("status") or "-"))}</dd></div>
                <div><dt>모델</dt><dd>{_h(str(model_provider))}</dd></div>
              </dl>
            </article>
            """
        )
    return "\n".join(cards)


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

.compact-form {
  grid-template-columns: minmax(0, 1fr) auto;
}

.compact-form input:nth-last-child(2) {
  grid-column: auto;
}

.trade-form {
  grid-template-columns: minmax(150px, 1.1fr) minmax(96px, 0.8fr) minmax(92px, 0.7fr) minmax(128px, 0.9fr) minmax(96px, 0.8fr) minmax(84px, 0.7fr) auto;
  align-items: end;
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
    grid-template-columns: 1fr;
  }

  .summary-band {
    display: grid;
  }

  .decision-box {
    min-width: 0;
  }

  .lens-grid,
  .report-grid {
    grid-template-columns: 1fr 1fr;
  }

  .analysis-feed-grid,
  .member-grid {
    grid-template-columns: 1fr 1fr;
  }

  .trade-form {
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
  .lens-grid,
  .report-grid,
  .analysis-feed-grid,
  .member-grid,
  .compact-form,
  .trade-form {
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
  const legend = document.getElementById("chartLegend");
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

  function draw() {
    const rect = fitCanvas();
    const width = rect.width;
    const height = rect.height;
    const left = 62;
    const right = 24;
    const top = 34;
    const bottom = 42;
    const volumeHeight = Math.min(92, Math.max(52, height * 0.22));
    const priceBottom = height - bottom - volumeHeight - 18;
    const volumeTop = priceBottom + 12;
    const volumeBottom = height - bottom;
    const slot = (width - left - right) / Math.max(bars.length - 1, 1);
    const candleWidth = Math.max(3, Math.min(12, slot * 0.58));

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
})();
"""


MEMBER_PAGE_JS = """
(() => {
  const configNode = document.getElementById("member-config");
  const config = JSON.parse(configNode?.textContent || "{}");
  const statusNode = document.getElementById("memberStatus");
  const authStatusNode = document.getElementById("authStatus");
  const authForm = document.getElementById("authForm");
  const authButtons = Array.from(document.querySelectorAll("[data-auth-action]"));
  const signOutButton = document.getElementById("signOutButton");
  const refreshButton = document.getElementById("refreshMemberData");
  const portfolioForm = document.getElementById("portfolioForm");
  const tradeForm = document.getElementById("tradeForm");
  const watchlistForm = document.getElementById("watchlistForm");
  const watchlistItemForm = document.getElementById("watchlistItemForm");
  const analysisRequestForm = document.getElementById("analysisRequestForm");
  const portfolioList = document.getElementById("portfolioList");
  const watchlistList = document.getElementById("watchlistList");
  const analysisRequestList = document.getElementById("analysisRequestList");
  const portfolioSelect = tradeForm?.elements?.portfolio_id;
  const watchlistSelect = watchlistItemForm?.elements?.watchlist_id;
  const tokenKey = "tradingagents.member.access_token";

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

  function accessToken() {
    return sessionStorage.getItem(tokenKey) || "";
  }

  function setToken(token) {
    if (token) sessionStorage.setItem(tokenKey, token);
    else sessionStorage.removeItem(tokenKey);
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

    setToken(token);
    setStatus("이메일 확인 완료. 로그인되었습니다.");
    return { shouldLoad: true };
  }

  async function supabaseAuth(path, body, params = {}) {
    if (!requireConfig()) return null;
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

  async function memberApi(path, options = {}) {
    const token = accessToken();
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
    if (!response.ok) throw new Error(payload.detail || "Request failed");
    return payload;
  }

  function itemCard(title, meta) {
    const node = document.createElement("article");
    node.className = "member-item";
    const strong = document.createElement("strong");
    strong.textContent = title;
    const small = document.createElement("small");
    small.textContent = meta;
    node.append(strong, small);
    return node;
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

  function fillSelect(select, rows, labelKey) {
    if (!select) return;
    select.replaceChildren(...rows.map((row) => {
      const option = document.createElement("option");
      option.value = row.id;
      option.textContent = row[labelKey] || row.id;
      return option;
    }));
  }

  function renderPortfolios(payload, details = {}) {
    const rows = payload.items || [];
    fillSelect(portfolioSelect, rows, "name");
    portfolioList.replaceChildren(
      ...(rows.length ? rows.map((row) => {
        const detail = details[row.id];
        const totals = detail?.totals || {};
        const meta = detail
          ? `${row.base_currency || "KRW"} / 평가 ${money(totals.market_value)} / 손익 ${money(totals.total_pnl)}`
          : `${row.base_currency || "KRW"} / ${row.id}`;
        return itemCard(row.name, meta);
      }) : [emptyNode("저장된 포트폴리오가 없습니다")])
    );
  }

  function renderWatchlists(payload, details = {}) {
    const rows = payload.items || [];
    fillSelect(watchlistSelect, rows, "name");
    watchlistList.replaceChildren(
      ...(rows.length ? rows.map((row) => {
        const detail = details[row.id];
        const meta = detail
          ? `${detail.item_count}종목 / 가격 ${detail.priced_item_count}개`
          : row.id;
        return itemCard(row.name, meta);
      }) : [emptyNode("저장된 관심목록이 없습니다")])
    );
  }

  function renderAnalysisRequests(payload) {
    const rows = payload.items || [];
    analysisRequestList.replaceChildren(
      ...(rows.length ? rows.map((row) => itemCard(`${row.ticker_name || row.ticker_code} ${row.ticker_code}`, `${row.status} / ${row.requested_trade_date}`)) : [emptyNode("분석 요청 내역이 없습니다")])
    );
  }

  async function loadMemberData() {
    if (!accessToken()) {
      setStatus(config.configured ? "로그인 필요" : "Supabase 공개 Auth 설정 대기 중", !config.configured);
      return;
    }
    const [portfolios, watchlists, requests] = await Promise.all([
      memberApi("/api/portfolios"),
      memberApi("/api/watchlists"),
      memberApi("/api/analysis-requests?limit=20")
    ]);
    const [portfolioDetails, watchlistDetails] = await Promise.all([
      detailMap((portfolios.items || []).slice(0, 6), (row) => `/api/portfolio/${encodeURIComponent(row.id)}?include_latest_prices=true`),
      detailMap((watchlists.items || []).slice(0, 6), (row) => `/api/watchlists/${encodeURIComponent(row.id)}?include_latest_prices=true`)
    ]);
    renderPortfolios(portfolios, portfolioDetails);
    renderWatchlists(watchlists, watchlistDetails);
    renderAnalysisRequests(requests);
    setStatus("로그인됨");
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
      const token = payload?.access_token || payload?.session?.access_token;
      if (!token) {
        setStatus("가입 요청 완료. 이메일 확인 후 로그인하세요.");
        return;
      }
      setToken(token);
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

  signOutButton?.addEventListener("click", () => {
    setToken("");
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
      fee: "0",
      tax: "0"
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

from datetime import date

import pytest
from fastapi.testclient import TestClient

from tradingagents.storage.repository import TEST_DATABASE_URL  # noqa: E402
from tradingagents.storage import (
    AgentReportInput,
    AnalysisOutcomeInput,
    AnalysisRequestInput,
    AnalysisRunInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)
from tradingagents.site.api_app import create_app
from tradingagents.site.seo import build_ads_txt, build_robots_txt, build_sitemap_xml, stock_canonical_url
from tradingagents.site.web_pages import (
    render_admin_console_page,
    render_feature_detail_page,
    render_feature_index_page,
    render_member_dashboard_page,
    render_policy_page,
    render_public_analysis_detail_page,
    render_public_analysis_feed_page,
    render_public_home_page,
    render_public_outcomes_page,
    render_public_stock_page,
)


def _payload():
    return {
        "ticker": {
            "code": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "currency": "KRW",
            "benchmark_symbol": "^KS11",
        },
        "analysis": {
            "status": "available",
            "run": {
                "id": "00000000-0000-0000-0000-000000000010",
                "trade_date": "2026-05-05",
                "model_provider": "openai",
            },
            "reports": [
                {
                    "role": "market",
                    "title": "Market report",
                    "content": "Korean market breadth and liquidity remain constructive.",
                }
            ],
            "decision": {
                "rating": "Hold",
                "action": "hold",
                "rationale": "Wait for stronger earnings confirmation.",
            },
            "outcomes": [
                {
                    "horizon_days": 5,
                    "status": "completed",
                    "actual_holding_days": 5,
                    "raw_return": 0.04,
                    "benchmark_return": 0.01,
                    "alpha_return": 0.03,
                }
            ],
        },
        "analysis_refresh": {"recommended": False, "reason": "fresh", "age_days": 0},
        "chart": {
            "status": "available",
            "ticker_code": "005930",
            "ticker_name": "삼성전자",
            "market": "KOSPI",
            "currency": "KRW",
            "vendor": "pykrx",
            "requested_vendor": "auto",
            "resolved_vendor": "pykrx",
            "point_count": 2,
            "data_source_label": "pykrx",
            "fallback_used": True,
            "start_date": "2026-05-04",
            "end_date": "2026-05-05",
            "points": [
                {"date": "2026-05-04", "open": 70000.0, "high": 71000.0, "low": 69000.0, "close": 70500.0, "volume": 1000},
                {"date": "2026-05-05", "open": 70600.0, "high": 72000.0, "low": 70200.0, "close": 71800.0, "volume": 2000},
            ],
        },
        "strategy_lenses": [
            {
                "id": "trend",
                "title": "추세",
                "status": "positive",
                "score": 1.8,
                "summary": "단기 가격이 20일 평균 위에서 움직입니다.",
                "metrics": {"return_20d": 0.08},
            },
            {
                "id": "safety",
                "title": "안전 가드레일",
                "status": "positive",
                "score": None,
                "summary": "실거래 주문은 차단되어 있습니다.",
                "metrics": {"live_trading": "disabled"},
            },
        ],
        "notices": [
            "AI analysis is for informational purposes only and is not investment advice.",
            "Live trading and broker order placement are intentionally not supported.",
        ],
        "generated_at": "2026-05-05T09:00:00+09:00",
    }


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine(TEST_DATABASE_URL))
    repo.create_schema()
    return repo


def test_render_public_stock_page_limits_intraday_period_tabs(monkeypatch):
    payload = _payload()
    payload["chart"]["interval"] = "1m"
    payload["chart"]["vendor"] = "yfinance"
    payload["chart"]["requested_vendor"] = "yfinance"
    payload["chart"]["resolved_vendor"] = "yfinance"
    payload["chart"]["data_source_label"] = "Yahoo Finance"
    monkeypatch.setattr("tradingagents.site.web_pages.build_public_stock_payload", lambda *args, **kwargs: payload)

    html = render_public_stock_page("005930", site_base_url="https://example.com")

    assert "Yahoo 시간·분봉" in html
    assert "1분봉" in html
    assert "1일" in html
    assert "6개월" not in html
    assert "3개월" not in html


def test_render_public_stock_page_surfaces_missing_data_warnings(monkeypatch):
    payload = _payload()
    payload["analysis"] = {"status": "missing", "reports": [], "decision": None, "outcomes": []}
    payload["analysis_refresh"] = {"recommended": True, "reason": "no_completed_public_analysis"}
    payload["chart"] = {
        "status": "unavailable",
        "start_date": "2026-05-01",
        "end_date": "2026-05-05",
        "vendor": "krx",
        "requested_vendor": "krx",
        "resolved_vendor": None,
        "point_count": 0,
        "data_source_label": "KRX Open API",
        "fallback_used": False,
        "error": "chart vendor offline",
        "points": [],
    }
    monkeypatch.setattr("tradingagents.site.web_pages.build_public_stock_payload", lambda *args, **kwargs: payload)

    html = render_public_stock_page("005930", site_base_url="https://example.com")

    assert "데이터 부족" in html
    assert "공개 분석이 아직 저장되지 않았습니다." in html
    assert "분석 업데이트 권장: 완료된 공개 리포트 없음" in html
    assert "차트 데이터를 불러오지 못했습니다: chart vendor offline" in html
    assert 'href="/analyses?ticker=005930">이 종목 리포트</a>' in html
    assert 'href="/member?mode=signup&amp;tab=analysis#analysis-request-section">분석 요청</a>' in html


def test_api_app_serves_public_home_page(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_public_home_page",
        lambda *args, **kwargs: "<!doctype html><html><body>home analysis explorer</body></html>",
    )
    client = TestClient(create_app(repo=None, load_repo_from_env=False, public_cache_seconds=60))

    response = client.get("/", params={"legacy": "1"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "home analysis explorer" in response.text


def test_render_public_home_page_is_usable_analysis_explorer():
    html = render_public_home_page(site_base_url="https://example.com")

    assert "TradingAgents Korea" in html
    assert "한국 주식 AI 분석" in html
    assert "최근 공개 분석" in html
    assert "한국 주식 AI 관제 시스템" in html
    assert "실거래 주문 없이 오직 데이터로 증명하는 한국 주식 AI 관제 시스템" in html
    assert "다차원 AI 데이터 엔진이 찾아낸 한국 주식의 맥락" in html
    assert "AI 리서치부터 가상 매매 시뮬레이션까지의 파이프라인" in html
    assert "내 공간 만들기" in html
    assert "AI 리포트 흐름 보기" in html
    assert "home-member-preview" in html
    assert 'href="/member?mode=signup&tab=analysis#analysis-request-section">분석 요청으로 시작하기</a>' in html
    assert "home-start-strip" in html
    assert "home-trust-panel" in html
    assert "공식·공개 데이터" in html
    assert "실거래 주문 기능 차단" in html
    assert "5일/20일 검증 결과" in html
    assert "삼성전자(005930) 실시간 AI 가상 관제 시뮬레이션 예시" in html
    assert "AI 가상 관제" in html
    assert "가상 진입 대기" in html
    assert "삼성전자 샘플 분석실 바로가기" in html
    assert "home-sample-pill" in html
    assert "캔들 차트" in html
    assert "정밀 캔들 차트와 이동평균, 거래량 흐름을 통해 가격의 맥락을 분석합니다." in html
    assert "home-analyst-window-caption" in html
    assert "homeSignalCanvas" in html
    assert "homeSignalTicker" in html
    assert "homeSignalDecision" in html
    assert "home-live-tape" in html
    assert "prefers-reduced-motion" in html
    assert "syncTopAuthLinks" in html
    assert "currentNavKey" in html
    assert 'path === "/" || path.startsWith("/stocks")' in html
    assert "syncTopNavigationState" in html
    assert '.top-links a[aria-current="page"]' in html
    assert "로그인" in html
    assert "회원으로 시작하기" in html
    assert 'href="/member?mode=signup"' in html
    assert 'href="/" aria-current="page">종목 검색</a>' in html
    assert 'href="/features/research"' in html
    assert 'href="/mypage"' in html
    assert "분석 흐름" in html
    assert "하나의 차트 위로 융합되는 5대 핵심 시그널 맵" in html
    assert "내 리서치 공간이 열립니다" in html
    assert "안전한 조회 전용 운영 원칙" in html
    assert "box-shadow: 0 0 10px rgba(220, 252, 19, 0.3)" in html
    assert ".public-home .analysis-feed-actions a" in html
    assert "color: rgba(246, 243, 232, 0.92)" in html
    assert "quick-card-action" in html
    assert "차트 관제" in html
    assert "home-flow-icon" in html
    assert "통화</dt>" not in html
    assert "페이지</dt>" not in html
    assert "KRW OHLCV" not in html
    assert "▦" not in html
    assert "⌁" not in html
    assert "home-service-map" in html
    assert "tickerSuggestions" in html
    assert "/api/tickers/search" in html
    assert "/stocks/005930" in html
    assert 'href="/stocks/005930">삼성전자</a>' not in html
    assert "/analyses" in html
    assert '<link rel="canonical" href="https://example.com/">' in html
    assert '<meta property="og:locale" content="ko_KR">' in html
    assert '<meta name="twitter:card" content="summary">' in html
    assert 'href="/disclaimer"' in html
    assert 'href="/terms"' in html
    assert 'href="/privacy"' in html


def test_render_member_dashboard_exposes_only_public_supabase_config(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")

    html = render_member_dashboard_page(site_base_url="https://example.com")

    assert "나만의 AI 리서치 공간을 시작하세요" in html
    assert "매매 일지, 관심그룹, AI 분석 요청" in html
    assert "보안 로그인" in html
    assert "조회 전용" in html
    assert "처음이라면 가입하기로 마이페이지를 열 수 있습니다." in html
    assert "마이페이지 진입을 위해 인증이 필요합니다." in html
    assert "auth-form-note" in html
    assert ".member-page .auth-form input" in html
    assert ".member-page .auth-form .password-toggle" in html
    assert ".button-row.auth-button-row" in html
    assert "position: absolute;" in html
    assert "background: transparent;" in html
    assert "font-size: 11px;" in html
    assert "margin: -8px 0 0;" in html
    assert "height: 46px;" in html
    assert "opacity: 0.6;" in html
    assert "마이페이지" in html
    assert "실거래 주문 기능은 차단하고 기록과 조회 흐름만 제공합니다." in html
    assert "memberSessionGate" in html
    assert "memberSessionTitle" in html
    assert "memberSessionMessage" in html
    assert "세션을 확인하고 있습니다" in html
    assert "세션 확인" in html
    assert "member-tab-strip" in html
    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in html
    assert 'role="tablist"' in html
    assert 'data-member-tab="home"' in html
    assert 'id="member-home-section"' in html
    assert "<h2>홈</h2>" in html
    assert "오늘 이어갈 항목입니다." in html
    assert "memberHomeStateNote" in html
    assert "저장된 항목을 불러오고 있습니다." in html
    assert "아직 저장된 항목이 없습니다. 매매 일지나 관심그룹부터 시작해 보세요." in html
    assert "내 리서치 공간이 활성화되었습니다." in html
    assert "member-home-grid" in html
    assert "member-primary-action" in html
    assert "align-items: center;" in html
    assert "display: inline-flex;" in html
    assert "display: flex;" in html
    assert "*01*" not in html
    assert "첫 매매 일지를 만들어 보세요" in html
    assert "실제 계좌 주문과 연결되지 않는 조회 전용 기록 공간입니다." in html
    assert "매매 일지 시작" in html
    assert 'data-member-primary-action="watchlist"' not in html
    assert "memberPrimaryActionButton" in html
    assert "setMemberPrimaryAction" in html
    assert "진행 중인 분석을 확인하세요" in html
    assert "관심그룹을 추가하세요" in html
    assert html.index('data-member-tab="portfolio"') < html.index('data-member-tab="watchlist"')
    assert "member-home-links" in html
    assert 'href="/analyses">AI 리포트 보기</a>' in html
    assert 'href="/outcomes">검증 결과 보기</a>' in html
    assert "member-paper-card" in html
    assert "AI 가상매매" in html
    assert 'data-member-tab="paper"' in html
    assert 'id="paper-simulation-section"' in html
    assert "AI의 가상 매수·매도 기록을 봅니다." in html
    assert "paper-simulation-flow" in html
    assert "가상 매수·매도 기록이 쌓입니다" in html
    assert "paperSimulationList" in html
    assert "/api/member/paper-simulations" in html
    assert "member-admin-link" in html
    assert "data-admin-token-visible hidden" not in html
    assert "운영 콘솔" in html
    assert "adminTokenItems" not in html
    assert 'class="member-admin-link" href="/admin" data-admin-only hidden>운영 콘솔</a>' in html
    assert 'data-theme="dark"' in html and "Pretendard" in html
    assert 'storageGet("tradingagents.admin.worker_token")' in html
    assert 'node.hidden = !(signedIn || storageGet("tradingagents.admin.worker_token") || window.location.pathname === "/admin")' in html
    assert 'data-member-jump="portfolio"' in html
    assert 'data-member-tab="portfolio"' in html
    assert 'aria-selected="true"' in html
    assert 'aria-controls="analysis-request-section"' in html
    assert 'data-member-panel="watchlist"' in html
    assert 'id="analysisWatchlistTickerSelect"' in html
    assert 'aria-label="관심그룹 종목 선택"' in html
    assert "watchlistTickerOptions" in html
    assert "fillAnalysisWatchlistTickerSelect" in html
    assert "관심그룹 종목 선택" in html
    assert "관심그룹 종목을 분석 요청에 넣었습니다." in html
    assert "prefillAnalysisRequest" in html
    assert "다시 요청" in html
    assert "재요청 내용을 입력했습니다. 확인 후 요청을 누르세요." in html
    assert ".member-page .member-form select option" in html
    assert "color-scheme: dark;" in html
    assert "memberOverview" in html
    assert "memberOverviewActiveRequests" in html
    assert "memberOverviewPaperSimulations" in html
    assert "새 매매 일지" in html
    assert "먼저 일지 이름을 만듭니다." in html
    assert 'aria-label="종목코드 또는 종목명"' in html
    assert 'id="memberTickerSuggestions"' in html
    assert "data-member-ticker-lookup" in html
    assert "memberSearchTickers" in html
    assert "setupMemberTickerLookup" in html
    assert "normalizeMemberTickerValue" in html
    assert "tickerFromForm" in html
    assert "매수/매도 기록" in html
    assert "목표/손절 메모" in html
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in html
    assert "display: inline-flex;" in html
    assert 'href="#portfolio-section"' in html
    assert 'id="watchlist-section"' in html
    assert "새 관심그룹" in html
    assert "그룹 만들기" in html
    assert "종목 담기" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in html
    assert "새 관심그룹 생성 가동" in html
    assert "그룹 이름 입력" not in html
    assert "그룹 이름 수정" in html
    assert "이름 저장" in html
    assert "종목 삭제" in html
    assert "그룹 만드는 중" in html
    assert "종목 담는 중" in html
    assert 'method: "PATCH"' in html
    assert 'id="memberAuthLanding"' in html
    assert 'id="memberWorkspace" hidden' in html
    assert 'data-auth="signed-out"' in html and 'data-auth="signed-in"' in html
    assert 'member-page is-member-checking"' in html
    assert 'href="/mypage"' in html
    assert 'href="/stocks/005930">삼성전자</a>' not in html
    assert "/api/portfolios" in html
    assert "/api/watchlists" in html
    assert "/api/analysis-requests" in html
    assert "/api/member/dashboard?include_latest_prices=true" in html
    assert 'id="targetForm"' in html
    assert "/targets/${encodeURIComponent(tickerCode)}" in html
    assert 'options.method || "POST"' in html
    assert 'method: "PUT", successMessage' in html
    assert 'name="target_price"' in html
    assert 'name="stop_price"' in html
    assert 'name="fee"' in html
    assert 'name="tax"' in html
    assert "tradeLines" in html
    assert "signedPercent" in html
    assert "target_gap_rate" in html
    assert "target_memo" in html
    assert "watchlistActionList" in html
    assert "portfolioCard" in html
    assert "watchlistCard" in html
    assert "member-empty-action" in html
    assert "emptyActionNode" in html
    assert "setFormControlsDisabled" in html
    assert "dashboardStatusMeta" in html
    assert "아직 저장된 항목이 없습니다" in html
    assert "아직 AI 가상매매 기록이 없습니다" in html
    assert "renderPaperSimulations" in html
    assert "paperSimulationCard" in html
    assert "paperSimulationEventCard" in html
    assert "최근 가상 매매 이벤트" in html
    assert "AI가 만든 가상 매수·매도 시점과 기록 사유입니다." in html
    assert "paperEventReasonLabel" in html
    assert "paperLearningNote" in html
    assert "paper-learning-buckets" in html
    assert "복기 요약" in html
    assert "진입 패턴" in html
    assert "진입 이유" in html
    assert "청산 이유" in html
    assert "사후 평가" in html
    assert "post_trade_evaluation" in html
    assert "exit_reason_detail" in html
    assert "reason_summary" in html
    assert "evaluation_summary" in html
    assert "pattern_label" in html
    assert "아직 매매 일지가 없습니다" in html
    assert "아직 관심그룹이 없습니다" in html
    assert "완료 후 AI 리포트 링크를 보여줍니다." in html
    assert "매매 일지를 만들었습니다." in html
    assert "관심그룹에 종목을 담았습니다." in html
    assert "member-metric-grid" in html
    assert "member-action-item" in html
    assert "public_stock_path" in html
    assert "pricing_status" in html
    assert 'method: "DELETE"' in html
    assert "analysisRequestSummary" in html
    assert "status_label" in html
    assert "처리 전 대기" in html
    assert "평일 18:10 자동 실행" in html
    assert "scheduleMemberDataPoll" in html
    assert "분석 요청" in html
    assert "새 분석 요청" in html
    assert "요청 상태, 가능 횟수, 완료 리포트를 확인합니다" in html
    assert "종목명이나 6자리 코드만 입력하면 최근 기준일로 요청합니다" in html
    assert "analysis-queue-overview" in html
    assert "analysis-queue-meters" in html
    assert "margin-top: 8px;" in html
    assert "새로운 종목 분석 대기열 가동" in html
    assert "요청 종목 입력" not in html
    assert "letter-spacing: -0.02em;" in html
    assert "quota_policy" in html
    assert "member_queue_position" in html
    assert "next_action_label" in html
    assert "status_hint" in html
    assert "request_reason" in html
    assert "failure_reason" in html
    assert "failureReasonLabel" in html
    assert "실패 사유" in html
    assert "member-inline-link" in html
    assert "analysis-status-running" in html
    assert "status_counts" in html
    assert "include_latest_prices=true" in html
    assert 'id="authStatus"' in html
    assert 'id="memberSignedIn"' in html
    assert "대시보드 준비 완료" in html
    assert "setSignedInState" in html
    assert "setAuthUiState" in html
    assert "syncMemberTopNavigationState" in html
    assert "currentMemberNavKey" in html
    assert "is-member-checking" in html
    assert "로그인 세션이 만료되었습니다" in html
    assert 'aria-live="polite"' in html
    assert 'id="passwordToggle"' in html
    assert "비밀번호 표시" in html
    assert "비밀번호 숨김" in html
    assert 'href="/admin"' in html
    assert 'type="button" data-auth-action="signup"' in html
    assert "가입하려면 이메일과 비밀번호를 입력한 뒤 가입하기를 선택하세요." in html
    assert "requestedAuthMode" in html
    assert "requestedMemberTab" in html
    assert 'url.searchParams.set("tab", tab)' in html
    assert "auth-suggested" in html
    assert "shouldSkipInitialLoad" in html
    assert 'href="/member?mode=signup"' in html
    assert "redirect_to: memberRedirectUrl()" in html
    assert "consumeRedirectSession" in html
    assert "refresh_token" in html
    assert "grant_type=refresh_token" in html
    assert "localStorage" in html
    assert "storageGet" in html
    assert "storageSet" in html
    assert "storageRemove" in html
    assert "sessionSnapshot" in html
    assert "preferredSessionSnapshot" in html
    assert "migrateSessionStorage" in html
    assert "bootstrapMemberSession" in html
    assert "setSessionCheckingState" in html
    assert "세션 복구 중" in html
    assert "저장된 로그인 정보를 확인하고 있습니다" in html
    assert "!accessToken() && refreshToken()" in html
    assert "저장된 세션으로 대시보드를 불러오고 있습니다" in html
    assert 'searchParams.has("code")' in html
    assert "tradingagents.member.active_tab" in html
    assert "setupMemberTabs" in html
    assert "activateMemberTab" in html
    assert "memberHomeStatus" in html
    assert "updateMemberOverview" in html
    assert "safeMemberApi" in html
    assert "member-sublist" in html
    assert "window.history.replaceState" in html
    assert 'throw new Error("Supabase 공개 인증 설정 대기 중")' in html
    assert '"Authorization": `Bearer ${config.supabase_anon_key}`' in html
    assert '"configured":true' in html
    assert "anon-key" in html
    assert "service-role-secret" not in html
    assert '<meta name="robots" content="noindex, nofollow">' in html


def test_api_app_serves_admin_ops_summary(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "worker-token")
    repo = _repo()
    queued_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id="00000000-0000-0000-0000-000000000001",
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            requested_trade_date=date(2026, 5, 5),
            reason="refresh",
        )
    )
    failed_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id="00000000-0000-0000-0000-000000000002",
            ticker_code="000660",
            ticker_name="SK하이닉스",
            market="KOSPI",
            requested_trade_date=date(2026, 5, 6),
            reason="retry",
        )
    )
    repo.update_analysis_request_status(failed_id, status="failed")
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.complete_analysis_run(run_id)
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=5,
            status="completed",
            raw_return=0.04,
            benchmark_return=0.01,
            alpha_return=0.03,
        )
    )
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 8),
            horizon_days=20,
            actual_holding_days=3,
            status="pending",
            error="insufficient_holding_days",
        )
    )
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=60,
            status="unavailable",
            error="return_data_unavailable",
        )
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/admin/ops-summary", headers={"X-TradingAgents-Worker-Token": "worker-token"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    assert payload["analysis_requests"]["counts"]["queued"] == 1
    assert payload["analysis_requests"]["counts"]["failed"] == 1
    assert payload["analysis_requests"]["active_count"] == 1
    assert payload["analysis_requests"]["recent"]["queued"][0]["id"] == queued_id
    assert "user_id" not in payload["analysis_requests"]["recent"]["queued"][0]
    assert payload["analysis_requests"]["recent"]["failed"][0]["id"] == failed_id
    assert payload["outcomes"]["candidate_runs"][0]["id"] == run_id
    assert payload["outcomes"]["recent_completed"][0]["alpha_return"] == 0.03
    assert payload["outcomes"]["recent_pending"][0]["actual_holding_days"] == 3
    assert payload["outcomes"]["recent_pending"][0]["error"] == "insufficient_holding_days"
    assert payload["outcomes"]["recent_unavailable"][0]["error"] == "return_data_unavailable"
    assert payload["outcomes"]["pending_sample_count"] == 1
    assert payload["outcomes"]["unavailable_sample_count"] == 1
    assert payload["paper_simulations"]["candidate_sample_count"] == 0
    assert payload["paper_simulations"]["open_count"] == 0
    assert payload["paper_simulations"]["closed_count"] == 0
    assert payload["inspect_paths"]["paper_simulations"] == "/api/admin/paper-simulations/process"
    assert payload["inspect_paths"]["public_outcomes"] == "/api/analysis-outcomes"


def test_api_app_serves_member_dashboard(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_member_dashboard_page",
        lambda *args, **kwargs: "<!doctype html><html><body>member dashboard</body></html>",
    )
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/member")
    mypage_response = client.get("/mypage")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "private, no-store"
    assert "member dashboard" in response.text
    assert mypage_response.status_code == 200
    assert mypage_response.headers["cache-control"] == "private, no-store"
    assert "member dashboard" in mypage_response.text


def test_api_app_serves_feature_and_admin_pages(monkeypatch):
    def fake_feature(slug, *args, **kwargs):
        if slug == "unknown":
            raise ValueError("Unknown feature page")
        return f"<!doctype html><html><body>feature {slug}</body></html>"

    monkeypatch.setattr("tradingagents.site.api_app.render_feature_detail_page", fake_feature)
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_feature_index_page",
        lambda *args, **kwargs: "<!doctype html><html><body>feature index</body></html>",
    )
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_policy_page",
        lambda slug, *args, **kwargs: f"<!doctype html><html><body>policy {slug}</body></html>",
    )
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_admin_console_page",
        lambda *args, **kwargs: "<!doctype html><html><body>admin console</body></html>",
    )
    client = TestClient(create_app(repo=None, load_repo_from_env=False, public_cache_seconds=60))

    feature_index_response = client.get("/features")
    feature_response = client.get("/features/research")
    unknown_response = client.get("/features/unknown")
    admin_response = client.get("/admin")
    privacy_response = client.get("/privacy")
    terms_response = client.get("/terms")
    disclaimer_response = client.get("/disclaimer")

    assert feature_index_response.status_code == 200
    assert feature_index_response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "feature index" in feature_index_response.text
    assert feature_response.status_code == 200
    assert feature_response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "feature research" in feature_response.text
    assert unknown_response.status_code == 404
    assert admin_response.status_code == 200
    assert admin_response.headers["cache-control"] == "private, no-store"
    assert "admin console" in admin_response.text
    assert privacy_response.status_code == 200
    assert privacy_response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "policy privacy" in privacy_response.text
    assert terms_response.status_code == 200
    assert terms_response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "policy terms" in terms_response.text
    assert disclaimer_response.status_code == 200
    assert disclaimer_response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "policy disclaimer" in disclaimer_response.text


def test_render_feature_detail_page_rejects_unknown_slug():
    with pytest.raises(ValueError, match="Unknown feature page"):
        render_feature_detail_page("unknown")


def test_render_policy_page_rejects_unknown_slug():
    with pytest.raises(ValueError, match="Unknown policy page"):
        render_policy_page("unknown")


def test_api_app_serves_public_analysis_feed_page(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_public_analysis_feed_page",
        lambda *args, **kwargs: "<!doctype html><html><body>analysis feed</body></html>",
    )
    client = TestClient(create_app(repo=None, load_repo_from_env=False, public_cache_seconds=60))

    response = client.get("/analyses")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "analysis feed" in response.text


def test_api_app_serves_public_outcomes_page(monkeypatch):
    captured = {}

    def fake_render(**kwargs):
        captured.update(kwargs)
        return "<!doctype html><html><body>outcomes page</body></html>"

    monkeypatch.setattr("tradingagents.site.api_app.render_public_outcomes_page", fake_render)
    client = TestClient(create_app(repo=None, load_repo_from_env=False, public_cache_seconds=60))

    response = client.get("/outcomes", params={"ticker": "005930", "status": "completed", "limit": 5})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "outcomes page" in response.text
    assert captured["ticker"] == "005930"
    assert captured["status"] == "completed"
    assert captured["limit"] == 5


def test_api_app_redirects_stock_lookup_to_canonical_page():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/stocks", params={"ticker": "005930"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/stocks/005930"


def test_api_app_redirects_stock_name_lookup_to_first_match():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/stocks", params={"ticker": "삼성전자"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/stocks/005930"


def test_api_app_serves_public_stock_html_page(monkeypatch):
    captured = {}

    def fake_render(ticker, **kwargs):
        captured["ticker"] = ticker
        captured.update(kwargs)
        return "<!doctype html><html><body>stock html</body></html>"

    monkeypatch.setattr("tradingagents.site.api_app.render_public_stock_page", fake_render)
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get(
        "/stocks/005930",
        params={"chart_start": "2026-01-01", "chart_vendor": "krx", "chart_interval": "1wk"},
    )

    assert response.status_code == 200
    assert response.text.startswith("<!doctype html>")
    assert captured["ticker"] == "005930"
    assert captured["chart_start"] == "2026-01-01"
    assert captured["chart_vendor"] == "krx"
    assert captured["chart_interval"] == "1wk"


def test_seo_helpers_build_canonical_robots_and_sitemap():
    assert stock_canonical_url("005930", site_base_url="https://example.com/") == "https://example.com/stocks/005930"
    robots = build_robots_txt(site_base_url="https://example.com")
    sitemap = build_sitemap_xml(
        site_base_url="https://example.com",
        tickers=["005930", "005930", "AAPL", "000660"],
        analysis_paths=["/analyses/run-1", "/not-public/run-2"],
        generated_date="2026-05-05",
    )

    assert "Allow: /" in robots
    assert "Disallow: /api/" in robots
    assert "Disallow: /member" in robots
    assert "Disallow: /mypage" in robots
    assert "Disallow: /admin" in robots
    assert "Sitemap: https://example.com/sitemap.xml" in robots
    assert "https://example.com/analyses" in sitemap
    assert "https://example.com/outcomes" in sitemap
    assert "https://example.com/analyses/run-1" in sitemap
    assert "/not-public/run-2" not in sitemap
    assert "https://example.com/features" in sitemap
    assert "https://example.com/features/research" in sitemap
    assert "https://example.com/features/member-workspace" in sitemap
    assert "https://example.com/features/methodology" in sitemap
    assert "https://example.com/privacy" in sitemap
    assert "https://example.com/terms" in sitemap
    assert "https://example.com/disclaimer" in sitemap
    assert "https://example.com/stocks/005930" in sitemap
    assert "https://example.com/stocks/000660" in sitemap
    assert "<changefreq>hourly</changefreq>" in sitemap
    assert "<priority>0.8</priority>" in sitemap
    assert "<changefreq>monthly</changefreq>" in sitemap
    assert "<priority>0.5</priority>" in sitemap
    assert "AAPL" not in sitemap


def test_ads_txt_uses_adsense_publisher_or_custom_override(monkeypatch):
    assert (
        build_ads_txt(adsense_publisher_id="ca-pub-0000000000000000")
        == "google.com, pub-0000000000000000, DIRECT, f08c47fec0942fa0\n"
    )
    assert build_ads_txt(ads_txt="example.com, seller, DIRECT\\nnext.com, seller, RESELLER") == (
        "example.com, seller, DIRECT\nnext.com, seller, RESELLER\n"
    )
    monkeypatch.setenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID", "invalid")
    try:
        build_ads_txt()
    except ValueError as exc:
        assert "publisher ID" in str(exc)
    else:
        raise AssertionError("invalid AdSense publisher ID should fail")


def test_api_app_serves_robots_sitemap_and_ads_txt(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_SITEMAP_TICKERS", "005930,000660")
    monkeypatch.setenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID", "pub-0000000000000000")
    client = TestClient(create_app(repo=None, load_repo_from_env=False, public_cache_seconds=60))

    robots_response = client.get("/robots.txt")
    sitemap_response = client.get("/sitemap.xml")
    ads_response = client.get("/ads.txt")
    favicon_response = client.get("/favicon.ico")

    assert robots_response.status_code == 200
    assert robots_response.headers["content-type"].startswith("text/plain")
    assert robots_response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "Sitemap: http://testserver/sitemap.xml" in robots_response.text
    assert sitemap_response.status_code == 200
    assert sitemap_response.headers["content-type"].startswith("application/xml")
    assert "http://testserver/analyses" in sitemap_response.text
    assert "http://testserver/features" in sitemap_response.text
    assert "http://testserver/features/research" in sitemap_response.text
    assert "http://testserver/features/methodology" in sitemap_response.text
    assert "http://testserver/privacy" in sitemap_response.text
    assert "http://testserver/terms" in sitemap_response.text
    assert "http://testserver/disclaimer" in sitemap_response.text
    assert "http://testserver/stocks/005930" in sitemap_response.text
    assert ads_response.status_code == 200
    assert ads_response.headers["content-type"].startswith("text/plain")
    assert "google.com, pub-0000000000000000, DIRECT, f08c47fec0942fa0" in ads_response.text
    assert favicon_response.status_code == 204


def test_api_app_sitemap_prefers_public_request_host_over_vercel_branch_env(monkeypatch):
    monkeypatch.setenv(
        "TRADINGAGENTS_SITE_BASE_URL",
        "https://trading-agents-git-codex-kr-market-jeonhongjins-projects.vercel.app",
    )
    client = TestClient(
        create_app(repo=None, load_repo_from_env=False),
        base_url="https://trading-agents-seven.vercel.app",
    )

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert "https://trading-agents-seven.vercel.app/outcomes" in response.text
    assert "trading-agents-git-codex-kr-market" not in response.text


def test_api_app_sitemap_includes_stored_public_analysis_tickers(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="373220",
            ticker_name="LG에너지솔루션",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.complete_analysis_run(run_id)
    monkeypatch.setenv("TRADINGAGENTS_SITEMAP_TICKERS", "005930")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert "http://testserver/stocks/005930" in response.text
    assert "http://testserver/stocks/373220" in response.text
    assert f"http://testserver/analyses/{run_id}" in response.text

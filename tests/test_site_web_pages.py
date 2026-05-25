from datetime import date

import pytest
from fastapi.testclient import TestClient

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
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def test_render_public_stock_page_contains_chart_and_payload(monkeypatch):
    monkeypatch.setattr("tradingagents.site.web_pages.build_public_stock_payload", lambda *args, **kwargs: _payload())

    html = render_public_stock_page("005930", site_base_url="https://example.com")

    assert "<!doctype html>" in html
    assert 'class="public-home market-page stock-page"' in html
    assert '--app-font-stack: Geist, "Geist Fallback", "Noto Sans KR"' in html
    assert ".public-home {\n  color-scheme: dark;" in html
    assert "--home-muted-readable: rgba(246, 243, 232, 0.8);" in html
    assert "grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));" in html
    assert 'class="skip-link"' in html
    assert "TradingAgents Korea" in html
    assert "삼성전자" in html
    assert "priceChart" in html
    assert "chartLegend" in html
    assert "chartTooltip" in html
    assert "chart-tab" in html
    assert "stock-hero-stack" in html
    assert "stock-signal-card" in html
    assert "stock-flow-strip" in html
    assert "공개 분석 이력" in html
    assert 'href="/member#analysis-request-section"' in html
    assert "1개월" in html
    assert "KRX 14D" in html
    assert "pykrx / 2개 거래일 / auto→pykrx 사용" in html
    assert "차트 데이터 출처" in html
    assert "2026-05-05 기준" in html
    assert "요청 auto / 응답 pykrx" in html
    assert "<dd>auto→pykrx 사용</dd>" in html
    assert "공개 분석 출처" in html
    assert "public run 00000000" in html
    assert "최신 (fresh / 0일 경과)" in html
    assert "분석 신뢰도" in html
    assert "근거 충분" in html
    assert "즉시 드러난 누락 경고는 없습니다" in html
    assert "<dt>기준일</dt>" in html
    assert "<dt>평가일</dt>" in html
    assert "movingAverage" in html
    assert "상승 빨강" in html
    assert "하락 파랑" in html
    assert "한국형 투자 렌즈" in html
    assert "안전 가드레일" in html
    assert "사후 성과 검증" in html
    assert "benchmark alpha +3.00%" in html
    assert "tickerSuggestions" in html
    assert "/api/tickers/search" in html
    assert 'type="application/ld+json"' in html
    assert '"@type":"WebPage"' in html
    assert '"additionalType":"KoreanStock"' in html
    assert 'href="/member"' in html
    assert 'href="/member?mode=signup"' in html
    assert 'href="/features/research"' in html
    assert 'href="/features/methodology"' in html
    assert 'href="/mypage"' in html
    assert "top-join-link" in html
    assert "005930 또는 삼성전자" in html
    assert '<link rel="canonical" href="https://example.com/stocks/005930">' in html
    assert 'property="og:title"' in html
    assert '<meta property="og:locale" content="ko_KR">' in html
    assert '<meta name="twitter:card" content="summary">' in html
    assert '"code":"005930"' in html
    assert "71,800원" in html


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
    assert "분석 업데이트 권장: no_completed_public_analysis" in html
    assert "차트 데이터를 불러오지 못했습니다: chart vendor offline" in html


def test_api_app_serves_public_home_page(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_public_home_page",
        lambda *args, **kwargs: "<!doctype html><html><body>home analysis explorer</body></html>",
    )
    client = TestClient(create_app(repo=None, load_repo_from_env=False, public_cache_seconds=60))

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "home analysis explorer" in response.text


def test_render_public_home_page_is_usable_analysis_explorer():
    html = render_public_home_page(site_base_url="https://example.com")

    assert "TradingAgents Korea" in html
    assert "한국 주식 AI 분석" in html
    assert "최근 공개 분석" in html
    assert "한국 투자자를 위한 AI 리서치 신호망" in html
    assert "KR Market Signal Desk" in html
    assert "home-trust-panel" in html
    assert "공식·공개 데이터" in html
    assert "실거래 주문 기능 차단" in html
    assert "5D / 20D outcome" in html
    assert "KRX SIGNAL" in html
    assert "homeSignalCanvas" in html
    assert "homeSignalTicker" in html
    assert "homeSignalDecision" in html
    assert "home-live-tape" in html
    assert "prefers-reduced-motion" in html
    assert "syncTopAuthLinks" in html
    assert "로그인" in html
    assert "가입하기" in html
    assert 'href="/member?mode=signup"' in html
    assert 'href="/features/research"' in html
    assert 'href="/outcomes">성과</a>' in html
    assert 'href="/mypage"' in html
    assert 'data-auth-visible="signed-out"' in html
    assert 'data-auth-visible="signed-in" hidden' in html
    assert "Analysis Lenses" in html
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

    assert "리서치 노트를 안전하게 보관하세요" in html
    assert "회원 작업공간은 로그인 후에만 열립니다" in html
    assert "내 투자 노트" in html
    assert "memberSessionGate" in html
    assert "세션을 확인하고 있습니다" in html
    assert "member-tab-strip" in html
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in html
    assert 'role="tablist"' in html
    assert 'data-member-tab="home"' in html
    assert 'id="member-home-section"' in html
    assert "마이페이지 홈" in html
    assert "member-home-grid" in html
    assert "운영 콘솔" in html
    assert "member-admin-card" in html
    assert 'class="top-admin-link" href="/admin" data-auth-visible="signed-in" hidden>운영 콘솔</a>' in html
    assert 'href="/admin">운영 콘솔 열기</a>' in html
    assert 'data-member-jump="portfolio"' in html
    assert 'data-member-tab="portfolio"' in html
    assert 'aria-selected="true"' in html
    assert 'aria-controls="analysis-request-section"' in html
    assert 'data-member-panel="watchlist"' in html
    assert "memberOverview" in html
    assert "memberOverviewActiveRequests" in html
    assert "새 포트폴리오" in html
    assert "매수/매도 기록" in html
    assert "목표/손절 메모" in html
    assert 'href="#portfolio-section"' in html
    assert 'id="watchlist-section"' in html
    assert 'id="memberAuthLanding"' in html
    assert 'id="memberWorkspace" hidden' in html
    assert 'class="member-page is-member-checking"' in html
    assert 'data-auth-visible="signed-out"' in html
    assert 'data-auth-visible="signed-in" hidden' in html
    assert 'href="/features/research"' in html
    assert 'href="/outcomes">성과</a>' in html
    assert 'href="/mypage"' in html
    assert 'href="/stocks/005930">삼성전자</a>' not in html
    assert "/api/portfolios" in html
    assert "/api/watchlists" in html
    assert "/api/analysis-requests" in html
    assert "/api/member/dashboard?include_latest_prices=true" in html
    assert 'id="targetForm"' in html
    assert "/targets/${encodeURIComponent(tickerCode)}" in html
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
    assert "member-metric-grid" in html
    assert "member-action-item" in html
    assert "public_stock_path" in html
    assert "pricing_status" in html
    assert 'method: "DELETE"' in html
    assert "analysisRequestSummary" in html
    assert "status_label" in html
    assert "worker 처리 대기 중" in html
    assert "worker 큐 상태, 제한 사용량, 완료 리포트 연결" in html
    assert "analysis-queue-overview" in html
    assert "analysis-queue-meters" in html
    assert "quota_policy" in html
    assert "member_queue_position" in html
    assert "next_action_label" in html
    assert "status_hint" in html
    assert "member-inline-link" in html
    assert "analysis-status-running" in html
    assert "status_counts" in html
    assert "include_latest_prices=true" in html
    assert 'id="authStatus"' in html
    assert 'id="memberSignedIn"' in html
    assert "대시보드 준비 완료" in html
    assert "setSignedInState" in html
    assert "setAuthUiState" in html
    assert "is-member-checking" in html
    assert "로그인 세션이 만료되었습니다" in html
    assert 'aria-live="polite"' in html
    assert 'id="passwordToggle"' in html
    assert 'type="button" data-auth-action="signup"' in html
    assert "가입하려면 이메일과 비밀번호를 입력한 뒤 가입하기를 선택하세요." in html
    assert "requestedAuthMode" in html
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
    assert "migrateSessionStorage" in html
    assert "tradingagents.member.active_tab" in html
    assert "setupMemberTabs" in html
    assert "activateMemberTab" in html
    assert "memberHomeStatus" in html
    assert "updateMemberOverview" in html
    assert "safeMemberApi" in html
    assert "member-sublist" in html
    assert "window.history.replaceState" in html
    assert 'throw new Error("Supabase 공개 Auth 설정 대기 중")' in html
    assert '"Authorization": `Bearer ${config.supabase_anon_key}`' in html
    assert '"configured":true' in html
    assert "anon-key" in html
    assert "service-role-secret" not in html
    assert '<meta name="robots" content="noindex,nofollow">' in html


def test_render_feature_detail_pages_use_public_theme():
    html = render_feature_detail_page("research", site_base_url="https://example.com")
    member_html = render_feature_detail_page("member-workspace", site_base_url="https://example.com")
    outcomes_html = render_feature_detail_page("outcomes", site_base_url="https://example.com")
    methodology_html = render_feature_detail_page("methodology", site_base_url="https://example.com")

    assert "KRX부터 공개 리포트까지 한 화면에 연결" in html
    assert "feature-diagram" in html
    assert "Loading Boundary" in html
    assert "페이지 목적에 맞는 데이터만 요청합니다" in html
    assert "color: var(--home-readable, rgba(246, 243, 232, 0.84));" in html
    assert 'href="/features/member-workspace">회원 기능 보기</a>' in html
    assert 'href="/outcomes">성과</a>' in html
    assert '<link rel="canonical" href="https://example.com/features/research">' in html
    assert 'href="/mypage"' in html
    assert "/api/member/dashboard" not in html
    assert 'href="/features/research">리서치 구조 보기</a>' in member_html
    assert "/api/member/dashboard" not in member_html
    assert 'href="/features/methodology">신뢰 기준 보기</a>' in outcomes_html
    assert "/api/member/dashboard" not in outcomes_html
    assert "데이터 출처와 한계를 함께 공개합니다" in methodology_html
    assert "KRX / DART / Naver" in methodology_html
    assert "주문 placement는 구현하지 않습니다" in methodology_html
    assert 'href="/features/outcomes">사후 검증 보기</a>' in methodology_html
    assert '<link rel="canonical" href="https://example.com/features/methodology">' in methodology_html
    assert "/api/member/dashboard" not in methodology_html


def test_render_admin_console_page_keeps_worker_secret_client_supplied():
    html = render_admin_console_page(site_base_url="https://example.com")

    assert "관리자 콘솔" in html
    assert 'aria-current="page">운영 콘솔</a>' in html
    assert 'href="/outcomes">성과</a>' in html
    assert "admin-health-strip" in html
    assert "admin-workflow-strip" in html
    assert ".admin-health-strip small" in html
    assert "color: var(--home-muted-readable, rgba(246, 243, 232, 0.8));" in html
    assert "admin-ops-panel" in html
    assert "adminOpsSummary" in html
    assert "adminRecentPanel" in html
    assert "data-admin-ops-summary" in html
    assert "/api/admin/ops-summary" in html
    assert "권장 운영 순서" in html
    assert "readinessButton" in html
    assert "adminReadinessPanel" in html
    assert "readiness-cell" in html
    assert "renderReadinessPanel" in html
    assert "Trust header" in html
    assert "Vendor probes" in html
    assert "Site URL" in html
    assert "AdSense 승인 후 publisher id 또는 ads.txt 값을 설정하세요." in html
    assert "probe_vendors" in html
    assert "vendor_probes" in html
    assert "quota headers" in html
    assert "dry run 우선" in html
    assert '<meta name="robots" content="noindex,nofollow">' in html
    assert "adminWorkerToken" in html
    assert "X-TradingAgents-Worker-Token" in html
    assert "/api/admin/analysis-requests/process" in html
    assert "/api/admin/analysis-outcomes/process" in html
    assert '<link rel="canonical" href="https://example.com/admin">' in html
    assert "TRADINGAGENTS_WORKER_TOKEN=" not in html


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
        "tradingagents.site.api_app.render_policy_page",
        lambda slug, *args, **kwargs: f"<!doctype html><html><body>policy {slug}</body></html>",
    )
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_admin_console_page",
        lambda *args, **kwargs: "<!doctype html><html><body>admin console</body></html>",
    )
    client = TestClient(create_app(repo=None, load_repo_from_env=False, public_cache_seconds=60))

    feature_response = client.get("/features/research")
    unknown_response = client.get("/features/unknown")
    admin_response = client.get("/admin")
    privacy_response = client.get("/privacy")
    terms_response = client.get("/terms")
    disclaimer_response = client.get("/disclaimer")

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


def test_render_policy_pages_use_public_theme():
    expected = {
        "privacy": ("개인정보는 기록과 인증에 필요한 만큼만 다룹니다", "/privacy"),
        "terms": ("이 서비스는 투자 실행이 아닌 근거 확인을 돕습니다", "/terms"),
        "disclaimer": ("AI 리포트는 투자 조언이 아니라 검토 자료입니다", "/disclaimer"),
    }

    for slug, (heading, path) in expected.items():
        html = render_policy_page(slug, site_base_url="https://example.com")

        assert "<!doctype html>" in html
        assert 'class="public-home market-page policy-page"' in html
        assert heading in html
        assert "policy-card-grid" in html
        assert "policy-callout-grid" in html
        assert "READ-ONLY" in html
        assert "실거래 주문 기능을 제공하지 않는 read-only AI research platform" in html
        assert f'<link rel="canonical" href="https://example.com{path}">' in html
        assert 'href="/features/methodology"' in html
        assert 'href="/mypage"' in html
        assert "/api/member/dashboard" not in html
        assert "/api/portfolios" not in html
        assert "/api/watchlists" not in html


def test_render_policy_page_rejects_unknown_slug():
    with pytest.raises(ValueError, match="Unknown policy page"):
        render_policy_page("unknown")


def test_render_public_analysis_feed_page_lists_completed_runs():
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
            model_provider="openai",
        )
    )
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=run_id,
            role="market",
            content="market report",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Hold",
            action="hold",
            raw_decision="Rating: Hold",
        )
    )
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=5,
            status="completed",
            raw_return=0.04,
            benchmark_return=0.01,
            alpha_return=0.03,
        )
    )
    repo.complete_analysis_run(run_id)

    html = render_public_analysis_feed_page(repo=repo, site_base_url="https://example.com")

    assert "<!doctype html>" in html
    assert 'class="public-home market-page analysis-page"' in html
    assert "analysis-filter-panel" in html
    assert "analysis-pipeline-strip" in html
    assert "Stored Run" in html
    assert 'id="analysisTicker"' in html
    assert "공개 분석 목록" in html
    assert "삼성전자" in html
    assert "공개 분석 커버리지 요약" in html
    assert "Public Track Record" in html
    assert "성과 검증 스냅샷" in html
    assert "알파 우위" in html
    assert "완료 리포트" in html
    assert "KOSPI 1" in html
    assert "Hold 1" in html
    assert "평균 알파 +3.00%" in html
    assert "판단 Hold" in html
    assert "analysis-feed-card-top" in html
    assert "analysis-feed-signal-row" in html
    assert "Run " in html
    assert "1개 리포트" in html
    assert "5D 검증 / +3.00%" in html
    assert "analysis-feed-actions" in html
    assert "is-positive-alpha" in html
    assert "<dt>알파</dt><dd>+3.00%</dd>" in html
    assert "<dt>리포트</dt><dd>1개</dd>" in html
    assert f'href="/analyses/{run_id}">리포트</a>' in html
    assert 'href="/outcomes?ticker=005930">성과</a>' in html
    assert f'href="/api/analyses/{run_id}">JSON</a>' in html
    assert "/stocks/005930" in html
    assert '<link rel="canonical" href="https://example.com/analyses">' in html


def test_render_public_analysis_feed_empty_state_has_next_actions():
    html = render_public_analysis_feed_page(repo=_repo(), site_base_url="https://example.com")

    assert "공개 분석 대기" in html
    assert 'href="/stocks/005930">샘플 종목</a>' in html
    assert 'href="/features/research">리서치 흐름</a>' in html
    assert 'href="/member#analysis-request-section">분석 요청</a>' in html


def test_render_public_outcomes_page_shows_public_track_record():
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
            model_provider="openai",
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
            decision_rating="Hold",
            decision_action="hold",
        )
    )

    html = render_public_outcomes_page(repo=repo, site_base_url="https://example.com")

    assert 'class="public-home market-page outcome-page"' in html
    assert "성과 검증" in html
    assert "대시보드" in html
    assert "Outcome Track Record" in html
    assert "outcome-filter-panel" in html
    assert "outcome-cadence-strip" in html
    assert "outcome-feed-card" in html
    assert "삼성전자" in html
    assert "평균 알파" in html
    assert "+3.00%" in html
    assert "알파 우위" in html
    assert '<dt>Alpha</dt><dd>+3.00%</dd>' in html
    assert f'href="/analyses/{run_id}">리포트</a>' in html
    assert 'href="/stocks/005930">종목</a>' in html
    assert "/api/analysis-outcomes" in html
    assert '<link rel="canonical" href="https://example.com/outcomes">' in html
    assert 'id="outcomes-payload"' in html
    assert "syncTopAuthLinks" in html
    assert "/api/member/dashboard" not in html
    assert "/api/portfolios" not in html
    assert "/api/watchlists" not in html


def test_render_public_outcomes_page_empty_state_has_next_actions():
    html = render_public_outcomes_page(repo=_repo(), site_base_url="https://example.com")

    assert "성과 검증 대기" in html
    assert "5D/20D 대기" in html
    assert "알파 대기" in html
    assert 'href="/stocks/005930">샘플 종목</a>' in html
    assert 'href="/analyses">분석 목록</a>' in html
    assert 'href="/features/outcomes">검증 방식</a>' in html
    assert 'href="/member#analysis-request-section">분석 요청</a>' in html


def test_render_public_analysis_detail_page_shows_report_context():
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
            model_provider="openai",
            deep_model="deep",
            quick_model="quick",
            metadata={
                "source": "trading_graph",
                "currency": "KRW",
                "output_language": "ko-KR",
                "selected_analysts": ["market", "news", "fundamentals"],
            },
        )
    )
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=run_id,
            role="market",
            title="Market report",
            content="market report body",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Hold",
            action="hold",
            rationale="현금흐름과 수급을 추가 확인합니다.",
            raw_decision="Rating: Hold",
        )
    )
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=5,
            status="completed",
            raw_return=0.04,
            benchmark_return=0.01,
            alpha_return=0.03,
        )
    )
    repo.complete_analysis_run(run_id)

    html = render_public_analysis_detail_page(run_id, repo=repo, site_base_url="https://example.com")

    assert 'class="public-home market-page analysis-page analysis-detail-page"' in html
    assert "삼성전자 공개 분석 리포트" in html
    assert "analysis-detail-map" in html
    assert "리포트 읽기 순서" in html
    assert 'href="#analysis-reports"' in html
    assert 'id="analysis-decision"' in html
    assert 'id="analysis-outcomes"' in html
    assert "데이터 기준일" in html
    assert "데이터/vendor" in html
    assert "KRX/DART/Naver" in html
    assert "Agent coverage" in html
    assert "market, news, fundamentals" in html
    assert "source trading_graph / currency KRW / language ko-KR" in html
    assert "휴장, vendor 장애, 누락 데이터, 모델 오류 가능성" in html
    assert "Decision checkpoint" in html
    assert "Market report" in html
    assert "근거 점검" in html
    assert "Ticker anchor" in html
    assert "Outcome Track Record" in html
    assert f'href="/api/analyses/{run_id}">JSON</a>' in html
    assert f'<link rel="canonical" href="https://example.com/analyses/{run_id}">' in html
    assert 'id="analysis-detail-payload"' in html
    assert "syncTopAuthLinks" in html
    assert "/api/portfolios" not in html
    assert "/api/watchlists" not in html


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

    response = client.get("/stocks/005930", params={"chart_start": "2026-01-01", "chart_vendor": "krx"})

    assert response.status_code == 200
    assert response.text.startswith("<!doctype html>")
    assert captured["ticker"] == "005930"
    assert captured["chart_start"] == "2026-01-01"
    assert captured["chart_vendor"] == "krx"


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

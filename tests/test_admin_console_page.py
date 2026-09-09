from tradingagents.site.admin_console_page import render_admin_console_page
from tradingagents.site.web_pages import ADMIN_PAGE_JS

# Every id / data-attribute that ADMIN_PAGE_JS binds via getElementById / querySelector.
ADMIN_JS_IDS = (
    "adminTokenForm",
    "adminWorkerToken",
    "adminTokenState",
    "adminReadinessOutput",
    "adminReadinessPanel",
    "adminOpsOutput",
    "adminOpsSummary",
    "adminRecentPanel",
    "adminRequestsOutput",
    "adminOutcomesOutput",
    "adminPaperSimulationOutput",
    "adminRequestsPanel",
    "adminOutcomesPanel",
    "adminPaperSimulationPanel",
    "adminRequestLimit",
    "adminOutcomeLimit",
    "adminPaperSimulationLimit",
    "adminRequestLimitHint",
    "adminOutcomeLimitHint",
    "adminPaperSimulationLimitHint",
    "adminProbeKrx",
    "adminProbeVendors",
)
ADMIN_JS_ATTRIBUTES = (
    "data-admin-token-clear",
    "data-admin-readiness",
    "data-admin-ops-summary",
    'data-admin-action="requests-dry-run"',
    'data-admin-action="requests-process"',
    'data-admin-action="outcomes-dry-run"',
    'data-admin-action="outcomes-process"',
    'data-admin-action="paper-dry-run"',
    'data-admin-action="paper-process"',
)
ADMIN_JS_CELL_CLASSES = ("ops-cell", "readiness-cell", "action-cell", "admin-recent-list", "admin-token-ready")


def test_admin_console_uses_shell_noindex_and_keeps_every_js_binding(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_WORKER_MAX_REQUESTS", "1")
    monkeypatch.setenv("TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS", "20")
    monkeypatch.setenv("TRADINGAGENTS_PAPER_SIMULATION_WORKER_MAX_RUNS", "20")

    html = render_admin_console_page(site_base_url="https://example.com")

    assert '<body class="ds ' in html
    assert "<title>운영 콘솔 | TradingAgents Korea</title>" in html
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert '<link rel="canonical" href="https://example.com/admin">' in html
    assert 'role="search"' not in html  # search=False
    assert 'aria-current="page">' not in html  # active=None (CSS selector text still mentions it)

    for element_id in ADMIN_JS_IDS:
        assert f'id="{element_id}"' in html, element_id
    for attribute in ADMIN_JS_ATTRIBUTES:
        assert attribute in html, attribute
    for css_class in ADMIN_JS_CELL_CLASSES:
        assert css_class in html, css_class

    assert ADMIN_PAGE_JS in html
    assert "<script>" + ADMIN_PAGE_JS + "</script>" in html
    assert "X-TradingAgents-Worker-Token" in html
    assert "/api/admin/ops-summary" in html
    assert "/api/admin/analysis-requests/process" in html
    assert "/api/admin/analysis-outcomes/process" in html
    assert "/api/admin/paper-simulations/process" in html


def test_admin_console_token_panel_and_member_link():
    html = render_admin_console_page()

    assert '<form class="card" id="adminTokenForm">' in html
    assert 'id="adminWorkerToken" name="worker_token" type="password" autocomplete="off"' in html
    assert "운영 토큰" in html
    assert "DASHBOARD_ADMIN_TOKEN" in html
    assert "OPERATOR_ACCESS_CODE" in html
    assert "운영 버튼은 토큰 입력 후 활성화됩니다" in html
    assert "관리자 계정으로 로그인한 경우 토큰 없이도 실행할 수 있습니다." in html
    assert 'href="/admin/members"' in html
    assert "회원 관리" in html
    assert 'href="/harness"' in html
    assert "선별 기록" in html
    assert "TRADINGAGENTS_WORKER_TOKEN=" not in html
    assert "service-role" not in html
    assert '<link rel="canonical" href="/admin">' in html


def test_admin_console_limits_follow_worker_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_WORKER_MAX_REQUESTS", "3")
    monkeypatch.setenv("TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS", "4")
    monkeypatch.setenv("TRADINGAGENTS_PAPER_SIMULATION_WORKER_MAX_RUNS", "50")

    html = render_admin_console_page()

    assert 'id="adminRequestLimit" type="number" min="1" max="3" value="3"' in html
    assert 'id="adminOutcomeLimit" type="number" min="1" max="4" value="4"' in html
    assert 'id="adminPaperSimulationLimit" type="number" min="1" max="50" value="10"' in html
    assert "현재 최대 3건" in html
    assert "현재 최대 4건" in html
    assert "현재 최대 50건" in html


def test_admin_console_plain_language_labels():
    html = render_admin_console_page()
    body = html.split("<main", 1)[1].split("</main>", 1)[0]

    assert "대상 미리보기" in body
    assert "대기열 처리 시작" in body
    assert "성과 검증 저장" in body
    assert "모의 매매 기록 저장" in body
    assert "권장 운영 순서" in body
    assert "실행 기록 확인" in body
    assert "실제 주문은 없습니다." in body
    for jargon in ("하네스", "유니버스", "깔때기", "감사 원장", "판정관", "리스크 패널", "내 공간", "사후 결과", "가상 매수"):
        assert jargon not in body, jargon

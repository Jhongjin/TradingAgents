import re

from tradingagents.site.stock_page import render_public_stock_page

CHART_IDS = (
    "stock-payload",
    "priceChart",
    "priceChartCanvas",
    "chartDrawingLayer",
    "chartLegend",
    "chartFallback",
    "chartTooltip",
    "chartToolState",
    "simulationPreview",
    "ticker",
    "tickerSuggestions",
)
CHART_HOOKS = (
    'class="ticker-search"',
    "[data-ticker-lookup]",
    'data-chart-indicator="ma5"',
    'data-chart-indicator="volume"',
    'data-chart-setting="maFast"',
    'data-chart-setting="bollingerDeviation"',
    "data-chart-apply-settings",
    "data-chart-draw-trend",
    "data-chart-clear-trends",
    "data-chart-fit",
    'data-simulation-url="/api/simulations/preview/005930"',
    "chart-interval-tabs",
    'class="chart-tab',
)
LEGACY_COLORS = (
    "#dcfc13",
    "#d7ff3f",
    "#10130f",
    "#111711",
    "#f6f3e8",
    "#146b63",
    "rgba(246, 243, 232",
    "rgba(246,243,232",
    "rgba(215, 255, 63",
    "--home-",
    "--app-font-stack",
    "--surface-strong",
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


def _page_css(html: str) -> str:
    match = re.search(r"<style>(.*?)</style>", html, flags=re.S)
    assert match, "shell must emit a single <style> block"
    return match.group(1)


def _render(monkeypatch, payload=None) -> str:
    monkeypatch.setattr(
        "tradingagents.site.web_pages.build_public_stock_payload",
        lambda *args, **kwargs: payload or _payload(),
    )
    return render_public_stock_page("005930", site_base_url="https://example.com")


def test_stock_page_uses_design_system_shell(monkeypatch):
    html = _render(monkeypatch)

    assert html.startswith("<!doctype html>")
    assert 'class="ds stock-page"' in html
    assert 'class="topbar"' in html
    assert "data-theme-trigger" in html
    assert 'class="skip-link"' in html
    assert "<footer class=\"site\">" in html
    # the page carries its own ticker search, so the shell search is off
    assert "top-search-form" not in html
    # legacy chrome must be gone
    assert "public-home market-page" not in html
    assert 'class="top-links"' not in html
    assert "brand-mark" not in html


def test_stock_page_keeps_every_chart_engine_hook(monkeypatch):
    html = _render(monkeypatch)

    for element_id in CHART_IDS:
        assert f'id="{element_id}"' in html, element_id
    for hook in CHART_HOOKS:
        assert hook in html, hook
    assert 'data-chart-engine="tradingview-lightweight"' in html
    assert "lightweight-charts@5.2.0" in html
    assert "bootStockPageChart" in html
    assert "loadSimulationPreview" in html
    assert "setupTrendDrawing" in html
    assert "/api/tickers/search" in html
    # the payload script is emitted before PAGE_JS runs
    assert html.index('id="stock-payload"') < html.index("bootStockPageChart")
    assert html.index("lightweight-charts@5.2.0") < html.index("bootStockPageChart")
    assert '"code":"005930"' in html


def test_stock_page_seo_and_copy(monkeypatch):
    html = _render(monkeypatch)

    assert '<link rel="canonical" href="https://example.com/stocks/005930">' in html
    assert '<script type="application/ld+json">' in html
    assert '"@type":"WebPage"' in html
    assert '"additionalType":"KoreanStock"' in html
    assert '"url":"https://example.com/stocks/005930"' in html
    assert "<title>삼성전자 (005930) | TradingAgents Korea</title>" in html
    assert 'property="og:title"' in html
    assert "삼성전자(005930)의 최근 주가, AI 리포트, 모의매매 검증 결과를 보여줍니다." in html
    assert "71,800원" in html
    assert "시장 대비 +3.00%" in html
    assert "투자 체크포인트" in html
    assert "AI 분석은 정보 제공용이며 투자 조언이 아닙니다" in html
    assert "AI analysis is for informational purposes" not in html
    assert 'href="/analyses?ticker=005930">' in html
    assert 'href="/member?mode=signup&amp;tab=analysis#analysis-request-section"' in html
    assert 'href="/analyses/00000000-0000-0000-0000-000000000010">전체 리포트 읽기</a>' in html
    assert 'id="stock-chart-section"' in html
    assert 'id="stock-analysis-section"' in html
    assert 'id="stock-reports-section"' in html
    assert 'id="stock-simulation-section"' in html
    assert 'id="analysis-outcomes"' in html
    assert "모의 매매 기록" in html
    assert "가상 매수·매도" not in html.split("<script")[0]


def test_stock_page_css_uses_design_tokens_only(monkeypatch):
    html = _render(monkeypatch)
    css = _page_css(html)

    for legacy in LEGACY_COLORS:
        assert legacy not in css, legacy
    assert ".ds .chart-wrap" in css
    assert ".ds .chart-tab.is-active" in css
    assert ".ds .stock-signal-card" in css
    assert ".ds .report-card" in css
    assert ".ds .outcome-card" in css
    assert ".ds .data-source-strip" in css
    assert ".ds .analysis-confidence-panel" in css
    assert "var(--panel)" in css and "var(--line)" in css and "var(--accent)" in css
    # the dark chart stage is derived from the design-system dark tokens
    assert "--chart-bg: #151c26" in css


def test_stock_page_limits_intraday_period_tabs(monkeypatch):
    payload = _payload()
    payload["chart"]["interval"] = "1m"
    payload["chart"]["vendor"] = "yfinance"
    payload["chart"]["requested_vendor"] = "yfinance"
    payload["chart"]["resolved_vendor"] = "yfinance"
    payload["chart"]["data_source_label"] = "Yahoo Finance"

    html = _render(monkeypatch, payload)

    assert "Yahoo 시간·분봉" in html
    assert "1분봉" in html
    assert "6개월" not in html
    assert "3개월" not in html


def test_stock_page_surfaces_missing_data_warnings(monkeypatch):
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

    html = _render(monkeypatch, payload)

    assert "데이터 부족" in html
    assert "공개 분석이 아직 저장되지 않았습니다." in html
    assert "분석 업데이트 권장: 완료된 공개 리포트 없음" in html
    assert "차트 데이터를 불러오지 못했습니다: chart vendor offline" in html
    assert 'href="/analyses?ticker=005930">이 종목 리포트</a>' in html
    assert 'href="/member?mode=signup&amp;tab=analysis#analysis-request-section">분석 요청</a>' in html
    for element_id in CHART_IDS:
        assert f'id="{element_id}"' in html, element_id

from datetime import date

from fastapi.testclient import TestClient

from tradingagents.storage import AnalysisRunInput, StorageRepository, create_storage_engine
from tradingagents.site.api_app import create_app
from tradingagents.site.seo import build_ads_txt, build_robots_txt, build_sitemap_xml, stock_canonical_url
from tradingagents.site.web_pages import render_public_analysis_feed_page, render_public_stock_page


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
            "run": {"trade_date": "2026-05-05"},
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
        },
        "analysis_refresh": {"recommended": False, "reason": "fresh"},
        "chart": {
            "status": "available",
            "ticker_code": "005930",
            "ticker_name": "삼성전자",
            "market": "KOSPI",
            "currency": "KRW",
            "vendor": "pykrx",
            "points": [
                {"date": "2026-05-04", "open": 70000.0, "high": 71000.0, "low": 69000.0, "close": 70500.0, "volume": 1000},
                {"date": "2026-05-05", "open": 70600.0, "high": 72000.0, "low": 70200.0, "close": 71800.0, "volume": 2000},
            ],
        },
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
    assert "TradingAgents Korea" in html
    assert "삼성전자" in html
    assert "priceChart" in html
    assert "tickerSuggestions" in html
    assert "/api/tickers/search" in html
    assert 'type="application/ld+json"' in html
    assert '"@type":"WebPage"' in html
    assert '"additionalType":"KoreanStock"' in html
    assert "005930 또는 삼성전자" in html
    assert '<link rel="canonical" href="https://example.com/stocks/005930">' in html
    assert 'property="og:title"' in html
    assert '"code":"005930"' in html
    assert "71,800원" in html


def test_api_app_serves_public_home_page(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_public_stock_page",
        lambda *args, **kwargs: "<!doctype html><html><body>005930 public page</body></html>",
    )
    client = TestClient(create_app(repo=None, load_repo_from_env=False, public_cache_seconds=60))

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "005930 public page" in response.text


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
    repo.complete_analysis_run(run_id)

    html = render_public_analysis_feed_page(repo=repo, site_base_url="https://example.com")

    assert "<!doctype html>" in html
    assert "공개 분석 목록" in html
    assert "삼성전자" in html
    assert "/stocks/005930" in html
    assert '<link rel="canonical" href="https://example.com/analyses">' in html


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

    response = client.get("/stocks/005930", params={"chart_start": "2026-01-01"})

    assert response.status_code == 200
    assert response.text.startswith("<!doctype html>")
    assert captured["ticker"] == "005930"
    assert captured["chart_start"] == "2026-01-01"


def test_seo_helpers_build_canonical_robots_and_sitemap():
    assert stock_canonical_url("005930", site_base_url="https://example.com/") == "https://example.com/stocks/005930"
    robots = build_robots_txt(site_base_url="https://example.com")
    sitemap = build_sitemap_xml(
        site_base_url="https://example.com",
        tickers=["005930", "005930", "AAPL", "000660"],
        generated_date="2026-05-05",
    )

    assert "Allow: /" in robots
    assert "Sitemap: https://example.com/sitemap.xml" in robots
    assert "https://example.com/stocks/005930" in sitemap
    assert "https://example.com/stocks/000660" in sitemap
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

    assert robots_response.status_code == 200
    assert robots_response.headers["content-type"].startswith("text/plain")
    assert robots_response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "Sitemap: http://testserver/sitemap.xml" in robots_response.text
    assert sitemap_response.status_code == 200
    assert sitemap_response.headers["content-type"].startswith("application/xml")
    assert "http://testserver/stocks/005930" in sitemap_response.text
    assert ads_response.status_code == 200
    assert ads_response.headers["content-type"].startswith("text/plain")
    assert "google.com, pub-0000000000000000, DIRECT, f08c47fec0942fa0" in ads_response.text


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

import io
import json
from datetime import date

from fastapi.testclient import TestClient

from tradingagents.harness import pipeline as harness_pipeline
from tradingagents.site import create_app, seo
from tradingagents.site.brand import favicon_ico, favicon_svg, icon_png, logo_svg
from tradingagents.site.og_image import render_og_image
from tradingagents.site.ticker_history_page import build_ticker_history_model, render_ticker_history_page
from tradingagents.storage import HarnessDecisionInput, HarnessOutcomeInput, HarnessRunInput, StorageRepository, create_storage_engine

TICKER = "000660"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _seed(repo: StorageRepository) -> str:
    run_id = repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 9, 8), broker="kis", dry_run=False, confirmer="debate", universe_size=350, candidate_count=2, order_count=1))
    decision_id = repo.add_harness_decision(
        HarnessDecisionInput(harness_run_id=run_id, as_of_date=date(2026, 9, 8), ticker_code=TICKER, stage="ordered", ticker_name="SK하이닉스", market="KOSPI", screener_rank=1, composite_score=1.9, forecast_expected_return=0.041, forecast_probability_up=0.62, confirmation_rating="Overweight", confirmation_confidence=0.86, quantity=3, order_status="accepted", reasons=["모의투자 매수주문이 완료되었습니다."])
    )
    repo.add_harness_decision(HarnessDecisionInput(harness_run_id=run_id, as_of_date=date(2026, 9, 8), ticker_code="005930", stage="forecast_rejected", ticker_name="삼성전자", market="KOSPI", screener_rank=2, reasons=["probability below threshold"]))
    repo.upsert_harness_outcome(HarnessOutcomeInput(harness_decision_id=decision_id, harness_run_id=run_id, ticker_code=TICKER, entry_date=date(2026, 9, 8), evaluated_at=date(2026, 9, 8), horizon_days=5, status="pending"))
    return run_id


def test_brand_assets_render():
    from PIL import Image

    svg = favicon_svg()
    assert svg.startswith("<?xml") and "<polyline" in svg and 'rx="16"' in svg
    assert 'viewBox="0 0 64 64"' in logo_svg(28)
    png = Image.open(io.BytesIO(icon_png(64)))
    assert png.size == (64, 64) and png.mode == "RGBA"
    assert png.getpixel((2, 2))[3] == 0  # rounded corner is transparent
    assert png.getpixel((32, 32))[:3] != (0, 0, 0)
    ico = Image.open(io.BytesIO(favicon_ico()))
    assert ico.format == "ICO"


def test_og_image_renders_korean_title_and_stats():
    from PIL import Image

    png = render_og_image("9월 8일 종목 선별: 후보 20개 중 3개 통과", "규칙 점수 → AI 토론 → 모의 주문", "선별 기록", (("대상 종목", "350"), ("모의 주문", "3")), "example.com")
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630) and img.format == "PNG"
    assert render_og_image("같은 제목", "", "k", (), "example.com") is render_og_image("같은 제목", "", "k", (), "example.com")  # memoised


def test_ticker_history_model_and_page():
    repo = _repo()
    run_id = _seed(repo)
    model = build_ticker_history_model(repo, ticker=TICKER, site_base_url="https://example.com")
    assert model["name"] == "SK하이닉스" and len(model["items"]) == 1 and len(model["passed"]) == 1
    assert model["answer"].startswith("SK하이닉스(000660)는 최근 1회 선별에서 1회 통과했습니다. 마지막 판정은 2026-09-08 비중 확대")

    html = render_ticker_history_page(TICKER, repo=repo, site_base_url="https://example.com")
    assert "<title>SK하이닉스(000660) AI 판정 이력 | TradingAgents Korea</title>" in html
    assert 'href="https://example.com/stocks/000660/history"' in html
    assert f'href="/harness/{run_id}"' in html and "모의 주문" in html and "검증 대기" in html
    assert '"FAQPage"' in html and '"BreadcrumbList"' in html and '<meta property="og:type" content="article">' in html
    assert 'content="https://example.com/og/stocks/000660.png"' in html

    empty = render_ticker_history_page("035420", repo=repo, site_base_url="https://example.com")
    assert "아직 종목 선별에 오른 기록이 없습니다" in empty


def test_routes_serve_icons_og_history_and_manifest(monkeypatch):
    repo = _repo()
    _seed(repo)
    monkeypatch.setenv("TRADINGAGENTS_SITE_BASE_URL", "https://example.com")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    assert client.get("/favicon.ico").headers["content-type"] == "image/x-icon"
    assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg+xml")
    assert client.get("/apple-touch-icon.png").headers["content-type"] == "image/png"
    assert client.get("/icon-192.png").status_code == 200 and client.get("/icon-77.png").status_code == 404
    manifest = client.get("/site.webmanifest").json()
    assert manifest["theme_color"] == "#0f766e" and manifest["icons"][1]["sizes"] == "512x512"

    for path in ("/og/default.png", "/og/home.png", "/og/harness.png", f"/og/stocks/{TICKER}.png", "/og/pricing.png"):
        response = client.get(path)
        assert response.status_code == 200 and response.headers["content-type"] == "image/png", path
        assert response.headers["cache-control"].startswith("public"), path
    assert client.get("/og/nope.png").status_code == 404

    home = client.get("/").text
    assert '<meta property="og:image" content="https://example.com/og/home.png">' in home
    assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg">' in home
    assert "<svg" in home.split('class="brand"', 1)[1][:600]  # logo mark in the header

    history = client.get(f"/stocks/{TICKER}/history")
    assert history.status_code == 200 and "AI 판정 이력" in history.text
    assert history.headers["cache-control"].startswith("public")
    assert client.get("/stocks/AAPL/history").status_code == 404

    sitemap = client.get("/sitemap.xml").text
    assert f"https://example.com/stocks/{TICKER}/history</loc>" in sitemap


def test_indexnow_submit_and_key_file(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_INDEXNOW_KEY", "abcdef1234567890")
    calls = []

    def transport(url, payload):
        calls.append((url, payload))
        return 202

    result = seo.submit_indexnow(["/harness/x", "/harness/x", "/"], site_base_url="https://example.com", transport=transport)
    assert result["status"] == "sent" and result["urls"] == ["https://example.com/harness/x", "https://example.com/"]
    assert calls[0][1]["host"] == "example.com" and calls[0][1]["keyLocation"] == "https://example.com/abcdef1234567890.txt"

    assert seo.submit_indexnow(["/"], site_base_url=None, transport=transport)["status"] == "skipped"
    assert seo.submit_indexnow(["/"], site_base_url="https://example.com", transport=lambda u, p: 500)["status"] == "failed"

    def boom(url, payload):
        raise RuntimeError("down")

    assert seo.submit_indexnow(["/"], site_base_url="https://example.com", transport=boom)["status"] == "failed"

    client = TestClient(create_app(repo=None, load_repo_from_env=False))
    assert client.get("/indexnow/abcdef1234567890.txt").text == "abcdef1234567890"
    assert client.get("/abcdef1234567890.txt").text == "abcdef1234567890"  # root location IndexNow validates against
    assert client.get("/robots.txt").status_code == 200 and client.get("/other12345.txt").status_code == 404
    assert client.get("/indexnow/other.txt").status_code == 404

    monkeypatch.setenv("OPERATOR_ACCESS_CODE", "op-token")
    monkeypatch.setattr(seo, "submit_indexnow", lambda paths, site_base_url=None, **kw: {"status": "sent", "urls": list(paths)})
    monkeypatch.setattr("tradingagents.site.api_app.submit_indexnow", lambda paths, site_base_url=None, **kw: {"status": "sent", "urls": list(paths)})
    ping = client.post("/api/admin/seo/indexnow", json={"paths": ["/harness"]}, headers={"X-TradingAgents-Worker-Token": "op-token"})
    assert ping.status_code == 200 and ping.json()["status"] == "sent"
    assert client.post("/api/admin/seo/indexnow", json={"paths": ["/harness"]}).status_code == 401


def test_pipeline_pings_indexnow_after_persist(monkeypatch):
    seen = {}

    def fake_submit(paths, **kwargs):
        seen["paths"] = list(paths)
        return {"status": "sent", "urls": list(paths)}

    monkeypatch.setattr(seo, "submit_indexnow", fake_submit)
    notes: list[str] = []

    class Decision:
        ticker_code = TICKER

    harness_pipeline._ping_search_engines("run-1", [Decision(), {"ticker_code": "005930"}], notes)
    assert seen["paths"] == ["/", "/harness", "/harness/run-1", f"/stocks/{TICKER}/history", "/stocks/005930/history"]
    assert notes == ["indexnow sent: 5 urls"]

    def boom(paths, **kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr(seo, "submit_indexnow", boom)
    harness_pipeline._ping_search_engines("run-2", [], notes)
    assert notes[-1] == "indexnow error: RuntimeError"

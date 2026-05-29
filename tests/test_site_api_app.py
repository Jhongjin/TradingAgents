from datetime import date, datetime, time as datetime_time
from decimal import Decimal
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi.testclient import TestClient

from tradingagents.dataflows.chart_data import ChartSeries, LatestPrice, OhlcvPoint
from tradingagents.dataflows import pykrx_vendor
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.site.api_app import create_app
from tradingagents.storage import (
    AgentReportInput,
    AnalysisOutcomeInput,
    AnalysisRequestInput,
    AnalysisRunInput,
    ManualTradeInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)


USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"


class BrokenPublicAnalysisRepo:
    def check_connection(self):
        return None

    def check_schema(self):
        raise RuntimeError("secret database detail")

    def list_public_analysis_runs(self, *args, **kwargs):
        raise RuntimeError("secret database detail")

    def list_analysis_outcomes(self, *args, **kwargs):
        raise RuntimeError("secret database detail")

    def latest_public_analysis_bundle(self, *args, **kwargs):
        raise RuntimeError("secret database detail")


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def _seed_public_analysis(repo: StorageRepository) -> None:
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
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
    repo.complete_analysis_run(run_id)


def _korea_timestamp(day: date) -> int:
    return int(datetime.combine(day, datetime_time.min, tzinfo=ZoneInfo("Asia/Seoul")).timestamp())


def _seed_public_buy_analysis(repo: StorageRepository) -> str:
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
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
            rating="Buy",
            action="buy",
            raw_decision="Rating: Buy",
        )
    )
    repo.complete_analysis_run(run_id)
    return run_id


def test_api_app_serves_public_stock_payload(monkeypatch):
    repo = _repo()
    _seed_public_analysis(repo)
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": [70000],
            "고가": [71000],
            "저가": [69000],
            "종가": [70500],
            "거래량": [123456],
        },
        index=[pd.Timestamp("2026-05-05")],
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)

    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    response = client.get(
        "/api/stocks/005930",
        params={
            "chart_start": "2026-05-05",
            "chart_end": "2026-05-05",
            "as_of_date": "2026-05-05",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"]["code"] == "005930"
    assert body["analysis"]["status"] == "available"
    assert body["chart"]["points"][0]["close"] == 70500.0


def test_api_app_stock_lookup_redirects_company_name_to_code():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/stocks", params={"ticker": "로켓헬스케어"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/stocks/376900"


def test_api_app_public_stock_api_resolves_company_name():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get(
        "/api/stocks/로켓헬스케어",
        params={"include_chart": "false", "include_analysis": "false"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"]["code"] == "376900"
    assert body["ticker"]["name"] == "로킷헬스케어"


def test_api_app_serves_tradingview_datafeed(monkeypatch):
    captured: dict[str, str] = {}

    def fake_chart_series(symbol, start_date, end_date, *, vendor, interval):
        captured.update(
            {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "vendor": vendor,
                "interval": interval,
            }
        )
        return ChartSeries(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            currency="KRW",
            vendor="pykrx",
            interval="1d",
            points=[
                OhlcvPoint("2026-05-04", open=70_000, high=71_000, low=69_000, close=70_500, volume=1000),
                OhlcvPoint("2026-05-05", open=71_000, high=72_000, low=70_000, close=71_500, volume=1200),
            ],
        )

    monkeypatch.setattr("tradingagents.site.tradingview_datafeed_api.get_ohlcv_chart_series", fake_chart_series)

    client = TestClient(create_app(repo=None, load_repo_from_env=False))
    config = client.get("/api/tradingview/config")
    search = client.get("/api/tradingview/search", params={"query": "삼성", "limit": 5})
    symbol = client.get("/api/tradingview/symbols", params={"symbol": "KRX:005930"})
    history = client.get(
        "/api/tradingview/history",
        params={
            "symbol": "KOSPI:005930",
            "resolution": "D",
            "from": _korea_timestamp(date(2026, 5, 4)),
            "to": _korea_timestamp(date(2026, 5, 5)),
        },
    )
    tv_time = client.get("/api/tradingview/time")

    assert config.status_code == 200
    assert {"1", "5", "15", "30", "60", "D", "W", "M"}.issubset(
        set(config.json()["supported_resolutions"])
    )
    assert search.status_code == 200
    assert search.json()[0]["symbol"] == "005930"
    assert search.json()[0]["description"] == "삼성전자"
    assert symbol.status_code == 200
    assert symbol.json()["ticker"] == "005930"
    assert symbol.json()["description"] == "삼성전자"
    assert symbol.json()["has_intraday"] is True
    assert symbol.json()["intraday_multipliers"] == ["1", "5", "15", "30", "60"]
    assert history.status_code == 200
    assert history.json()["s"] == "ok"
    assert history.json()["c"] == [70500.0, 71500.0]
    assert history.json()["v"] == [1000, 1200]
    assert captured == {
        "symbol": "005930",
        "start_date": "2026-05-04",
        "end_date": "2026-05-05",
        "vendor": "pykrx",
        "interval": "1d",
    }
    assert tv_time.status_code == 200
    assert tv_time.headers["cache-control"] == "no-store"
    assert tv_time.text.strip().isdigit()


def test_api_app_serves_charting_library_placeholder_when_asset_missing():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/charting_library/charting_library.js")
    missing_asset = client.get("/charting_library/static/bundles/missing.css")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.text == ""
    assert missing_asset.status_code == 404


def test_api_app_serves_public_simulation_preview(monkeypatch):
    repo = _repo()
    run_id = _seed_public_buy_analysis(repo)
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": [70_000, 73_000, 76_000],
            "고가": [71_000, 74_000, 77_000],
            "저가": [69_000, 72_000, 75_000],
            "종가": [70_000, 73_000, 76_000],
            "거래량": [1000, 1100, 1200],
        },
        index=[pd.Timestamp("2026-05-05"), pd.Timestamp("2026-05-06"), pd.Timestamp("2026-05-07")],
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)

    client = TestClient(create_app(repo=repo, load_repo_from_env=False, public_cache_seconds=60))
    response = client.get(
        "/api/simulations/preview/005930",
        params={"as_of_date": "2026-05-07", "slippage_bps": 0},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    body = response.json()
    assert body["status"] == "available"
    assert body["execution_boundary"] == "simulation_only_no_orders"
    assert body["analysis_run_id"] == run_id
    assert body["decision"]["rating"] == "Buy"
    assert body["simulation"]["status"] == "closed"
    assert body["simulation"]["exit_reason"] == "take_profit"
    assert body["simulation"]["events"][0]["side"] == "buy"
    assert body["simulation"]["events"][1]["side"] == "sell"
    assert "실제 주문" in body["notices"][0]


def test_api_app_simulation_preview_degrades_without_analysis():
    client = TestClient(create_app(repo=_repo(), load_repo_from_env=False))

    response = client.get("/api/simulations/preview/005930")

    assert response.status_code == 200
    assert response.json()["status"] == "no_completed_analysis"


def test_api_app_serves_member_paper_simulations(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            user_id=USER_ID,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Buy",
            action="buy",
        )
    )
    repo.complete_analysis_run(run_id)
    fake_stock = MagicMock()
    fake_stock.get_market_ohlcv_by_date.return_value = pd.DataFrame(
        {
            "시가": [70_000, 73_000, 76_000],
            "고가": [71_000, 74_000, 77_000],
            "저가": [69_000, 72_000, 75_000],
            "종가": [70_000, 73_000, 76_000],
            "거래량": [1000, 1100, 1200],
        },
        index=[pd.Timestamp("2026-05-05"), pd.Timestamp("2026-05-06"), pd.Timestamp("2026-05-07")],
    )
    monkeypatch.setattr(pykrx_vendor, "_get_pykrx_stock_module", lambda: fake_stock)
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    worker_response = client.post(
        "/api/admin/paper-simulations/process",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 1, "as_of_date": "2026-05-07"},
    )
    member_response = client.get(
        "/api/member/paper-simulations",
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert worker_response.status_code == 200
    assert worker_response.json()["execution_boundary"] == "simulation_only_no_orders"
    assert worker_response.json()["summary"]["created_count"] == 1
    assert member_response.status_code == 200
    assert member_response.headers["cache-control"] == "private, no-store"
    body = member_response.json()
    assert body["status"] == "available"
    assert body["summary"]["closed_count"] == 1
    assert body["summary"]["learning"]["best_bucket"]["label"] == "Buy / buy"
    assert body["positions"][0]["analysis_run_id"] == run_id
    assert body["positions"][0]["stock_path"] == "/stocks/005930"


def test_api_app_admin_paper_simulation_dry_run_clamps_to_worker_limit(monkeypatch):
    repo = _repo()
    for ticker_code in ("005930", "000660"):
        run_id = repo.create_analysis_run(
            AnalysisRunInput(
                user_id=USER_ID,
                ticker_code=ticker_code,
                trade_date=date(2026, 5, 5),
                visibility="public",
            )
        )
        repo.record_trade_decision(
            TradeDecisionInput(
                analysis_run_id=run_id,
                rating="Buy",
                action="buy",
            )
        )
        repo.complete_analysis_run(run_id)
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    monkeypatch.setenv("TRADINGAGENTS_PAPER_SIMULATION_WORKER_MAX_RUNS", "1")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post(
        "/api/admin/paper-simulations/process",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 5, "dry_run": True},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "dry_run"
    assert body["candidate_count"] == 1
    assert body["limit"] == 1
    assert body["requested_limit"] == 5
    assert body["max_limit"] == 1
    assert "처리 한도 1건" in body["notice"]


def test_api_app_hides_operator_routes_from_openapi(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_DOCS_ENABLED", "true")
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/stocks/{ticker}" in paths
    assert "/api/admin/analysis-requests/process" not in paths
    assert "/api/cron/process-analysis-requests" not in paths


def test_api_app_serves_non_secret_readiness(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("NAVER_CLIENT_ID", "naver-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "naver-secret")
    monkeypatch.setenv("TRADINGAGENTS_SITE_BASE_URL", "https://example.com")
    monkeypatch.setenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID", "pub-0000000000000000")
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", "codex/kr-market")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "1234567890abcdef")
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/readiness")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["storage_configured"] is False
    assert body["checks"]["storage_online"] is False
    assert body["checks"]["storage_schema_ready"] is False
    assert body["checks"]["openai_configured"] is True
    assert body["checks"]["supabase_auth_configured"] is True
    assert body["checks"]["site_base_url_configured"] is True
    assert body["checks"]["ads_configured"] is True
    assert body["checks"]["live_trading_disabled"] is True
    assert body["checks"]["api_docs_disabled"] is True
    assert body["checks"]["trusted_member_user_header_disabled"] is True
    assert body["checks"]["https_request"] is True
    assert body["missing_environment"]["storage_configured"] == ["DATABASE_URL"]
    assert "supabase_auth_configured" not in body["missing_environment"]
    assert body["configuration_errors"] == {}
    assert body["deployment"]["vercel_env"] == "preview"
    assert body["deployment"]["git_ref"] == "codex/kr-market"
    assert body["deployment"]["git_sha"] == "1234567890ab"
    assert body["deployment"]["trace_source"] == "git_sha"
    assert body["deployment"]["trace_id"] == "1234567890ab"
    assert "diagnostics" not in body
    assert "sk-test" not in response.text
    assert "anon" not in response.text


def test_api_app_readiness_traces_archive_deployments_without_git_sha(monkeypatch):
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_DEPLOYMENT_SHA", raising=False)
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VERCEL_DEPLOYMENT_ID", "dpl_archive_deployment_123")
    monkeypatch.setenv("VERCEL_URL", "trading-agents-archive.vercel.app")
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/readiness", headers={"X-Forwarded-Proto": "https"})

    deployment = response.json()["deployment"]
    assert deployment["git_sha"] is None
    assert deployment["deployment_id"] == "dpl_archive_deployment_123"
    assert deployment["vercel_url"] == "trading-agents-archive.vercel.app"
    assert deployment["trace_source"] == "deployment_id"
    assert deployment["trace_id"] == "dpl_archive_deployment_123"


def test_api_app_readiness_falls_back_to_vercel_url_trace(monkeypatch):
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_DEPLOYMENT_SHA", raising=False)
    monkeypatch.delenv("VERCEL_DEPLOYMENT_ID", raising=False)
    monkeypatch.setenv("VERCEL_URL", "trading-agents-fallback.vercel.app")
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/readiness")

    deployment = response.json()["deployment"]
    assert deployment["git_sha"] is None
    assert deployment["deployment_id"] is None
    assert deployment["trace_source"] == "vercel_url"
    assert deployment["trace_id"] == "trading-agents-fallback.vercel.app"


def test_api_app_readiness_degrades_when_live_trading_enabled(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", "true")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["live_trading_disabled"] is False
    assert "TRADINGAGENTS_ENABLE_LIVE_TRADING=false" in body["configuration_errors"]["live_trading_disabled"]


def test_api_app_readiness_degrades_when_security_guards_are_relaxed(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("TRADINGAGENTS_API_DOCS_ENABLED", "true")
    client = TestClient(
        create_app(
            repo=repo,
            load_repo_from_env=False,
            trust_member_user_header=True,
        )
    )

    response = client.get("/api/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["api_docs_disabled"] is False
    assert body["checks"]["trusted_member_user_header_disabled"] is False
    assert "TRADINGAGENTS_API_DOCS_ENABLED=false" in body["configuration_errors"]["api_docs_disabled"]
    assert "TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER=false" in body["configuration_errors"]["trusted_member_user_header_disabled"]


def test_api_app_readiness_degrades_for_non_https_production_probe(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("VERCEL_ENV", "production")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    insecure_response = client.get("/api/readiness")
    secure_response = client.get("/api/readiness", headers={"X-Forwarded-Proto": "https"})

    assert insecure_response.status_code == 200
    assert insecure_response.json()["status"] == "degraded"
    assert insecure_response.json()["checks"]["https_request"] is False
    assert "Production readiness must be checked over HTTPS" in insecure_response.json()["configuration_errors"]["https_request"]
    assert secure_response.json()["checks"]["https_request"] is True
    assert "https_request" not in secure_response.json()["configuration_errors"]


def test_api_app_readiness_checks_storage_connection():
    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["storage_configured"] is True
    assert body["checks"]["storage_online"] is True
    assert body["checks"]["storage_schema_ready"] is True
    assert "krx_online" not in body["checks"]
    assert body["configuration_errors"] == {}


def test_api_app_readiness_can_probe_krx_online(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    monkeypatch.setenv("TRADINGAGENTS_KRX_PROBE_TICKER", "086520")
    monkeypatch.setenv("TRADINGAGENTS_READINESS_KRX_PROBE_DATE", "2026-05-14")
    captured = {}

    def fake_frame(symbol, start_date, end_date):
        captured["symbol"] = symbol
        return pd.DataFrame({"Close": [270500]})

    monkeypatch.setattr(
        "tradingagents.site.api_app.krx_openapi.get_ohlcv_frame",
        fake_frame,
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/readiness", params={"probe_krx": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["krx_configured"] is True
    assert body["checks"]["krx_online"] is True
    assert captured["symbol"] == "086520"
    assert body["diagnostics"]["krx_probe"]["status"] == "ok"
    assert body["diagnostics"]["krx_probe"]["ticker"] == "086520"
    assert body["diagnostics"]["krx_probe"]["date"] == "2026-05-14"
    assert body["diagnostics"]["krx_probe"]["row_count"] == 1
    assert isinstance(body["diagnostics"]["krx_probe"]["elapsed_ms"], int)
    assert "krx_online" not in body["configuration_errors"]


def test_api_app_readiness_uses_recent_krx_business_day_when_latest_empty(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    monkeypatch.setenv("TRADINGAGENTS_KRX_PROBE_TICKER", "005930")
    monkeypatch.delenv("TRADINGAGENTS_READINESS_KRX_PROBE_DATE", raising=False)
    monkeypatch.setattr(
        "tradingagents.site.api_app._recent_korea_business_dates",
        lambda: ["2026-05-25", "2026-05-22"],
    )
    calls = []

    def fake_frame(symbol, start_date, end_date):
        calls.append((symbol, start_date, end_date))
        if start_date == "2026-05-22":
            return pd.DataFrame({"Close": [56000]})
        return pd.DataFrame()

    monkeypatch.setattr(
        "tradingagents.site.api_app.krx_openapi.get_ohlcv_frame",
        fake_frame,
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/readiness", params={"probe_krx": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["krx_online"] is True
    assert calls == [
        ("005930", "2026-05-25", "2026-05-25"),
        ("005930", "2026-05-22", "2026-05-22"),
    ]
    assert body["diagnostics"]["krx_probe"]["status"] == "ok"
    assert body["diagnostics"]["krx_probe"]["date"] == "2026-05-22"
    assert body["diagnostics"]["krx_probe"]["attempted_dates"] == ["2026-05-25", "2026-05-22"]
    assert body["diagnostics"]["krx_probe"]["request_count"] == 2
    assert body["diagnostics"]["krx_probe"]["row_count"] == 1


def test_api_app_readiness_can_probe_vendor_latency_and_quota(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    monkeypatch.setenv("DART_API_KEY", "dart-key")
    monkeypatch.setenv("NAVER_CLIENT_ID", "naver-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "naver-secret")
    monkeypatch.setenv("TRADINGAGENTS_READINESS_KRX_PROBE_DATE", "2026-05-14")

    monkeypatch.setattr(
        "tradingagents.site.api_app.krx_openapi.get_ohlcv_frame",
        lambda *args, **kwargs: pd.DataFrame({"Close": [270500]}),
    )

    class FakeResponse:
        def __init__(self, payload, *, headers=None, status_code=200):
            self._payload = payload
            self.headers = headers or {}
            self.status_code = status_code

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    def fake_get(url, **kwargs):
        if "opendart" in url:
            return FakeResponse(
                {"status": "000", "corp_name": "삼성전자"},
                headers={"X-RateLimit-Remaining": "19999"},
            )
        if "naver.com" in url:
            return FakeResponse(
                {"items": [{"title": "삼성전자"}]},
                headers={"X-RateLimit-Remaining": "24"},
            )
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr("tradingagents.site.api_app.requests.get", fake_get)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/readiness", params={"probe_vendors": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["krx_online"] is True
    assert body["checks"]["dart_online"] is True
    assert body["checks"]["naver_online"] is True
    assert body["checks"]["vendor_probes_ok"] is True
    probes = body["diagnostics"]["vendor_probes"]
    assert probes["krx"]["request_count"] == 1
    assert probes["dart"]["status"] == "ok"
    assert probes["dart"]["quota_signal"] == "headers_present"
    assert probes["dart"]["quota_headers"]["X-RateLimit-Remaining"] == "19999"
    assert probes["naver"]["item_count"] == 1
    assert probes["naver"]["quota_headers"]["X-RateLimit-Remaining"] == "24"
    assert "dart-key" not in response.text
    assert "naver-secret" not in response.text


def test_api_app_readiness_reports_vendor_probe_failure(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    monkeypatch.setenv("DART_API_KEY", "dart-key")
    monkeypatch.setenv("NAVER_CLIENT_ID", "naver-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "naver-secret")
    monkeypatch.setattr(
        "tradingagents.site.api_app.krx_openapi.get_ohlcv_frame",
        lambda *args, **kwargs: pd.DataFrame({"Close": [270500]}),
    )

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {"status": "000", "corp_name": "삼성전자"}

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        if "opendart" in url:
            return FakeResponse()
        raise RuntimeError("rate limit")

    monkeypatch.setattr("tradingagents.site.api_app.requests.get", fake_get)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/readiness", params={"probe_vendors": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["vendor_probes_ok"] is False
    assert body["checks"]["naver_online"] is False
    assert body["diagnostics"]["vendor_probes"]["naver"]["status"] == "failed"
    assert "Naver news probe failed" in body["configuration_errors"]["naver_online"]
    assert "naver-secret" not in response.text


def test_api_app_readiness_reports_krx_probe_failure(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    monkeypatch.setenv("TRADINGAGENTS_READINESS_KRX_PROBE_DATE", "2026-05-14")

    def fail_probe(*args, **kwargs):
        raise VendorUnavailableError("Invalid API key (401 Unauthorized)")

    monkeypatch.setattr("tradingagents.site.api_app.krx_openapi.get_ohlcv_frame", fail_probe)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get("/api/readiness", params={"probe_krx": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["krx_configured"] is True
    assert body["checks"]["krx_online"] is False
    assert body["diagnostics"]["krx_probe"]["status"] == "failed"
    assert body["diagnostics"]["krx_probe"]["error_type"] == "VendorUnavailableError"
    assert "KRX Open API probe failed" in body["configuration_errors"]["krx_online"]
    assert "krx-key" not in response.text


def test_api_app_readiness_checks_storage_schema():
    client = TestClient(create_app(repo=BrokenPublicAnalysisRepo(), load_repo_from_env=False))

    response = client.get("/api/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["storage_configured"] is True
    assert body["checks"]["storage_online"] is True
    assert body["checks"]["storage_schema_ready"] is False
    assert "apply the Supabase migrations" in body["configuration_errors"]["storage_schema_ready"]
    assert "secret database detail" not in response.text


def test_api_app_readiness_accepts_next_public_supabase_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon")
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["supabase_auth_configured"] is True
    assert "supabase_auth_configured" not in body["missing_environment"]
    assert "anon" not in response.text


def test_api_app_readiness_reports_invalid_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "not-a-valid-database-url")
    client = TestClient(create_app())

    response = client.get("/api/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["storage_configured"] is False
    assert body["checks"]["storage_online"] is False
    assert body["checks"]["storage_schema_ready"] is False
    assert "storage_configured" not in body["missing_environment"]
    assert "DATABASE_URL could not be initialized" in body["configuration_errors"]["storage_configured"]
    assert "not-a-valid-database-url" not in response.text


def test_api_app_disables_docs_by_default(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_API_DOCS_ENABLED", raising=False)
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_api_app_rejects_non_korean_public_stock_ticker():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/stocks/AAPL", params={"include_chart": "false"})

    assert response.status_code == 400
    assert "Korean 6-digit ticker codes or Korean company names" in response.json()["detail"]


def test_api_app_serves_manual_portfolio_payload():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="005930",
            side="buy",
            trade_date=date(2026, 1, 2),
            price=Decimal("70000"),
            quantity=10,
        )
    )

    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))
    response = client.get(
        f"/api/portfolio/{portfolio_id}",
        params={"current_prices": "005930:83000"},
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pricing_status"] == "complete"
    assert body["totals"]["market_value"] == 830000.0


def test_api_app_manual_portfolio_can_use_latest_prices(monkeypatch):
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="005930",
            side="buy",
            trade_date=date(2026, 1, 2),
            price=Decimal("70000"),
            quantity=10,
        )
    )
    monkeypatch.setattr(
        "tradingagents.site.api_app.build_latest_prices_payload",
        lambda tickers, **kwargs: {
            "status": "available",
            "vendor": "pykrx",
            "as_of_date": "2026-05-05",
            "requested_tickers": tickers,
            "prices": {"005930": {"close": 83000.0}},
            "errors": {},
        },
    )

    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))
    response = client.get(
        f"/api/portfolio/{portfolio_id}",
        params={"include_latest_prices": "true"},
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pricing_status"] == "complete"
    assert body["totals"]["market_value"] == 830000.0
    assert body["market_price_source"]["priced_ticker_count"] == 1


def test_api_app_creates_manual_portfolio_and_trade():
    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    create_response = client.post(
        "/api/portfolios",
        headers={"X-TradingAgents-User-Id": USER_ID},
        json={"name": "Main", "base_currency": "KRW"},
    )
    portfolio_id = create_response.json()["portfolio_id"]
    trade_response = client.post(
        f"/api/portfolio/{portfolio_id}/trades",
        headers={"X-TradingAgents-User-Id": USER_ID},
        json={
            "ticker_code": "005930",
            "side": "buy",
            "trade_date": "2026-01-02",
            "price": "70000",
            "quantity": 10,
            "fee": "100",
            "tax": "0",
            "memo": "first buy",
        },
    )

    assert create_response.status_code == 200
    assert create_response.headers["cache-control"] == "private, no-store"
    assert create_response.json()["status"] == "created"
    assert trade_response.status_code == 200
    assert trade_response.json()["status"] == "created"
    assert trade_response.json()["portfolio"]["positions"][0]["ticker_code"] == "005930"
    assert trade_response.json()["portfolio"]["positions"][0]["quantity"] == 10


def test_api_app_rejects_manual_sell_before_persisting_trade():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="005930",
            side="buy",
            trade_date=date(2026, 1, 2),
            price=Decimal("70000"),
            quantity=3,
        )
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.post(
        f"/api/portfolio/{portfolio_id}/trades",
        headers={"X-TradingAgents-User-Id": USER_ID},
        json={
            "ticker_code": "005930",
            "side": "sell",
            "trade_date": "2026-01-03",
            "price": "72000",
            "quantity": 4,
        },
    )

    assert response.status_code == 400
    assert "sell quantity exceeds current 005930 position (3)" in response.json()["detail"]
    assert len(repo.manual_trades_for_portfolio(portfolio_id)) == 1
    assert repo.manual_positions(portfolio_id)["005930"].quantity == 3


def test_api_app_lists_member_manual_portfolios():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    repo.create_manual_portfolio(user_id=OTHER_USER_ID, name="Other")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.get(
        "/api/portfolios",
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["item_count"] == 1
    assert response.json()["items"][0]["id"] == portfolio_id


def test_api_app_limits_member_manual_portfolio_list():
    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.get(
        "/api/portfolios",
        params={"limit": 999},
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 400
    assert "limit cannot exceed" in response.json()["detail"]


def test_api_app_sets_manual_portfolio_target_and_enforces_owner():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    rejected = client.put(
        f"/api/portfolio/{portfolio_id}/targets/005930",
        headers={"X-TradingAgents-User-Id": OTHER_USER_ID},
        json={"target_price": "82000", "stop_price": "65000"},
    )
    accepted = client.put(
        f"/api/portfolio/{portfolio_id}/targets/005930",
        headers={"X-TradingAgents-User-Id": USER_ID},
        json={"target_price": "82000", "stop_price": "65000", "memo": "plan"},
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "saved"
    assert repo.price_targets_for_portfolio(portfolio_id)[0]["target_price"] == Decimal("82000.0000")


def test_api_app_serves_watchlist_payload():
    repo = _repo()
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")
    repo.add_watchlist_item(watchlist_id=watchlist_id, ticker_code="005930")

    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))
    response = client.get(
        f"/api/watchlists/{watchlist_id}",
        params={"current_prices": "005930:83000"},
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["watchlist"]["name"] == "관심종목"
    assert body["items"][0]["current_price"] == 83000.0


def test_api_app_watchlist_can_use_latest_prices(monkeypatch):
    repo = _repo()
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")
    repo.add_watchlist_item(watchlist_id=watchlist_id, ticker_code="005930")
    monkeypatch.setattr(
        "tradingagents.site.api_app.build_latest_prices_payload",
        lambda tickers, **kwargs: {
            "status": "available",
            "vendor": "pykrx",
            "as_of_date": "2026-05-05",
            "requested_tickers": tickers,
            "prices": {"005930": {"close": 83000.0}},
            "errors": {},
        },
    )

    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))
    response = client.get(
        f"/api/watchlists/{watchlist_id}",
        params={"include_latest_prices": "true"},
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["current_price"] == 83000.0
    assert body["market_price_source"]["priced_ticker_count"] == 1


def test_api_app_creates_updates_and_deletes_watchlist_items():
    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    create_response = client.post(
        "/api/watchlists",
        headers={"X-TradingAgents-User-Id": USER_ID},
        json={"name": "관심종목"},
    )
    watchlist_id = create_response.json()["watchlist_id"]
    add_response = client.post(
        f"/api/watchlists/{watchlist_id}/items",
        headers={"X-TradingAgents-User-Id": USER_ID},
        json={"ticker_code": "005930", "memo": "memory leader"},
    )
    rename_response = client.patch(
        f"/api/watchlists/{watchlist_id}",
        headers={"X-TradingAgents-User-Id": USER_ID},
        json={"name": "반도체 관심그룹"},
    )
    delete_response = client.delete(
        f"/api/watchlists/{watchlist_id}/items/005930",
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert create_response.status_code == 200
    assert create_response.headers["cache-control"] == "private, no-store"
    assert create_response.json()["status"] == "created"
    assert add_response.status_code == 200
    assert add_response.json()["watchlist"]["item_count"] == 1
    assert add_response.json()["watchlist"]["items"][0]["ticker_code"] == "005930"
    assert rename_response.status_code == 200
    assert rename_response.json()["status"] == "updated"
    assert rename_response.json()["watchlist"]["name"] == "반도체 관심그룹"
    assert delete_response.status_code == 200
    assert delete_response.json()["watchlist"]["item_count"] == 0


def test_api_app_lists_member_manual_watchlists():
    repo = _repo()
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")
    repo.create_watchlist(user_id=OTHER_USER_ID, name="Other")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.get(
        "/api/watchlists",
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["item_count"] == 1
    assert response.json()["items"][0]["id"] == watchlist_id


def test_api_app_limits_member_manual_watchlist_list():
    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.get(
        "/api/watchlists",
        params={"limit": 999},
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 400
    assert "limit cannot exceed" in response.json()["detail"]


def test_api_app_watchlist_writes_enforce_owner():
    repo = _repo()
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.post(
        f"/api/watchlists/{watchlist_id}/items",
        headers={"X-TradingAgents-User-Id": OTHER_USER_ID},
        json={"ticker_code": "005930"},
    )
    rename_response = client.patch(
        f"/api/watchlists/{watchlist_id}",
        headers={"X-TradingAgents-User-Id": OTHER_USER_ID},
        json={"name": "Other name"},
    )

    assert response.status_code == 403
    assert rename_response.status_code == 403


def test_api_app_portfolio_requires_storage_repo():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get(f"/api/portfolio/{USER_ID}")

    assert response.status_code == 503
    assert response.json()["detail"] == "Storage repository is not configured"


def test_api_app_watchlist_requires_storage_repo():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get(f"/api/watchlists/{USER_ID}")

    assert response.status_code == 503
    assert response.json()["detail"] == "Storage repository is not configured"


def test_api_app_member_routes_reject_untrusted_user_header():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get(
        f"/api/portfolio/{portfolio_id}",
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 403
    assert "trusted auth layer" in response.json()["detail"]


def test_api_app_member_routes_require_user_header_when_trusted():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.get(f"/api/portfolio/{portfolio_id}")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-TradingAgents-User-Id"


def test_api_app_member_routes_enforce_owner():
    repo = _repo()
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.get(
        f"/api/watchlists/{watchlist_id}",
        headers={"X-TradingAgents-User-Id": OTHER_USER_ID},
    )

    assert response.status_code == 403
    assert "does not belong" in response.json()["detail"]


def test_api_app_member_routes_accept_verified_supabase_bearer(monkeypatch):
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    captured = {}
    auth_response = MagicMock()
    auth_response.status_code = 200
    auth_response.json.return_value = {"id": USER_ID}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return auth_response

    monkeypatch.setattr("tradingagents.site.auth.requests.get", fake_get)

    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    response = client.get(
        f"/api/portfolio/{portfolio_id}",
        headers={"Authorization": "Bearer user-token"},
    )

    assert response.status_code == 200
    assert captured["url"] == "https://example.supabase.co/auth/v1/user"
    assert captured["headers"]["Authorization"] == "Bearer user-token"
    assert captured["headers"]["apikey"] == "anon-key"


def test_api_app_serves_member_dashboard_bootstrap_with_single_bearer_auth(monkeypatch):
    repo = _repo()
    portfolio_ids = [repo.create_manual_portfolio(user_id=USER_ID, name=f"Portfolio {index}") for index in range(7)]
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_ids[0],
            ticker_code="005930",
            side="buy",
            trade_date=date(2026, 1, 2),
            price=Decimal("70000"),
            quantity=10,
        )
    )
    other_portfolio_id = repo.create_manual_portfolio(user_id=OTHER_USER_ID, name="Other")
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")
    repo.add_watchlist_item(watchlist_id=watchlist_id, ticker_code="005930")
    other_watchlist_id = repo.create_watchlist(user_id=OTHER_USER_ID, name="Other")
    request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
            reason="refresh",
        )
    )
    other_request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=OTHER_USER_ID,
            ticker_code="000660",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    auth_response = MagicMock()
    auth_response.status_code = 200
    auth_response.json.return_value = {"id": USER_ID}
    auth_calls = []

    def fake_get(url, **kwargs):
        auth_calls.append((url, kwargs))
        return auth_response

    monkeypatch.setattr("tradingagents.site.auth.requests.get", fake_get)

    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    response = client.get(
        "/api/member/dashboard",
        headers={"Authorization": "Bearer user-token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert len(auth_calls) == 1
    assert body["status"] == "available"
    assert body["member"]["user_id"] == USER_ID
    assert body["errors"] == {}
    assert body["portfolios"]["item_count"] == 7
    assert other_portfolio_id not in {item["id"] for item in body["portfolios"]["items"]}
    assert len(body["portfolio_details"]) == 6
    assert set(body["portfolio_details"]).issubset({item["id"] for item in body["portfolios"]["items"]})
    assert body["watchlists"]["item_count"] == 1
    assert body["watchlists"]["items"][0]["id"] == watchlist_id
    assert other_watchlist_id not in body["watchlist_details"]
    assert body["watchlist_details"][watchlist_id]["items"][0]["ticker_code"] == "005930"
    assert body["analysis_requests"]["item_count"] == 1
    assert body["analysis_requests"]["items"][0]["id"] == request_id
    assert other_request_id not in {item["id"] for item in body["analysis_requests"]["items"]}


def test_api_app_member_dashboard_returns_partial_errors_and_keeps_owner_scope(monkeypatch):
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")
    other_watchlist_id = repo.create_watchlist(user_id=OTHER_USER_ID, name="Other")
    repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
            reason="refresh",
        )
    )

    def broken_watchlist_payload(repo_arg, payload_watchlist_id, **kwargs):
        if payload_watchlist_id == watchlist_id:
            raise RuntimeError("watchlist detail unavailable")
        raise AssertionError("dashboard should not load another member's watchlist detail")

    monkeypatch.setattr("tradingagents.site.api_app.build_watchlist_payload", broken_watchlist_payload)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    unauthenticated = client.get("/api/member/dashboard")
    response = client.get(
        "/api/member/dashboard",
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["portfolios"]["item_count"] == 1
    assert portfolio_id in body["portfolio_details"]
    assert body["watchlists"]["item_count"] == 1
    assert body["watchlists"]["items"][0]["id"] == watchlist_id
    assert body["watchlist_details"] == {}
    assert body["errors"] == {"watchlist_details": {watchlist_id: "watchlist detail unavailable"}}
    assert other_watchlist_id not in {item["id"] for item in body["watchlists"]["items"]}
    assert body["analysis_requests"]["item_count"] == 1


def test_api_app_queues_analysis_refresh_request_with_bearer(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    auth_response = MagicMock()
    auth_response.status_code = 200
    auth_response.json.return_value = {"id": USER_ID}
    monkeypatch.setattr("tradingagents.site.auth.requests.get", lambda *args, **kwargs: auth_response)

    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    response = client.post(
        "/api/analysis-requests",
        headers={"Authorization": "Bearer user-token"},
        json={
            "ticker": "005930",
            "requested_trade_date": "2026-05-05",
            "reason": "stale",
        },
    )
    queued = repo.list_analysis_requests(user_id=USER_ID)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "queued"
    assert response.json()["duplicate"] is False
    assert response.json()["public_stock_path"] == "/stocks/005930"
    assert response.json()["status_label"] == "대기"
    assert queued[0]["ticker_code"] == "005930"


def test_api_app_limits_member_analysis_refresh_requests(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_REQUEST_ACTIVE_LIMIT", "1")
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_REQUEST_DAILY_LIMIT", "20")
    auth_response = MagicMock()
    auth_response.status_code = 200
    auth_response.json.return_value = {"id": USER_ID}
    monkeypatch.setattr("tradingagents.site.auth.requests.get", lambda *args, **kwargs: auth_response)

    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    first = client.post(
        "/api/analysis-requests",
        headers={"Authorization": "Bearer user-token"},
        json={"ticker": "005930", "requested_trade_date": "2026-05-05"},
    )
    second = client.post(
        "/api/analysis-requests",
        headers={"Authorization": "Bearer user-token"},
        json={"ticker": "000660", "requested_trade_date": "2026-05-05"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["cache-control"] == "private, no-store"
    assert second.json()["detail"]["status"] == "quota_exceeded"
    assert second.json()["detail"]["kind"] == "active"
    assert second.json()["detail"]["limit"] == 1


def test_api_app_lists_member_analysis_requests():
    repo = _repo()
    request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
            reason="refresh",
        )
    )
    repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=OTHER_USER_ID,
            ticker_code="000660",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    list_response = client.get(
        "/api/analysis-requests",
        headers={"X-TradingAgents-User-Id": USER_ID},
    )
    item_response = client.get(
        f"/api/analysis-requests/{request_id}",
        headers={"X-TradingAgents-User-Id": USER_ID},
    )
    rejected = client.get(
        f"/api/analysis-requests/{request_id}",
        headers={"X-TradingAgents-User-Id": OTHER_USER_ID},
    )

    assert list_response.status_code == 200
    assert list_response.headers["cache-control"] == "private, no-store"
    assert list_response.json()["item_count"] == 1
    assert list_response.json()["items"][0]["id"] == request_id
    assert list_response.json()["items"][0]["public_stock_path"] == "/stocks/005930"
    assert list_response.json()["items"][0]["status_label"] == "대기"
    assert list_response.json()["items"][0]["status_hint"].startswith("대기열에 등록되었습니다")
    assert list_response.json()["items"][0]["next_action_label"] == "상태 새로고침"
    assert list_response.json()["items"][0]["member_queue_position"] == 1
    assert list_response.json()["items"][0]["is_active"] is True
    assert list_response.json()["summary"]["active_count"] == 1
    assert list_response.json()["summary"]["quota_policy"]["active_used"] == 1
    assert list_response.json()["summary"]["status_counts"] == {"queued": 1}
    assert item_response.status_code == 200
    assert item_response.json()["item"]["reason"] == "refresh"
    assert rejected.status_code == 403


def test_api_app_limits_member_analysis_request_list():
    repo = _repo()
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.get(
        "/api/analysis-requests",
        params={"limit": 999},
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 400
    assert "limit cannot exceed" in response.json()["detail"]


def test_api_app_admin_worker_requires_token(monkeypatch):
    repo = _repo()
    monkeypatch.delenv("TRADINGAGENTS_WORKER_TOKEN", raising=False)
    monkeypatch.delenv("DASHBOARD_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("OPERATOR_ACCESS_CODE", raising=False)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post("/api/admin/analysis-requests/process", json={"dry_run": True})

    assert response.status_code == 503
    assert "Operation token" in response.json()["detail"]


def test_api_app_admin_worker_dry_run_requires_matching_token(monkeypatch):
    repo = _repo()
    repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    rejected = client.post(
        "/api/admin/analysis-requests/process",
        headers={"X-TradingAgents-Worker-Token": "wrong"},
        json={"dry_run": True},
    )
    accepted = client.post(
        "/api/admin/analysis-requests/process",
        headers={"Authorization": "Bearer secret"},
        json={"dry_run": True},
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.headers["cache-control"] == "private, no-store"
    assert accepted.json()["status"] == "dry_run"
    assert accepted.json()["item_count"] == 1


def test_api_app_admin_worker_accepts_dashboard_admin_token(monkeypatch):
    repo = _repo()
    repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    monkeypatch.delenv("TRADINGAGENTS_WORKER_TOKEN", raising=False)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setenv("DASHBOARD_ADMIN_TOKEN", "dashboard-secret")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post(
        "/api/admin/analysis-requests/process",
        headers={"X-TradingAgents-Worker-Token": "dashboard-secret"},
        json={"dry_run": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dry_run"
    assert response.json()["item_count"] == 1


def test_api_app_admin_worker_dry_run_clamps_to_worker_limit(monkeypatch):
    repo = _repo()
    repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="000660",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    monkeypatch.setenv("TRADINGAGENTS_WORKER_MAX_REQUESTS", "1")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post(
        "/api/admin/analysis-requests/process",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 5, "dry_run": True},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "dry_run"
    assert body["item_count"] == 1
    assert body["limit"] == 1
    assert body["requested_limit"] == 5
    assert body["max_limit"] == 1
    assert "처리 한도 1건" in body["notice"]


def test_api_app_admin_worker_processes_one_request(monkeypatch):
    repo = _repo()
    repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")

    def fake_runner(request, **kwargs):
        run_id = repo.create_analysis_run(
            AnalysisRunInput(
                ticker_code=request["ticker_code"],
                trade_date=request["requested_trade_date"],
                visibility="public",
            )
        )
        repo.complete_analysis_run(run_id)
        return run_id

    monkeypatch.setattr("tradingagents.site.analysis_runner.run_tradingagents_graph_for_request", fake_runner)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post(
        "/api/admin/analysis-requests/process",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 1},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert response.json()["results"][0]["status"] == "completed"
    assert repo.list_analysis_requests(status="completed")[0]["analysis_run_id"]


def test_api_app_cron_worker_uses_cron_secret(monkeypatch):
    repo = _repo()
    repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
        )
    )
    monkeypatch.delenv("TRADINGAGENTS_WORKER_TOKEN", raising=False)
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    monkeypatch.setenv("TRADINGAGENTS_WORKER_CRON_LIMIT", "1")

    def fake_runner(request, **kwargs):
        run_id = repo.create_analysis_run(
            AnalysisRunInput(
                ticker_code=request["ticker_code"],
                trade_date=request["requested_trade_date"],
                visibility="public",
            )
        )
        repo.complete_analysis_run(run_id)
        return run_id

    monkeypatch.setattr("tradingagents.site.analysis_runner.run_tradingagents_graph_for_request", fake_runner)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get(
        "/api/cron/process-analysis-requests",
        headers={"Authorization": "Bearer cron-secret"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "processed"
    assert response.json()["results"][0]["status"] == "completed"


def test_api_app_admin_outcome_worker_processes_public_runs(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 1),
            visibility="public",
        )
    )
    repo.complete_analysis_run(run_id)
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    monkeypatch.setattr(
        "tradingagents.site.outcome_worker.fetch_korean_returns",
        lambda ticker, trade_date, holding_days: (0.04, 0.01, holding_days),
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post(
        "/api/admin/analysis-outcomes/process",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 1, "horizons": [5]},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "processed"
    assert response.json()["horizons"] == [5]
    assert response.json()["summary"]["completed_count"] == 1
    assert response.json()["summary"]["status_counts"] == {"completed": 1}
    assert response.json()["inspect_path"] == "/api/analysis-outcomes"
    assert response.json()["results"][0]["status"] == "completed"
    assert repo.list_analysis_outcomes(analysis_run_id=run_id)[0]["alpha_return"] == 0.01


def test_api_app_admin_outcome_worker_dry_run_summarizes_candidate_work(monkeypatch):
    repo = _repo()
    repo.complete_analysis_run(
        repo.create_analysis_run(
            AnalysisRunInput(
                ticker_code="005930",
                trade_date=date(2026, 5, 1),
                visibility="public",
            )
        )
    )
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post(
        "/api/admin/analysis-outcomes/process",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 1, "horizons": [5, 20], "dry_run": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dry_run"
    assert response.json()["run_count"] == 1
    assert response.json()["horizons"] == [5, 20]
    assert response.json()["estimated_outcome_count"] == 2
    assert response.json()["inspect_path"] == "/api/analysis-outcomes"


def test_api_app_admin_outcome_worker_dry_run_clamps_to_worker_limit(monkeypatch):
    repo = _repo()
    for ticker_code in ("005930", "000660"):
        repo.complete_analysis_run(
            repo.create_analysis_run(
                AnalysisRunInput(
                    ticker_code=ticker_code,
                    trade_date=date(2026, 5, 1),
                    visibility="public",
                )
            )
        )
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    monkeypatch.setenv("TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS", "1")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post(
        "/api/admin/analysis-outcomes/process",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 5, "horizons": [5], "dry_run": True},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "dry_run"
    assert body["run_count"] == 1
    assert body["limit"] == 1
    assert body["requested_limit"] == 5
    assert body["max_limit"] == 1
    assert "처리 한도 1건" in body["notice"]


def test_api_app_outcome_worker_uses_separate_limit_from_analysis_worker(monkeypatch):
    repo = _repo()
    for ticker_code, trade_date in (("005930", date(2026, 5, 1)), ("000660", date(2026, 5, 2))):
        run_id = repo.create_analysis_run(
            AnalysisRunInput(
                ticker_code=ticker_code,
                ticker_name="테스트",
                market="KOSPI",
                trade_date=trade_date,
                visibility="public",
            )
        )
        repo.complete_analysis_run(run_id)
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    monkeypatch.setenv("TRADINGAGENTS_WORKER_MAX_REQUESTS", "1")
    monkeypatch.delenv("TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS", raising=False)
    monkeypatch.setattr(
        "tradingagents.site.outcome_worker.fetch_korean_returns",
        lambda ticker, trade_date, holding_days: (0.02, 0.01, holding_days),
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post(
        "/api/admin/analysis-outcomes/process",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 2, "horizons": [5]},
    )

    assert response.status_code == 200
    assert response.json()["item_count"] == 2


def test_api_app_outcome_worker_respects_outcome_specific_limit(monkeypatch):
    repo = _repo()
    repo.complete_analysis_run(
        repo.create_analysis_run(
            AnalysisRunInput(
                ticker_code="005930",
                trade_date=date(2026, 5, 1),
                visibility="public",
            )
        )
    )
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "secret")
    monkeypatch.setenv("TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS", "1")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post(
        "/api/admin/analysis-outcomes/process",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 2, "horizons": [5]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "limit cannot exceed 1"


def test_api_app_serves_public_analysis_feed():
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
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

    client = TestClient(create_app(repo=repo, load_repo_from_env=False, public_cache_seconds=60))
    response = client.get("/api/analyses", params={"ticker": "005930", "limit": 1})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    body = response.json()
    assert body["item_count"] == 1
    assert body["items"][0]["id"] == run_id
    assert body["items"][0]["decision_rating"] == "Hold"
    assert body["items"][0]["report_count"] == 1
    assert body["items"][0]["alpha_return"] == 0.03
    assert body["summary"]["decision_rating_counts"] == {"Hold": 1}
    assert body["summary"]["average_alpha_return"] == 0.03
    assert body["summary"]["outcome_covered_count"] == 1
    assert body["summary"]["positive_alpha_rate"] == 1.0


def test_api_app_serves_public_analysis_bundle_by_run_id():
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    private_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="000660",
            ticker_name="SK하이닉스",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="private",
        )
    )
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=run_id,
            role="market",
            title="Market report",
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
    repo.complete_analysis_run(run_id)
    repo.complete_analysis_run(private_run_id)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, public_cache_seconds=60))

    response = client.get(f"/api/analyses/{run_id}")
    private_response = client.get(f"/api/analyses/{private_run_id}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    body = response.json()
    assert body["run"]["id"] == run_id
    assert body["reports"][0]["role"] == "market"
    assert body["reports"][0]["quality_checks"]["status"] == "review"
    assert body["decision"]["rating"] == "Hold"
    assert body["summary"]["report_roles"] == ["market"]
    assert body["summary"]["has_decision"] is True
    assert private_response.status_code == 404


def test_api_app_serves_public_analysis_detail_page_by_run_id():
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
    private_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="000660",
            ticker_name="SK하이닉스",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="private",
        )
    )
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=run_id,
            role="market",
            title="Market report",
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
    repo.complete_analysis_run(run_id)
    repo.complete_analysis_run(private_run_id)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, public_cache_seconds=60))

    response = client.get(f"/analyses/{run_id}")
    private_response = client.get(f"/analyses/{private_run_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert "삼성전자 공개 분석 리포트" in response.text
    assert "근거 점검" in response.text
    assert f"/api/analyses/{run_id}" in response.text
    assert private_response.status_code == 404


def test_api_app_serves_public_analysis_outcomes():
    repo = _repo()
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
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=5,
            raw_return=0.04,
            benchmark_return=0.01,
            alpha_return=0.03,
            status="completed",
        )
    )

    client = TestClient(create_app(repo=repo, load_repo_from_env=False, public_cache_seconds=60))
    response = client.get("/api/analysis-outcomes", params={"ticker": "005930", "limit": 1})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    body = response.json()
    assert body["item_count"] == 1
    assert body["summary"]["average_alpha_return"] == 0.03


def test_api_app_degrades_public_analysis_feed_on_storage_failure():
    client = TestClient(create_app(repo=BrokenPublicAnalysisRepo(), load_repo_from_env=False))

    response = client.get("/api/analyses", params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["items"] == []
    assert body["error"] == "RuntimeError"
    assert "secret database detail" not in response.text


def test_api_app_degrades_public_analysis_outcomes_on_storage_failure():
    client = TestClient(create_app(repo=BrokenPublicAnalysisRepo(), load_repo_from_env=False))

    response = client.get("/api/analysis-outcomes", params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["items"] == []
    assert body["error"] == "RuntimeError"
    assert "secret database detail" not in response.text


def test_api_app_degrades_public_stock_analysis_on_storage_failure():
    client = TestClient(create_app(repo=BrokenPublicAnalysisRepo(), load_repo_from_env=False))

    response = client.get("/api/stocks/005930", params={"include_chart": "false"})

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["status"] == "unavailable"
    assert body["analysis"]["error"] == "RuntimeError"
    assert "secret database detail" not in response.text


def test_api_app_member_routes_require_supabase_auth_config_for_bearer(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", raising=False)
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.get(
        f"/api/portfolio/{portfolio_id}",
        headers={"Authorization": "Bearer user-token"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Supabase Auth verification is not configured"


def test_api_app_rejects_malformed_current_prices():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.get(
        f"/api/portfolio/{portfolio_id}",
        params={"current_prices": "005930"},
        headers={"X-TradingAgents-User-Id": USER_ID},
    )

    assert response.status_code == 400
    assert "ticker:price" in response.json()["detail"]


def test_api_app_sets_public_and_private_cache_headers():
    repo = _repo()
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    client = TestClient(
        create_app(
            repo=repo,
            load_repo_from_env=False,
            public_cache_seconds=60,
            trust_member_user_header=True,
        )
    )

    stock_response = client.get(
        "/api/stocks/005930",
        params={"include_chart": "false", "include_analysis": "false"},
    )
    portfolio_response = client.get(
        f"/api/portfolio/{portfolio_id}",
        headers={"X-TradingAgents-User-Id": USER_ID},
    )
    secure_response = client.get("/api/readiness", headers={"X-Forwarded-Proto": "https"})

    assert stock_response.status_code == 200
    assert stock_response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert stock_response.headers["x-content-type-options"] == "nosniff"
    assert stock_response.headers["x-frame-options"] == "DENY"
    assert stock_response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in stock_response.headers["permissions-policy"]
    assert "frame-ancestors 'none'" in stock_response.headers["content-security-policy"]
    assert "https://unpkg.com" in stock_response.headers["content-security-policy"]
    assert "connect-src 'self' https://*.supabase.co" in stock_response.headers["content-security-policy"]
    assert portfolio_response.status_code == 200
    assert portfolio_response.headers["cache-control"] == "private, no-store"
    assert secure_response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_api_app_supports_configured_cors_origins():
    client = TestClient(
        create_app(
            repo=None,
            load_repo_from_env=False,
            cors_origins=["https://example.com"],
        )
    )

    response = client.options(
        "/api/stocks/005930",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.com"
    assert "GET" in response.headers["access-control-allow-methods"]

    post_response = client.options(
        "/api/analysis-requests",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert post_response.status_code == 200
    assert post_response.headers["access-control-allow-origin"] == "https://example.com"
    assert "POST" in post_response.headers["access-control-allow-methods"]
    assert "PUT" in post_response.headers["access-control-allow-methods"]
    assert "DELETE" in post_response.headers["access-control-allow-methods"]


def test_api_app_serves_latest_prices(monkeypatch):
    def fake_latest(ticker, *args, **kwargs):
        assert ticker == "005930"
        return LatestPrice(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            currency="KRW",
            vendor="pykrx",
            date="2026-01-05",
            close=71200.0,
        )

    monkeypatch.setattr("tradingagents.site.market_api.get_latest_close_price", fake_latest)
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get(
        "/api/prices/latest",
        params={"tickers": "005930", "date": "2026-01-06"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert response.json()["prices"]["005930"]["close"] == 71200.0


def test_api_app_rejects_too_many_latest_price_tickers():
    client = TestClient(create_app(repo=None, load_repo_from_env=False, max_price_tickers=1))

    response = client.get("/api/prices/latest", params={"tickers": "005930,000660"})

    assert response.status_code == 400
    assert "more than 1" in response.json()["detail"]


def test_api_app_rejects_negative_public_cache_seconds():
    try:
        create_app(load_repo_from_env=False, public_cache_seconds=-1)
    except ValueError as exc:
        assert "public_cache_seconds" in str(exc)
    else:
        raise AssertionError("negative public cache seconds should fail")

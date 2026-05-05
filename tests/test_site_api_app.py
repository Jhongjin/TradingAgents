from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
from fastapi.testclient import TestClient

from tradingagents.dataflows.chart_data import LatestPrice
from tradingagents.dataflows import pykrx_vendor
from tradingagents.site.api_app import create_app
from tradingagents.storage import (
    AgentReportInput,
    AnalysisRequestInput,
    AnalysisRunInput,
    ManualTradeInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)


USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"


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
    assert body["checks"]["openai_configured"] is True
    assert body["checks"]["supabase_auth_configured"] is True
    assert body["checks"]["site_base_url_configured"] is True
    assert body["checks"]["ads_configured"] is True
    assert body["deployment"]["vercel_env"] == "preview"
    assert body["deployment"]["git_ref"] == "codex/kr-market"
    assert body["deployment"]["git_sha"] == "1234567890ab"
    assert "sk-test" not in response.text
    assert "anon" not in response.text


def test_api_app_can_disable_docs(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_DOCS_ENABLED", "false")
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_api_app_rejects_non_korean_public_stock_ticker():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/stocks/AAPL", params={"include_chart": "false"})

    assert response.status_code == 400
    assert "Korean 6-digit" in response.json()["detail"]


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
    assert delete_response.status_code == 200
    assert delete_response.json()["watchlist"]["item_count"] == 0


def test_api_app_watchlist_writes_enforce_owner():
    repo = _repo()
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))

    response = client.post(
        f"/api/watchlists/{watchlist_id}/items",
        headers={"X-TradingAgents-User-Id": OTHER_USER_ID},
        json={"ticker_code": "005930"},
    )

    assert response.status_code == 403


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
    assert queued[0]["ticker_code"] == "005930"


def test_api_app_admin_worker_requires_token(monkeypatch):
    repo = _repo()
    monkeypatch.delenv("TRADINGAGENTS_WORKER_TOKEN", raising=False)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    response = client.post("/api/admin/analysis-requests/process", json={"dry_run": True})

    assert response.status_code == 503
    assert "worker token" in response.json()["detail"]


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
    repo.complete_analysis_run(run_id)

    client = TestClient(create_app(repo=repo, load_repo_from_env=False, public_cache_seconds=60))
    response = client.get("/api/analyses", params={"ticker": "005930", "limit": 1})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    body = response.json()
    assert body["item_count"] == 1
    assert body["items"][0]["id"] == run_id


def test_api_app_member_routes_require_supabase_auth_config_for_bearer(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_SUPABASE_URL", raising=False)
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

    assert stock_response.status_code == 200
    assert stock_response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert stock_response.headers["x-content-type-options"] == "nosniff"
    assert portfolio_response.status_code == 200
    assert portfolio_response.headers["cache-control"] == "private, no-store"


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

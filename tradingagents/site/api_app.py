"""FastAPI adapter for TradingAgents public-site services."""

from __future__ import annotations

import os
import hmac
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.middleware.cors import CORSMiddleware

from tradingagents.dataflows import dart, krx_openapi, naver_news
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.storage import ManualTradeInput, StorageRepository, create_storage_engine

from .analysis_api import (
    AnalysisRequestQuotaExceeded,
    build_member_analysis_request_payload,
    build_member_analysis_requests_payload,
    build_public_analysis_bundle_payload,
    build_public_analysis_feed_payload,
    build_public_analysis_outcomes_payload,
    queue_analysis_refresh_request,
)
from .auth import SUPABASE_API_KEY_ENV_NAMES, SUPABASE_URL_ENV_NAMES, resolve_member_user_id
from .market_api import build_latest_prices_payload
from .portfolio_api import build_manual_portfolio_list_payload, build_manual_portfolio_payload, normalize_portfolio_ticker
from .public_api import build_public_stock_payload
from .seo import build_ads_txt, build_robots_txt, build_sitemap_xml, sitemap_tickers_from_env
from .ticker_api import build_ticker_search_payload
from .watchlist_api import build_watchlist_list_payload, build_watchlist_payload
from .web_pages import (
    render_admin_console_page,
    render_feature_detail_page,
    render_member_dashboard_page,
    render_public_analysis_detail_page,
    render_public_analysis_feed_page,
    render_public_home_page,
    render_public_outcomes_page,
    render_public_stock_page,
)


class AnalysisRefreshRequestBody(BaseModel):
    ticker: str
    requested_trade_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str | None = None


class AnalysisWorkerRequestBody(BaseModel):
    limit: int = Field(default=1, ge=1)
    dry_run: bool = False


class OutcomeWorkerRequestBody(BaseModel):
    limit: int = Field(default=20, ge=1)
    horizons: list[int] = Field(default_factory=lambda: [5, 20])
    dry_run: bool = False


class ManualPortfolioCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_currency: str = Field(default="KRW", pattern=r"^[A-Z]{3}$")


class ManualTradeCreateBody(BaseModel):
    ticker_code: str
    side: str = Field(pattern=r"^(buy|sell)$")
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    price: Decimal
    quantity: int = Field(ge=1)
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    memo: str | None = Field(default=None, max_length=500)


class ManualPriceTargetBody(BaseModel):
    target_price: Decimal | None = None
    stop_price: Decimal | None = None
    memo: str | None = Field(default=None, max_length=500)


class WatchlistCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class WatchlistItemBody(BaseModel):
    ticker_code: str
    memo: str | None = Field(default=None, max_length=500)


def create_app(
    *,
    repo: StorageRepository | None = None,
    load_repo_from_env: bool = True,
    cors_origins: list[str] | None = None,
    cors_methods: list[str] | None = None,
    public_cache_seconds: int | None = None,
    max_price_tickers: int | None = None,
    trust_member_user_header: bool | None = None,
) -> FastAPI:
    """Create the TradingAgents API app.

    `repo` injection keeps tests and future serverless handlers deterministic.
    In deployment, `DATABASE_URL` can be used to create the repository without
    auto-creating schemas.
    """

    docs_enabled = _api_docs_enabled()
    app = FastAPI(
        title="TradingAgents Korea API",
        version="0.1.0",
        description="Read-only API surface for Korean stock analysis and manual portfolio summaries.",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.storage_configuration_error = None
    if load_repo_from_env and repo is None:
        app.state.repository, app.state.storage_configuration_error = _load_repo_from_env()
    else:
        app.state.repository = repo
    app.state.public_cache_seconds = _public_cache_seconds(public_cache_seconds)
    app.state.max_price_tickers = _max_price_tickers(max_price_tickers)
    app.state.max_analysis_feed_limit = _max_analysis_feed_limit()
    app.state.trust_member_user_header = _trust_member_user_header(trust_member_user_header)
    _install_cors(app, cors_origins, cors_methods)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", _content_security_policy())
        if _request_is_https(request):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path in {"/member", "/mypage", "/admin"}:
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif (
            request.url.path == "/"
            or request.url.path == "/analyses"
            or request.url.path.startswith("/analyses/")
            or request.url.path == "/outcomes"
            or request.url.path == "/stocks"
            or request.url.path.startswith("/stocks/")
            or request.url.path.startswith("/features/")
            or request.url.path in {"/ads.txt", "/robots.txt", "/sitemap.xml"}
        ):
            seconds = request.app.state.public_cache_seconds
            response.headers.setdefault(
                "Cache-Control",
                f"public, max-age={seconds}, stale-while-revalidate={seconds * 2}",
            )
        elif request.url.path.startswith("/api/stocks/"):
            seconds = request.app.state.public_cache_seconds
            response.headers.setdefault(
                "Cache-Control",
                f"public, max-age={seconds}, stale-while-revalidate={seconds * 2}",
            )
        elif request.url.path == "/api/analyses" or request.url.path.startswith("/api/analyses/") or request.url.path == "/api/analysis-outcomes":
            seconds = request.app.state.public_cache_seconds
            response.headers.setdefault(
                "Cache-Control",
                f"public, max-age={seconds}, stale-while-revalidate={seconds * 2}",
            )
        elif request.url.path.startswith("/api/prices/"):
            response.headers.setdefault("Cache-Control", "public, max-age=60, stale-while-revalidate=120")
        elif request.url.path == "/api/tickers/search":
            response.headers.setdefault("Cache-Control", "public, max-age=300, stale-while-revalidate=600")
        elif request.url.path == "/api/readiness":
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif request.url.path.startswith("/api/member/"):
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif request.url.path.startswith("/api/portfolio/") or request.url.path.startswith("/api/portfolios"):
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif request.url.path.startswith("/api/watchlists"):
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif request.url.path.startswith("/api/analysis-requests"):
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif request.url.path.startswith("/api/admin/"):
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif request.url.path.startswith("/api/cron/"):
            response.headers.setdefault("Cache-Control", "private, no-store")
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/readiness")
    def readiness(request: Request) -> dict[str, object]:
        probe_vendors = _query_bool(request, "probe_vendors", default=False)
        probe_krx = _query_bool(request, "probe_krx", default=False) or probe_vendors
        storage_connectivity_error = _storage_connectivity_error(request.app.state.repository)
        storage_schema_error = _storage_schema_error(
            request.app.state.repository,
            storage_connectivity_error=storage_connectivity_error,
        )
        krx_probe = _krx_online_readiness_probe() if probe_krx else None
        vendor_probes = _vendor_readiness_probes(krx_probe=krx_probe) if probe_vendors else None
        krx_online_error = _krx_readiness_probe_error(krx_probe)
        vendor_probe_errors = _vendor_readiness_probe_errors(vendor_probes)
        checks = {
            "storage_configured": request.app.state.repository is not None,
            "storage_online": request.app.state.repository is not None and storage_connectivity_error is None,
            "storage_schema_ready": (
                request.app.state.repository is not None
                and storage_connectivity_error is None
                and storage_schema_error is None
            ),
            "supabase_auth_configured": _supabase_auth_configured(),
            "worker_token_configured": bool(_expected_worker_token()),
            "site_base_url_configured": bool(os.getenv("TRADINGAGENTS_SITE_BASE_URL")),
            "ads_configured": bool(os.getenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID") or os.getenv("TRADINGAGENTS_ADS_TXT")),
            "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "dart_configured": bool(os.getenv("DART_API_KEY")),
            "naver_configured": bool(os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET")),
            "krx_configured": bool(os.getenv("KRX_API_KEY") or os.getenv("KRX_OPENAPI_KEY")),
            "live_trading_disabled": _live_trading_disabled(),
            "api_docs_disabled": not _api_docs_enabled(),
            "trusted_member_user_header_disabled": not request.app.state.trust_member_user_header,
            "https_request": _request_is_https(request) if _production_env() else True,
        }
        if probe_krx:
            checks["krx_online"] = krx_probe is not None and krx_probe.get("status") == "ok"
        if probe_vendors:
            checks["dart_online"] = vendor_probes is not None and vendor_probes["dart"].get("status") == "ok"
            checks["naver_online"] = vendor_probes is not None and vendor_probes["naver"].get("status") == "ok"
            checks["vendor_probes_ok"] = _vendor_readiness_probes_ok(vendor_probes)
        required = [
            "storage_configured",
            "storage_online",
            "storage_schema_ready",
            "live_trading_disabled",
            "api_docs_disabled",
            "trusted_member_user_header_disabled",
            "https_request",
        ]
        if probe_krx:
            required.append("krx_online")
        if probe_vendors:
            required.append("vendor_probes_ok")
        status = "ok" if all(checks[name] for name in required) else "degraded"
        payload: dict[str, object] = {
            "status": status,
            "deployment": _deployment_context(),
            "checks": checks,
            "missing_environment": _missing_readiness_environment(checks),
            "configuration_errors": _readiness_configuration_errors(
                request,
                storage_connectivity_error=storage_connectivity_error,
                storage_schema_error=storage_schema_error,
                krx_online_error=krx_online_error,
                vendor_probe_errors=vendor_probe_errors,
            ),
        }
        diagnostics: dict[str, object] = {}
        if krx_probe is not None:
            diagnostics["krx_probe"] = krx_probe
        if vendor_probes is not None:
            diagnostics["vendor_probes"] = vendor_probes
        if diagnostics:
            payload["diagnostics"] = diagnostics
        return payload

    @app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
    def robots_txt(request: Request) -> PlainTextResponse:
        return PlainTextResponse(build_robots_txt(site_base_url=_request_site_base_url(request)))

    @app.get("/ads.txt", response_class=PlainTextResponse, include_in_schema=False)
    def ads_txt() -> PlainTextResponse:
        try:
            return PlainTextResponse(build_ads_txt())
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap_xml(request: Request) -> Response:
        try:
            content = build_sitemap_xml(
                site_base_url=_request_site_base_url(request),
                tickers=_sitemap_tickers(request.app.state.repository),
                analysis_paths=_sitemap_analysis_paths(request.app.state.repository),
            )
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(content, media_type="application/xml")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(
        request: Request,
        ticker: Annotated[str, Query(pattern=r"^\d{6}$")] = "005930",
    ) -> HTMLResponse:
        if ticker != "005930":
            return _stock_html_response(ticker, request)
        return HTMLResponse(render_public_home_page(repo=request.app.state.repository, site_base_url=_request_site_base_url(request)))

    @app.get("/analyses", response_class=HTMLResponse, include_in_schema=False)
    def analysis_feed_page(
        request: Request,
        ticker: str | None = None,
        limit: int = 20,
    ) -> HTMLResponse:
        repo = request.app.state.repository
        try:
            html = render_public_analysis_feed_page(
                repo=repo,
                ticker=ticker,
                limit=limit,
                max_limit=request.app.state.max_analysis_feed_limit,
                site_base_url=_request_site_base_url(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return HTMLResponse(html)

    @app.get("/analyses/{analysis_run_id}", response_class=HTMLResponse, include_in_schema=False)
    def analysis_detail_page(analysis_run_id: str, request: Request) -> HTMLResponse:
        repo = request.app.state.repository
        try:
            html = render_public_analysis_detail_page(
                analysis_run_id,
                repo=repo,
                site_base_url=_request_site_base_url(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(html)

    @app.get("/outcomes", response_class=HTMLResponse, include_in_schema=False)
    def analysis_outcomes_page(
        request: Request,
        ticker: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> HTMLResponse:
        repo = request.app.state.repository
        try:
            html = render_public_outcomes_page(
                repo=repo,
                ticker=ticker,
                status=status,
                limit=limit,
                max_limit=request.app.state.max_analysis_feed_limit,
                site_base_url=_request_site_base_url(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return HTMLResponse(html)

    @app.get("/member", response_class=HTMLResponse, include_in_schema=False)
    def member_dashboard(request: Request) -> HTMLResponse:
        return HTMLResponse(render_member_dashboard_page(site_base_url=_request_site_base_url(request)))

    @app.get("/mypage", response_class=HTMLResponse, include_in_schema=False)
    def mypage(request: Request) -> HTMLResponse:
        return HTMLResponse(render_member_dashboard_page(site_base_url=_request_site_base_url(request), canonical_path="/mypage"))

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def admin_console(request: Request) -> HTMLResponse:
        return HTMLResponse(render_admin_console_page(site_base_url=_request_site_base_url(request)))

    @app.get("/features/{feature_slug}", response_class=HTMLResponse, include_in_schema=False)
    def feature_detail(feature_slug: str, request: Request) -> HTMLResponse:
        try:
            html = render_feature_detail_page(feature_slug, site_base_url=_request_site_base_url(request))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(html)

    @app.get("/stocks", include_in_schema=False)
    def stocks_lookup(
        ticker: Annotated[str, Query(min_length=1, max_length=80)] = "005930",
    ) -> RedirectResponse:
        try:
            code = _resolve_stock_lookup(ticker)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(url=f"/stocks/{quote(code)}", status_code=302)

    @app.get("/stocks/{ticker}", response_class=HTMLResponse, include_in_schema=False)
    def stock_html_page(
        ticker: str,
        request: Request,
        chart_start: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        chart_end: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        as_of_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        chart_vendor: str | None = None,
        max_analysis_age_days: int = 1,
    ) -> HTMLResponse:
        return _stock_html_response(
            ticker,
            request,
            chart_start=chart_start,
            chart_end=chart_end,
            as_of_date=as_of_date,
            chart_vendor=chart_vendor,
            max_analysis_age_days=max_analysis_age_days,
        )

    @app.get("/api/stocks/{ticker}")
    def stock_page(
        ticker: str,
        request: Request,
        chart_start: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        chart_end: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        as_of_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        chart_vendor: str | None = None,
        include_chart: bool = True,
        include_analysis: bool = True,
        max_analysis_age_days: int = 1,
    ) -> dict:
        try:
            return build_public_stock_payload(
                ticker,
                repo=request.app.state.repository,
                chart_start=chart_start,
                chart_end=chart_end,
                as_of_date=as_of_date,
                chart_vendor=chart_vendor,
                include_chart=include_chart,
                include_analysis=include_analysis,
                max_analysis_age_days=max_analysis_age_days,
            )
        except (VendorUnavailableError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/prices/latest")
    def latest_prices(
        request: Request,
        tickers: Annotated[str, Query(description="Comma-separated Korean ticker codes, e.g. 005930,000660")],
        date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        lookback_days: int = 14,
        ignore_errors: bool = True,
    ) -> dict:
        try:
            return build_latest_prices_payload(
                tickers.split(","),
                end_date=date,
                lookback_days=lookback_days,
                ignore_errors=ignore_errors,
                max_tickers=request.app.state.max_price_tickers,
            )
        except (VendorUnavailableError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tickers/search")
    def ticker_search(
        q: Annotated[str, Query(min_length=1, max_length=80)],
        limit: int = 10,
        lookup_pykrx: bool = True,
    ) -> dict:
        try:
            return build_ticker_search_payload(q, limit=limit, lookup_pykrx=lookup_pykrx)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/analyses")
    def public_analysis_feed(
        request: Request,
        ticker: str | None = None,
        limit: int = 20,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        try:
            return build_public_analysis_feed_payload(
                repo,
                ticker=ticker,
                limit=limit,
                max_limit=request.app.state.max_analysis_feed_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/analyses/{analysis_run_id}")
    def public_analysis_bundle(analysis_run_id: str, request: Request) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        try:
            payload = build_public_analysis_bundle_payload(repo, analysis_run_id=analysis_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if payload is None:
            raise HTTPException(status_code=404, detail="Public analysis not found")
        return payload

    @app.get("/api/analysis-outcomes")
    def public_analysis_outcomes(
        request: Request,
        ticker: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        try:
            return build_public_analysis_outcomes_payload(
                repo,
                ticker=ticker,
                status=status,
                limit=limit,
                max_limit=request.app.state.max_analysis_feed_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/portfolios")
    def create_manual_portfolio(
        body: ManualPortfolioCreateBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="portfolio name cannot be empty")
        try:
            portfolio_id = repo.create_manual_portfolio(
                user_id=user_id,
                name=name,
                base_currency=body.base_currency,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "created", "portfolio_id": portfolio_id}

    @app.get("/api/member/dashboard")
    def member_dashboard_bootstrap(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
        include_latest_prices: bool = False,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        return _member_dashboard_payload(
            repo,
            user_id=user_id,
            include_latest_prices=include_latest_prices,
            max_tickers=request.app.state.max_price_tickers,
            max_list_limit=request.app.state.max_analysis_feed_limit,
        )

    @app.get("/api/portfolios")
    def member_manual_portfolios(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
        limit: int = 20,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            return build_manual_portfolio_list_payload(
                repo,
                user_id=user_id,
                limit=limit,
                max_limit=request.app.state.max_analysis_feed_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/portfolio/{portfolio_id}/trades")
    def add_manual_portfolio_trade(
        portfolio_id: str,
        body: ManualTradeCreateBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_portfolio_owner(repo, portfolio_id, user_id)
        _validate_non_negative_money(body.fee, "fee")
        _validate_non_negative_money(body.tax, "tax")
        _validate_positive_money(body.price, "price")
        if body.side == "sell":
            _require_sellable_manual_quantity(repo, portfolio_id, body.ticker_code, body.quantity)
        try:
            trade_id = repo.add_manual_trade(
                ManualTradeInput(
                    portfolio_id=portfolio_id,
                    ticker_code=body.ticker_code,
                    side=body.side,
                    trade_date=_parse_date(body.trade_date, "trade_date"),
                    price=body.price,
                    quantity=body.quantity,
                    fee=body.fee,
                    tax=body.tax,
                    memo=body.memo,
                )
            )
            portfolio = build_manual_portfolio_payload(repo, portfolio_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "created", "trade_id": trade_id, "portfolio": portfolio}

    @app.put("/api/portfolio/{portfolio_id}/targets/{ticker_code}")
    def set_manual_portfolio_target(
        portfolio_id: str,
        ticker_code: str,
        body: ManualPriceTargetBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_portfolio_owner(repo, portfolio_id, user_id)
        _validate_optional_positive_money(body.target_price, "target_price")
        _validate_optional_positive_money(body.stop_price, "stop_price")
        try:
            target_id = repo.set_price_target(
                portfolio_id=portfolio_id,
                ticker_code=ticker_code,
                target_price=body.target_price,
                stop_price=body.stop_price,
                memo=body.memo,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved", "target_id": target_id}

    @app.get("/api/portfolio/{portfolio_id}")
    def manual_portfolio(
        portfolio_id: str,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
        current_prices: Annotated[
            str | None,
            Query(description="Comma-separated prices, e.g. 005930:83000,000660:140000"),
        ] = None,
        include_latest_prices: bool = False,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_portfolio_owner(repo, portfolio_id, user_id)
        try:
            prices, source = _portfolio_current_prices(
                repo,
                portfolio_id,
                current_prices=current_prices,
                include_latest_prices=include_latest_prices,
                max_tickers=request.app.state.max_price_tickers,
            )
            payload = build_manual_portfolio_payload(
                repo,
                portfolio_id,
                current_prices=prices,
            )
            if source is not None:
                payload["market_price_source"] = source
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/analysis-requests")
    def create_analysis_request(
        body: AnalysisRefreshRequestBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            return queue_analysis_refresh_request(
                repo,
                ticker=body.ticker,
                user_id=user_id,
                requested_trade_date=body.requested_trade_date,
                reason=body.reason,
            )
        except AnalysisRequestQuotaExceeded as exc:
            raise HTTPException(status_code=429, detail=exc.to_payload()) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/analysis-requests")
    def member_analysis_requests(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
        status: Annotated[str | None, Query(pattern=r"^(queued|running|completed|failed|skipped)$")] = None,
        limit: int = 20,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            return build_member_analysis_requests_payload(
                repo,
                user_id=user_id,
                status=status,
                limit=limit,
                max_limit=request.app.state.max_analysis_feed_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/analysis-requests/{request_id}")
    def member_analysis_request(
        request_id: str,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            payload = build_member_analysis_request_payload(repo, request_id=request_id, user_id=user_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if payload is None:
            raise HTTPException(status_code=404, detail="Analysis request not found")
        return payload

    @app.post("/api/admin/analysis-requests/process", include_in_schema=False)
    def process_analysis_requests_admin(
        body: AnalysisWorkerRequestBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        max_limit = _max_worker_limit()
        if body.limit > max_limit:
            raise HTTPException(status_code=400, detail=f"limit cannot exceed {max_limit}")
        if body.dry_run:
            queued = repo.list_analysis_requests(status="queued", limit=body.limit)
            return {"status": "dry_run", "item_count": len(queued), "items": queued}

        return _process_analysis_request_queue(repo, limit=body.limit)

    @app.get("/api/cron/process-analysis-requests", include_in_schema=False)
    def process_analysis_requests_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        return _process_analysis_request_queue(repo, limit=_cron_worker_limit())

    @app.post("/api/admin/analysis-outcomes/process", include_in_schema=False)
    def process_analysis_outcomes_admin(
        body: OutcomeWorkerRequestBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        max_limit = _max_outcome_worker_limit()
        if body.limit > max_limit:
            raise HTTPException(status_code=400, detail=f"limit cannot exceed {max_limit}")
        _validate_outcome_horizons(body.horizons)
        if body.dry_run:
            runs = repo.list_public_analysis_runs(limit=body.limit)
            return {
                "status": "dry_run",
                "run_count": len(runs),
                "horizons": body.horizons,
                "estimated_outcome_count": len(runs) * len(body.horizons),
                "inspect_path": "/api/analysis-outcomes",
                "items": runs,
            }
        return _process_analysis_outcomes(repo, limit=body.limit, horizons=body.horizons)

    @app.get("/api/cron/process-analysis-outcomes", include_in_schema=False)
    def process_analysis_outcomes_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        return _process_analysis_outcomes(repo, limit=_outcome_cron_worker_limit(), horizons=[5, 20])

    @app.post("/api/watchlists")
    def create_manual_watchlist(
        body: WatchlistCreateBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="watchlist name cannot be empty")
        try:
            watchlist_id = repo.create_watchlist(user_id=user_id, name=name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "created", "watchlist_id": watchlist_id}

    @app.get("/api/watchlists")
    def member_manual_watchlists(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
        limit: int = 20,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            return build_watchlist_list_payload(
                repo,
                user_id=user_id,
                limit=limit,
                max_limit=request.app.state.max_analysis_feed_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/watchlists/{watchlist_id}/items")
    def add_manual_watchlist_item(
        watchlist_id: str,
        body: WatchlistItemBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_watchlist_owner(repo, watchlist_id, user_id)
        try:
            item_id = repo.add_watchlist_item(
                watchlist_id=watchlist_id,
                ticker_code=body.ticker_code,
                memo=body.memo,
            )
            watchlist = build_watchlist_payload(repo, watchlist_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved", "item_id": item_id, "watchlist": watchlist}

    @app.delete("/api/watchlists/{watchlist_id}/items/{ticker_code}")
    def remove_manual_watchlist_item(
        watchlist_id: str,
        ticker_code: str,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_watchlist_owner(repo, watchlist_id, user_id)
        try:
            repo.remove_watchlist_item(watchlist_id=watchlist_id, ticker_code=ticker_code)
            watchlist = build_watchlist_payload(repo, watchlist_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "deleted", "watchlist": watchlist}

    @app.get("/api/watchlists/{watchlist_id}")
    def manual_watchlist(
        watchlist_id: str,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
        current_prices: Annotated[
            str | None,
            Query(description="Comma-separated prices, e.g. 005930:83000,000660:140000"),
        ] = None,
        include_latest_prices: bool = False,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_watchlist_owner(repo, watchlist_id, user_id)
        try:
            prices, source = _watchlist_current_prices(
                repo,
                watchlist_id,
                current_prices=current_prices,
                include_latest_prices=include_latest_prices,
                max_tickers=request.app.state.max_price_tickers,
            )
            payload = build_watchlist_payload(
                repo,
                watchlist_id,
                current_prices=prices,
            )
            if source is not None:
                payload["market_price_source"] = source
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def _stock_html_response(
    ticker: str,
    request: Request,
    *,
    chart_start: str | None = None,
    chart_end: str | None = None,
    as_of_date: str | None = None,
    chart_vendor: str | None = None,
    max_analysis_age_days: int = 1,
) -> HTMLResponse:
    try:
        html = render_public_stock_page(
            ticker,
            repo=request.app.state.repository,
            chart_start=chart_start,
            chart_end=chart_end,
            as_of_date=as_of_date,
            chart_vendor=chart_vendor,
            max_analysis_age_days=max_analysis_age_days,
            site_base_url=_request_site_base_url(request),
        )
    except (VendorUnavailableError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse(html)


def _resolve_stock_lookup(value: str) -> str:
    query = value.strip()
    if not query:
        raise ValueError("ticker query cannot be empty")
    if query.isdigit() and len(query) == 6:
        return query
    results = build_ticker_search_payload(query, limit=1)["items"]
    if not results:
        raise ValueError("matching Korean ticker was not found")
    return str(results[0]["code"])


def _request_site_base_url(request: Request) -> str:
    request_base = str(request.base_url).rstrip("/")
    configured = os.getenv("TRADINGAGENTS_SITE_BASE_URL")
    if configured:
        configured_host = urlparse(configured).netloc.lower()
        request_host = urlparse(request_base).netloc.lower()
        if _should_prefer_request_site_base(configured_host, request_host):
            return request_base
        return configured
    return request_base


def _should_prefer_request_site_base(configured_host: str, request_host: str) -> bool:
    if not configured_host or not request_host or configured_host == request_host:
        return False
    if request_host == "testserver" or request_host.startswith(("localhost", "127.0.0.1")):
        return False
    return configured_host.endswith(".vercel.app") and "-git-" in configured_host


def _sitemap_tickers(repo: StorageRepository | None) -> tuple[str, ...]:
    tickers = list(sitemap_tickers_from_env())
    if repo is not None:
        try:
            rows = repo.list_public_analysis_runs(limit=_sitemap_max_analysis_tickers())
        except Exception:
            rows = []
        tickers.extend(str(row["ticker_code"]) for row in rows if row.get("ticker_code"))
    cleaned = []
    seen = set()
    for ticker in tickers:
        if ticker in seen:
            continue
        seen.add(ticker)
        cleaned.append(ticker)
    return tuple(cleaned)


def _sitemap_analysis_paths(repo: StorageRepository | None) -> tuple[str, ...]:
    if repo is None:
        return ()
    try:
        rows = repo.list_public_analysis_runs(limit=_sitemap_max_analysis_tickers())
    except Exception:
        return ()
    return tuple(f"/analyses/{row['id']}" for row in rows if row.get("id"))


def _sitemap_max_analysis_tickers() -> int:
    raw = int(os.getenv("TRADINGAGENTS_SITEMAP_MAX_ANALYSIS_TICKERS", "200"))
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_SITEMAP_MAX_ANALYSIS_TICKERS must be positive")
    return raw


def _process_analysis_request_queue(repo: StorageRepository, *, limit: int) -> dict:
    from .analysis_runner import run_tradingagents_graph_for_request
    from .analysis_worker import process_queued_analysis_requests

    results = process_queued_analysis_requests(
        repo,
        lambda queued_request: run_tradingagents_graph_for_request(
            queued_request,
            config={"database_url": os.getenv("DATABASE_URL")},
        ),
        limit=limit,
    )
    return {
        "status": "processed",
        "item_count": len(results),
        "results": [result.__dict__ for result in results],
    }


def _process_analysis_outcomes(repo: StorageRepository, *, limit: int, horizons: list[int]) -> dict:
    from .outcome_worker import evaluate_public_analysis_outcomes, summarize_analysis_outcome_results

    results = evaluate_public_analysis_outcomes(repo, limit=limit, horizons=horizons)
    return {
        "status": "processed",
        "item_count": len(results),
        "horizons": horizons,
        "summary": summarize_analysis_outcome_results(results),
        "inspect_path": "/api/analysis-outcomes",
        "results": [result.__dict__ for result in results],
    }


def _validate_outcome_horizons(horizons: list[int]) -> None:
    if not horizons:
        raise HTTPException(status_code=400, detail="at least one horizon is required")
    if any(horizon <= 0 for horizon in horizons):
        raise HTTPException(status_code=400, detail="horizons must be positive")


def _load_repo_from_env() -> tuple[StorageRepository | None, str | None]:
    if not os.getenv("DATABASE_URL"):
        return None, None
    try:
        return StorageRepository(create_storage_engine()), None
    except Exception as exc:
        return None, type(exc).__name__


def _repo_from_env() -> StorageRepository | None:
    repo, _ = _load_repo_from_env()
    return repo


def _install_cors(app: FastAPI, cors_origins: list[str] | None, cors_methods: list[str] | None) -> None:
    origins = cors_origins if cors_origins is not None else _csv_env("TRADINGAGENTS_API_CORS_ORIGINS")
    if not origins:
        return
    methods = cors_methods if cors_methods is not None else _csv_env("TRADINGAGENTS_API_CORS_METHODS")
    if not methods:
        methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=[method.upper() for method in methods],
        allow_headers=["*"],
    )


def _public_cache_seconds(value: int | None) -> int:
    raw = value if value is not None else int(os.getenv("TRADINGAGENTS_API_PUBLIC_CACHE_SECONDS", "300"))
    if raw < 0:
        raise ValueError("public_cache_seconds must be non-negative")
    return raw


def _max_price_tickers(value: int | None) -> int:
    raw = value if value is not None else int(os.getenv("TRADINGAGENTS_API_MAX_PRICE_TICKERS", "20"))
    if raw <= 0:
        raise ValueError("max_price_tickers must be positive")
    return raw


def _max_analysis_feed_limit() -> int:
    raw = int(os.getenv("TRADINGAGENTS_API_MAX_ANALYSIS_FEED_LIMIT", "50"))
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_API_MAX_ANALYSIS_FEED_LIMIT must be positive")
    return raw


def _api_docs_enabled() -> bool:
    return os.getenv("TRADINGAGENTS_API_DOCS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _content_security_policy() -> str:
    return (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' https://*.supabase.co https://*.supabase.com"
    )


def _request_is_https(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or "https" in {part.strip().lower() for part in forwarded_proto.split(",")}


def _production_env() -> bool:
    return os.getenv("VERCEL_ENV", "").strip().lower() == "production"


def _supabase_auth_configured() -> bool:
    has_url = _has_any_env(SUPABASE_URL_ENV_NAMES)
    has_key = _has_any_env(SUPABASE_API_KEY_ENV_NAMES)
    return has_url and has_key


def _missing_readiness_environment(checks: dict[str, bool]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    if not checks["storage_configured"] and not os.getenv("DATABASE_URL"):
        missing["storage_configured"] = ["DATABASE_URL"]
    if not checks["supabase_auth_configured"]:
        names: list[str] = []
        if not _has_any_env(SUPABASE_URL_ENV_NAMES):
            names.append("SUPABASE_URL or NEXT_PUBLIC_SUPABASE_URL")
        if not _has_any_env(SUPABASE_API_KEY_ENV_NAMES):
            names.append("SUPABASE_ANON_KEY or NEXT_PUBLIC_SUPABASE_ANON_KEY")
        missing["supabase_auth_configured"] = names
    if not checks["worker_token_configured"]:
        missing["worker_token_configured"] = ["TRADINGAGENTS_WORKER_TOKEN or CRON_SECRET"]
    if not checks["site_base_url_configured"]:
        missing["site_base_url_configured"] = ["TRADINGAGENTS_SITE_BASE_URL"]
    if not checks["ads_configured"]:
        missing["ads_configured"] = ["TRADINGAGENTS_ADSENSE_PUBLISHER_ID or TRADINGAGENTS_ADS_TXT"]
    if not checks["openai_configured"]:
        missing["openai_configured"] = ["OPENAI_API_KEY"]
    if not checks["dart_configured"]:
        missing["dart_configured"] = ["DART_API_KEY"]
    if not checks["naver_configured"]:
        missing["naver_configured"] = ["NAVER_CLIENT_ID and NAVER_CLIENT_SECRET"]
    if not checks["krx_configured"]:
        missing["krx_configured"] = ["KRX_API_KEY or KRX_OPENAPI_KEY"]
    return missing


def _storage_connectivity_error(repo: StorageRepository | None) -> str | None:
    if repo is None:
        return None
    try:
        repo.check_connection()
    except Exception as exc:
        return type(exc).__name__
    return None


def _storage_schema_error(
    repo: StorageRepository | None,
    *,
    storage_connectivity_error: str | None,
) -> str | None:
    if repo is None or storage_connectivity_error:
        return None
    try:
        repo.check_schema()
    except Exception as exc:
        return type(exc).__name__
    return None


def _krx_online_readiness_probe() -> dict[str, object]:
    probe_symbol = _krx_readiness_probe_symbol()
    probe_date = os.getenv("TRADINGAGENTS_READINESS_KRX_PROBE_DATE") or _last_korea_business_date()
    result: dict[str, object] = {
        "vendor": "krx",
        "probe": "daily_ohlcv",
        "ticker": probe_symbol,
        "date": probe_date,
        "row_count": 0,
        "request_count": 1,
        "elapsed_ms": 0,
        "quota_signal": "wrapper_no_headers",
    }
    if not krx_openapi.is_configured():
        result.update(
            {
                "status": "not_configured",
                "error": "KRX_API_KEY or KRX_OPENAPI_KEY is not configured",
            }
        )
        return result

    started = time.perf_counter()
    try:
        frame = krx_openapi.get_ohlcv_frame(probe_symbol, probe_date, probe_date)
    except Exception as exc:
        result.update(
            {
                "status": "failed",
                "elapsed_ms": _elapsed_ms(started),
                "error_type": exc.__class__.__name__,
                "error": (
                    f"KRX Open API probe failed for {probe_symbol} on {probe_date} ({_safe_error_name(exc)}); "
                    "check key value and service-level approval"
                ),
            }
        )
        return result

    row_count = 0 if frame is None else len(frame.index)
    result.update({"elapsed_ms": _elapsed_ms(started), "row_count": row_count})
    if frame is None or frame.empty:
        result.update(
            {
                "status": "empty",
                "error": f"KRX Open API returned no rows for {probe_symbol} on {probe_date}",
            }
        )
        return result
    result["status"] = "ok"
    return result


def _vendor_readiness_probes(*, krx_probe: dict[str, object] | None) -> dict[str, dict[str, object]]:
    return {
        "krx": krx_probe or _krx_online_readiness_probe(),
        "dart": _dart_online_readiness_probe(),
        "naver": _naver_online_readiness_probe(),
    }


def _dart_online_readiness_probe() -> dict[str, object]:
    ticker = os.getenv("TRADINGAGENTS_DART_PROBE_TICKER", "005930").strip() or "005930"
    result: dict[str, object] = {
        "vendor": "dart",
        "probe": "company_profile",
        "ticker": ticker,
        "endpoint": "company.json",
        "request_count": 1,
        "elapsed_ms": 0,
        "quota_signal": "headers_unavailable",
        "quota_headers": {},
    }
    api_key = os.getenv("DART_API_KEY") or os.getenv("OPEN_DART_API_KEY")
    if not api_key:
        result.update({"status": "not_configured", "error": "DART_API_KEY is not configured"})
        return result

    started = time.perf_counter()
    try:
        corp_code = dart.get_corp_code(ticker)
        response = requests.get(
            "https://opendart.fss.or.kr/api/company.json",
            params={"crtfc_key": api_key, "corp_code": corp_code},
            timeout=_vendor_probe_timeout(),
        )
        quota_headers = _quota_headers(response.headers)
        result.update(
            {
                "elapsed_ms": _elapsed_ms(started),
                "status_code": response.status_code,
                "corp_code": corp_code,
                "quota_headers": quota_headers,
                "quota_signal": "headers_present" if quota_headers else "headers_unavailable",
            }
        )
        response.raise_for_status()
        payload = response.json()
        dart_status = str(payload.get("status") or "")
        if dart_status and dart_status != "000":
            result.update(
                {
                    "status": "failed",
                    "dart_status": dart_status,
                    "error": f"OpenDART company.json returned {dart_status}: {payload.get('message', 'Unknown status')}",
                }
            )
            return result
        result.update(
            {
                "status": "ok",
                "corp_name": payload.get("corp_name"),
            }
        )
        return result
    except Exception as exc:
        result.update(
            {
                "status": "failed",
                "elapsed_ms": _elapsed_ms(started),
                "error_type": exc.__class__.__name__,
                "error": f"DART probe failed ({_safe_error_name(exc)}); check key, quota, and endpoint availability",
            }
        )
        return result


def _naver_online_readiness_probe() -> dict[str, object]:
    query = os.getenv("TRADINGAGENTS_NAVER_PROBE_QUERY", "삼성전자 주가").strip() or "삼성전자 주가"
    result: dict[str, object] = {
        "vendor": "naver",
        "probe": "news_search",
        "query": query,
        "endpoint": "news.json",
        "request_count": 1,
        "elapsed_ms": 0,
        "quota_signal": "headers_unavailable",
        "quota_headers": {},
    }
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        result.update({"status": "not_configured", "error": "NAVER_CLIENT_ID and NAVER_CLIENT_SECRET are not configured"})
        return result

    started = time.perf_counter()
    try:
        response = requests.get(
            naver_news._API_URL,
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={"query": query, "display": 1, "sort": "date"},
            verify=naver_news._requests_verify_setting(),
            timeout=_vendor_probe_timeout(),
        )
        quota_headers = _quota_headers(response.headers)
        result.update(
            {
                "elapsed_ms": _elapsed_ms(started),
                "status_code": response.status_code,
                "quota_headers": quota_headers,
                "quota_signal": "headers_present" if quota_headers else "headers_unavailable",
            }
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        result.update({"status": "ok", "item_count": len(items)})
        return result
    except Exception as exc:
        result.update(
            {
                "status": "failed",
                "elapsed_ms": _elapsed_ms(started),
                "error_type": exc.__class__.__name__,
                "error": f"Naver news probe failed ({_safe_error_name(exc)}); check credentials, quota, and endpoint availability",
            }
        )
        return result


def _vendor_readiness_probes_ok(probes: dict[str, dict[str, object]] | None) -> bool:
    return bool(probes) and all(probe.get("status") == "ok" for probe in probes.values())


def _vendor_readiness_probe_errors(probes: dict[str, dict[str, object]] | None) -> dict[str, str]:
    if not probes:
        return {}
    errors: dict[str, str] = {}
    for vendor, probe in probes.items():
        if vendor == "krx" or probe.get("status") == "ok":
            continue
        errors[f"{vendor}_online"] = str(probe.get("error") or f"{vendor} probe is unavailable")
    return errors


def _quota_headers(headers) -> dict[str, str]:
    observed: dict[str, str] = {}
    for key, value in dict(headers or {}).items():
        normalized = str(key).lower()
        if (
            normalized == "retry-after"
            or "ratelimit" in normalized
            or "rate-limit" in normalized
            or "quota" in normalized
            or normalized.endswith("remaining")
            or normalized.endswith("limit")
        ):
            observed[str(key)] = str(value)[:120]
    return observed


def _vendor_probe_timeout() -> int:
    raw = os.getenv("TRADINGAGENTS_VENDOR_PROBE_TIMEOUT_SECONDS", "8")
    try:
        timeout = int(raw)
    except ValueError:
        return 8
    return min(max(timeout, 1), 30)


def _krx_readiness_probe_error(probe: dict[str, object] | None) -> str | None:
    if probe is None or probe.get("status") == "ok":
        return None
    return str(probe.get("error") or "KRX Open API probe is unavailable")


def _elapsed_ms(started: float) -> int:
    return int(round((time.perf_counter() - started) * 1000))


def _readiness_configuration_errors(
    request: Request,
    *,
    storage_connectivity_error: str | None,
    storage_schema_error: str | None,
    krx_online_error: str | None = None,
    vendor_probe_errors: dict[str, str] | None = None,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    storage_error = getattr(request.app.state, "storage_configuration_error", None)
    if storage_error:
        errors["storage_configured"] = (
            f"DATABASE_URL could not be initialized ({storage_error}); "
            "check the connection string and URL-encode special characters in the password"
        )
    if storage_connectivity_error:
        errors["storage_online"] = (
            f"DATABASE_URL connection failed ({storage_connectivity_error}); "
            "check the Supabase database password, pooler URL, and URL-encoding"
        )
    if storage_schema_error:
        errors["storage_schema_ready"] = (
            f"Storage schema check failed ({storage_schema_error}); "
            "apply the Supabase migrations in order"
        )
    if krx_online_error:
        errors["krx_online"] = krx_online_error
    if vendor_probe_errors:
        errors.update(vendor_probe_errors)
    if not _live_trading_disabled():
        errors["live_trading_disabled"] = "Set TRADINGAGENTS_ENABLE_LIVE_TRADING=false before public deployment"
    if _api_docs_enabled():
        errors["api_docs_disabled"] = "Set TRADINGAGENTS_API_DOCS_ENABLED=false before public deployment"
    if request.app.state.trust_member_user_header:
        errors["trusted_member_user_header_disabled"] = (
            "Set TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER=false outside trusted internal gateways"
        )
    if _production_env() and not _request_is_https(request):
        errors["https_request"] = "Production readiness must be checked over HTTPS"
    return errors


def _has_any_env(names: tuple[str, ...]) -> bool:
    return any(bool(os.getenv(name)) for name in names)


def _deployment_context() -> dict[str, str | None]:
    return {
        "vercel_env": os.getenv("VERCEL_ENV"),
        "git_ref": os.getenv("VERCEL_GIT_COMMIT_REF"),
        "git_sha": _short_sha(os.getenv("VERCEL_GIT_COMMIT_SHA")),
        "vercel_url": os.getenv("VERCEL_URL"),
    }


def _short_sha(value: str | None) -> str | None:
    if not value:
        return None
    return value[:12]


def _query_bool(request: Request, name: str, *, default: bool = False) -> bool:
    value = request.query_params.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _last_korea_business_date() -> str:
    current = datetime.now(ZoneInfo("Asia/Seoul")).date() - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current.isoformat()


def _krx_readiness_probe_symbol() -> str:
    return (
        os.getenv("TRADINGAGENTS_READINESS_KRX_PROBE_TICKER")
        or os.getenv("TRADINGAGENTS_KRX_PROBE_TICKER")
        or "005930"
    ).strip()


def _safe_error_name(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return message[:160]


def _member_dashboard_payload(
    repo: StorageRepository,
    *,
    user_id: str,
    include_latest_prices: bool,
    max_tickers: int,
    max_list_limit: int,
) -> dict:
    list_limit = min(20, max_list_limit)
    detail_limit = 6
    errors: dict[str, object] = {}
    portfolios: dict = {"status": "unavailable", "limit": list_limit, "items": [], "item_count": 0}
    portfolio_details: dict[str, dict] = {}
    watchlists: dict = {"status": "unavailable", "limit": list_limit, "items": [], "item_count": 0}
    watchlist_details: dict[str, dict] = {}
    analysis_requests: dict = {"status": "unavailable", "limit": list_limit, "items": [], "item_count": 0}

    try:
        portfolios = build_manual_portfolio_list_payload(
            repo,
            user_id=user_id,
            limit=list_limit,
            max_limit=max_list_limit,
        )
    except Exception as exc:
        errors["portfolios"] = _safe_error_name(exc)
    else:
        detail_errors: dict[str, str] = {}
        for portfolio in portfolios.get("items", [])[:detail_limit]:
            portfolio_id = str(portfolio.get("id") or "")
            if not portfolio_id:
                continue
            try:
                prices, source = _portfolio_current_prices(
                    repo,
                    portfolio_id,
                    current_prices=None,
                    include_latest_prices=include_latest_prices,
                    max_tickers=max_tickers,
                )
                payload = build_manual_portfolio_payload(repo, portfolio_id, current_prices=prices)
                if source is not None:
                    payload["market_price_source"] = source
                portfolio_details[portfolio_id] = payload
            except Exception as exc:
                detail_errors[portfolio_id] = _safe_error_name(exc)
        if detail_errors:
            errors["portfolio_details"] = detail_errors

    try:
        watchlists = build_watchlist_list_payload(
            repo,
            user_id=user_id,
            limit=list_limit,
            max_limit=max_list_limit,
        )
    except Exception as exc:
        errors["watchlists"] = _safe_error_name(exc)
    else:
        detail_errors = {}
        for watchlist in watchlists.get("items", [])[:detail_limit]:
            watchlist_id = str(watchlist.get("id") or "")
            if not watchlist_id:
                continue
            try:
                prices, source = _watchlist_current_prices(
                    repo,
                    watchlist_id,
                    current_prices=None,
                    include_latest_prices=include_latest_prices,
                    max_tickers=max_tickers,
                )
                payload = build_watchlist_payload(repo, watchlist_id, current_prices=prices)
                if source is not None:
                    payload["market_price_source"] = source
                watchlist_details[watchlist_id] = payload
            except Exception as exc:
                detail_errors[watchlist_id] = _safe_error_name(exc)
        if detail_errors:
            errors["watchlist_details"] = detail_errors

    try:
        analysis_requests = build_member_analysis_requests_payload(
            repo,
            user_id=user_id,
            limit=list_limit,
            max_limit=max_list_limit,
        )
    except Exception as exc:
        errors["analysis_requests"] = _safe_error_name(exc)

    return {
        "status": "partial" if errors else "available",
        "member": {"user_id": user_id},
        "portfolios": portfolios,
        "portfolio_details": portfolio_details,
        "watchlists": watchlists,
        "watchlist_details": watchlist_details,
        "analysis_requests": analysis_requests,
        "errors": errors,
    }


def _trust_member_user_header(value: bool | None) -> bool:
    if value is not None:
        return value
    return os.getenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "false").strip().lower() in {"1", "true", "yes", "on"}


def _live_trading_disabled() -> bool:
    return os.getenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", "false").strip().lower() not in {"1", "true", "yes", "on"}


def _max_worker_limit() -> int:
    raw = int(os.getenv("TRADINGAGENTS_WORKER_MAX_REQUESTS", "1"))
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_WORKER_MAX_REQUESTS must be positive")
    return raw


def _max_outcome_worker_limit() -> int:
    raw = int(os.getenv("TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS", "20"))
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS must be positive")
    return raw


def _cron_worker_limit() -> int:
    raw = int(os.getenv("TRADINGAGENTS_WORKER_CRON_LIMIT", str(_max_worker_limit())))
    max_limit = _max_worker_limit()
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_WORKER_CRON_LIMIT must be positive")
    if raw > max_limit:
        raise HTTPException(status_code=400, detail=f"cron limit cannot exceed {max_limit}")
    return raw


def _outcome_cron_worker_limit() -> int:
    max_limit = _max_outcome_worker_limit()
    raw = int(os.getenv("TRADINGAGENTS_OUTCOME_WORKER_CRON_LIMIT", str(min(5, max_limit))))
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_OUTCOME_WORKER_CRON_LIMIT must be positive")
    if raw > max_limit:
        raise HTTPException(status_code=400, detail=f"outcome cron limit cannot exceed {max_limit}")
    return raw


def _require_worker_token(request: Request, header_token: str | None) -> None:
    expected = _expected_worker_token()
    if not expected:
        raise HTTPException(status_code=503, detail="Analysis worker token is not configured")
    token = header_token or _bearer_token(request.headers.get("Authorization"))
    if not token:
        raise HTTPException(status_code=401, detail="Missing analysis worker token")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid analysis worker token")


def _expected_worker_token() -> str:
    return (os.getenv("TRADINGAGENTS_WORKER_TOKEN") or os.getenv("CRON_SECRET") or "").strip()


def _bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _require_portfolio_owner(repo: StorageRepository, portfolio_id: str, user_id: str) -> None:
    try:
        portfolio = repo.get_manual_portfolio(portfolio_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    if str(portfolio["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Portfolio does not belong to the authenticated user")


def _require_sellable_manual_quantity(repo: StorageRepository, portfolio_id: str, ticker_code: str, quantity: int) -> None:
    try:
        ticker = normalize_portfolio_ticker(ticker_code)
        position = repo.manual_positions(portfolio_id).get(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    available = position.quantity if position is not None else 0
    if quantity > available:
        raise HTTPException(
            status_code=400,
            detail=f"sell quantity exceeds current {ticker} position ({available})",
        )


def _require_watchlist_owner(repo: StorageRepository, watchlist_id: str, user_id: str) -> None:
    try:
        watchlist = repo.get_watchlist(watchlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    if str(watchlist["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Watchlist does not belong to the authenticated user")


def _csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_current_prices(value: str | None) -> dict[str, Decimal]:
    if not value:
        return {}

    prices: dict[str, Decimal] = {}
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError("current_prices must use ticker:price pairs")
        ticker, price = item.split(":", 1)
        ticker = ticker.strip()
        if not ticker:
            raise ValueError("current_prices ticker cannot be empty")
        try:
            parsed = Decimal(price.strip())
        except Exception as exc:
            raise ValueError("current_prices values must be numeric") from exc
        prices[ticker] = parsed
    return prices


def _portfolio_current_prices(
    repo: StorageRepository,
    portfolio_id: str,
    *,
    current_prices: str | None,
    include_latest_prices: bool,
    max_tickers: int,
) -> tuple[dict[str, Decimal], dict | None]:
    parsed = _parse_current_prices(current_prices)
    if parsed or not include_latest_prices:
        return parsed, None
    return _latest_current_prices(repo.manual_positions(portfolio_id).keys(), max_tickers=max_tickers)


def _watchlist_current_prices(
    repo: StorageRepository,
    watchlist_id: str,
    *,
    current_prices: str | None,
    include_latest_prices: bool,
    max_tickers: int,
) -> tuple[dict[str, Decimal], dict | None]:
    parsed = _parse_current_prices(current_prices)
    if parsed or not include_latest_prices:
        return parsed, None
    return _latest_current_prices(
        [str(row["ticker_code"]) for row in repo.watchlist_items(watchlist_id)],
        max_tickers=max_tickers,
    )


def _latest_current_prices(tickers, *, max_tickers: int) -> tuple[dict[str, Decimal], dict]:
    cleaned = [str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()]
    if not cleaned:
        return {}, {"status": "empty", "vendor": "pykrx", "priced_ticker_count": 0}
    payload = build_latest_prices_payload(cleaned, ignore_errors=True, max_tickers=max_tickers)
    prices = {
        str(ticker): Decimal(str(item["close"]))
        for ticker, item in (payload.get("prices") or {}).items()
        if item.get("close") is not None
    }
    source = {
        "status": payload.get("status"),
        "vendor": payload.get("vendor"),
        "as_of_date": payload.get("as_of_date"),
        "requested_tickers": payload.get("requested_tickers") or [],
        "priced_ticker_count": len(prices),
        "errors": payload.get("errors") or {},
    }
    return prices, source


def _parse_date(value: str, field_name: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


def _validate_positive_money(value: Decimal, field_name: str) -> None:
    if value <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name} must be positive")


def _validate_non_negative_money(value: Decimal, field_name: str) -> None:
    if value < 0:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be negative")


def _validate_optional_positive_money(value: Decimal | None, field_name: str) -> None:
    if value is not None and value <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name} must be positive")


app = create_app()

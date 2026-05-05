"""FastAPI adapter for TradingAgents public-site services."""

from __future__ import annotations

import os
import hmac
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.middleware.cors import CORSMiddleware

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.storage import ManualTradeInput, StorageRepository, create_storage_engine

from .analysis_api import build_public_analysis_feed_payload, queue_analysis_refresh_request
from .auth import resolve_member_user_id
from .market_api import build_latest_prices_payload
from .portfolio_api import build_manual_portfolio_payload
from .public_api import build_public_stock_payload
from .seo import build_ads_txt, build_robots_txt, build_sitemap_xml, sitemap_tickers_from_env
from .watchlist_api import build_watchlist_payload
from .web_pages import render_public_stock_page


class AnalysisRefreshRequestBody(BaseModel):
    ticker: str
    requested_trade_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str | None = None


class AnalysisWorkerRequestBody(BaseModel):
    limit: int = Field(default=1, ge=1)
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
    app.state.repository = repo or _repo_from_env() if load_repo_from_env else repo
    app.state.public_cache_seconds = _public_cache_seconds(public_cache_seconds)
    app.state.max_price_tickers = _max_price_tickers(max_price_tickers)
    app.state.max_analysis_feed_limit = _max_analysis_feed_limit()
    app.state.trust_member_user_header = _trust_member_user_header(trust_member_user_header)
    _install_cors(app, cors_origins, cors_methods)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if (
            request.url.path == "/"
            or request.url.path == "/stocks"
            or request.url.path.startswith("/stocks/")
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
        elif request.url.path == "/api/analyses":
            seconds = request.app.state.public_cache_seconds
            response.headers.setdefault(
                "Cache-Control",
                f"public, max-age={seconds}, stale-while-revalidate={seconds * 2}",
            )
        elif request.url.path.startswith("/api/prices/"):
            response.headers.setdefault("Cache-Control", "public, max-age=60, stale-while-revalidate=120")
        elif request.url.path == "/api/readiness":
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
        checks = {
            "storage_configured": request.app.state.repository is not None,
            "supabase_auth_configured": _supabase_auth_configured(),
            "worker_token_configured": bool(_expected_worker_token()),
            "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "dart_configured": bool(os.getenv("DART_API_KEY")),
            "naver_configured": bool(os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET")),
            "krx_configured": bool(os.getenv("KRX_API_KEY") or os.getenv("KRX_OPENAPI_KEY")),
        }
        required = ["storage_configured"]
        status = "ok" if all(checks[name] for name in required) else "degraded"
        return {"status": status, "checks": checks}

    @app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
    def robots_txt(request: Request) -> PlainTextResponse:
        return PlainTextResponse(build_robots_txt(site_base_url=_request_site_base_url(request)))

    @app.get("/ads.txt", response_class=PlainTextResponse, include_in_schema=False)
    def ads_txt() -> PlainTextResponse:
        try:
            return PlainTextResponse(build_ads_txt())
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap_xml(request: Request) -> Response:
        try:
            content = build_sitemap_xml(
                site_base_url=_request_site_base_url(request),
                tickers=sitemap_tickers_from_env(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(content, media_type="application/xml")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(
        request: Request,
        ticker: Annotated[str, Query(pattern=r"^\d{6}$")] = "005930",
    ) -> HTMLResponse:
        return _stock_html_response(ticker, request)

    @app.get("/stocks", include_in_schema=False)
    def stocks_lookup(
        ticker: Annotated[str, Query(pattern=r"^\d{6}$")] = "005930",
    ) -> RedirectResponse:
        return RedirectResponse(url=f"/stocks/{quote(ticker.strip())}", status_code=302)

    @app.get("/stocks/{ticker}", response_class=HTMLResponse, include_in_schema=False)
    def stock_html_page(
        ticker: str,
        request: Request,
        chart_start: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        chart_end: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        as_of_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        max_analysis_age_days: int = 1,
    ) -> HTMLResponse:
        return _stock_html_response(
            ticker,
            request,
            chart_start=chart_start,
            chart_end=chart_end,
            as_of_date=as_of_date,
            max_analysis_age_days=max_analysis_age_days,
        )

    @app.get("/api/stocks/{ticker}")
    def stock_page(
        ticker: str,
        request: Request,
        chart_start: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        chart_end: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        as_of_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
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
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_portfolio_owner(repo, portfolio_id, user_id)
        try:
            return build_manual_portfolio_payload(
                repo,
                portfolio_id,
                current_prices=_parse_current_prices(current_prices),
            )
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
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_watchlist_owner(repo, watchlist_id, user_id)
        try:
            return build_watchlist_payload(
                repo,
                watchlist_id,
                current_prices=_parse_current_prices(current_prices),
            )
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
    max_analysis_age_days: int = 1,
) -> HTMLResponse:
    try:
        html = render_public_stock_page(
            ticker,
            repo=request.app.state.repository,
            chart_start=chart_start,
            chart_end=chart_end,
            as_of_date=as_of_date,
            max_analysis_age_days=max_analysis_age_days,
            site_base_url=_request_site_base_url(request),
        )
    except (VendorUnavailableError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse(html)


def _request_site_base_url(request: Request) -> str:
    configured = os.getenv("TRADINGAGENTS_SITE_BASE_URL")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


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


def _repo_from_env() -> StorageRepository | None:
    if not os.getenv("DATABASE_URL"):
        return None
    return StorageRepository(create_storage_engine())


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
    return os.getenv("TRADINGAGENTS_API_DOCS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _supabase_auth_configured() -> bool:
    has_url = bool(os.getenv("SUPABASE_URL") or os.getenv("TRADINGAGENTS_SUPABASE_URL"))
    has_key = bool(
        os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_PUBLISHABLE_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    )
    return has_url and has_key


def _trust_member_user_header(value: bool | None) -> bool:
    if value is not None:
        return value
    return os.getenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "false").strip().lower() in {"1", "true", "yes", "on"}


def _max_worker_limit() -> int:
    raw = int(os.getenv("TRADINGAGENTS_WORKER_MAX_REQUESTS", "1"))
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_WORKER_MAX_REQUESTS must be positive")
    return raw


def _cron_worker_limit() -> int:
    raw = int(os.getenv("TRADINGAGENTS_WORKER_CRON_LIMIT", str(_max_worker_limit())))
    max_limit = _max_worker_limit()
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_WORKER_CRON_LIMIT must be positive")
    if raw > max_limit:
        raise HTTPException(status_code=400, detail=f"cron limit cannot exceed {max_limit}")
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

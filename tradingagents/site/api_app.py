"""FastAPI adapter for TradingAgents public-site services."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.storage import StorageRepository, create_storage_engine

from .analysis_api import build_public_analysis_feed_payload, queue_analysis_refresh_request
from .auth import resolve_member_user_id
from .market_api import build_latest_prices_payload
from .portfolio_api import build_manual_portfolio_payload
from .public_api import build_public_stock_payload
from .watchlist_api import build_watchlist_payload


class AnalysisRefreshRequestBody(BaseModel):
    ticker: str
    requested_trade_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str | None = None


def create_app(
    *,
    repo: StorageRepository | None = None,
    load_repo_from_env: bool = True,
    cors_origins: list[str] | None = None,
    public_cache_seconds: int | None = None,
    max_price_tickers: int | None = None,
    trust_member_user_header: bool | None = None,
) -> FastAPI:
    """Create the TradingAgents API app.

    `repo` injection keeps tests and future serverless handlers deterministic.
    In deployment, `DATABASE_URL` can be used to create the repository without
    auto-creating schemas.
    """

    app = FastAPI(
        title="TradingAgents Korea API",
        version="0.1.0",
        description="Read-only API surface for Korean stock analysis and manual portfolio summaries.",
    )
    app.state.repository = repo or _repo_from_env() if load_repo_from_env else repo
    app.state.public_cache_seconds = _public_cache_seconds(public_cache_seconds)
    app.state.max_price_tickers = _max_price_tickers(max_price_tickers)
    app.state.max_analysis_feed_limit = _max_analysis_feed_limit()
    app.state.trust_member_user_header = _trust_member_user_header(trust_member_user_header)
    _install_cors(app, cors_origins)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.url.path.startswith("/api/stocks/"):
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
        elif request.url.path.startswith("/api/portfolio/"):
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif request.url.path.startswith("/api/watchlists/"):
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif request.url.path.startswith("/api/analysis-requests"):
            response.headers.setdefault("Cache-Control", "private, no-store")
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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


def _repo_from_env() -> StorageRepository | None:
    if not os.getenv("DATABASE_URL"):
        return None
    return StorageRepository(create_storage_engine())


def _install_cors(app: FastAPI, cors_origins: list[str] | None) -> None:
    origins = cors_origins if cors_origins is not None else _csv_env("TRADINGAGENTS_API_CORS_ORIGINS")
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET"],
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


def _trust_member_user_header(value: bool | None) -> bool:
    if value is not None:
        return value
    return os.getenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "false").strip().lower() in {"1", "true", "yes", "on"}


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


app = create_app()

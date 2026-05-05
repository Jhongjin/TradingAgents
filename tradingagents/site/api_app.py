"""FastAPI adapter for TradingAgents public-site services."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from starlette.middleware.cors import CORSMiddleware

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.storage import StorageRepository, create_storage_engine

from .portfolio_api import build_manual_portfolio_payload
from .public_api import build_public_stock_payload


def create_app(
    *,
    repo: StorageRepository | None = None,
    load_repo_from_env: bool = True,
    cors_origins: list[str] | None = None,
    public_cache_seconds: int | None = None,
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
        elif request.url.path.startswith("/api/portfolio/"):
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

    @app.get("/api/portfolio/{portfolio_id}")
    def manual_portfolio(
        portfolio_id: str,
        request: Request,
        current_prices: Annotated[
            str | None,
            Query(description="Comma-separated prices, e.g. 005930:83000,000660:140000"),
        ] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        try:
            return build_manual_portfolio_payload(
                repo,
                portfolio_id,
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

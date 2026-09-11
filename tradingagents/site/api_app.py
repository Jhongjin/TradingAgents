"""FastAPI adapter for TradingAgents public-site services."""

from __future__ import annotations

import json
import os
import hmac
from uuid import UUID
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.middleware.cors import CORSMiddleware

from tradingagents.dataflows import dart, krx_openapi, naver_news
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.kr_tickers import is_kr_ticker
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
from .admin_members import SupabaseAdminClient, SupabaseAdminError, grant_member_plan, list_members, set_member_role
from .admin_members_page import render_admin_members_page
from .auth import SUPABASE_API_KEY_ENV_NAMES, SUPABASE_URL_ENV_NAMES, resolve_member_profile, resolve_member_user_id
from .journal_alerts import notify_journal_alerts
from .harness_api import (
    SUPPORTED_WEB_CONFIRMERS,
    build_harness_outcomes_payload,
    build_harness_run_payload,
    build_harness_runs_payload,
    build_harness_ticker_history_payload,
)
from .billing import (
    PLANS,
    PortOneClient,
    PortOneConfig,
    PortOneError,
    RESEARCH_TOOL_NOTICES,
    build_checkout_payload,
    cancel_at_period_end,
    gate_harness_payload,
    gate_paper_account_payload,
    handle_portone_webhook,
    latest_visible_run_id,
    process_subscription_renewals,
    request_refund,
    resolve_plan_access,
    start_trial,
    verify_webhook_signature,
)
from .billing_page import render_billing_page
from .harness_pages import render_harness_page
from .brand import favicon_ico, favicon_svg, icon_png, web_manifest
from .design_system import rating_label
from .home_page import build_home_view_model, render_home_page
from .og_image import og_stats, render_og_image
from .ticker_history_page import build_ticker_history_model, render_ticker_history_page
from .notifications import (
    TelegramClient,
    TelegramConfig,
    TelegramError,
    channel_status,
    create_link_code,
    handle_telegram_update,
    notify_exit_alerts,
    notify_harness_issue,
    notify_outcome_results,
    unlink_channel,
)
from .pricing_page import render_pricing_page
from .market_api import build_latest_prices_payload, build_sparkline_payload
from .paper_simulation_api import EXECUTION_BOUNDARY_LABEL, build_member_paper_simulation_payload
from .portfolio_api import build_manual_portfolio_list_payload, build_manual_portfolio_payload, normalize_portfolio_ticker
from .public_api import build_public_stock_payload
from .screener_api import build_forecast_payload, build_screener_payload
from .seo import build_ads_txt, build_llms_txt, build_robots_txt, build_sitemap_xml, indexnow_key, sitemap_tickers_from_env, submit_indexnow, verification_files
from .simulation_api import build_public_simulation_preview_payload
from .ticker_api import build_ticker_search_payload
from .watchlist_api import build_watchlist_list_payload, build_watchlist_payload
from .web_pages import (
    render_admin_console_page,
    render_feature_detail_page,
    render_feature_index_page,
    render_member_dashboard_page,
    render_policy_page,
    render_public_analysis_detail_page,
    render_public_analysis_feed_page,
    render_public_home_page,
    render_public_outcomes_page,
    render_public_stock_page,
)


class CheckoutBody(BaseModel):
    plan: str = Field(pattern=r"^(daily|pro)$")


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


class PaperSimulationWorkerRequestBody(BaseModel):
    limit: int = Field(default=20, ge=1)
    dry_run: bool = False
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class HarnessOutcomeWorkerRequestBody(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    horizons: list[int] = Field(default_factory=lambda: [5, 20])
    dry_run: bool = False


class HarnessRunRequestBody(BaseModel):
    confirmer: str = Field(default="none", pattern=r"^(none|playbook|debate)$")
    confirm_top_n: int = Field(default=3, ge=1, le=10)
    top_n: int = Field(default=20, ge=1, le=50)
    markets: str = Field(default="KOSPI,KOSDAQ", pattern=r"^(?i:kospi|kosdaq)(,(?i:kospi|kosdaq))*$")
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    dry_run: bool = True


class IndexNowBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=500)


class GoldStudyBody(BaseModel):
    symbol: str = "GC=F"
    interval: str = "1h"
    study: dict = Field(default_factory=dict)


class MemberPreferencesBody(BaseModel):
    markets: list[str] = Field(default_factory=lambda: ["KOSPI", "KOSDAQ"], max_length=4)
    exclude_etf: bool = True
    min_rating: str = "any"
    max_price: float | None = None
    excluded_tickers: list[str] = Field(default_factory=list, max_length=50)
    excluded_sectors: list[str] = Field(default_factory=list, max_length=20)


class MemberPlanBody(BaseModel):
    plan: str = Field(pattern=r"^(free|daily|pro)$")
    days: int = Field(default=30, ge=0, le=366)


class MemberRoleBody(BaseModel):
    role: str = Field(pattern=r"^(admin|member)$")


WORKER_TOKEN_ENV_NAMES = (
    "TRADINGAGENTS_WORKER_TOKEN",
    "DASHBOARD_ADMIN_TOKEN",
    "OPERATOR_ACCESS_CODE",
    "CRON_SECRET",
)


class ManualPortfolioCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_currency: str = Field(default="KRW", pattern=r"^[A-Z]{3}$")


class ManualPortfolioUpdateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


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


class WatchlistUpdateBody(BaseModel):
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
        redirect_target = _canonical_host_redirect(request)
        if redirect_target:
            return RedirectResponse(url=redirect_target, status_code=301)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", _content_security_policy())
        if _request_is_https(request):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.headers.get("Authorization") or request.headers.get("X-TradingAgents-User-Id") or request.url.path.startswith("/api/billing/"):
            # Plan-gated and member responses must never be shared through a public cache.
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif request.url.path.startswith("/lab/") or request.url.path in {"/member", "/mypage", "/admin", "/admin/members", "/billing"}:
            response.headers.setdefault("Cache-Control", "private, no-store")
        elif (
            request.url.path == "/"
            or request.url.path == "/analyses"
            or request.url.path.startswith("/analyses/")
            or request.url.path == "/outcomes"
            or request.url.path == "/harness"
            or request.url.path.startswith("/harness/")
            or request.url.path == "/stocks"
            or request.url.path.startswith("/stocks/")
            or request.url.path == "/features"
            or request.url.path.startswith("/features/")
            or request.url.path in {"/privacy", "/terms", "/disclaimer", "/pricing"}
            or request.url.path in {"/ads.txt", "/robots.txt", "/sitemap.xml", "/llms.txt", "/site.webmanifest"}
            or request.url.path.startswith("/og/")
            or request.url.path.endswith("/history")
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
        elif request.url.path.startswith("/api/simulations/"):
            seconds = request.app.state.public_cache_seconds
            response.headers.setdefault(
                "Cache-Control",
                f"public, max-age={seconds}, stale-while-revalidate={seconds * 2}",
            )
        elif request.url.path == "/api/screener" or request.url.path.startswith("/api/forecast/") or request.url.path.startswith("/api/harness/"):
            seconds = request.app.state.public_cache_seconds
            response.headers.setdefault(
                "Cache-Control",
                f"public, max-age={seconds}, stale-while-revalidate={seconds * 2}",
            )
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

    @app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
    def llms_txt(request: Request) -> PlainTextResponse:
        latest = None
        repo = request.app.state.repository
        if repo is not None:
            try:
                rows = repo.list_harness_runs(limit=1)
                if rows:
                    latest = str(rows[0].get("as_of_date") or "")[:10] or None
            except Exception:  # storage trouble must not break a text file
                latest = None
        return PlainTextResponse(build_llms_txt(site_base_url=_request_site_base_url(request), latest_run_date=latest), media_type="text/markdown; charset=utf-8")

    @app.get("/ads.txt", response_class=PlainTextResponse, include_in_schema=False)
    def ads_txt() -> PlainTextResponse:
        try:
            return PlainTextResponse(build_ads_txt())
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(favicon_ico(), media_type="image/x-icon", headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon_svg_route() -> Response:
        return Response(favicon_svg(), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/apple-touch-icon.png", include_in_schema=False)
    def apple_touch_icon() -> Response:
        return Response(icon_png(180), media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/icon-{size}.png", include_in_schema=False)
    def app_icon(size: int) -> Response:
        if size not in {32, 64, 96, 128, 192, 256, 512}:
            raise HTTPException(status_code=404, detail="icon size not available")
        return Response(icon_png(size), media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/site.webmanifest", include_in_schema=False)
    def site_webmanifest(request: Request) -> Response:
        return Response(json.dumps(web_manifest(site_base_url=_request_site_base_url(request)), ensure_ascii=False), media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/indexnow/{key}.txt", response_class=PlainTextResponse, include_in_schema=False)
    @app.get("/{key}.txt", response_class=PlainTextResponse, include_in_schema=False)
    def indexnow_key_file(key: str) -> PlainTextResponse:
        configured = indexnow_key()
        if not configured or key != configured:
            raise HTTPException(status_code=404, detail="Not found")
        return PlainTextResponse(configured)

    @app.post("/api/admin/seo/indexnow", include_in_schema=False)
    def indexnow_ping(
        body: IndexNowBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_operator(request, x_tradingagents_worker_token)
        return submit_indexnow(body.paths, site_base_url=_request_site_base_url(request))

    @app.post("/api/admin/seo/selfcheck", include_in_schema=False)
    def seo_selfcheck(
        body: IndexNowBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        """Fetch public paths on the canonical host from inside the deployment (operators only).

        Lets an operator on a restricted network confirm what search engines see:
        status, content type, size, latency and the first bytes of each response.
        """

        _require_operator(request, x_tradingagents_worker_token)
        import time

        import requests as _requests

        base = _request_site_base_url(request)
        results = []
        for path in body.paths[:20]:
            path = str(path)
            if not path.startswith("/"):
                path = "/" + path
            url = f"{base}{path}"
            started = time.monotonic()
            try:
                response = _requests.get(url, timeout=25, allow_redirects=False, headers={"User-Agent": "TradingAgentsKorea-selfcheck/1.0"})
                results.append({
                    "path": path,
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "location": response.headers.get("location"),
                    "bytes": len(response.content),
                    "seconds": round(time.monotonic() - started, 2),
                    "head": response.text[:160],
                })
            except Exception as exc:
                results.append({"path": path, "error": f"{exc.__class__.__name__}: {exc}", "seconds": round(time.monotonic() - started, 2)})
        return {"base": base, "results": results}

    @app.get("/api/admin/diagnostics/llm", include_in_schema=False)
    def admin_llm_diagnostics(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        """Report whether the configured LLM key is accepted, without revealing it."""

        _require_operator(request, x_tradingagents_worker_token)
        return _probe_llm_credentials()

    # ------------------------------------------------------ Open Graph images
    _OG_HEADERS = {"Cache-Control": "public, max-age=3600, stale-while-revalidate=86400"}

    def _og_footer(request: Request) -> str:
        base = _request_site_base_url(request)
        return base.split("://", 1)[-1].rstrip("/")

    @app.get("/og/default.png", include_in_schema=False)
    def og_default(request: Request) -> Response:
        png = render_og_image("코스피200·코스닥150을 매일 아침 규칙과 AI 토론으로 거르고, 모의투자로 검증합니다", "실계좌 주문 없음 · 5·20거래일 성과 공개 · 투자 조언 아님", "한국 주식 AI 리서치", (), _og_footer(request))
        return Response(png, media_type="image/png", headers=_OG_HEADERS)

    @app.get("/og/home.png", include_in_schema=False)
    def og_home(request: Request) -> Response:
        model = build_home_view_model(request.app.state.repository, site_base_url=_request_site_base_url(request))
        run = model.get("run") or {}
        decisions = model.get("decisions") or []
        ordered = [d for d in decisions if d.get("stage") in {"ordered", "exit"}]
        stats = og_stats([("대상 종목", f"{int(run.get('universe_size') or 0):,}" if run else "–"), ("후보", str(len(decisions)) if run else "–"), ("AI 토론 통과", str(len(ordered)) if run else "–"), ("모의 주문", str(int(run.get("order_count") or 0)) if run else "–")])
        png = render_og_image(str(model.get("headline") or "오늘의 선정 종목"), f"{model.get('run_date_text') or ''} 선별 · 강세·약세 AI 토론 · 모의투자 검증".strip(" ·"), "오늘의 선정 종목", stats, _og_footer(request))
        return Response(png, media_type="image/png", headers=_OG_HEADERS)

    @app.get("/og/harness.png", include_in_schema=False)
    @app.get("/og/harness/{harness_run_id}.png", include_in_schema=False)
    def og_harness(request: Request, harness_run_id: str | None = None) -> Response:
        payload = build_harness_run_payload(request.app.state.repository, harness_run_id=harness_run_id) if request.app.state.repository is not None else None
        run = (payload or {}).get("run") or {}
        summary = (payload or {}).get("summary") or {}
        if run:
            title = f"{run.get('as_of_date')} 종목 선별: 후보 {summary.get('decision_count', 0)}개 중 {summary.get('ordered_count', 0)}개 모의 주문"
            stats = og_stats([("대상 종목", f"{int(run.get('universe_size') or 0):,}"), ("후보", str(summary.get("decision_count", 0))), ("모의 주문", str(summary.get("ordered_count", 0))), ("탈락", str(summary.get("rejected_count", 0)))])
        else:
            title, stats = "종목 선별 기록", ()
        png = render_og_image(title, "규칙 점수 → 20일 예상 → AI 토론 → 모의 주문 → 5·20일 검증", "선별 기록", stats, _og_footer(request))
        return Response(png, media_type="image/png", headers=_OG_HEADERS)

    @app.get("/og/stocks/{ticker}.png", include_in_schema=False)
    def og_stock(ticker: str, request: Request) -> Response:
        if not is_kr_ticker(ticker):
            raise HTTPException(status_code=404, detail="Not found")
        model = build_ticker_history_model(request.app.state.repository, ticker=ticker, site_base_url=_request_site_base_url(request))
        latest = model.get("latest") or {}
        stats = og_stats([("선별 등장", f"{len(model['items'])}회"), ("AI 토론 통과", f"{len(model['passed'])}회"), ("마지막 판정", rating_label(latest.get("confirmation_rating")) or str(latest.get("stage_label") or "–")), ("판정일", str(latest.get("as_of_date") or "–"))])
        png = render_og_image(f"{model['name']}({ticker}) AI 판정 이력", model["answer"], f"{model['market']} 종목", stats, _og_footer(request))
        return Response(png, media_type="image/png", headers=_OG_HEADERS)

    @app.get("/og/{page}.png", include_in_schema=False)
    def og_page(page: str, request: Request) -> Response:
        titles = {
            "pricing": ("무료 · 데일리 패스 월 10,000원 · 프로 월 30,000원", "당일 선별 결과와 AI 토론 전문, 분석 요청 횟수를 넓히는 리서치 도구 요금제", "요금제"),
            "outcomes": ("선정 종목의 5·20거래일 성과 검증", "지수 대비 초과수익으로 확정한 공개 성적표", "성과 검증"),
            "analyses": ("종목별 AI 분석 리포트", "강세·약세 의견, 판정, 리스크 점검을 담은 공개 리포트", "AI 리포트"),
            "features": ("서비스 소개와 분석 기준", "선별 규칙, 예측 모델, 토론 절차, 리스크 한도", "분석 기준"),
        }
        if page not in titles:
            raise HTTPException(status_code=404, detail="Not found")
        title, subtitle, kicker = titles[page]
        return Response(render_og_image(title, subtitle, kicker, (), _og_footer(request)), media_type="image/png", headers=_OG_HEADERS)

    @app.get("/stocks/{ticker}/history", response_class=HTMLResponse, include_in_schema=False)
    def stock_history_page(ticker: str, request: Request) -> HTMLResponse:
        if not is_kr_ticker(ticker):
            raise HTTPException(status_code=404, detail="6자리 한국 종목코드가 필요합니다.")
        return HTMLResponse(render_ticker_history_page(ticker, repo=request.app.state.repository, site_base_url=_request_site_base_url(request)))

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap_xml(request: Request) -> Response:
        try:
            content = build_sitemap_xml(
                site_base_url=_request_site_base_url(request),
                tickers=_sitemap_tickers(request.app.state.repository),
                analysis_paths=_sitemap_analysis_paths(request.app.state.repository),
                harness_paths=_sitemap_harness_paths(request.app.state.repository),
                history_paths=_sitemap_history_paths(request.app.state.repository),
            )
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(content, media_type="application/xml")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(
        request: Request,
        ticker: Annotated[str, Query(pattern=r"^\d{6}$")] = "005930",
        legacy: bool = False,
    ) -> HTMLResponse:
        if ticker != "005930":
            return _stock_html_response(ticker, request)
        if legacy:
            return HTMLResponse(render_public_home_page(repo=request.app.state.repository, site_base_url=_request_site_base_url(request)))
        return HTMLResponse(render_home_page(repo=request.app.state.repository, site_base_url=_request_site_base_url(request)))

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

    @app.get("/harness", response_class=HTMLResponse, include_in_schema=False)
    def harness_page(request: Request) -> HTMLResponse:
        return HTMLResponse(render_harness_page(repo=request.app.state.repository, site_base_url=_request_site_base_url(request)))

    @app.get("/harness/{harness_run_id}", response_class=HTMLResponse, include_in_schema=False)
    def harness_detail_page(harness_run_id: str, request: Request) -> HTMLResponse:
        try:
            html = render_harness_page(
                repo=request.app.state.repository,
                harness_run_id=harness_run_id,
                site_base_url=_request_site_base_url(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(html)

    @app.get("/api/harness/runs")
    def harness_runs(request: Request, limit: int = 20) -> dict:
        try:
            return build_harness_runs_payload(
                request.app.state.repository,
                limit=limit,
                max_limit=request.app.state.max_analysis_feed_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/harness/runs/latest")
    def harness_latest_run(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        access = resolve_plan_access(repo, _optional_member_user_id(request, x_tradingagents_user_id))
        run_id = latest_visible_run_id(repo, access)
        payload = build_harness_run_payload(repo, harness_run_id=run_id) if run_id else build_harness_run_payload(repo)
        if payload is None:
            raise HTTPException(status_code=404, detail="No harness runs yet")
        return gate_harness_payload(payload, access)

    @app.get("/api/harness/runs/{harness_run_id}")
    def harness_run(
        harness_run_id: str,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        try:
            payload = build_harness_run_payload(repo, harness_run_id=harness_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if payload is None:
            raise HTTPException(status_code=404, detail="Harness run not found")
        access = resolve_plan_access(repo, _optional_member_user_id(request, x_tradingagents_user_id))
        return gate_harness_payload(payload, access)

    # ------------------------------------------------------------ billing
    @app.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
    def pricing_page(request: Request) -> HTMLResponse:
        return HTMLResponse(render_pricing_page(site_base_url=_request_site_base_url(request)))

    @app.get("/api/billing/plans")
    def billing_plans() -> dict:
        return {
            "status": "available",
            "mode": "research_tool",
            "plans": [PLANS[name].as_dict() for name in ("free", "daily", "pro")],
            "payment_configured": PortOneConfig.from_env().is_configured(),
            "notices": RESEARCH_TOOL_NOTICES,
        }

    @app.get("/api/billing/me")
    def billing_me(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        profile = resolve_member_profile(request, x_tradingagents_user_id)
        user_id = profile["id"]
        access = resolve_plan_access(repo, user_id)
        events = repo.list_billing_events(user_id=user_id, limit=10) if repo is not None else []
        return {
            "status": "available",
            "access": access.as_dict(),
            "role": profile["role"],
            "is_admin": bool(profile["is_admin"]),
            "events": [
                {"event_type": item.get("event_type"), "status": item.get("status"), "amount": item.get("amount"), "created_at": item.get("created_at"), "message": item.get("message")}
                for item in events
            ],
            "notices": RESEARCH_TOOL_NOTICES,
        }

    @app.post("/api/billing/trial")
    def billing_trial(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            return start_trial(repo, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/billing/checkout")
    def billing_checkout(
        body: CheckoutBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            return build_checkout_payload(user_id, body.plan, PortOneConfig.from_env(), redirect_url=f"{_request_site_base_url(request)}/mypage?billing=return")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PortOneError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/billing/cancel")
    def billing_cancel(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            return cancel_at_period_end(repo, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/billing/refund")
    def billing_refund(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        config = PortOneConfig.from_env()
        client = getattr(request.app.state, "portone_client", None) or PortOneClient(config)
        try:
            return request_refund(repo, user_id, client)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PortOneError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/billing/portone/webhook")
    async def portone_webhook(request: Request) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        raw = await request.body()
        config = PortOneConfig.from_env()
        try:
            verify_webhook_signature(request.headers, raw, config.webhook_secret)
        except PortOneError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        try:
            event = json.loads(raw.decode("utf-8") or "{}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        client = getattr(request.app.state, "portone_client", None) or PortOneClient(config)
        try:
            return handle_portone_webhook(repo, event, client)
        except PortOneError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/billing", response_class=HTMLResponse, include_in_schema=False)
    def billing_page(request: Request) -> HTMLResponse:
        return HTMLResponse(render_billing_page(site_base_url=_request_site_base_url(request)))

    # ------------------------------------------------------ member management (operators)
    @app.get("/admin/members", response_class=HTMLResponse, include_in_schema=False)
    def admin_members_page(request: Request) -> HTMLResponse:
        return HTMLResponse(render_admin_members_page(site_base_url=_request_site_base_url(request)))

    @app.get("/api/admin/members")
    def admin_members_list(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_operator(request, x_tradingagents_worker_token)
        repo = _require_repository(request)
        try:
            return list_members(repo, _supabase_admin_client(request))
        except SupabaseAdminError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/admin/members/{user_id}/plan")
    def admin_members_plan(
        user_id: str,
        body: MemberPlanBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        actor = _require_operator(request, x_tradingagents_worker_token)
        repo = _require_repository(request)
        _validate_uuid_param(user_id)
        try:
            result = grant_member_plan(repo, user_id, plan=body.plan, days=body.days, actor=actor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", **result}

    @app.post("/api/admin/members/{user_id}/role")
    def admin_members_role(
        user_id: str,
        body: MemberRoleBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_operator(request, x_tradingagents_worker_token)
        _validate_uuid_param(user_id)
        try:
            result = set_member_role(_supabase_admin_client(request), user_id, body.role)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SupabaseAdminError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "ok", **result}

    # ------------------------------------------------------ notifications
    @app.post("/api/notifications/telegram/link")
    def telegram_link(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        return create_link_code(repo, user_id, TelegramConfig.from_env())

    @app.delete("/api/notifications/telegram/link")
    def telegram_unlink(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        return unlink_channel(repo, user_id)

    @app.get("/api/notifications/telegram/status")
    def telegram_status(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        return channel_status(repo, user_id)

    @app.post("/api/notifications/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        config = TelegramConfig.from_env()
        if not config.webhook_secret or not x_telegram_bot_api_secret_token or not hmac.compare_digest(config.webhook_secret, x_telegram_bot_api_secret_token):
            raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")
        try:
            update = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        client = getattr(request.app.state, "telegram_client", None) or TelegramClient(config)
        return handle_telegram_update(repo, update if isinstance(update, dict) else {}, client)

    @app.post("/api/admin/notifications/telegram/setup")
    def telegram_setup(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        config = TelegramConfig.from_env()
        client = getattr(request.app.state, "telegram_client", None) or TelegramClient(config)
        try:
            me = client.get_me()
            webhook = client.set_webhook(f"{_request_site_base_url(request)}/api/notifications/telegram/webhook", secret_token=config.webhook_secret)
            info = client.get_webhook_info()
        except TelegramError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"status": "configured", "bot": {"username": me.get("username"), "id": me.get("id")}, "webhook": webhook, "secret_configured": bool(config.webhook_secret), "webhook_info": _webhook_info_summary(info)}

    @app.get("/api/admin/notifications/telegram/status")
    def telegram_admin_status(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        config = TelegramConfig.from_env()
        client = getattr(request.app.state, "telegram_client", None) or TelegramClient(config)
        try:
            info = client.get_webhook_info()
        except TelegramError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"status": "ok", "webhook_info": _webhook_info_summary(info)}

    @app.post("/api/admin/notifications/harness-issue")
    def admin_notify_harness_issue(
        request: Request,
        harness_run_id: str | None = None,
        force: bool = False,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _notify_harness_issue(request, harness_run_id=harness_run_id, force=force)

    @app.get("/api/cron/notify-harness-issue")
    def notify_harness_issue_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _notify_harness_issue(request)

    @app.post("/api/admin/notifications/exits")
    def admin_notify_exits(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _notify_generic(request, notify_exit_alerts)

    @app.get("/api/cron/notify-exits")
    def notify_exits_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _notify_generic(request, notify_exit_alerts)

    def _notify_journal(request: Request) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        max_tickers = request.app.state.max_price_tickers

        def price_loader(portfolio_id: str):
            return _portfolio_current_prices(repo, portfolio_id, current_prices=None, include_latest_prices=True, max_tickers=max_tickers)

        return _notify_generic(request, lambda repo_, client, site_base_url=None: notify_journal_alerts(repo_, client, site_base_url=site_base_url, price_loader=price_loader))

    @app.get("/api/cron/notify-weekly-report", include_in_schema=False)
    def notify_weekly_report_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        from .weekly_report import notify_weekly_report

        return _notify_generic(request, notify_weekly_report)

    @app.post("/api/admin/notifications/weekly-report")
    def admin_notify_weekly_report(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        from .weekly_report import notify_weekly_report

        return _notify_generic(request, notify_weekly_report)

    @app.post("/api/admin/notifications/disclosures")
    def admin_notify_disclosures(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        from .disclosure_alerts import notify_disclosure_alerts

        return _notify_generic(request, notify_disclosure_alerts)

    @app.get("/api/cron/notify-disclosures", include_in_schema=False)
    def notify_disclosures_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        from .disclosure_alerts import notify_disclosure_alerts

        return _notify_generic(request, notify_disclosure_alerts)

    @app.post("/api/admin/notifications/journal-targets")
    def admin_notify_journal_targets(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _notify_journal(request)

    @app.get("/api/cron/notify-journal-targets")
    def notify_journal_targets_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _notify_journal(request)

    @app.post("/api/admin/notifications/outcomes")
    def admin_notify_outcomes(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _notify_generic(request, notify_outcome_results)

    @app.get("/api/cron/notify-outcomes")
    def notify_outcomes_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _notify_generic(request, notify_outcome_results)

    @app.post("/api/admin/subscriptions/renew")
    def admin_subscription_renewals(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _process_subscription_renewals(request)

    @app.get("/api/cron/process-subscription-renewals")
    def process_subscription_renewals_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        return _process_subscription_renewals(request)

    @app.get("/api/harness/outcomes")
    def harness_outcomes(
        request: Request,
        ticker: str | None = None,
        status: Annotated[str | None, Query(pattern=r"^(pending|completed|unavailable)$")] = None,
        limit: int = 50,
    ) -> dict:
        try:
            return build_harness_outcomes_payload(
                request.app.state.repository,
                ticker_code=ticker,
                status=status,
                limit=limit,
                max_limit=max(request.app.state.max_analysis_feed_limit, 200),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/admin/harness-outcomes/process", include_in_schema=False)
    def process_harness_outcomes_admin(
        body: HarnessOutcomeWorkerRequestBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        _validate_outcome_horizons(body.horizons)
        if body.dry_run:
            decisions = repo.list_harness_decisions_for_outcomes(limit=body.limit)
            return {
                "status": "dry_run",
                "decision_count": len(decisions),
                "horizons": body.horizons,
                "items": [{"id": str(d["id"]), "ticker_code": d["ticker_code"], "as_of_date": d["as_of_date"], "existing_outcomes": len(d.get("outcomes") or [])} for d in decisions],
            }
        return _process_harness_outcomes(repo, limit=body.limit, horizons=body.horizons)

    @app.get("/api/cron/process-harness-outcomes", include_in_schema=False)
    def process_harness_outcomes_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        return _process_harness_outcomes(repo, limit=_harness_outcome_cron_limit(), horizons=[5, 20])

    @app.get("/api/harness/tickers/{ticker}")
    def harness_ticker_history(ticker: str, request: Request, limit: int = 20) -> dict:
        if not is_kr_ticker(ticker):
            raise HTTPException(status_code=400, detail="6자리 한국 종목코드가 필요합니다.")
        try:
            return build_harness_ticker_history_payload(request.app.state.repository, ticker_code=ticker, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/admin/harness/run", include_in_schema=False)
    def run_harness_admin(
        body: HarnessRunRequestBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        if not body.dry_run:
            raise HTTPException(status_code=400, detail="web harness runs are dry-run only; use the CLI for paper/KIS execution")
        return _run_harness(
            repo,
            confirmer=body.confirmer,
            confirm_top_n=body.confirm_top_n,
            top_n=body.top_n,
            markets=body.markets,
            as_of_date=body.as_of_date,
        )

    @app.get("/api/cron/run-harness", include_in_schema=False)
    def run_harness_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        return _run_harness(
            repo,
            confirmer=_harness_cron_confirmer(),
            confirm_top_n=_harness_cron_confirm_top_n(),
            top_n=20,
            markets=os.getenv("TRADINGAGENTS_HARNESS_MARKETS", "KOSPI,KOSDAQ"),
            as_of_date=None,
        )

    @app.get("/member", response_class=HTMLResponse, include_in_schema=False)
    def member_dashboard(request: Request) -> HTMLResponse:
        return HTMLResponse(render_member_dashboard_page(site_base_url=_request_site_base_url(request)))

    @app.get("/mypage", response_class=HTMLResponse, include_in_schema=False)
    def mypage(request: Request) -> HTMLResponse:
        return HTMLResponse(render_member_dashboard_page(site_base_url=_request_site_base_url(request), canonical_path="/mypage"))

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def admin_console(request: Request) -> HTMLResponse:
        return HTMLResponse(render_admin_console_page(site_base_url=_request_site_base_url(request)))

    @app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
    def privacy_page(request: Request) -> HTMLResponse:
        return HTMLResponse(render_policy_page("privacy", site_base_url=_request_site_base_url(request)))

    @app.get("/terms", response_class=HTMLResponse, include_in_schema=False)
    def terms_page(request: Request) -> HTMLResponse:
        return HTMLResponse(render_policy_page("terms", site_base_url=_request_site_base_url(request)))

    @app.get("/disclaimer", response_class=HTMLResponse, include_in_schema=False)
    def disclaimer_page(request: Request) -> HTMLResponse:
        return HTMLResponse(render_policy_page("disclaimer", site_base_url=_request_site_base_url(request)))

    @app.get("/features", response_class=HTMLResponse, include_in_schema=False)
    def feature_index(request: Request) -> HTMLResponse:
        return HTMLResponse(render_feature_index_page(site_base_url=_request_site_base_url(request)))

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
        chart_interval: str | None = None,
        max_analysis_age_days: int = 1,
    ) -> HTMLResponse:
        return _stock_html_response(
            ticker,
            request,
            chart_start=chart_start,
            chart_end=chart_end,
            as_of_date=as_of_date,
            chart_vendor=chart_vendor,
            chart_interval=chart_interval,
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
        chart_interval: str | None = None,
        include_chart: bool = True,
        include_analysis: bool = True,
        max_analysis_age_days: int = 1,
    ) -> dict:
        try:
            resolved_ticker = _resolve_public_stock_api_ticker(ticker)
            return build_public_stock_payload(
                resolved_ticker,
                repo=request.app.state.repository,
                chart_start=chart_start,
                chart_end=chart_end,
                as_of_date=as_of_date,
                chart_vendor=chart_vendor,
                chart_interval=chart_interval,
                include_chart=include_chart,
                include_analysis=include_analysis,
                max_analysis_age_days=max_analysis_age_days,
            )
        except (VendorUnavailableError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/simulations/preview/{ticker}")
    def simulation_preview(
        ticker: str,
        request: Request,
        as_of_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        chart_vendor: str | None = None,
        initial_cash: Annotated[float, Query(gt=0, le=1_000_000_000)] = 10_000_000.0,
        take_profit_pct: Annotated[float, Query(gt=0, le=1)] = 0.08,
        stop_loss_pct: Annotated[float, Query(gt=0, le=1)] = 0.05,
        max_holding_days: Annotated[int, Query(ge=1, le=120)] = 20,
        slippage_bps: Annotated[float, Query(ge=0, le=100)] = 3.0,
    ) -> dict:
        try:
            return build_public_simulation_preview_payload(
                request.app.state.repository,
                ticker=ticker,
                as_of_date=as_of_date,
                chart_vendor=chart_vendor,
                initial_cash=initial_cash,
                take_profit_pct=take_profit_pct,
                stop_loss_pct=stop_loss_pct,
                max_holding_days=max_holding_days,
                slippage_bps=slippage_bps,
            )
        except (VendorUnavailableError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/screener")
    def screener(
        as_of_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        markets: Annotated[str, Query(pattern=r"^(?i:kospi|kosdaq)(,(?i:kospi|kosdaq))*$")] = "KOSPI,KOSDAQ",
        top_n: Annotated[int, Query(ge=1, le=50)] = 20,
        min_market_cap: Annotated[float | None, Query(ge=0)] = None,
        max_per: Annotated[float | None, Query(gt=0)] = None,
    ) -> dict:
        try:
            return build_screener_payload(
                as_of_date=as_of_date,
                markets=markets,
                top_n=top_n,
                min_market_cap=min_market_cap,
                max_per=max_per,
            )
        except (VendorUnavailableError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/forecast/{ticker}")
    def forecast(
        ticker: str,
        as_of_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        horizon_days: Annotated[int, Query(ge=1, le=60)] = 20,
        chart_vendor: str | None = None,
    ) -> dict:
        try:
            return build_forecast_payload(
                ticker,
                as_of_date=as_of_date,
                horizon_days=horizon_days,
                chart_vendor=chart_vendor,
            )
        except (VendorUnavailableError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/paper", response_class=HTMLResponse, include_in_schema=False)
    def paper_account_page(request: Request) -> HTMLResponse:
        from .paper_account_page import render_paper_account_page

        return HTMLResponse(render_paper_account_page(repo=request.app.state.repository, site_base_url=_request_site_base_url(request)))

    @app.post("/api/member/paper-account/copy")
    def copy_paper_account_to_journal(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        """Copy the account's visible holdings into the member's own journal."""

        from tradingagents.harness.paper_state import build_combined_account_payload

        from .paper_copy import copy_account_holdings

        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        access = resolve_plan_access(repo, user_id)
        visible = gate_paper_account_payload(build_combined_account_payload(repo), access) or {}
        return copy_account_holdings(repo, user_id=user_id, positions=list(visible.get("positions") or []))

    @app.get("/lab/gold", response_class=HTMLResponse, include_in_schema=False)
    def gold_chart_page(
        request: Request,
        intervals: Annotated[str | None, Query(max_length=64)] = None,
        bars: Annotated[int, Query(ge=120, le=1200)] = 600,
    ) -> HTMLResponse:
        """A private pattern chart, apart from the product: no menu, no index."""

        from .gold_page import DEFAULT_INTERVALS, render_gold_chart_page

        wanted = tuple(part.strip() for part in (intervals or "").split(",") if part.strip()) or DEFAULT_INTERVALS
        html = render_gold_chart_page(repo=request.app.state.repository, intervals=wanted, bars=bars)
        return HTMLResponse(html, headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "private, no-store"})

    @app.get("/lab/gold/data", include_in_schema=False)
    def gold_chart_data(
        request: Request,
        interval: Annotated[str, Query(max_length=8)] = "1h",
        bars: Annotated[int, Query(ge=120, le=1200)] = 600,
    ) -> Response:
        """One timeframe, fetched now, for the chart's tabs and its refresh timer."""

        from goldlab.data import INTERVAL_MAX_DAYS

        from .gold_page import build_gold_frame

        if interval not in INTERVAL_MAX_DAYS:
            raise HTTPException(status_code=400, detail="unsupported interval")
        try:
            frame = build_gold_frame(repo=request.app.state.repository, interval=interval, bars=bars)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"quote source unavailable: {exc.__class__.__name__}") from exc
        return Response(
            json.dumps(frame, ensure_ascii=False),
            media_type="application/json",
            headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "private, no-store"},
        )

    @app.post("/api/admin/lab/gold/study", include_in_schema=False)
    def store_gold_study(
        body: GoldStudyBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        """Receive a measurement taken on the operator's machine.

        Measuring years of bars takes minutes, which no web request can spend,
        so the lab runs it locally and posts the result here for the page to
        quote.
        """

        _require_operator(request, x_tradingagents_worker_token)
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        from .gold_page import study_label

        study = body.study or {}
        run_id = repo.save_backtest_run(
            {
                "start_date": str(study.get("start") or "")[:10] or "1970-01-01",
                "end_date": str(study.get("end") or "")[:10] or "1970-01-01",
                "universe_size": int(study.get("bars") or 0),
                "metrics": {"study": study, "trade_count": len(study.get("patterns") or [])},
                "config": {"symbol": body.symbol, "interval": body.interval, "horizons": study.get("horizons")},
                "equity_curve": [],
                "trades": [],
                "notes": study.get("notes") or [],
            },
            label=study_label(body.symbol, body.interval),
        )
        return {"status": "stored", "id": run_id, "patterns": len(study.get("patterns") or [])}

    @app.get("/api/backtest")
    def backtest_latest(request: Request) -> dict:
        """The newest rule replay over history. Not the account's record."""

        repo = request.app.state.repository
        if repo is None:
            return {"status": "not_configured"}
        try:
            row = repo.latest_backtest_run()
        except Exception as exc:
            return {"status": "unavailable", "error": f"{exc.__class__.__name__}: {exc}"}
        if not row:
            return {"status": "empty"}
        return {
            "status": "available",
            "label": row.get("label"),
            "start_date": str(row.get("start_date") or ""),
            "end_date": str(row.get("end_date") or ""),
            "universe_size": row.get("universe_size"),
            "metrics": row.get("metrics_json") or {},
            "config": row.get("config_json") or {},
            "equity_curve": row.get("equity_curve_json") or [],
            "notes": row.get("notes") or [],
            "created_at": str(row.get("created_at") or ""),
        }

    @app.get("/api/factor-study")
    def factor_study_latest(request: Request) -> dict:
        """Whether each part of the rule score predicted the return that followed."""

        repo = request.app.state.repository
        if repo is None:
            return {"status": "not_configured"}
        try:
            row = repo.latest_backtest_run(label="factors")
        except Exception as exc:
            return {"status": "unavailable", "error": f"{exc.__class__.__name__}: {exc}"}
        if not row:
            return {"status": "empty"}
        metrics = row.get("metrics_json") or {}
        return {
            "status": "available",
            "start_date": str(row.get("start_date") or ""),
            "end_date": str(row.get("end_date") or ""),
            "universe_size": row.get("universe_size"),
            "horizon_days": metrics.get("horizon_days"),
            "sample_dates": metrics.get("sample_dates"),
            "factors": metrics.get("factors") or [],
            "notes": row.get("notes") or [],
        }

    @app.get("/api/paper-account/curve")
    def paper_account_curve(request: Request) -> dict:
        """Daily equity curve of the paper account against KOSPI (public)."""

        from .paper_snapshot_worker import build_paper_curve_payload

        return build_paper_curve_payload(request.app.state.repository)

    @app.get("/api/cron/record-paper-snapshot", include_in_schema=False)
    def record_paper_snapshot_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_worker_token(request, x_tradingagents_worker_token)
        from .paper_snapshot_worker import record_all_account_snapshots

        return record_all_account_snapshots(request.app.state.repository)

    @app.post("/api/admin/paper-account/snapshot", include_in_schema=False)
    def record_paper_snapshot_admin(
        request: Request,
        date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        _require_operator(request, x_tradingagents_worker_token)
        from .paper_snapshot_worker import record_paper_account_snapshot

        return record_paper_account_snapshot(request.app.state.repository, as_of=date)

    @app.get("/api/paper-account")
    def paper_account(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        """Holdings and closed trades of the harness paper account (read-only).

        Same-day entries and exits are the paid layer; free callers get the
        settled record plus a count of what is withheld.
        """

        from tradingagents.harness.paper_state import build_combined_account_payload

        repo = request.app.state.repository
        access = resolve_plan_access(repo, _optional_member_user_id(request, x_tradingagents_user_id))
        return gate_paper_account_payload(build_combined_account_payload(repo), access)

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

    @app.get("/api/prices/sparkline")
    def price_sparklines(
        request: Request,
        tickers: Annotated[str, Query(description="Comma-separated Korean ticker codes")],
        days: int = 60,
    ) -> dict:
        try:
            return build_sparkline_payload(tickers.split(","), days=days, max_tickers=request.app.state.max_price_tickers)
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

    @app.patch("/api/portfolios/{portfolio_id}")
    def update_manual_portfolio(
        portfolio_id: str,
        body: ManualPortfolioUpdateBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = _require_repository(request)
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_portfolio_owner(repo, portfolio_id, user_id)
        try:
            portfolio = repo.update_manual_portfolio(portfolio_id=portfolio_id, name=body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        return {"status": "updated", "portfolio": {"id": str(portfolio.get("id")), "name": portfolio.get("name"), "base_currency": portfolio.get("base_currency")}}

    @app.delete("/api/portfolios/{portfolio_id}")
    def delete_manual_portfolio(
        portfolio_id: str,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = _require_repository(request)
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_portfolio_owner(repo, portfolio_id, user_id)
        try:
            repo.delete_manual_portfolio(portfolio_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "deleted", "portfolio_id": portfolio_id}

    @app.delete("/api/portfolios/{portfolio_id}/trades/{trade_id}")
    def delete_manual_trade(
        portfolio_id: str,
        trade_id: str,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = _require_repository(request)
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_portfolio_owner(repo, portfolio_id, user_id)
        try:
            removed = repo.delete_manual_trade(portfolio_id=portfolio_id, trade_id=trade_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail="Trade not found")
        return {"status": "deleted", "trade_id": trade_id}

    @app.delete("/api/portfolios/{portfolio_id}/targets/{ticker_code}")
    def delete_manual_price_target(
        portfolio_id: str,
        ticker_code: str,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = _require_repository(request)
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_portfolio_owner(repo, portfolio_id, user_id)
        try:
            removed = repo.delete_price_target(portfolio_id=portfolio_id, ticker_code=ticker_code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail="Price target not found")
        return {"status": "deleted", "ticker_code": ticker_code.upper()}

    @app.get("/api/member/preferences")
    def member_preferences_read(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        from .member_preferences import normalize

        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            stored = repo.get_member_preferences(user_id)
        except Exception:
            stored = None
        merged = dict(stored or {})
        merged.setdefault("excluded_sectors", (merged.get("metadata_json") or {}).get("excluded_sectors") or [])
        return {"status": "available", "preferences": normalize(merged if stored else None), "saved": stored is not None}

    @app.put("/api/member/preferences")
    def member_preferences_write(
        body: MemberPreferencesBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        from .member_preferences import normalize

        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        cleaned = normalize(body.model_dump())
        repo.save_member_preferences(user_id, cleaned)
        return {"status": "saved", "preferences": cleaned}

    @app.get("/api/member/picks")
    def member_picks(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        """The picks this member may see, narrowed to their own conditions."""

        from .member_preferences import filter_picks

        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        access = resolve_plan_access(repo, user_id)
        run_id = latest_visible_run_id(repo, access)
        payload = gate_harness_payload(build_harness_run_payload(repo, harness_run_id=run_id) if run_id else None, access) or {}
        picks = [item for item in (payload.get("decisions") or []) if str(item.get("stage") or "") in {"ordered", "exit"}]
        try:
            stored = repo.get_member_preferences(user_id)
        except Exception:
            stored = None
        if stored:
            stored = {**stored, "excluded_sectors": (stored.get("metadata_json") or {}).get("excluded_sectors") or []}
        result = filter_picks(picks, stored)
        run = payload.get("run") or {}
        return {
            "status": "available" if picks else "empty",
            "as_of_date": run.get("as_of_date"),
            "run_path": f"/harness/{run.get('id')}" if run.get("id") else None,
            "plan_gate": payload.get("plan_gate"),
            **result,
        }

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

    @app.get("/api/member/paper-simulations")
    def member_paper_simulations(
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
        limit: int = 20,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        try:
            return build_member_paper_simulation_payload(
                repo,
                user_id=user_id,
                limit=limit,
                max_limit=request.app.state.max_analysis_feed_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        access = resolve_plan_access(repo, user_id)
        active_limit, daily_limit = _plan_request_limits(access)
        try:
            return queue_analysis_refresh_request(
                repo,
                ticker=body.ticker,
                user_id=user_id,
                requested_trade_date=body.requested_trade_date,
                reason=body.reason,
                active_limit=active_limit,
                daily_limit=daily_limit,
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

    @app.get("/api/admin/ops-summary", include_in_schema=False)
    def admin_ops_summary(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        return _admin_ops_summary(repo)

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
        if body.dry_run:
            effective_limit = min(body.limit, max_limit)
            queued = repo.list_analysis_requests(status="queued", limit=effective_limit)
            payload: dict[str, object] = {
                "status": "dry_run",
                "item_count": len(queued),
                "items": queued,
                "limit": effective_limit,
                "requested_limit": body.limit,
                "max_limit": max_limit,
            }
            if body.limit > max_limit:
                payload["notice"] = f"처리 한도 {max_limit}건에 맞춰 실행 전 확인 범위를 조정했습니다."
            return payload
        if body.limit > max_limit:
            raise HTTPException(status_code=400, detail=f"limit cannot exceed {max_limit}")

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
        _validate_outcome_horizons(body.horizons)
        if body.dry_run:
            effective_limit = min(body.limit, max_limit)
            runs = repo.list_public_analysis_runs(limit=effective_limit)
            payload: dict[str, object] = {
                "status": "dry_run",
                "run_count": len(runs),
                "horizons": body.horizons,
                "estimated_outcome_count": len(runs) * len(body.horizons),
                "inspect_path": "/api/analysis-outcomes",
                "items": runs,
                "limit": effective_limit,
                "requested_limit": body.limit,
                "max_limit": max_limit,
            }
            if body.limit > max_limit:
                payload["notice"] = f"처리 한도 {max_limit}건에 맞춰 실행 전 확인 범위를 조정했습니다."
            return payload
        if body.limit > max_limit:
            raise HTTPException(status_code=400, detail=f"limit cannot exceed {max_limit}")
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

    @app.post("/api/admin/paper-simulations/process", include_in_schema=False)
    def process_paper_simulations_admin(
        body: PaperSimulationWorkerRequestBody,
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        max_limit = _max_paper_simulation_worker_limit()
        if body.dry_run:
            effective_limit = min(body.limit, max_limit)
            candidates = repo.list_paper_simulation_candidates(limit=effective_limit)
            open_positions = repo.list_open_paper_simulation_positions(limit=effective_limit)
            payload: dict[str, object] = {
                "status": "dry_run",
                "item_count": len(candidates) + len(open_positions),
                "candidate_count": len(candidates),
                "open_position_count": len(open_positions),
                "mode": "paper_simulation",
                "execution_boundary": "simulation_only_no_orders",
                "execution_boundary_label": EXECUTION_BOUNDARY_LABEL,
                "items": [_admin_paper_candidate_preview(row) for row in candidates],
                "open_positions": [_admin_paper_open_preview(row) for row in open_positions],
                "limit": effective_limit,
                "requested_limit": body.limit,
                "max_limit": max_limit,
            }
            if body.limit > max_limit:
                payload["notice"] = f"처리 한도 {max_limit}건에 맞춰 실행 전 확인 범위를 조정했습니다."
            return payload
        if body.limit > max_limit:
            raise HTTPException(status_code=400, detail=f"limit cannot exceed {max_limit}")
        return _process_paper_simulations(repo, limit=body.limit, as_of_date=body.as_of_date)

    @app.get("/api/cron/process-paper-simulations", include_in_schema=False)
    def process_paper_simulations_cron(
        request: Request,
        x_tradingagents_worker_token: Annotated[str | None, Header(alias="X-TradingAgents-Worker-Token")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        _require_worker_token(request, x_tradingagents_worker_token)
        return _process_paper_simulations(repo, limit=_paper_simulation_cron_worker_limit())

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

    @app.patch("/api/watchlists/{watchlist_id}")
    def update_manual_watchlist(
        watchlist_id: str,
        body: WatchlistUpdateBody,
        request: Request,
        x_tradingagents_user_id: Annotated[str | None, Header(alias="X-TradingAgents-User-Id")] = None,
    ) -> dict:
        repo = request.app.state.repository
        if repo is None:
            raise HTTPException(status_code=503, detail="Storage repository is not configured")
        user_id = resolve_member_user_id(request, x_tradingagents_user_id)
        _require_watchlist_owner(repo, watchlist_id, user_id)
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="watchlist name cannot be empty")
        try:
            watchlist = repo.update_watchlist(watchlist_id=watchlist_id, name=name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if watchlist is None:
            raise HTTPException(status_code=404, detail="Watchlist not found")
        return {"status": "updated", "watchlist": watchlist}

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

    # catch-all for search-console ownership files: registered last so it never shadows page routes
    @app.get("/{verification_file}", include_in_schema=False)
    def search_console_verification_file(verification_file: str) -> Response:
        if verification_file.startswith("google") and verification_file.endswith(".html") or verification_file.startswith("naver") and verification_file.endswith(".html") or verification_file == "BingSiteAuth.xml" or verification_file.startswith("yandex_"):
            try:
                files = verification_files()
            except ValueError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            content = files.get(verification_file)
            if content:
                media = "text/xml; charset=utf-8" if verification_file.endswith(".xml") else "text/html; charset=utf-8"
                return Response(content, media_type=media, headers={"Cache-Control": "public, max-age=3600"})
        raise HTTPException(status_code=404, detail="Not found")

    return app


def _stock_html_response(
    ticker: str,
    request: Request,
    *,
    chart_start: str | None = None,
    chart_end: str | None = None,
    as_of_date: str | None = None,
    chart_vendor: str | None = None,
    chart_interval: str | None = None,
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
            chart_interval=chart_interval,
            max_analysis_age_days=max_analysis_age_days,
            site_base_url=_request_site_base_url(request),
        )
    except (VendorUnavailableError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse(html)


def _resolve_stock_lookup(value: str) -> str:
    query = value.strip()
    if not query:
        raise ValueError("검색어를 입력해 주세요.")
    if query.isdigit() and len(query) == 6:
        return query
    results = build_ticker_search_payload(query, limit=1)["items"]
    if not results:
        raise ValueError("일치하는 한국 종목을 찾지 못했습니다.")
    return str(results[0]["code"])


def _resolve_public_stock_api_ticker(value: str) -> str:
    query = value.strip()
    if is_kr_ticker(query):
        return query
    try:
        return _resolve_stock_lookup(query)
    except ValueError as exc:
        raise VendorUnavailableError(
            "공개 종목 API는 6자리 종목코드 또는 한국 종목명을 지원합니다."
        ) from exc


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


def _canonical_host_redirect(request: Request) -> str | None:
    """301 to the canonical host (TRADINGAGENTS_CANONICAL_HOST) for public page requests.

    API, cron and health paths are left alone so Vercel crons and workers keep
    hitting the deployment URL; local and test hosts never redirect.
    """

    canonical = (os.getenv("TRADINGAGENTS_CANONICAL_HOST") or "").strip().lower().rstrip("/")
    if not canonical:
        return None
    if "://" in canonical:
        canonical = urlparse(canonical).netloc.lower()
    request_host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip().lower()
    if not request_host or request_host == canonical:
        return None
    if request_host == "testserver" or request_host.startswith(("localhost", "127.0.0.1")):
        return None
    path = request.url.path
    # The lab is private and unindexed, so it has no canonical host to be sent
    # to, and leaving it alone keeps it reachable on the deployment URL too.
    if path.startswith(("/api/", "/health", "/indexnow/", "/lab/")) or path == "/BingSiteAuth.xml" or (path.startswith(("/google", "/naver", "/yandex_")) and path.endswith(".html")):
        return None
    query = f"?{request.url.query}" if request.url.query else ""
    return f"https://{canonical}{path}{query}"


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


def _sitemap_harness_paths(repo: StorageRepository | None) -> tuple[str, ...]:
    if repo is None:
        return ()
    try:
        rows = repo.list_harness_runs(limit=60)
    except Exception:
        return ()
    return tuple(f"/harness/{row['id']}" for row in rows if row.get("id"))


def _sitemap_history_paths(repo: StorageRepository | None) -> tuple[str, ...]:
    if repo is None:
        return ()
    try:
        rows = repo.list_harness_decisions(limit=400)
    except Exception:
        return ()
    codes = []
    for row in rows:
        code = str(row.get("ticker_code") or "")
        if code and code not in codes:
            codes.append(code)
    return tuple(f"/stocks/{code}/history" for code in codes[:200])


def _sitemap_max_analysis_tickers() -> int:
    raw = int(os.getenv("TRADINGAGENTS_SITEMAP_MAX_ANALYSIS_TICKERS", "200"))
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_SITEMAP_MAX_ANALYSIS_TICKERS must be positive")
    return raw


def _admin_ops_summary(repo: StorageRepository) -> dict[str, object]:
    request_statuses = ("queued", "running", "completed", "failed", "skipped")
    request_counts = {
        status: repo.count_analysis_requests(statuses=(status,))
        for status in request_statuses
    }
    recent_requests = {
        status: [_admin_request_preview(row) for row in repo.list_analysis_requests(status=status, limit=5)]
        for status in ("queued", "running", "failed", "completed")
    }
    outcome_candidates = repo.list_public_analysis_runs(limit=5)
    recent_outcomes = repo.list_analysis_outcomes(status="completed", limit=5, public_only=True)
    pending_outcomes = repo.list_analysis_outcomes(status="pending", limit=5, public_only=True)
    unavailable_outcomes = repo.list_analysis_outcomes(status="unavailable", limit=5, public_only=True)
    paper_candidates = repo.list_paper_simulation_candidates(limit=5)
    open_paper_positions = repo.list_open_paper_simulation_positions(limit=5)
    open_paper_count = repo.count_paper_simulation_positions(statuses=("open",))
    closed_paper_count = repo.count_paper_simulation_positions(statuses=("closed",))
    return {
        "status": "available",
        "analysis_requests": {
            "counts": request_counts,
            "recent": recent_requests,
            "active_count": request_counts["queued"] + request_counts["running"],
            "failed_count": request_counts["failed"],
        },
        "outcomes": {
            "candidate_runs": [_admin_run_preview(row) for row in outcome_candidates],
            "recent_completed": [_admin_outcome_preview(row) for row in recent_outcomes],
            "recent_pending": [_admin_outcome_preview(row) for row in pending_outcomes],
            "recent_unavailable": [_admin_outcome_preview(row) for row in unavailable_outcomes],
            "pending_sample_count": len(pending_outcomes),
            "unavailable_sample_count": len(unavailable_outcomes),
        },
        "paper_simulations": {
            "candidate_runs": [_admin_paper_candidate_preview(row) for row in paper_candidates],
            "open_positions": [_admin_paper_open_preview(row) for row in open_paper_positions],
            "open_count": open_paper_count,
            "closed_count": closed_paper_count,
            "candidate_sample_count": len(paper_candidates),
            "open_sample_count": len(open_paper_positions),
        },
        "limits": {
            "analysis_worker_max": _max_worker_limit(),
            "outcome_worker_max": _max_outcome_worker_limit(),
            "paper_simulation_worker_max": _max_paper_simulation_worker_limit(),
            "analysis_cron_limit": _cron_worker_limit(),
            "outcome_cron_limit": _outcome_cron_worker_limit(),
            "paper_simulation_cron_limit": _paper_simulation_cron_worker_limit(),
        },
        "inspect_paths": {
            "analysis_requests": "/api/admin/analysis-requests/process",
            "outcomes": "/api/admin/analysis-outcomes/process",
            "paper_simulations": "/api/admin/paper-simulations/process",
            "public_outcomes": "/api/analysis-outcomes",
        },
    }


def _admin_request_preview(row: dict[str, Any]) -> dict[str, object]:
    analysis_run_id = str(row.get("analysis_run_id") or "")
    return {
        "id": str(row.get("id") or ""),
        "ticker_code": row.get("ticker_code"),
        "ticker_name": row.get("ticker_name"),
        "market": row.get("market"),
        "status": row.get("status"),
        "requested_trade_date": row.get("requested_trade_date"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "analysis_run_id": analysis_run_id or None,
        "report_path": f"/analyses/{analysis_run_id}" if analysis_run_id else None,
        "reason": row.get("reason"),
    }


def _admin_run_preview(row: dict[str, Any]) -> dict[str, object]:
    run_id = str(row.get("id") or "")
    return {
        "id": run_id,
        "ticker_code": row.get("ticker_code"),
        "ticker_name": row.get("ticker_name"),
        "market": row.get("market"),
        "trade_date": row.get("trade_date"),
        "status": row.get("status"),
        "report_path": f"/analyses/{run_id}" if run_id else None,
    }


def _admin_outcome_preview(row: dict[str, Any]) -> dict[str, object]:
    run_id = str(row.get("analysis_run_id") or "")
    return {
        "id": str(row.get("id") or ""),
        "analysis_run_id": run_id,
        "ticker_code": row.get("ticker_code"),
        "ticker_name": row.get("ticker_name"),
        "market": row.get("market"),
        "trade_date": row.get("trade_date"),
        "evaluated_at": row.get("evaluated_at"),
        "horizon_days": row.get("horizon_days"),
        "actual_holding_days": row.get("actual_holding_days"),
        "status": row.get("status"),
        "alpha_return": row.get("alpha_return"),
        "error": row.get("error"),
        "report_path": f"/analyses/{run_id}" if run_id else None,
    }


def _admin_paper_candidate_preview(row: dict[str, Any]) -> dict[str, object]:
    run_id = str(row.get("analysis_run_id") or "")
    return {
        "analysis_run_id": run_id,
        "analysis_request_id": str(row.get("analysis_request_id") or "") or None,
        "user_id": str(row.get("user_id") or "") or None,
        "ticker_code": row.get("ticker_code"),
        "ticker_name": row.get("ticker_name"),
        "market": row.get("market"),
        "trade_date": row.get("trade_date"),
        "decision_rating": row.get("decision_rating"),
        "decision_action": row.get("decision_action"),
        "target_weight": row.get("target_weight"),
        "report_path": f"/analyses/{run_id}" if run_id else None,
    }


def _admin_paper_open_preview(row: dict[str, Any]) -> dict[str, object]:
    run_id = str(row.get("analysis_run_id") or "")
    metadata = row.get("metadata_json") or {}
    return {
        "id": str(row.get("id") or ""),
        "analysis_run_id": run_id or None,
        "user_id": str(row.get("user_id") or "") or None,
        "ticker_code": row.get("ticker_code"),
        "ticker_name": row.get("ticker_name"),
        "market": row.get("market"),
        "status": row.get("status"),
        "entry_date": row.get("entry_date"),
        "entry_price": row.get("entry_price"),
        "target_price": row.get("target_price"),
        "stop_price": row.get("stop_price"),
        "mark_date": metadata.get("mark_date"),
        "unrealized_return": metadata.get("unrealized_return"),
        "report_path": f"/analyses/{run_id}" if run_id else None,
    }


def _process_analysis_request_queue(repo: StorageRepository, *, limit: int) -> dict:
    from .analysis_runner import run_tradingagents_graph_for_request
    from .analysis_worker import process_queued_analysis_requests

    results = process_queued_analysis_requests(
        repo,
        lambda queued_request: run_tradingagents_graph_for_request(
            queued_request,
            config={"database_url": os.getenv("DATABASE_URL")},
            repo=repo,
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


def _process_paper_simulations(repo: StorageRepository, *, limit: int, as_of_date: str | None = None) -> dict:
    from .paper_simulation_worker import process_paper_simulations, summarize_paper_simulation_results

    results = process_paper_simulations(repo, limit=limit, as_of_date=as_of_date)
    return {
        "status": "processed",
        "mode": "paper_simulation",
        "execution_boundary": "simulation_only_no_orders",
        "execution_boundary_label": EXECUTION_BOUNDARY_LABEL,
        "item_count": len(results),
        "summary": summarize_paper_simulation_results(results),
        "inspect_path": "/api/member/paper-simulations",
        "results": [result.__dict__ for result in results],
    }


def _run_harness(
    repo: StorageRepository,
    *,
    confirmer: str,
    confirm_top_n: int,
    top_n: int,
    markets: str,
    as_of_date: str | None,
) -> dict:
    from .harness_api import run_harness_for_web

    try:
        return run_harness_for_web(
            repo,
            confirmer=confirmer,
            confirm_top_n=confirm_top_n,
            top_n=top_n,
            markets=markets,
            as_of_date=as_of_date,
        )
    except (VendorUnavailableError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _process_harness_outcomes(repo: StorageRepository, *, limit: int, horizons: list[int]) -> dict:
    from .harness_outcome_worker import evaluate_harness_outcomes, summarize_harness_outcome_results

    results = evaluate_harness_outcomes(repo, limit=limit, horizons=horizons)
    return {
        "status": "processed",
        "mode": "harness_outcomes",
        "item_count": len(results),
        "horizons": horizons,
        "summary": summarize_harness_outcome_results(results),
        "inspect_path": "/api/harness/outcomes",
        "results": [result.__dict__ for result in results],
    }


def _harness_outcome_cron_limit() -> int:
    raw = int(os.getenv("TRADINGAGENTS_HARNESS_OUTCOME_CRON_LIMIT", "50"))
    if raw <= 0 or raw > 200:
        raise HTTPException(status_code=400, detail="TRADINGAGENTS_HARNESS_OUTCOME_CRON_LIMIT must be between 1 and 200")
    return raw


def _harness_cron_confirmer() -> str:
    value = os.getenv("TRADINGAGENTS_HARNESS_CRON_CONFIRMER", "none").strip().lower()
    if value not in SUPPORTED_WEB_CONFIRMERS:
        raise HTTPException(status_code=400, detail=f"TRADINGAGENTS_HARNESS_CRON_CONFIRMER must be one of {', '.join(SUPPORTED_WEB_CONFIRMERS)}")
    return value


def _harness_cron_confirm_top_n() -> int:
    raw = int(os.getenv("TRADINGAGENTS_HARNESS_CRON_CONFIRM_TOP_N", "3"))
    if raw <= 0 or raw > 10:
        raise HTTPException(status_code=400, detail="TRADINGAGENTS_HARNESS_CRON_CONFIRM_TOP_N must be between 1 and 10")
    return raw


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


# Ad networks fan out across many hosts, and Google's consent platform is one
# more: without it the EEA consent message cannot render and those readers see
# no ads at all. These stay out of the policy entirely
# until a publisher ID is configured, so a site without ads keeps the tight one.
_AD_SCRIPT_HOSTS = "https://pagead2.googlesyndication.com https://*.googlesyndication.com https://*.googleadservices.com https://adservice.google.com https://www.googletagservices.com https://fundingchoicesmessages.google.com"
_AD_FRAME_HOSTS = "https://googleads.g.doubleclick.net https://*.googlesyndication.com https://*.doubleclick.net https://fundingchoicesmessages.google.com"
_AD_IMG_HOSTS = "https://*.googlesyndication.com https://*.googleadservices.com https://*.doubleclick.net https://*.google.com https://*.gstatic.com"
_AD_CONNECT_HOSTS = "https://pagead2.googlesyndication.com https://*.googlesyndication.com https://*.doubleclick.net https://ep1.adtrafficquality.google https://ep2.adtrafficquality.google https://fundingchoicesmessages.google.com"


def _ads_enabled() -> bool:
    from .seo import normalize_adsense_publisher_id

    try:
        return bool(normalize_adsense_publisher_id())
    except ValueError:
        return False


def _content_security_policy() -> str:
    ads = _ads_enabled()
    script = "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.portone.io https://cdn.iamport.kr"
    img = "img-src 'self' data: https://*.portone.io https://*.iamport.co https://*.iamport.kr"
    frame = "frame-src 'self' https://*.portone.io https://*.iamport.co https://*.iamport.kr https://*.tosspayments.com https://*.kakao.com https://*.kakaopay.com https://*.naver.com https://*.inicis.com https://*.nicepay.co.kr"
    connect = "connect-src 'self' https://*.supabase.co https://*.supabase.com https://*.portone.io https://*.iamport.co https://*.iamport.kr https://*.tosspayments.com"
    if ads:
        script = f"{script} {_AD_SCRIPT_HOSTS}"
        img = f"{img} {_AD_IMG_HOSTS}"
        frame = f"{frame} {_AD_FRAME_HOSTS}"
        connect = f"{connect} {_AD_CONNECT_HOSTS}"
    return (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        f"{img}; "
        "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        f"{script}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        f"{frame}; "
        f"{connect}"
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
        missing["worker_token_configured"] = [
            "TRADINGAGENTS_WORKER_TOKEN or DASHBOARD_ADMIN_TOKEN or OPERATOR_ACCESS_CODE or CRON_SECRET"
        ]
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
    configured_probe_date = os.getenv("TRADINGAGENTS_READINESS_KRX_PROBE_DATE")
    probe_dates = (
        [configured_probe_date.strip()]
        if configured_probe_date and configured_probe_date.strip()
        else _recent_korea_business_dates()
    )
    result: dict[str, object] = {
        "vendor": "krx",
        "probe": "daily_ohlcv",
        "ticker": probe_symbol,
        "date": probe_dates[0],
        "attempted_dates": probe_dates,
        "row_count": 0,
        "request_count": 0,
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
    empty_dates: list[str] = []
    for probe_date in probe_dates:
        result["request_count"] = int(result["request_count"]) + 1
        try:
            frame = krx_openapi.get_ohlcv_frame(probe_symbol, probe_date, probe_date)
        except Exception as exc:
            result.update(
                {
                    "date": probe_date,
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
        result.update({"date": probe_date, "elapsed_ms": _elapsed_ms(started), "row_count": row_count})
        if frame is not None and not frame.empty:
            result["status"] = "ok"
            return result
        empty_dates.append(probe_date)

    result.update(
        {
            "status": "empty",
            "empty_dates": empty_dates,
            "error": f"KRX Open API returned no rows for {probe_symbol} on recent dates: {', '.join(empty_dates)}",
        }
    )
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


def _probe_llm_credentials() -> dict:
    """Check the OpenAI key's shape and whether the provider accepts it.

    Only the key's shape is reported (length, prefix, stray quotes or spaces):
    a pasted key with wrapping quotes or a trailing newline fails exactly like a
    revoked one, and the two need different fixes.
    """

    import requests as _http

    from tradingagents.default_config import DEFAULT_CONFIG

    from .analysis_worker import scrub_failure_reason

    raw = os.getenv("OPENAI_API_KEY") or ""
    trimmed = raw.strip()
    unquoted = trimmed.strip('"').strip("'")
    shape = {
        "configured": bool(raw),
        "length": len(raw),
        "trimmed_length": len(trimmed),
        "has_surrounding_whitespace": raw != trimmed,
        "wrapped_in_quotes": trimmed != unquoted,
        "prefix": unquoted[:7] if unquoted else None,
    }
    if not unquoted:
        return {"status": "not_configured", "key": shape}
    base_url = (os.getenv("OPENAI_BASE_URL") or DEFAULT_CONFIG.get("backend_url") or "https://api.openai.com/v1").rstrip("/")
    started = time.monotonic()
    try:
        response = _http.get(f"{base_url}/models", headers={"Authorization": f"Bearer {unquoted}"}, timeout=20)
    except Exception as exc:
        return {"status": "probe_failed", "key": shape, "base_url": base_url, "error": f"{exc.__class__.__name__}: {exc}"}
    detail = None
    if response.status_code >= 400:
        detail = scrub_failure_reason(response.text, limit=200)
    return {
        "status": "accepted" if response.status_code < 400 else "rejected",
        "key": shape,
        "base_url": base_url,
        "http_status": response.status_code,
        "detail": detail,
        "seconds": round(time.monotonic() - started, 2),
    }


def _deployment_context() -> dict[str, str | None]:
    git_sha = _short_sha(os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("TRADINGAGENTS_DEPLOYMENT_SHA"))
    deployment_id = _non_empty_env("VERCEL_DEPLOYMENT_ID")
    vercel_url = _non_empty_env("VERCEL_URL")
    trace_source, trace_id = _deployment_trace(
        git_sha=git_sha,
        deployment_id=deployment_id,
        vercel_url=vercel_url,
    )
    return {
        "vercel_env": _non_empty_env("VERCEL_ENV"),
        "target_env": _non_empty_env("VERCEL_TARGET_ENV"),
        "git_ref": _non_empty_env("VERCEL_GIT_COMMIT_REF") or _non_empty_env("TRADINGAGENTS_DEPLOYMENT_REF"),
        "git_sha": git_sha,
        "deployment_id": deployment_id,
        "vercel_url": vercel_url,
        "production_url": _non_empty_env("VERCEL_PROJECT_PRODUCTION_URL"),
        "region": _non_empty_env("VERCEL_REGION"),
        "trace_source": trace_source,
        "trace_id": trace_id,
    }


def _deployment_trace(
    *,
    git_sha: str | None,
    deployment_id: str | None,
    vercel_url: str | None,
) -> tuple[str | None, str | None]:
    if git_sha:
        return "git_sha", git_sha
    if deployment_id:
        return "deployment_id", deployment_id
    if vercel_url:
        return "vercel_url", vercel_url
    return None, None


def _non_empty_env(name: str) -> str | None:
    value = os.getenv(name)
    if not value:
        return None
    value = value.strip()
    return value or None


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


def _recent_korea_business_dates(limit: int = 5) -> list[str]:
    dates: list[str] = []
    current = datetime.now(ZoneInfo("Asia/Seoul")).date() - timedelta(days=1)
    while len(dates) < limit:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current -= timedelta(days=1)
    return dates


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
    paper_simulations: dict = {"status": "unavailable", "limit": list_limit, "positions": [], "item_count": 0}

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

    try:
        paper_simulations = build_member_paper_simulation_payload(
            repo,
            user_id=user_id,
            limit=list_limit,
            max_limit=max_list_limit,
        )
    except Exception as exc:
        errors["paper_simulations"] = _safe_error_name(exc)

    return {
        "status": "partial" if errors else "available",
        "member": {"user_id": user_id},
        "portfolios": portfolios,
        "portfolio_details": portfolio_details,
        "watchlists": watchlists,
        "watchlist_details": watchlist_details,
        "analysis_requests": analysis_requests,
        "paper_simulations": paper_simulations,
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


def _max_paper_simulation_worker_limit() -> int:
    raw = int(os.getenv("TRADINGAGENTS_PAPER_SIMULATION_WORKER_MAX_RUNS", "20"))
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_PAPER_SIMULATION_WORKER_MAX_RUNS must be positive")
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


def _paper_simulation_cron_worker_limit() -> int:
    max_limit = _max_paper_simulation_worker_limit()
    raw = int(os.getenv("TRADINGAGENTS_PAPER_SIMULATION_WORKER_CRON_LIMIT", str(min(5, max_limit))))
    if raw <= 0:
        raise ValueError("TRADINGAGENTS_PAPER_SIMULATION_WORKER_CRON_LIMIT must be positive")
    if raw > max_limit:
        raise HTTPException(status_code=400, detail=f"paper simulation cron limit cannot exceed {max_limit}")
    return raw


def _optional_member_user_id(request: Request, header_token: str | None) -> str | None:
    """Resolve a member when credentials are present; anonymous visitors get None."""

    if not request.headers.get("Authorization") and not header_token:
        return None
    try:
        return resolve_member_user_id(request, header_token)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return None
        raise


def _plan_request_limits(access) -> tuple[int, int]:
    """Plan quotas capped by the operator's env ceilings (the smaller value wins)."""

    from .analysis_api import (
        ANALYSIS_REQUEST_ACTIVE_LIMIT_ENV,
        ANALYSIS_REQUEST_DAILY_LIMIT_ENV,
        DEFAULT_ANALYSIS_REQUEST_ACTIVE_LIMIT,
        DEFAULT_ANALYSIS_REQUEST_DAILY_LIMIT,
    )

    def env_int(name: str, default: int) -> int:
        try:
            return max(int(os.getenv(name, str(default))), 1)
        except ValueError:
            return default

    env_active = env_int(ANALYSIS_REQUEST_ACTIVE_LIMIT_ENV, DEFAULT_ANALYSIS_REQUEST_ACTIVE_LIMIT)
    env_daily = env_int(ANALYSIS_REQUEST_DAILY_LIMIT_ENV, DEFAULT_ANALYSIS_REQUEST_DAILY_LIMIT)
    return min(access.plan.active_requests_limit, env_active), min(access.plan.analysis_requests_per_day, env_daily)


def _webhook_info_summary(info: Any) -> dict:
    info = info or {}
    return {
        "url": info.get("url"),
        "pending_update_count": info.get("pending_update_count"),
        "last_error_date": info.get("last_error_date"),
        "last_error_message": info.get("last_error_message"),
        "has_custom_certificate": info.get("has_custom_certificate"),
        "max_connections": info.get("max_connections"),
    }


def _notify_harness_issue(request: Request, *, harness_run_id: str | None = None, force: bool = False) -> dict:
    repo = request.app.state.repository
    if repo is None:
        raise HTTPException(status_code=503, detail="Storage repository is not configured")
    config = TelegramConfig.from_env()
    client = getattr(request.app.state, "telegram_client", None) or TelegramClient(config)
    if client.transport is None and not config.is_configured():
        return {"status": "not_configured", "sent": 0}
    try:
        return notify_harness_issue(repo, client, site_base_url=_request_site_base_url(request), harness_run_id=harness_run_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _notify_generic(request: Request, sender) -> dict:
    repo = request.app.state.repository
    if repo is None:
        raise HTTPException(status_code=503, detail="Storage repository is not configured")
    config = TelegramConfig.from_env()
    client = getattr(request.app.state, "telegram_client", None) or TelegramClient(config)
    if client.transport is None and not config.is_configured():
        return {"status": "not_configured", "sent": 0}
    return sender(repo, client, site_base_url=_request_site_base_url(request))


def _process_subscription_renewals(request: Request) -> dict:
    repo = request.app.state.repository
    if repo is None:
        raise HTTPException(status_code=503, detail="Storage repository is not configured")
    config = PortOneConfig.from_env()
    client = getattr(request.app.state, "portone_client", None) or PortOneClient(config)
    if client.transport is None and not config.api_secret:
        return {"status": "not_configured", "due_count": 0, "charged_count": 0, "results": []}
    result = process_subscription_renewals(repo, client)
    return {"status": "completed", **result}


def _require_worker_token(request: Request, header_token: str | None) -> None:
    _require_operator(request, header_token)


def _require_operator(request: Request, header_token: str | None) -> str:
    """Allow a worker token (header or bearer) or a signed-in admin member; return the actor label."""

    expected_tokens = _expected_worker_tokens()
    bearer = _bearer_token(request.headers.get("Authorization"))
    token = header_token or bearer
    if not token:
        if not expected_tokens:
            raise HTTPException(status_code=503, detail="Operation token is not configured")
        raise HTTPException(status_code=401, detail="Missing operation token")
    if any(hmac.compare_digest(token, expected) for expected in expected_tokens):
        return "worker"
    if bearer and token == bearer:
        profile = _admin_profile_or_none(request)
        if profile is not None:
            return str(profile.get("email") or profile.get("id") or "admin")
    if not expected_tokens:
        raise HTTPException(status_code=503, detail="Operation token is not configured")
    raise HTTPException(status_code=403, detail="Invalid operation token")


def _admin_profile_or_none(request: Request) -> dict | None:
    try:
        profile = resolve_member_profile(request, None)
    except HTTPException:
        return None
    return profile if profile.get("is_admin") else None


def _supabase_admin_client(request: Request) -> SupabaseAdminClient:
    client = getattr(request.app.state, "supabase_admin_client", None)
    return client if client is not None else SupabaseAdminClient.from_env()


def _require_repository(request: Request) -> StorageRepository:
    repo = request.app.state.repository
    if repo is None:
        raise HTTPException(status_code=503, detail="Storage repository is not configured")
    return repo


def _validate_uuid_param(value: str) -> None:
    try:
        UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="user_id must be a UUID") from exc


def _expected_worker_token() -> str:
    tokens = _expected_worker_tokens()
    return tokens[0] if tokens else ""


def _expected_worker_tokens() -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for name in WORKER_TOKEN_ENV_NAMES:
        value = (os.getenv(name) or "").strip()
        if value and value not in seen:
            tokens.append(value)
            seen.add(value)
    return tuple(tokens)


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

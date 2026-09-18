"""The local desk's FastAPI app, its guard, and the data it reads."""

from __future__ import annotations

import secrets
from typing import Any, Mapping

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .page import render_desk

DESK_TOKEN_HEADER = "x-desk-token"
DESK_TOKEN_COOKIE = "desk_token"
DESK_TOKEN_QUERY = "t"

# Loopback only. A Host header naming anything else means the request reached
# this process through a name that resolves here from somewhere else, which is
# the shape of a DNS rebinding attack.
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def _host_is_loopback(request: Request) -> bool:
    host = (request.headers.get("host") or "").split(":", 1)[0].strip().lower()
    return host in LOOPBACK_HOSTS


def _cross_site(request: Request) -> bool:
    """Whether a browser says this came from another origin.

    Sec-Fetch-Site is sent by every current browser and cannot be set by page
    script, so it is the one signal here a hostile page cannot forge. Absent
    (curl, older clients) is treated as same-site: the token still has to be
    right, and refusing everything without the header would block the CLI.
    """

    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    return site in {"cross-site", "same-site"}


def _token_of(request: Request) -> str:
    return (
        request.headers.get(DESK_TOKEN_HEADER)
        or request.query_params.get(DESK_TOKEN_QUERY)
        or request.cookies.get(DESK_TOKEN_COOKIE)
        or ""
    ).strip()


def create_desk_app(*, token: str, client_factory=None) -> FastAPI:
    """The desk, locked to this machine and this launch.

    ``client_factory`` returns something with ``balance()`` and
    ``current_price()``; tests pass a stub so no call leaves the machine.
    """

    app = FastAPI(title="AgentTrust 데스크", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.desk_token = token
    app.state.client_factory = client_factory or _default_client_factory

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not _host_is_loopback(request):
            return JSONResponse({"detail": "이 데스크는 이 컴퓨터에서만 열립니다."}, status_code=403)
        if _cross_site(request):
            return JSONResponse({"detail": "다른 사이트에서 온 요청은 받지 않습니다."}, status_code=403)
        if not secrets.compare_digest(_token_of(request), app.state.desk_token):
            return JSONResponse(
                {"detail": "토큰이 없거나 맞지 않습니다. 데스크를 실행한 터미널의 주소로 다시 여세요."},
                status_code=401,
            )
        response = await call_next(request)
        # Nothing here should be cached, proxied or framed.
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/", response_class=HTMLResponse)
    def desk(request: Request) -> HTMLResponse:
        response = HTMLResponse(render_desk(mode=_mode(request)))
        # so the page's own fetches carry it without putting it in every URL
        response.set_cookie(
            DESK_TOKEN_COOKIE, app.state.desk_token,
            httponly=True, samesite="strict", path="/",
        )
        return response

    @app.get("/gold", response_class=HTMLResponse)
    def gold(
        request: Request,
        intervals: str = Query("", max_length=64),
        bars: int = Query(600, ge=120, le=1200),
    ) -> HTMLResponse:
        """The pattern chart, rendered here rather than pulled from the site.

        The same page exists at agenttrust.kr/lab/gold. Drawing it locally
        means it still works when the site does not, and avoids framing a
        remote page into a desk that sets X-Frame-Options: DENY.
        """

        from tradingagents.site.gold_page import DEFAULT_INTERVALS, render_gold_chart_page

        wanted = tuple(part.strip() for part in intervals.split(",") if part.strip()) or DEFAULT_INTERVALS
        return HTMLResponse(render_gold_chart_page(repo=None, intervals=wanted, bars=bars, data_url="/gold/data"))

    @app.get("/gold/data")
    def gold_data(
        request: Request,
        interval: str = Query("1h", max_length=8),
        bars: int = Query(600, ge=120, le=1200),
    ) -> JSONResponse:
        from tradingagents.site.gold_page import build_gold_frame

        try:
            frame = build_gold_frame(repo=None, interval=interval, bars=bars)
        except Exception as exc:                        # noqa: BLE001 - one timeframe, not the page
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)
        return JSONResponse(frame)

    @app.get("/api/account")
    def account(request: Request) -> JSONResponse:
        return JSONResponse(_account_payload(request))

    @app.get("/api/quote")
    def quote(request: Request, code: str = Query(min_length=1, max_length=12)) -> JSONResponse:
        client = request.app.state.client_factory()
        if client is None:
            return JSONResponse({"error": _unconfigured()}, status_code=503)
        try:
            raw = client.current_price(code)
        except Exception as exc:                        # noqa: BLE001 - shown to one person
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)
        return JSONResponse({"quote": _quote_row(raw)})

    return app


# ------------------------------------------------------------------ reading
def _default_client_factory():
    from tradingagents.execution.nh_client import NHClient, NHConfig

    config = NHConfig.from_env()
    return NHClient(config=config) if config.configured else None


def _mode(request: Request) -> str:
    from tradingagents.execution.nh_client import NHConfig

    return NHConfig.from_env().mode


def _unconfigured() -> str:
    from tradingagents.execution.nh_client import NHConfig

    config = NHConfig.from_env()
    prefix = "NH_PAPER_" if config.is_paper else "NH_"
    return (
        f"{config.mode} 자격증명이 없습니다. .env 에 {prefix}APP_KEY, {prefix}APP_SECRET_KEY, "
        f"{prefix}ACCOUNT_NO 를 넣어주세요."
    )


def _account_payload(request: Request) -> dict[str, Any]:
    client = request.app.state.client_factory()
    if client is None:
        return {"error": _unconfigured(), "mode": _mode(request)}
    try:
        raw = client.balance()
    except Exception as exc:                            # noqa: BLE001 - shown to one person
        return {"error": f"{type(exc).__name__}: {exc}", "mode": _mode(request)}

    summary = raw.get("Output_0") or {}
    rows = raw.get("Output_1") or []
    return {
        "mode": _mode(request),
        "summary": {
            "total_assets": _num(summary.get("tot_aet_amt")),
            "cash": _num(summary.get("dca")),
            "withdrawable": _num(summary.get("drn_pbl_amt")),
            "holdings_value": _num(summary.get("tot_eal_amt")),
            "unrealised": _num(summary.get("tot_eal_pls")),
            "return_pct": _num(summary.get("pft_rt")),
        },
        "holdings": [_holding(row) for row in rows if isinstance(row, Mapping)],
    }


def _holding(row: Mapping[str, Any]) -> dict[str, Any]:
    """One position, with only the fields the page draws.

    NH returns nearly thirty per row and the names are opaque enough that
    passing them through would make the page unreadable and the next change
    guesswork.
    """

    # Field names read off a live response, not guessed: the first guess gave a
    # table of dashes because NH calls the quantity itg_bnc_qty and the average
    # phs_pr. Fallbacks are kept only where NH itself uses two spellings.
    return {
        "code": str(row.get("iem_cd") or "").strip(),
        "name": str(row.get("iem_nm") or row.get("iem_krl_nm") or "").strip().lstrip("*"),
        "quantity": _num(row.get("itg_bnc_qty") or row.get("rsdl_qty")),
        "average_price": _num(row.get("phs_pr")),
        "last_price": _num(row.get("now_pr")),
        "value": _num(row.get("eal_amt")),
        "unrealised": _num(row.get("eal_pls_amt")),
        "return_pct": _num(row.get("pft_rt")),
        "kind": str(row.get("tp_cd_nm") or "").strip(),
    }


def _quote_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    out = raw.get("Output_0") or {}
    return {
        "code": str(out.get("iem_cd") or "").strip(),
        "name": str(out.get("iem_nm") or "").strip().lstrip("*"),
        "price": _num(out.get("stck_prpr")),
        "change": _num(out.get("prdy_vrss")),
        "change_pct": _num(out.get("prdy_ctrt")),
        "open": _num(out.get("stck_oprc")),
        "high": _num(out.get("stck_hgpr")),
        "low": _num(out.get("stck_lwpr")),
        "volume": _num(out.get("acml_vol")),
    }


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None

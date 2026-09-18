"""The local desk's FastAPI app, its guard, and the data it reads."""

from __future__ import annotations

import secrets
from typing import Any, Mapping

from fastapi import Body, FastAPI, Query, Request
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

    @app.get("/api/search")
    def search(request: Request, q: str = Query(min_length=1, max_length=40)) -> JSONResponse:
        """Name to code, locally. NH's quote call only speaks in codes."""

        from tradingagents.dataflows.kr_ticker_directory import search_directory

        found = search_directory(q, limit=8)
        return JSONResponse({"results": [
            {"code": entry.code, "name": entry.name, "market": entry.market} for entry in found
        ]})

    @app.get("/api/quote")
    def quote(request: Request, code: str = Query(min_length=1, max_length=40)) -> JSONResponse:
        client = request.app.state.client_factory()
        if client is None:
            return JSONResponse({"error": _unconfigured()}, status_code=503)

        # Typing 가온전선 and getting IGW40011 back is the API's answer, not a
        # useful one. A name is resolved here so the broker only ever sees a code.
        resolved, matches = _resolve(code)
        if resolved is None:
            return JSONResponse(
                {"error": f"'{code}' 종목을 찾지 못했습니다.", "suggestions": matches},
                status_code=404,
            )
        try:
            raw = client.current_price(resolved)
        except Exception as exc:                        # noqa: BLE001 - shown to one person
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)
        return JSONResponse({"quote": _quote_row(raw), "book": _book(raw)})

    @app.get("/api/orders")
    def orders(request: Request, on: str = Query("", max_length=10)) -> JSONResponse:
        client = request.app.state.client_factory()
        if client is None:
            return JSONResponse({"error": _unconfigured()}, status_code=503)
        try:
            raw = client.executions(on=on or None)
        except Exception as exc:                        # noqa: BLE001 - shown to one person
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)
        rows = raw.get("Output_0") or []
        return JSONResponse({"orders": [_execution(row) for row in rows if isinstance(row, Mapping)]})

    @app.post("/api/cancel")
    def cancel(request: Request, body: dict = Body(...)) -> JSONResponse:
        """Take an order back. No cap and no typed confirmation.

        Every other guard here exists to slow down committing money. Cancelling
        is the other direction, and a limit that keeps you in a position you are
        trying to leave is worse than no limit at all.
        """

        from .orders import ledger, new_attempt, record

        client = request.app.state.client_factory()
        if client is None:
            return JSONResponse({"error": _unconfigured()}, status_code=503)
        try:
            order_no = int(body.get("order_no"))
        except (TypeError, ValueError):
            return JSONResponse({"error": "주문번호가 필요합니다."}, status_code=400)

        resolved, matches = _resolve(str(body.get("code") or ""))
        if resolved is None:
            return JSONResponse({"error": "종목을 찾지 못했습니다.", "suggestions": matches}, status_code=404)

        quantity = body.get("quantity")
        book, mode = ledger(), _mode(request)
        common = dict(attempt=new_attempt(), side="cancel", code=resolved,
                      quantity=int(quantity or 0), price=0, amount=0, mode=mode)
        record(book, stage="sent", **common)
        try:
            result = client.cancel_order(
                order_no=order_no, code=resolved,
                quantity=int(quantity) if quantity else None,
            )
        except Exception as exc:                        # noqa: BLE001
            record(book, stage="failed", **common, error=f"{type(exc).__name__}: {exc}")
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)
        record(book, stage="accepted", **common, result=result)
        return JSONResponse({"ok": True, "message": result.get("rsp_msg")})

    @app.get("/api/candles")
    def candles(
        request: Request,
        code: str = Query(min_length=1, max_length=40),
        count: int = Query(60, ge=10, le=200),
    ) -> JSONResponse:
        client = request.app.state.client_factory()
        if client is None:
            return JSONResponse({"error": _unconfigured()}, status_code=503)
        resolved, matches = _resolve(code)
        if resolved is None:
            return JSONResponse({"error": "종목을 찾지 못했습니다.", "suggestions": matches}, status_code=404)
        try:
            raw = client.daily_candles(resolved, count=count)
        except Exception as exc:                        # noqa: BLE001 - shown to one person
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)

        rows = raw.get("Output_0") or []
        # NH hands these back newest first; a chart reads the other way
        bars = [_candle(row) for row in rows if isinstance(row, Mapping)]
        return JSONResponse({"code": resolved, "candles": list(reversed(bars))})

    @app.get("/api/capacity")
    def capacity(
        request: Request,
        code: str = Query(min_length=1, max_length=40),
        side: str = Query("buy", max_length=8),
        price: int = Query(0, ge=0),
    ) -> JSONResponse:
        """How much of this the account could actually do, asked before offering it."""

        client = request.app.state.client_factory()
        if client is None:
            return JSONResponse({"error": _unconfigured()}, status_code=503)
        resolved, matches = _resolve(code)
        if resolved is None:
            return JSONResponse({"error": "종목을 찾지 못했습니다.", "suggestions": matches}, status_code=404)

        try:
            if str(side).lower() == "sell":
                raw = (client.sellable_quantity(resolved).get("Output_0") or {})
                return JSONResponse({"side": "sell", "code": resolved,
                                     "quantity": _num(raw.get("sll_pbl_qty")),
                                     "held": _num(raw.get("bnc_qty"))})
            if price <= 0:
                return JSONResponse({"error": "지정가를 먼저 입력해 주세요."}, status_code=400)
            raw = (client.buyable_quantity(resolved, price).get("Output_0") or {})
            return JSONResponse({"side": "buy", "code": resolved,
                                 "quantity": _num(raw.get("csh_orr_pbl_qty")),
                                 "amount": _num(raw.get("csh_orr_pbl_amt"))})
        except Exception as exc:                        # noqa: BLE001 - shown to one person
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)

    @app.get("/api/limits")
    def limits(request: Request) -> JSONResponse:
        from .orders import Limits, ledger, today_spent

        rules = Limits.from_env()
        spent, count = today_spent(ledger())
        return JSONResponse({
            "mode": _mode(request),
            "max_order_krw": rules.max_order_krw,
            "max_daily_krw": rules.max_daily_krw,
            "max_daily_orders": rules.max_daily_orders,
            "spent_today": spent,
            "orders_today": count,
        })

    @app.post("/api/order")
    def order(request: Request, body: dict = Body(...)) -> JSONResponse:
        """Send one limit order, after everything in orders.check holds."""

        from .orders import Limits, OrderRefused, check, ledger, new_attempt, record, today_spent

        mode = _mode(request)
        side = str(body.get("side") or "").strip().lower()
        code = str(body.get("code") or "").strip()
        try:
            quantity = int(body.get("quantity") or 0)
            price = int(body.get("price") or 0)
        except (TypeError, ValueError):
            return JSONResponse({"error": "수량과 가격은 숫자여야 합니다."}, status_code=400)

        # A name in the order box has to become a code before anything is
        # checked against it, and an ambiguous one must not become an order.
        resolved, matches = _resolve(code)
        if resolved is None:
            return JSONResponse(
                {"error": f"'{code}' 종목을 찾지 못했습니다. 코드로 입력해 주세요.", "suggestions": matches},
                status_code=404,
            )
        code = resolved

        book = ledger()
        spent, count = today_spent(book)
        try:
            amount = check(
                side=side, code=code, quantity=quantity, price=price,
                confirmation=str(body.get("confirmation") or ""),
                mode=mode, limits=Limits.from_env(),
                spent_today=spent, orders_today=count,
            )
        except OrderRefused as refused:
            return JSONResponse({"error": str(refused)}, status_code=400)

        client = request.app.state.client_factory()
        if client is None:
            return JSONResponse({"error": _unconfigured()}, status_code=503)

        # Written before the call as well as after: a crash mid-flight still
        # leaves a record that an order was attempted, which is the one thing
        # you need when the account and the ledger disagree.
        common = dict(attempt=new_attempt(), side=side, code=code, quantity=quantity,
                      price=price, amount=amount, mode=mode)
        record(book, stage="sent", **common)
        try:
            result = client.place_order(side=side, code=code, quantity=quantity, price=price)
        except Exception as exc:                        # noqa: BLE001 - shown to one person
            record(book, stage="failed", **common, error=f"{type(exc).__name__}: {exc}")
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)
        record(book, stage="accepted", **common, result=result)
        return JSONResponse({
            "ok": True,
            "order_no": (result.get("Output_0") or {}).get("mkt_orr_no"),
            "message": result.get("rsp_msg"),
            "amount": amount,
        })

    @app.post("/api/mode")
    def switch(request: Request, body: dict = Body(...)) -> JSONResponse:
        """Swap between the paper and live account for this process.

        Reading the live account is harmless; ordering into it still needs
        TRADINGAGENTS_ENABLE_LIVE_TRADING, which is not something a page can
        set. Switching is off unless TRADINGAGENTS_DESK_ALLOW_LIVE says so, so
        the default desk cannot be pointed at real money by a mis-click.
        """

        import os

        want = "paper" if str(body.get("mode") or "").strip().lower() != "live" else "live"
        if want == "live" and (os.getenv("TRADINGAGENTS_DESK_ALLOW_LIVE") or "").strip().lower() not in {"1", "true", "yes", "on"}:
            return JSONResponse(
                {"error": "실계좌 전환이 꺼져 있습니다. .env 에 TRADINGAGENTS_DESK_ALLOW_LIVE=true 를 넣으세요."},
                status_code=403,
            )
        os.environ["NH_IS_PAPER"] = "false" if want == "live" else "true"
        return JSONResponse({"mode": want})

    return app


def _resolve(value: str) -> tuple[str | None, list[dict[str, Any]]]:
    """A six-digit code, or the names that might have been meant."""

    from tradingagents.dataflows.kr_ticker_directory import lookup_directory, search_directory

    text = str(value).strip()
    digits = "".join(character for character in text if character.isdigit())
    if digits and len(digits) <= 6 and not any(character.isalpha() for character in text):
        return digits.zfill(6), []

    found = search_directory(text, limit=8)
    if len(found) == 1:
        return found[0].code, []
    # An exact name is an answer, not a shortlist. 삼성전자 matches 삼성전자우,
    # KODEX 삼성전자채권혼합 and more, and offering those back is the search
    # failing on the one word it should be surest about.
    folded = text.replace(" ", "").lower()
    exact = [entry for entry in found if entry.name.replace(" ", "").lower() == folded]
    if len(exact) == 1:
        return exact[0].code, []
    if found:
        return None, [{"code": e.code, "name": e.name, "market": e.market} for e in found]
    return None, []


# ------------------------------------------------------------------ reading
def _default_client_factory():
    from tradingagents.execution.nh_client import NHClient, NHConfig

    config = NHConfig.from_env()
    # configured covers the key pair; without an account number every call
    # comes back IGW40011, which reads like a bug rather than a blank field
    return NHClient(config=config) if config.configured and config.account_no else None


def _mode(request: Request) -> str:
    from tradingagents.execution.nh_client import NHConfig

    return NHConfig.from_env().mode


def _unconfigured() -> str:
    from tradingagents.execution.nh_client import NHConfig

    config = NHConfig.from_env()
    account = "NH_PAPER_ACCOUNT_NO" if config.is_paper else "NH_ACCOUNT_NO"
    missing = [name for name, value in (
        ("NH_APP_KEY", config.app_key),
        ("NH_APP_SECRET_KEY", config.app_secret_key),
        (account, config.account_no),
    ) if not value]
    return f".env 에 {', '.join(missing)} 를 넣어주세요. ({config.mode})" if missing else ""


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


def _candle(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "date": str(row.get("bsop_date") or "").strip(),
        "open": _num(row.get("stck_oprc")),
        "high": _num(row.get("stck_hgpr")),
        "low": _num(row.get("stck_lwpr")),
        "close": _num(row.get("stck_clpr")),
        "volume": _num(row.get("acml_vol")),
        "change_pct": _num(row.get("prdy_ctrt")),
    }


def _execution(row: Mapping[str, Any]) -> dict[str, Any]:
    """One of today's orders: what was asked, what filled, what can still go."""

    ordered = _num(row.get("orr_qty")) or 0
    filled = _num(row.get("tot_cns_qty")) or 0
    return {
        "order_no": row.get("itg_orr_no"),
        "code": str(row.get("iem_cd") or "").strip(),
        "name": str(row.get("iem_nm") or "").strip().lstrip("*"),
        "side": str(row.get("sby_dit_cd_nm") or "").strip(),
        "quantity": ordered,
        "price": _num(row.get("orr_pr")),
        "filled": filled,
        "filled_price": _num(row.get("cns_avg_uit_pr")),
        # what the broker says is still cancellable, not ordered-minus-filled:
        # a partly cancelled order would make that subtraction wrong
        "cancellable": _num(row.get("can_qty")) or 0,
        "status": str(row.get("orr_rjt_rsn_cd_nm") or "").strip(),
    }


def _book(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The ten levels either side, already inside the quote response.

    NH pushes these over a websocket too, but they are in currentPrice as
    askp1..10 / bidp1..10 with their sizes — which is a depth view that can be
    drawn and checked today rather than one that waits for the market to open.
    """

    out = raw.get("Output_0") or {}
    levels = lambda side: [
        {"price": _num(out.get(f"{side}p{index}")), "size": _num(out.get(f"{side}p_rsqn{index}"))}
        for index in range(1, 11)
    ]
    asks = [row for row in levels("ask") if row["price"]]
    bids = [row for row in levels("bid") if row["price"]]
    return {
        # asks are listed best-first by NH; a depth ladder reads worst at the top
        "asks": list(reversed(asks)),
        "bids": bids,
        "ask_total": _num(out.get("total_askp_rsqn")),
        "bid_total": _num(out.get("total_bidp_rsqn")),
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

"""The local desk: what it refuses, and what it shows when it does not."""

import pytest
from fastapi.testclient import TestClient

from tradingagents.desk import DESK_TOKEN_HEADER, create_desk_app, new_token

BALANCE = {
    "rsp_cd": "00166",
    "Output_0": {"tot_aet_amt": 1_986_430, "dca": 122_790, "drn_pbl_amt": 120_000,
                 "tot_eal_amt": 1_863_640, "tot_eal_pls": 25_320, "pft_rt": 1.377344532},
    "Output_1": [
        {"iem_cd": "005930", "iem_nm": "삼성전자", "tp_cd_nm": "현금매수", "itg_bnc_qty": 5.0,
         "rsdl_qty": 5.0, "phs_pr": 250_000, "now_pr": 260_000, "eal_amt": 1_300_000,
         "eal_pls_amt": 50_000, "pft_rt": 4.0},
    ],
}
QUOTE = {"rsp_cd": "00000", "Output_0": {"iem_cd": "005930", "iem_nm": "*삼성전자",
                                         "stck_prpr": 260_000, "prdy_vrss": 7_500, "prdy_ctrt": 2.97,
                                         "stck_hgpr": 262_000, "stck_lwpr": 255_000, "acml_vol": 12_345_678}}


class _Stub:
    """Stands in for NHClient so no test call leaves the machine."""

    def __init__(self, *, fail=None):
        self.fail = fail

    def balance(self, account_no=None):
        if self.fail:
            raise RuntimeError(self.fail)
        return BALANCE

    def current_price(self, code, *, market="KRX"):
        if self.fail:
            raise RuntimeError(self.fail)
        return QUOTE


def _app(client=None, *, token="T0KEN"):
    return create_desk_app(token=token, client_factory=lambda: client if client is not None else _Stub())


def _client(app):
    # TestClient sends Host: testserver, which the desk is right to refuse
    return TestClient(app, base_url="http://127.0.0.1:8787")


def test_a_request_without_the_token_is_refused():
    with _client(_app()) as http:
        assert http.get("/api/account").status_code == 401
        assert http.get("/").status_code == 401


def test_the_token_is_accepted_in_a_header_a_query_or_a_cookie():
    with _client(_app()) as http:
        assert http.get("/api/account", headers={DESK_TOKEN_HEADER: "T0KEN"}).status_code == 200
        assert http.get("/api/account?t=T0KEN").status_code == 200
        http.cookies.set("desk_token", "T0KEN")
        assert http.get("/api/account").status_code == 200


def test_a_wrong_token_is_refused_even_with_everything_else_right():
    with _client(_app()) as http:
        assert http.get("/api/account", headers={DESK_TOKEN_HEADER: "nope"}).status_code == 401


def test_a_request_that_did_not_come_from_this_machine_is_refused():
    """Any page in any tab can POST to 127.0.0.1; the Host header is the check."""

    with TestClient(_app(), base_url="http://desk.example.com") as http:
        assert http.get("/api/account?t=T0KEN").status_code == 403


def test_a_request_from_another_site_is_refused_even_with_the_token():
    """Sec-Fetch-Site cannot be set by page script, so a hostile tab cannot lie."""

    with _client(_app()) as http:
        blocked = http.get("/api/account?t=T0KEN", headers={"sec-fetch-site": "cross-site"})
        assert blocked.status_code == 403
        allowed = http.get("/api/account?t=T0KEN", headers={"sec-fetch-site": "same-origin"})
        assert allowed.status_code == 200
        # and a client that sends no such header at all still works
        assert http.get("/api/account?t=T0KEN").status_code == 200


def test_the_page_says_which_account_it_is_looking_at(monkeypatch):
    monkeypatch.setenv("NH_IS_PAPER", "true")
    with _client(_app()) as http:
        page = http.get("/?t=T0KEN")
    assert page.status_code == 200
    assert "모의투자" in page.text
    # the mode is said out loud because the order form below it is live
    assert "주문" in page.text and "지정가만" in page.text
    assert "시장가는 코드값" in page.text        # and why there is no market order
    assert "noindex" in page.text
    # the cookie is set so the page's own fetches carry the token
    assert page.cookies.get("desk_token") == "T0KEN"


def test_nothing_the_desk_serves_may_be_cached_or_framed():
    with _client(_app()) as http:
        response = http.get("/?t=T0KEN")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert "noindex" in response.headers["x-robots-tag"]


def test_the_balance_is_reshaped_into_names_a_person_can_read():
    """NH returns thirty opaque fields per row; the page draws seven."""

    with _client(_app()) as http:
        data = http.get("/api/account?t=T0KEN").json()

    assert data["summary"]["total_assets"] == 1_986_430
    assert data["summary"]["cash"] == 122_790
    assert data["summary"]["unrealised"] == 25_320
    holding = data["holdings"][0]
    assert holding == {
        "code": "005930", "name": "삼성전자", "quantity": 5.0,
        "average_price": 250_000.0, "last_price": 260_000.0, "value": 1_300_000.0,
        "unrealised": 50_000.0, "return_pct": 4.0, "kind": "현금매수",
    }


def test_the_holding_fields_are_the_ones_nh_actually_returns():
    """The first guess drew a table of dashes: NH calls quantity itg_bnc_qty."""

    import inspect

    from tradingagents.desk import app as desk_app

    source = inspect.getsource(desk_app._holding)
    for field in ("itg_bnc_qty", "phs_pr", "now_pr", "eal_amt", "eal_pls_amt", "pft_rt"):
        assert field in source, field
    # and the names that were guessed are gone rather than left as fallbacks
    for guess in ('"bnc_qty"', "pchs_avg_pric", "prsnt_pric", "evlu_pfls_rt"):
        assert guess not in source, guess


def test_a_quote_keeps_only_what_is_drawn_and_drops_the_star():
    with _client(_app()) as http:
        quote = http.get("/api/quote?code=005930&t=T0KEN").json()["quote"]
    assert quote["name"] == "삼성전자"          # NH prefixes some names with *
    assert quote["price"] == 260_000.0 and quote["change_pct"] == 2.97


def test_a_broker_failure_is_reported_rather_than_shown_as_an_empty_account():
    with _client(_app(_Stub(fail="IGW40011"))) as http:
        data = http.get("/api/account?t=T0KEN").json()
        assert "IGW40011" in data["error"]
        assert "summary" not in data
        assert http.get("/api/quote?code=005930&t=T0KEN").status_code == 502


def test_with_no_credentials_it_says_which_ones_are_missing(monkeypatch):
    # cli.main calls load_dotenv() at import, so the developer's own .env is in
    # os.environ by the time this runs. Clearing them is what makes this a test
    # of the message rather than of whoever's machine it runs on.
    for name in ("NH_APP_KEY", "NH_APP_SECRET_KEY", "NH_ACCOUNT_NO", "NH_PAPER_ACCOUNT_NO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NH_IS_PAPER", "true")

    app = create_desk_app(token="T0KEN", client_factory=lambda: None)
    with _client(app) as http:
        data = http.get("/api/account?t=T0KEN").json()
    for name in ("NH_APP_KEY", "NH_APP_SECRET_KEY", "NH_PAPER_ACCOUNT_NO"):
        assert name in data["error"], name
    assert "summary" not in data

    # and the account number alone missing is called out, not left to come back
    # as IGW40011 from the broker
    monkeypatch.setenv("NH_APP_KEY", "K")
    monkeypatch.setenv("NH_APP_SECRET_KEY", "S")
    with _client(create_desk_app(token="T0KEN", client_factory=lambda: None)) as http:
        data = http.get("/api/account?t=T0KEN").json()
    assert data["error"].strip().startswith(".env 에 NH_PAPER_ACCOUNT_NO")


def test_every_launch_gets_its_own_token():
    assert new_token() != new_token()
    assert len(new_token()) >= 24


def test_the_desk_refuses_to_bind_anywhere_but_loopback():
    """A brokerage balance has no business on the network."""

    import inspect

    from cli import main as cli

    source = inspect.getsource(cli.desk_command)
    assert '"127.0.0.1", "localhost", "::1"' in source
    assert "데스크는 127.0.0.1 에만 엽니다" in source
    assert 'host="127.0.0.1"' in source or '"--host"' in source


def test_the_desk_is_not_part_of_the_deployed_site():
    """It shows a brokerage balance; it must not ship to a public host."""

    from pathlib import Path

    ignored = Path(".vercelignore").read_text(encoding="utf-8")
    assert "tradingagents/desk" in ignored

    # and nothing in the public app routes to it
    api = Path("tradingagents/site/api_app.py").read_text(encoding="utf-8")
    assert "desk" not in api.replace("desktop", "")


def test_the_gold_chart_is_drawn_here_rather_than_pulled_from_the_site():
    """Framing a remote page into a desk that sets X-Frame-Options: DENY does not work."""

    import inspect

    from tradingagents.desk import app as desk_app

    source = inspect.getsource(desk_app.create_desk_app)
    assert 'data_url="/gold/data"' in source          # its own data route, not the site's
    assert "repo=None" in source                       # no database needed to draw it
    # and it fetches nothing over the network from the deployed site
    code = "".join(line.split("#", 1)[0] for line in source.splitlines())
    assert "https://" not in code and "iframe" not in code


def test_the_gold_routes_are_behind_the_same_guard():
    """A chart is harmless; a route that skips the guard is not."""

    with _client(_app()) as http:
        assert http.get("/gold").status_code == 401
        assert http.get("/gold/data?interval=1h").status_code == 401
        blocked = http.get("/gold?t=T0KEN", headers={"sec-fetch-site": "cross-site"})
        assert blocked.status_code == 403


def test_one_timeframe_failing_does_not_take_the_page_down(monkeypatch):
    def explode(**kwargs):
        raise RuntimeError("vendor rate limit")

    monkeypatch.setattr("tradingagents.site.gold_page.build_gold_frame", explode)
    with _client(_app()) as http:
        response = http.get("/gold/data?interval=1h&t=T0KEN")
    assert response.status_code == 502
    assert "vendor rate limit" in response.json()["error"]


def test_the_desk_links_to_the_chart():
    with _client(_app()) as http:
        page = http.get("/?t=T0KEN")
    assert 'href="/gold"' in page.text and "골드 차트" in page.text


def test_a_name_is_turned_into_a_code_before_the_broker_sees_it():
    """Typing 가온전선 got IGW40011 back, which is the API's answer not a useful one."""

    from tradingagents.desk.app import _resolve

    assert _resolve("가온전선")[0] == "000500"
    assert _resolve("005930")[0] == "005930"
    assert _resolve("5930")[0] == "005930"              # padded, as NH wants six

    # several matches is not a pick: the caller is offered the names instead
    code, suggestions = _resolve("삼성")
    assert code is None and len(suggestions) > 1
    assert all({"code", "name", "market"} <= set(item) for item in suggestions)

    assert _resolve("존재하지않는종목")[0] is None


def test_an_unknown_name_is_a_404_with_the_near_misses():
    with _client(_app()) as http:
        response = http.get("/api/quote?code=삼성&t=T0KEN")
    assert response.status_code == 404
    body = response.json()
    assert "찾지 못했습니다" in body["error"]
    assert len(body["suggestions"]) > 1


def test_switching_to_the_live_account_is_off_unless_it_is_turned_on(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_DESK_ALLOW_LIVE", raising=False)
    monkeypatch.setenv("NH_IS_PAPER", "true")
    with _client(_app()) as http:
        blocked = http.post("/api/mode?t=T0KEN", json={"mode": "live"})
        assert blocked.status_code == 403
        assert "TRADINGAGENTS_DESK_ALLOW_LIVE" in blocked.json()["error"]
        # and the desk is still looking at paper afterwards
        assert http.get("/api/limits?t=T0KEN").json()["mode"] == "paper"

    monkeypatch.setenv("TRADINGAGENTS_DESK_ALLOW_LIVE", "true")
    with _client(_app()) as http:
        assert http.post("/api/mode?t=T0KEN", json={"mode": "live"}).json()["mode"] == "live"
        assert http.get("/api/limits?t=T0KEN").json()["mode"] == "live"
        # going back needs no permission at all
        assert http.post("/api/mode?t=T0KEN", json={"mode": "paper"}).json()["mode"] == "paper"


def test_an_exact_name_is_an_answer_not_a_shortlist():
    """삼성전자 also matches 삼성전자우 and KODEX 삼성전자채권혼합."""

    from tradingagents.desk.app import _resolve

    assert _resolve("삼성전자")[0] == "005930"
    assert _resolve("삼성전자우")[0] == "005935"
    assert _resolve("SK하이닉스")[0] == _resolve("sk하이닉스")[0] == "000660"
    # a prefix that is nobody's whole name still asks
    assert _resolve("삼성")[0] is None


def test_capacity_is_asked_before_an_order_is_offered(monkeypatch):
    class _Room:
        def buyable_quantity(self, code, price, account_no=None):
            return {"rsp_cd": "XA102", "Output_0": {"csh_orr_pbl_qty": 1919, "csh_orr_pbl_amt": 499_014_190}}

        def sellable_quantity(self, code, account_no=None):
            return {"rsp_cd": "XA102", "Output_0": {"bnc_qty": 90, "sll_pbl_qty": 65}}

    app = create_desk_app(token="T0KEN", client_factory=lambda: _Room())
    with _client(app) as http:
        buy = http.get("/api/capacity?code=005930&side=buy&price=260000&t=T0KEN").json()
        assert buy == {"side": "buy", "code": "005930", "quantity": 1919.0, "amount": 499_014_190.0}

        # 매도가능 is not the balance: today's buys may not have settled
        sell = http.get("/api/capacity?code=005930&side=sell&t=T0KEN").json()
        assert sell["quantity"] == 65.0 and sell["held"] == 90.0

        # buying needs a price to be measured against
        assert http.get("/api/capacity?code=005930&side=buy&t=T0KEN").status_code == 400


def test_the_candles_are_turned_around_for_a_chart():
    """NH hands them back newest first; a chart reads the other way."""

    class _Bars:
        def daily_candles(self, code, *, count=60, market="KRX"):
            return {"rsp_cd": "00000", "Output_0": [
                {"bsop_date": "26/09/18", "stck_oprc": 261_000, "stck_hgpr": 262_000,
                 "stck_lwpr": 257_500, "stck_clpr": 260_000, "acml_vol": 17_489_615},
                {"bsop_date": "26/09/17", "stck_oprc": 257_000, "stck_hgpr": 259_000,
                 "stck_lwpr": 251_500, "stck_clpr": 256_000, "acml_vol": 11_827_514},
            ]}

    app = create_desk_app(token="T0KEN", client_factory=lambda: _Bars())
    with _client(app) as http:
        bars = http.get("/api/candles?code=005930&t=T0KEN").json()["candles"]

    assert [bar["date"] for bar in bars] == ["26/09/17", "26/09/18"]
    assert bars[-1]["close"] == 260_000 and bars[-1]["high"] == 262_000


def test_the_capacity_and_candle_routes_are_behind_the_guard():
    with _client(_app()) as http:
        assert http.get("/api/capacity?code=005930&side=sell").status_code == 401
        assert http.get("/api/candles?code=005930").status_code == 401


def test_the_order_book_comes_out_of_the_quote_rather_than_a_websocket():
    """currentPrice already carries askp1..10 / bidp1..10 with their sizes."""

    class _Depth:
        def current_price(self, code, *, market="KRX"):
            out = {"iem_cd": "005930", "iem_nm": "삼성전자", "stck_prpr": 260_000,
                   "total_askp_rsqn": 446_211, "total_bidp_rsqn": 192_648}
            for index in range(1, 11):
                out[f"askp{index}"] = 260_000 + (index - 1) * 500
                out[f"askp_rsqn{index}"] = 30_594 + index
                out[f"bidp{index}"] = 259_500 - (index - 1) * 500
                out[f"bidp_rsqn{index}"] = 48_062 + index
            return {"rsp_cd": "00000", "Output_0": out}

    app = create_desk_app(token="T0KEN", client_factory=lambda: _Depth())
    with _client(app) as http:
        book = http.get("/api/quote?code=005930&t=T0KEN").json()["book"]

    assert len(book["asks"]) == len(book["bids"]) == 10
    # asks come back best-first and a ladder reads worst at the top, so the
    # touch price is the last ask and the first bid
    assert book["asks"][-1]["price"] == 260_000
    assert book["bids"][0]["price"] == 259_500
    assert book["ask_total"] == 446_211 and book["bid_total"] == 192_648


def test_a_quote_with_no_depth_does_not_invent_levels():
    class _Thin:
        def current_price(self, code, *, market="KRX"):
            return {"rsp_cd": "00000", "Output_0": {"iem_cd": "005930", "stck_prpr": 100}}

    app = create_desk_app(token="T0KEN", client_factory=lambda: _Thin())
    with _client(app) as http:
        book = http.get("/api/quote?code=005930&t=T0KEN").json()["book"]
    assert book["asks"] == [] and book["bids"] == []


def test_clicking_a_price_fills_the_order_box():
    """Looking at the ladder before placing a limit is the point of showing it."""

    with _client(_app()) as http:
        page = http.get("/?t=T0KEN").text
    assert "drawBook" in page
    assert "el('o-price').value" in page


def test_the_period_pnl_accepts_both_spellings_nh_uses():
    """The spec writes byn_cst_sum1; the gateway answers byn_cst_sum."""

    class _Books:
        def daily_pnl(self, *, start, end, account_no=None):
            return {"rsp_cd": "00000",
                    "Output_0": {"byn_cst_sum": 1_838_320, "sll_cst_sum": 0,
                                 "pls_amt_sum": 23_536, "acl_sdr_xps": 450},
                    "Output_1": [{"sby_dt": "20260907", "byn_amt": 1_838_320, "sll_amt": 0,
                                  "pls_amt": -740, "pft_rt": -0.217}]}

        def trading_pnl(self, *, start, end, account_no=None):
            return {"rsp_cd": "00000", "Output_0": {},
                    "Output_1": [{"iem_cd": "034020", "iem_nm": "두산에너빌리티",
                                  "byn_qty": 10.0, "byn_amt": 839_000, "sll_amt": 0,
                                  "pls_amt": 0, "pft_rt": 0.0}]}

        def realized_pnl(self, account_no=None):
            return {"rsp_cd": "00000", "Output_0": {"tdy_dca": 122_790, "eal_pls_amt": 31_760,
                                                    "aet_amt": 1_031_760}}

    app = create_desk_app(token="T0KEN", client_factory=lambda: _Books())
    with _client(app) as http:
        body = http.get("/api/pnl?days=90&t=T0KEN").json()

    assert body["totals"]["bought"] == 1_838_320
    assert body["totals"]["profit"] == 23_536
    assert body["days"][0]["date"] == "20260907"
    assert body["stocks"][0]["name"] == "두산에너빌리티"
    assert body["standing"]["open_profit"] == 31_760


def test_the_standing_line_missing_does_not_take_the_period_figures_down():
    """realizedPnl is a separate call; losing it must not lose the panel."""

    class _Half:
        def daily_pnl(self, *, start, end, account_no=None):
            return {"rsp_cd": "00000", "Output_0": {"pls_amt_sum": 100}, "Output_1": []}

        def trading_pnl(self, *, start, end, account_no=None):
            return {"rsp_cd": "00000", "Output_0": {}, "Output_1": []}

        def realized_pnl(self, account_no=None):
            raise RuntimeError("모의투자에서는 해당업무가 제공되지 않습니다")

    app = create_desk_app(token="T0KEN", client_factory=lambda: _Half())
    with _client(app) as http:
        body = http.get("/api/pnl?t=T0KEN").json()

    assert body["totals"]["profit"] == 100
    assert body["standing"] is None


def test_the_investor_columns_are_read_under_either_name():
    class _Flow:
        def investors(self, code, *, days=20, market="KRX"):
            return {"rsp_cd": "00000", "Output_0": [
                {"bsop_date1": "20260918", "stck_prpr": 260_000, "prdy_ctrt": 2.97,
                 "for_rate": 46.46, "frgn_ntby_qty": -1_379_955,
                 "person": -2_975_813, "gigwan": 2_746_972, "program": -1_433_248},
                {"bsop_date1": "20260917", "stck_prpr": 256_000,
                 "personz10": -39_299, "gigwanz10": 196_838, "programz10": -1_935_285},
            ]}

    app = create_desk_app(token="T0KEN", client_factory=lambda: _Flow())
    with _client(app) as http:
        rows = http.get("/api/investors?code=005930&days=3&t=T0KEN").json()["rows"]

    assert rows[0]["institution"] == 2_746_972
    assert rows[1]["institution"] == 196_838      # the z10 spelling, same column
    assert rows[0]["foreign"] == -1_379_955


def test_a_reserved_order_is_capped_and_confirmed_like_any_other(monkeypatch, tmp_path):
    """It is money committed, just later, so it goes through the same gate."""

    monkeypatch.setenv("TRADINGAGENTS_DESK_LEDGER", str(tmp_path / "orders.jsonl"))
    monkeypatch.setenv("NH_IS_PAPER", "false")
    sent = []

    class _Queue:
        def place_reserved_order(self, *, side, code, quantity, price, account_no=None):
            sent.append((side, code, quantity, price))
            return {"rsp_cd": "00210", "Output_0": {"bkg_orr_no": 27}, "rsp_msg": "예약되었습니다."}

    app = create_desk_app(token="T0KEN", client_factory=lambda: _Queue())
    with _client(app) as http:
        wrong = http.post("/api/reserved/order?t=T0KEN", json={
            "side": "buy", "code": "005930", "quantity": 2, "price": 1_000, "confirmation": "3"})
        assert wrong.status_code == 400 and not sent

        big = http.post("/api/reserved/order?t=T0KEN", json={
            "side": "buy", "code": "005930", "quantity": 100, "price": 1_000_000,
            "confirmation": "100"})
        assert big.status_code == 400 and not sent

        good = http.post("/api/reserved/order?t=T0KEN", json={
            "side": "buy", "code": "삼성전자", "quantity": 2, "price": 1_000, "confirmation": "2"})

    assert good.status_code == 200 and good.json()["reserved_no"] == 27
    assert sent == [("buy", "005930", 2, 1_000)]


def test_the_paper_account_is_told_it_has_no_reserved_orders_not_shown_a_fault(monkeypatch):
    """NH answers 19999 there; a 502 would read as something being broken."""

    monkeypatch.setenv("NH_IS_PAPER", "true")
    asked = []

    class _Loud:
        def reserved_orders(self, account_no=None):
            asked.append(1)
            raise AssertionError("the paper gateway should not have been called")

    app = create_desk_app(token="T0KEN", client_factory=lambda: _Loud())
    with _client(app) as http:
        listing = http.get("/api/reserved?t=T0KEN")
        placing = http.post("/api/reserved/order?t=T0KEN", json={
            "side": "buy", "code": "005930", "quantity": 1, "price": 100, "confirmation": "1"})

    assert listing.status_code == 200 and listing.json()["reserved"] == []
    assert "모의투자" in listing.json()["unsupported"]
    assert placing.status_code == 400 and "모의투자" in placing.json()["error"]
    assert not asked


def test_the_new_panels_are_on_the_page_and_behind_the_guard():
    # a fresh client: loading the page sets the cookie, which would carry the
    # token into every call after it and prove nothing about the guard
    with _client(_app()) as http:
        assert http.get("/api/pnl").status_code == 401
        assert http.get("/api/investors?code=005930").status_code == 401
        assert http.get("/api/reserved").status_code == 401
        assert http.post("/api/reserved/cancel", json={}).status_code == 401

    with _client(_app()) as http:
        page = http.get("/?t=T0KEN").text

    for marker in ("실현손익", "예약 주문", "수급", "loadPnl", "loadFlow", "loadReserved"):
        assert marker in page

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
    assert "주문 기능은 아직 없습니다" in page.text
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
    monkeypatch.setenv("NH_IS_PAPER", "true")
    app = create_desk_app(token="T0KEN", client_factory=lambda: None)
    with _client(app) as http:
        data = http.get("/api/account?t=T0KEN").json()
    assert "NH_PAPER_APP_KEY" in data["error"]
    assert "summary" not in data


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

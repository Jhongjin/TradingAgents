"""The NH 나무증권 client: auth shape, token reuse, and the gates on trading."""

import json
import time

import pytest

from tradingagents.execution.kis_client import LiveTradingDisabledError
from tradingagents.execution.nh_client import (
    NHClient,
    NHConfig,
    NHError,
    NHOrdersUnavailableError,
)


def _recorder(response=None, *, fail_first=False):
    """A transport that records what was sent and answers with `response`."""

    calls = []
    state = {"failed": False}

    def transport(method, url, headers, params, data):
        calls.append({"method": method, "url": url, "headers": dict(headers),
                      "params": params, "data": dict(data or {})})
        if fail_first and not state["failed"]:
            state["failed"] = True
            raise NHError("429 too many requests")
        return dict(response or {"access_token": "TOKEN", "token_type": "Bearer",
                                 "scope": "oob", "expires_in": 86400})

    transport.calls = calls
    return transport


def _ready(transport=None, **overrides):
    """A client that already holds a token, so calls[0] is the business call."""

    client = _client(transport, **overrides)
    client._token = "TOKEN"                                             # noqa: SLF001
    client._token_expires_at = time.time() + 3600                       # noqa: SLF001
    return client


def _client(transport=None, **overrides):
    config = NHConfig(app_key="KEY", app_secret_key="SECRET", **overrides)
    return NHClient(config=config, transport=transport or _recorder())


def test_the_token_request_is_the_form_nh_documents_not_the_one_kis_wants():
    """Same grant type as KIS, different encoding, different field name."""

    transport = _recorder()
    token = _client(transport).access_token()
    assert token == "TOKEN"

    sent = transport.calls[0]
    assert sent["method"] == "POST"
    assert sent["url"] == "https://api.nhplug.com:8443/oauth2/token"
    assert sent["headers"]["content-type"] == "application/x-www-form-urlencoded"
    # appsecretkey, not KIS's appsecret, and scope=oob which KIS has no notion of
    assert sent["data"] == {
        "appkey": "KEY", "appsecretkey": "SECRET",
        "grant_type": "client_credentials", "scope": "oob",
    }
    # the body goes as form data; sending it as JSON is what the shape change means
    assert sent["params"] is None


def test_a_token_is_reused_rather_than_re_issued():
    """NH allows one request per second and says not to re-issue for 24 hours."""

    transport = _recorder()
    client = _client(transport)
    assert client.access_token() == client.access_token() == "TOKEN"
    assert len(transport.calls) == 1

    # and a forced refresh is the only thing that asks again
    client.access_token(force_refresh=True)
    assert len(transport.calls) == 2


def test_a_token_that_is_about_to_expire_is_not_handed_out():
    transport = _recorder({"access_token": "SHORT", "expires_in": 30})
    client = _client(transport)
    assert client.access_token() == "SHORT"
    # 30 seconds is inside the one-minute margin, so the next call re-asks
    assert client.access_token() == "SHORT"
    assert len(transport.calls) == 2


def test_credentials_are_required_and_never_come_from_code():
    client = NHClient(config=NHConfig(), transport=_recorder())
    with pytest.raises(NHError, match="NH_APP_KEY"):
        client.access_token()
    assert NHConfig().configured is False
    assert NHConfig(app_key="a", app_secret_key="b").configured is True


def test_a_response_without_a_token_says_so_without_printing_the_secret():
    transport = _recorder({"error": "invalid_client", "appkey": "KEY"})
    with pytest.raises(NHError) as caught:
        _client(transport).access_token()
    message = str(caught.value)
    assert "invalid_client" in message
    assert "KEY" not in message and "***" in message


def test_a_live_order_needs_the_live_trading_gate(monkeypatch):
    """The gate exists to protect real money and is checked before the call."""

    monkeypatch.delenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", raising=False)
    transport = _recorder()
    client = _client(transport, is_paper=False, account_no="20901867134")
    with pytest.raises(LiveTradingDisabledError):
        client.place_order(side="buy", code="005930", quantity=1, price=70_000)
    assert transport.calls == []                        # nothing left the machine


def test_a_paper_order_does_not_need_that_gate(monkeypatch):
    """Paper is where mistakes belong; the gate is about real money."""

    monkeypatch.delenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", raising=False)
    transport = _recorder({"rsp_cd": "00047", "Output_0": {"mkt_orr_no": 1}})
    client = _client(transport, is_paper=True, account_no="50001004611")
    client._token = "TOKEN"                                             # noqa: SLF001
    client._token_expires_at = time.time() + 3600                       # noqa: SLF001

    client.place_order(side="buy", code="005930", quantity=1, price=70_000)
    sent = transport.calls[-1]
    assert sent["url"].endswith("/krstock/order/v1/cashBuy")
    assert sent["headers"]["tr_cd"] == "SCSOS61803A"
    assert sent["data"]["Input_0"]["act_no"] == "50001004611"
    assert sent["data"]["Input_0"]["orr_qty"] == 1
    assert sent["data"]["Input_0"]["orr_pr"] == 70_000


def test_a_sell_goes_to_the_sell_endpoint():
    transport = _recorder({"rsp_cd": "00047", "Output_0": {}})
    client = _client(transport, is_paper=True, account_no="50001004611")
    client._token = "TOKEN"                                             # noqa: SLF001
    client._token_expires_at = time.time() + 3600                       # noqa: SLF001

    client.place_order(side="sell", code="005930", quantity=2, price=71_000)
    sent = transport.calls[-1]
    assert sent["url"].endswith("/krstock/order/v1/cashSell")
    assert sent["headers"]["tr_cd"] == "SCSOS61801A"


def test_nonsense_never_reaches_the_broker():
    transport = _recorder()
    client = _client(transport, is_paper=True, account_no="50001004611")
    for bad in ({"side": "short"}, {"quantity": 0}, {"price": -1}):
        with pytest.raises(ValueError):
            client.place_order(**{"side": "buy", "code": "005930", "quantity": 1,
                                  "price": 1000, **bad})
    assert transport.calls == []


def test_the_token_cache_is_shared_across_processes_and_kept_private(tmp_path, monkeypatch):
    """Every CLI and cron process must reuse one token, as the KIS one does."""

    monkeypatch.setenv("TRADINGAGENTS_NH_TOKEN_CACHE_DIR", str(tmp_path))
    config = NHConfig(app_key="KEY", app_secret_key="SECRET")

    calls = {"n": 0}

    def transport(method, url, headers, params, data):
        calls["n"] += 1
        return {"access_token": "CACHED", "expires_in": 86400}

    # the first client writes the cache; a transport of None is what enables it,
    # so the write path is exercised by swapping it in after construction
    first = NHClient(config=config, transport=transport)
    first.transport = None
    first._request = lambda *a, **k: {"access_token": "CACHED", "expires_in": 86400}  # noqa: SLF001
    assert first.access_token() == "CACHED"

    written = list(tmp_path.glob("token-*.json"))
    assert len(written) == 1
    stored = json.loads(written[0].read_text(encoding="utf-8"))
    assert stored["access_token"] == "CACHED" and stored["expires_at"] > time.time()

    # a second process finds it and never calls the endpoint
    second = NHClient(config=config, transport=transport)
    second.transport = None
    assert second.access_token() == "CACHED"
    assert calls["n"] == 0


def test_the_base_url_and_paths_match_the_published_guide():
    from tradingagents.execution import nh_client

    assert nh_client.BASE_URL == "https://api.nhplug.com:8443"
    assert nh_client.TOKEN_PATH == "/oauth2/token"
    assert nh_client.REVOKE_PATH == "/oauth2/revoke"
    # the rate limit the guide states is one per second, so the retry pause is
    # seconds rather than the minute KIS needs
    assert 1 <= nh_client.TOKEN_RATE_LIMIT_WAIT_SECONDS <= 5


def test_the_account_number_is_sent_the_way_nh_wants_not_the_way_it_displays():
    """Its own page shows 209-01-867134; the API answers IGW40011 to that."""

    from tradingagents.execution.nh_client import _account

    assert _account("209-01-867134") == "20901867134"
    assert _account("20901867134") == "20901867134"
    assert _account(" 209-01-867134 ") == "20901867134"
    assert _account("") == ""


def test_one_key_pair_covers_both_accounts_and_only_the_account_differs(monkeypatch):
    """NAMUH PLUG registers 모의투자 with the API service; no second key."""

    monkeypatch.setenv("NH_APP_KEY", "K")
    monkeypatch.setenv("NH_APP_SECRET_KEY", "S")
    monkeypatch.setenv("NH_ACCOUNT_NO", "209-01-867134")
    monkeypatch.setenv("NH_PAPER_ACCOUNT_NO", "500-01-004611")
    monkeypatch.delenv("NH_IS_PAPER", raising=False)

    # paper by default, because the alternative default is a live brokerage
    # account reachable by a typo
    paper = NHConfig.from_env()
    assert paper.mode == "paper"
    assert (paper.app_key, paper.account_no) == ("K", "50001004611")

    live = NHConfig.from_env(paper=False)
    assert (live.app_key, live.account_no) == ("K", "20901867134")

    monkeypatch.setenv("NH_IS_PAPER", "false")
    assert NHConfig.from_env().mode == "live"


def test_the_account_goes_to_the_paper_host_and_the_quote_never_does():
    """Paper answers IGW40023 for quotes, so prices always come from live."""

    from tradingagents.execution.nh_client import BASE_URL, PAPER_BASE_URL

    paper = NHConfig(app_key="K", app_secret_key="S", is_paper=True)
    assert paper.account_url == PAPER_BASE_URL
    assert paper.quote_url == BASE_URL

    live = NHConfig(app_key="K", app_secret_key="S", is_paper=False)
    assert live.account_url == BASE_URL == live.quote_url


def test_a_paper_client_sends_the_balance_and_the_quote_to_different_hosts():
    from tradingagents.execution.nh_client import BASE_URL, PAPER_BASE_URL

    transport = _recorder({"rsp_cd": "00000", "Output_0": {}})
    client = _client(transport, account_no="50001004611", is_paper=True)
    client._token = "TOKEN"                                             # noqa: SLF001
    client._token_expires_at = time.time() + 3600                       # noqa: SLF001

    client.balance()
    assert transport.calls[-1]["url"].startswith(PAPER_BASE_URL)
    client.current_price("005930")
    assert transport.calls[-1]["url"].startswith(BASE_URL)


def test_the_token_is_always_issued_on_the_live_host():
    """The paper host answers IGW40058 to a token request."""

    from tradingagents.execution.nh_client import BASE_URL

    transport = _recorder()
    client = _client(transport, is_paper=True)
    client.access_token()
    assert transport.calls[0]["url"] == f"{BASE_URL}/oauth2/token"


def test_the_token_cache_is_per_mode(monkeypatch, tmp_path):
    """A paper token must never be handed to a live call, or the reverse."""

    monkeypatch.setenv("TRADINGAGENTS_NH_TOKEN_CACHE_DIR", str(tmp_path))
    paper = NHClient(config=NHConfig(app_key="K", app_secret_key="S", is_paper=True))
    live = NHClient(config=NHConfig(app_key="K", app_secret_key="S", is_paper=False))
    assert paper._token_cache_path() != live._token_cache_path()   # noqa: SLF001


def test_business_calls_are_json_and_carry_the_tr_code():
    """The token call is form-encoded; everything else is not."""

    transport = _recorder({"rsp_cd": "00166", "Output_0": {"tot_aet_amt": 1}})
    client = _client(transport, account_no="20901867134")
    client._token = "TOKEN"                                             # noqa: SLF001
    client._token_expires_at = time.time() + 3600                       # noqa: SLF001

    client.balance()
    sent = transport.calls[-1]
    assert sent["url"].endswith("/krstock/inquiry/v1/balance")
    assert sent["headers"]["tr_cd"] == "SCIOT983691"
    assert sent["headers"]["Authorization"] == "Bearer TOKEN"
    assert "json" in sent["headers"]["Content-Type"]
    assert sent["data"]["Input_0"]["act_no"] == "20901867134"

    client.current_price("5930")
    sent = transport.calls[-1]
    assert sent["headers"]["tr_cd"] == "IVOUTKMST04"
    # six digits, however the ticker was typed
    assert sent["data"]["Input_0"] == {"market_cd": "KRX", "iem_cd": "005930"}


def test_a_business_failure_is_raised_rather_than_returned_as_an_empty_result():
    """NH answers 200 with a code; only some of them mean it worked."""

    transport = _recorder({"rsp_cd": "IGW40011", "rsp_msg": "act_no 길이나 data type을 확인하세요."})
    client = _client(transport)
    client._token = "TOKEN"                                             # noqa: SLF001
    client._token_expires_at = time.time() + 3600                       # noqa: SLF001

    with pytest.raises(NHError, match="IGW40011"):
        client.balance("20901867134")


def test_a_token_the_gateway_has_already_retired_is_replaced_and_the_call_retried():
    """NH can drop a token before the expiry it handed out. The cache cannot know."""

    state = {"issued": 0, "tried": 0}

    def transport(method, url, headers, params, data):
        if url.endswith("/oauth2/token"):
            state["issued"] += 1
            return {"access_token": f"T{state['issued']}", "expires_in": 86400}
        state["tried"] += 1
        if headers["Authorization"] == "Bearer T1":
            raise NHError('NH POST ... -> 400: {"rsp_cd":"IGW40043","rsp_msg":"유효하지 않은 token 입니다."}')
        return {"rsp_cd": "00166", "Output_0": {"dca": 1}}

    client = _client(transport, account_no="50001004611")
    assert client.balance()["Output_0"]["dca"] == 1
    assert state["issued"] == 2      # the stale one, then a fresh one
    assert state["tried"] == 2       # and the business call was sent twice


def test_any_other_failure_is_not_retried_with_a_new_token():
    """A closed market is not an auth problem, and burning a token on it hides that."""

    state = {"issued": 0}

    def transport(method, url, headers, params, data):
        if url.endswith("/oauth2/token"):
            state["issued"] += 1
            return {"access_token": "TOKEN", "expires_in": 86400}
        raise NHError("NH ... -> 14580: 장운영일이 아닙니다.")

    client = _client(transport, account_no="50001004611")
    with pytest.raises(NHError, match="14580"):
        client.balance()
    assert state["issued"] == 1


def test_the_period_pnl_calls_send_dates_as_eight_digits_however_they_are_written():
    transport = _recorder({"rsp_cd": "00000", "Output_0": {}, "Output_1": []})
    client = _ready(transport, account_no="50001004611")
    client.daily_pnl(start="2026-06-01", end="2026-07-01")
    client.trading_pnl(start="20260601", end="20260701")

    daily, trading = transport.calls[0], transport.calls[1]
    assert daily["headers"]["tr_cd"] == "SCSOS63119A"
    assert trading["headers"]["tr_cd"] == "SCSOS63122A"
    for sent in (daily, trading):
        assert sent["data"]["Input_0"]["iqr_sta_dt"] == "20260601"
        assert sent["data"]["Input_0"]["iqr_end_dt"] == "20260701"


def test_the_investor_flow_is_asked_of_the_live_host_because_paper_has_no_prices():
    transport = _recorder({"rsp_cd": "00000", "Output_0": []})
    client = _ready(transport, account_no="50001004611", is_paper=True)
    client.investors("5930", days=20)

    sent = transport.calls[0]
    assert sent["url"].startswith("https://api.nhplug.com:8443")
    assert sent["headers"]["tr_cd"] == "IVOUORDAY05"
    assert sent["data"]["Input_0"] == {"market_cd": "KRX", "iem_cd": "005930", "array_cnt": "20"}


def test_a_reserved_buy_and_sell_are_the_two_numbers_nh_uses_for_the_sides():
    """sby_dit_cd is 2 for a buy and 1 for a sell, which is easy to get backwards."""

    transport = _recorder({"rsp_cd": "00210", "Output_0": {"bkg_orr_no": 27}})
    client = _ready(transport, account_no="50001004611", is_paper=True)
    client.place_reserved_order(side="buy", code="005940", quantity=10, price=35_000)
    client.place_reserved_order(side="sell", code="005940", quantity=10, price=35_000)

    buy, sell = transport.calls[0], transport.calls[1]
    assert buy["headers"]["tr_cd"] == "SCSOS61201A"
    assert buy["data"]["Input_0"]["sby_dit_cd"] == "2"
    assert sell["data"]["Input_0"]["sby_dit_cd"] == "1"
    assert buy["data"]["Input_0"]["orr_qty"] == 10
    assert buy["data"]["Input_0"]["orr_uit_pr"] == 35_000


def test_a_reserved_order_into_the_live_account_needs_the_same_switch_as_a_live_one(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", raising=False)
    transport = _recorder({"rsp_cd": "00210", "Output_0": {"bkg_orr_no": 27}})
    client = _client(transport, account_no="50001004611", is_paper=False)

    with pytest.raises(LiveTradingDisabledError):
        client.place_reserved_order(side="buy", code="005940", quantity=1, price=100)
    assert len(transport.calls) == 0        # not even a token was fetched


def test_cancelling_a_reservation_names_the_order_and_the_side():
    transport = _recorder({"rsp_cd": "00106", "Output_0": {}})
    client = _ready(transport, account_no="50001004611", is_paper=True)
    client.cancel_reserved_order(reserved_no=27, code="005940", side="buy")

    sent = transport.calls[0]
    assert sent["headers"]["tr_cd"] == "SCSOS61202A"
    assert sent["data"]["Input_0"]["bkg_orr_no"] == 27
    assert sent["data"]["Input_0"]["sby_dit_cd"] == "2"

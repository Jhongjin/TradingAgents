"""NH 나무증권 (NAMUH PLUG) REST client.

Shaped after ``kis_client`` because the two brokers authenticate the same way —
``client_credentials`` against an app key and secret, one long-lived bearer
token — but the details differ enough to burn an afternoon:

    KIS   POST /oauth2/tokenP   application/json              appsecret
    NH    POST /oauth2/token    x-www-form-urlencoded         appsecretkey, scope=oob

NH publishes a limit of one token request per second and says plainly not to
re-issue before the 24 hours are up, so the token is cached on disk and shared
across processes exactly as the KIS one is.

Orders are 현금 매수/매도 at a limit price and nothing else. The catalogue also
has credit and reserved orders, and a 시장가 code this project cannot read the
meaning of; none of them are wired, because each is a separate decision rather
than a missing branch.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .kis_client import LiveTradingDisabledError, live_trading_enabled

BASE_URL = "https://api.nhplug.com:8443"
# 모의투자 runs on its own host with the same credentials. Two rules the guide
# does not put together and the errors do: the token must be issued on the live
# host (the paper one answers IGW40058 "모의투자 서버는 토큰발급이 제한됩니다"),
# and quotes are not served there either (IGW40023 "모의투자에서는 미지원"), so
# prices always come from live while the account and orders go to paper.
PAPER_BASE_URL = "https://moapi.nhplug.com:8443"
TOKEN_PATH = "/oauth2/token"
REVOKE_PATH = "/oauth2/revoke"

# 현금 매수/매도 only. Credit and reserved orders exist in the catalogue and are
# not wired: they are a different risk conversation, not a missing branch.
SUCCESS_PREFIXES = ("0", "XA1")

ORDER_PATHS = {
    "buy": ("/krstock/order/v1/cashBuy", "SCSOS61803A"),
    "sell": ("/krstock/order/v1/cashSell", "SCSOS61801A"),
}

# NAMUH PLUG documents ThroughputQuotaRule.requestLimit = 1 on the token
# endpoint, measured per second.
TOKEN_RATE_LIMIT_WAIT_SECONDS = 2
# The gateway's way of saying the bearer token is no longer good, whatever the
# expiry it came with claimed.
TOKEN_REJECTED = "IGW40043"

Transport = Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None, Mapping[str, Any] | None], Mapping[str, Any]]


class NHError(RuntimeError):
    """Raised for NH transport or API-level failures."""


class NHOrdersUnavailableError(NHError):
    """Raised when an order cannot be attempted at all."""


@dataclass(frozen=True)
class NHConfig:
    """Credentials and account, read from the environment.

    The key and secret are never written anywhere by this project: they go in
    .env by hand, like every other credential here.
    """

    app_key: str = ""
    app_secret_key: str = ""
    account_no: str = ""
    base_url: str = BASE_URL
    is_paper: bool = True

    @property
    def account_url(self) -> str:
        """Where the balance and the orders go."""

        return PAPER_BASE_URL if self.is_paper else self.base_url

    @property
    def quote_url(self) -> str:
        """Where prices come from: always live, because paper has none."""

        return self.base_url

    @classmethod
    def from_env(cls, *, paper: bool | None = None) -> "NHConfig":
        """Credentials for one account, paper unless told otherwise.

        A key is bound to the account it was issued for: asking the live key
        about the 모의투자 account returns IGW40018 "토큰정보로 발급된
        계좌정보와 일치하지 않습니다". So the two are separate triples and
        this picks one, rather than pretending a single key covers both.

        Paper is the default because the alternative default is a live
        brokerage account reachable by a typo.
        """

        want_paper = _flag("NH_IS_PAPER", default=True) if paper is None else paper
        # One credential pair covers both: NAMUH PLUG registers the 모의투자
        # service automatically with the API service, and only the host and the
        # account number differ. NH_PAPER_ACCOUNT_NO is the 500- account.
        account = os.getenv("NH_PAPER_ACCOUNT_NO" if want_paper else "NH_ACCOUNT_NO") or ""
        return cls(
            app_key=(os.getenv("NH_APP_KEY") or "").strip(),
            app_secret_key=(os.getenv("NH_APP_SECRET_KEY") or "").strip(),
            account_no=_account(account),
            base_url=(os.getenv("NH_BASE_URL") or BASE_URL).strip().rstrip("/"),
            is_paper=want_paper,
        )

    @property
    def mode(self) -> str:
        return "paper" if self.is_paper else "live"

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret_key)


@dataclass
class NHClient:
    """Thin REST client. ``transport(method, url, headers, params, data)`` returns parsed JSON."""

    config: NHConfig
    transport: Transport | None = None
    timeout: float = 10.0
    _token: str | None = field(default=None, init=False, repr=False)
    _token_expires_at: float = field(default=0.0, init=False, repr=False)

    # ----------------------------------------------------------------- auth
    def access_token(self, *, force_refresh: bool = False) -> str:
        """A valid bearer token, reusing the on-disk cache across processes."""

        if self._token and not force_refresh and time.time() < self._token_expires_at - 60:
            return self._token
        if not force_refresh:
            cached = self._load_cached_token()
            if cached:
                self._token, self._token_expires_at = cached
                return self._token
        if not self.config.configured:
            raise NHError("NH_APP_KEY and NH_APP_SECRET_KEY are required")

        body = {
            "appkey": self.config.app_key,
            "appsecretkey": self.config.app_secret_key,
            "grant_type": "client_credentials",
            "scope": "oob",
        }
        headers = {"content-type": "application/x-www-form-urlencoded"}
        try:
            response = self._request("POST", TOKEN_PATH, headers=headers, data=body)
        except NHError:
            # One request per second, so a second attempt after a pause is the
            # difference between a transient limit and a real failure.
            if self.transport is not None:
                raise
            time.sleep(TOKEN_RATE_LIMIT_WAIT_SECONDS)
            response = self._request("POST", TOKEN_PATH, headers=headers, data=body)

        token = str(response.get("access_token") or "")
        if not token:
            raise NHError(f"NH token response did not include access_token: {_redact(response)}")
        self._token = token
        self._token_expires_at = time.time() + float(response.get("expires_in") or 86_400)
        self._store_cached_token()
        return token

    def revoke(self) -> Mapping[str, Any]:
        """Hand the token back, and forget it here and on disk."""

        if not self._token:
            cached = self._load_cached_token()
            if cached:
                self._token, self._token_expires_at = cached
        if not self._token:
            return {"revoked": False, "reason": "no token"}
        response = self._request(
            "POST",
            REVOKE_PATH,
            headers={"content-type": "application/x-www-form-urlencoded"},
            data={"appkey": self.config.app_key, "appsecretkey": self.config.app_secret_key, "token": self._token},
        )
        self._token, self._token_expires_at = None, 0.0
        path = self._token_cache_path()
        if path is not None and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        return response

    def _token_cache_path(self) -> Path | None:
        if self.transport is not None:                  # injected transports never touch disk
            return None
        root = os.getenv("TRADINGAGENTS_NH_TOKEN_CACHE_DIR") or os.path.join(
            os.path.expanduser("~"), ".tradingagents", "nh"
        )
        digest = hashlib.sha256(f"nh:{self.config.mode}:{self.config.app_key}".encode("utf-8")).hexdigest()[:16]
        return Path(root) / f"token-{digest}.json"

    def _load_cached_token(self) -> tuple[str, float] | None:
        path = self._token_cache_path()
        if path is None or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            token = str(payload.get("access_token") or "")
            expires_at = float(payload.get("expires_at") or 0.0)
        except (OSError, ValueError, TypeError):
            return None
        if not token or time.time() >= expires_at - 60:
            return None
        return token, expires_at

    def _store_cached_token(self) -> None:
        path = self._token_cache_path()
        if path is None or not self._token:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"access_token": self._token, "expires_at": self._token_expires_at}),
                encoding="utf-8",
            )
            try:                                        # the token is a credential
                path.chmod(0o600)
            except OSError:
                pass
        except OSError:
            pass

    # ----------------------------------------------------------- read only
    def _call(self, path: str, tr_code: str, payload: Mapping[str, Any], *, live_only: bool = False) -> Mapping[str, Any]:
        """One NAMUH PLUG business call.

        The token endpoint is form-encoded; everything else is JSON and carries
        the TR code the catalogue lists under extraParam.tr_cd, which is the
        same place KIS puts tr_id.
        """

        base = self.config.quote_url if live_only else self.config.account_url
        body = {"Input_0": dict(payload)}

        def send(token: str) -> Mapping[str, Any]:
            return self._request("POST", path, base_url=base, json_body=body, headers={
                "Content-Type": "application/json; charset=UTF-8",
                "Authorization": f"Bearer {token}",
                "tr_cd": tr_code,
            })

        try:
            response = send(self.access_token())
        except NHError as first:
            # NH can retire a token before the expiry it handed out, and the
            # cache on disk has no way to know. IGW40043 is that and only that,
            # so it is worth one fresh token before giving up — otherwise the
            # desk goes dark until someone deletes the cache file by hand.
            if TOKEN_REJECTED not in str(first):
                raise
            response = send(self.access_token(force_refresh=True))

        code = str(response.get("rsp_cd") or "")
        # NH answers HTTP 200 with a business code, and only some mean success,
        # so a failure must not arrive upstream looking like an empty result.
        #
        # Observed successes: 00000, 00047 매수완료, 00164 정정완료, 00166 잔고,
        # 00192 취소완료, XA102 조회완료. Observed failures: IGW40011/40018/
        # 40023/40058/42903, 11165 계좌번호, 14580 장운영일. An unknown code is
        # treated as a failure on purpose — reporting an order as placed when it
        # was not is the expensive direction to be wrong in.
        if code and not code.startswith(SUCCESS_PREFIXES):
            raise NHError(f"NH {path} -> {code}: {response.get('rsp_msg') or ''}")
        return response

    def balance(self, account_no: str | None = None) -> Mapping[str, Any]:
        """국내 주식 잔고."""

        return self._call("/krstock/inquiry/v1/balance", "SCIOT983691", {
            "act_no": account_no or self.config.account_no,
            "bnc_bse_cd": "1", "ltg_aot_dit_cd": "9", "aet_bse": "2",
            "qut_dit_cd": "UNT", "aly_qut_cd": "2",
        })

    def current_price(self, code: str, *, market: str = "KRX") -> Mapping[str, Any]:
        """국내 주식 현재가."""

        # Always from the live host: the paper one answers IGW40023.
        return self._call("/krstock/quote/v1/currentPrice", "IVOUTKMST04",
                          {"market_cd": market, "iem_cd": _code(code)}, live_only=True)

    # --------------------------------------------------------------- orders
    def place_order(
        self,
        *,
        side: str,
        code: str,
        quantity: int,
        price: int,
        account_no: str | None = None,
    ) -> Mapping[str, Any]:
        """One 지정가 order. Limit only, and deliberately so.

        NAMUH PLUG's catalogue gives working values for nmn_pr_tp_cd,
        orr_cnd_dit_cd and the rest in its request example, but documents what
        none of them mean — the description field is twenty-one characters and
        tr/property is empty. So the example's values go through verbatim and
        there is no 시장가 option: guessing which code means "at market" is the
        kind of guess that sells a position at any price it can find.
        """

        chosen = str(side).strip().lower()
        if chosen not in ORDER_PATHS:
            raise ValueError(f"side must be buy or sell, not {side!r}")
        if int(quantity) <= 0 or int(price) <= 0:
            raise ValueError("quantity and price must both be positive")
        if not self.config.is_paper and not live_trading_enabled():
            raise LiveTradingDisabledError(
                "TRADINGAGENTS_ENABLE_LIVE_TRADING is not set; no live order will be sent"
            )

        path, tr_code = ORDER_PATHS[chosen]
        return self._call(path, tr_code, {
            "act_no": account_no or self.config.account_no,
            "iem_cd": _code(code),
            "orr_qty": int(quantity),
            "orr_pr": int(price),
            # straight from the published request example; see the docstring
            "nmn_pr_tp_cd": "01",
            "orr_cnd_dit_cd": "00",
            "ssl_nmn_pr_dit_cd": "00",
            "rmt_mkt_cd": "SOR",
            "sor_mkt_sli_yn": "N",
        })

    def cancel_order(
        self,
        *,
        order_no: int,
        code: str,
        quantity: int | None = None,
        account_no: str | None = None,
    ) -> Mapping[str, Any]:
        """Cancel an order, all of it or part.

        all_pat_dit_cd is 1 for the whole thing and 2 for a quantity, which is
        how NH's own examples use it — 2 always arrives with cor_qty. Cancelling
        never needs the live-trading gate: taking an order back is the safe
        direction, and a gate that blocks it is a gate that traps you in a
        position.
        """

        payload: dict[str, Any] = {
            "act_no": account_no or self.config.account_no,
            "org_mkt_orr_no": int(order_no),
            "all_pat_dit_cd": "1" if quantity is None else "2",
            "iem_cd": _code(code),
        }
        if quantity is not None:
            if int(quantity) <= 0:
                raise ValueError("quantity must be positive")
            payload["cor_qty"] = int(quantity)
        return self._call("/krstock/order/v1/cancel", "SCSOS61809A", payload)

    def modify_order(
        self,
        *,
        order_no: int,
        code: str,
        price: int,
        account_no: str | None = None,
    ) -> Mapping[str, Any]:
        """Move an order to a new limit price, in full."""

        if int(price) <= 0:
            raise ValueError("price must be positive")
        if not self.config.is_paper and not live_trading_enabled():
            raise LiveTradingDisabledError(
                "TRADINGAGENTS_ENABLE_LIVE_TRADING is not set; no live order will be changed"
            )
        return self._call("/krstock/order/v1/modify", "SCSOS61808A", {
            "act_no": account_no or self.config.account_no,
            "org_mkt_orr_no": int(order_no),
            "all_pat_dit_cd": "1",
            "iem_cd": _code(code),
            "cor_pr": int(price),
            "rmt_mkt_cd": "SOR",
            "sor_mkt_sli_yn": "N",
        })

    def executions(self, *, on: str | None = None, account_no: str | None = None) -> Mapping[str, Any]:
        """Today's orders and what became of them. `on` is YYYYMMDD."""

        from datetime import datetime
        from zoneinfo import ZoneInfo

        day = on or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
        return self._call("/krstock/inquiry/v1/dailyOrderExecution", "SCSOS630261", {
            "orr_dt": "".join(ch for ch in str(day) if ch.isdigit())[:8],
            "act_no": account_no or self.config.account_no,
            "orr_mkt_cd": "00",
            "ost_cns_dit": "0",
        })

    def buyable_quantity(self, code: str, price: int, account_no: str | None = None) -> Mapping[str, Any]:
        """How many the account could buy at that price.

        The TR code here is SCSOS62018A, not the balance one — an earlier
        version reused SCIOT983691 and the gateway answered for the wrong
        transaction entirely.
        """

        return self._call("/krstock/inquiry/v1/buyableQuantity", "SCSOS62018A", {
            "ost_dit_cd": "1",
            "act_no": account_no or self.config.account_no,
            "iem_cd": _code(code),
            "nmn_pr_tp_cd": "01",
            "orr_pr": int(price),
            "mdi_tp_cd": "3",
            "cfd_lon_cd": "00",
            "lon_dt": "",
        })

    def daily_candles(self, code: str, *, count: int = 60, market: str = "KRX") -> Mapping[str, Any]:
        """Daily bars, newest first. Live host only, like every other quote."""

        return self._call("/krstock/quote/v1/currentDaily", "IVOUTKDAY04", {
            "market_cd": market,
            "iem_cd": _code(code),
            "array_cnt": str(int(count)),
            "view_main_yn": "N",
        }, live_only=True)

    # KRX 금시장's one liquid contract: 1kg bars of 99.99% gold, priced in won
    # per gram. Not the same instrument as COMEX gold, which is dollars an ounce.
    GOLD_99_99_1KG = "M04020000"

    def gold_price(self, code: str = GOLD_99_99_1KG) -> Mapping[str, Any]:
        """Spot gold on KRX right now, in won per gram."""

        return self._call("/krgold/quote/v1/goldCurrent", "IVOGLDMST01",
                          {"code": str(code).strip()}, live_only=True)

    def gold_candles(self, *, start: str, end: str, code: str = GOLD_99_99_1KG,
                     period: str = "1") -> Mapping[str, Any]:
        """Daily bars for KRX gold. period is 1 daily, 2 weekly, 3 monthly."""

        return self._call("/krgold/quote/v1/goldDailyTrend", "IVOGLDDAY01", {
            "iem_cd": str(code).strip(),
            "sdate": _day(start),
            "edate": _day(end),
            "gubun": str(period),
        }, live_only=True)

    def daily_pnl(self, *, start: str, end: str, account_no: str | None = None) -> Mapping[str, Any]:
        """Realised profit day by day between two dates (YYYYMMDD)."""

        return self._call("/krstock/inquiry/v1/dailyPnl", "SCSOS63119A", {
            "act_no": account_no or self.config.account_no,
            "iqr_sta_dt": _day(start),
            "iqr_end_dt": _day(end),
        })

    def trading_pnl(self, *, start: str, end: str, account_no: str | None = None) -> Mapping[str, Any]:
        """The same window broken down by ticker."""

        return self._call("/krstock/inquiry/v1/tradingPnl", "SCSOS63122A", {
            "act_no": account_no or self.config.account_no,
            "iqr_sta_dt": _day(start),
            "iqr_end_dt": _day(end),
        })

    def investors(self, code: str, *, days: int = 20, market: str = "KRX") -> Mapping[str, Any]:
        """Who was buying: foreigners, institutions, individuals, by day."""

        return self._call("/krstock/quote/v1/currentInvestor", "IVOUORDAY05", {
            "market_cd": market, "iem_cd": _code(code), "array_cnt": str(int(days)),
        }, live_only=True)

    def transactions(self, *, start: str, end: str, account_no: str | None = None) -> Mapping[str, Any]:
        """Every trade the broker recorded in a window — its books, not ours."""

        return self._call("/common/inquiry/v1/totalTransaction", "SCIOT920011", {
            "iqr_tp_cd": "1",
            "iqr_rge_cd": "1",
            "act_no": account_no or self.config.account_no,
            "iqr_sta_dt": _day(start),
            "iqr_end_dt": _day(end),
            "iem_llf_cd": "00",
            "act_trd_dtl_cd": "00",
        })

    def cash_movements(self, *, start: str, end: str, account_no: str | None = None) -> Mapping[str, Any]:
        """Money in and out of the account, which no trade record explains."""

        return self._call("/common/inquiry/v1/depositWithdrawal", "SCIOT920011", {
            "iqr_tp_cd": "1",
            "act_no": account_no or self.config.account_no,
            "iqr_sta_dt": _day(start),
            "iqr_end_dt": _day(end),
            "act_trd_dtl_cd": "01",
        })

    def accounts(self) -> Mapping[str, Any]:
        """Which accounts this key can see. No TR code and no body: NH's odd one out."""

        return self._request("POST", "/n2/acctinfo", base_url=self.config.base_url, json_body={},
                             headers={"Content-Type": "application/json; charset=UTF-8",
                                      "Authorization": f"Bearer {self.access_token()}"})

    def realized_pnl(self, account_no: str | None = None) -> Mapping[str, Any]:
        """Today's standing: cash, evaluation, and profit on what is still held."""

        return self._call("/krstock/inquiry/v1/realizedPnl", "SCIOT933581", {
            "act_no": account_no or self.config.account_no,
            "iqr_dit_cd1": "0",
            "fee_dit_cd": "1",
            "qut_dit_cd": "UNT",
            "aly_qut_cd": "2",
        })

    def reserved_orders(self, account_no: str | None = None) -> Mapping[str, Any]:
        """Orders queued for a later session. Live account only — the paper
        gateway answers 19999 for every 예약주문 call."""

        return self._call("/krstock/inquiry/v1/reservedInquiry", "SCSOS63053A", {
            "act_no": account_no or self.config.account_no,
            "sby_dit_cd": "0",
            "bkg_orr_tp_cd": "0",
        })

    def place_reserved_order(
        self,
        *,
        side: str,
        code: str,
        quantity: int,
        price: int,
        account_no: str | None = None,
    ) -> Mapping[str, Any]:
        """Queue a limit order for the next session.

        sby_dit_cd is 1 for a sell and 2 for a buy, which is the one place NH
        numbers the two sides rather than naming them — and the one place it is
        easy to get backwards, so it is written here once.
        """

        chosen = str(side).strip().lower()
        if chosen not in {"buy", "sell"}:
            raise ValueError(f"side must be buy or sell, not {side!r}")
        if int(quantity) <= 0 or int(price) <= 0:
            raise ValueError("quantity and price must both be positive")
        if not self.config.is_paper and not live_trading_enabled():
            raise LiveTradingDisabledError(
                "TRADINGAGENTS_ENABLE_LIVE_TRADING is not set; no live order will be sent"
            )

        return self._call("/krstock/order/v1/reservedOrder", "SCSOS61201A", {
            "act_no": account_no or self.config.account_no,
            "iem_cd": _code(code),
            "sby_dit_cd": "2" if chosen == "buy" else "1",
            "frs_sba_orr_yn": "N",
            "nmn_pr_tp_cd": "01",
            "cfd_lon_cd": "00",
            "orr_qty": int(quantity),
            "orr_uit_pr": int(price),
            "bkg_orr_tp_cd": "1",
            "bkg_orr_enf_tp_cd": "1",
            "rmt_mkt_cd": "KRX",
        })

    def cancel_reserved_order(
        self,
        *,
        reserved_no: int,
        code: str,
        side: str,
        account_no: str | None = None,
    ) -> Mapping[str, Any]:
        """Take a queued order back."""

        chosen = str(side).strip().lower()
        return self._call("/krstock/order/v1/reservedCancel", "SCSOS61202A", {
            "act_no": account_no or self.config.account_no,
            "sby_dit_cd": "2" if chosen == "buy" else "1",
            "iem_cd": _code(code),
            "bkg_orr_no": int(reserved_no),
            "bkg_orr_tp_cd": "1",
            "rmt_mkt_cd": "KRX",
        })

    def sellable_quantity(self, code: str, account_no: str | None = None) -> Mapping[str, Any]:
        """How many of it the account could sell right now.

        Not the same as the balance: today's buys may not have settled, which
        is the gap between bnc_qty and sll_pbl_qty.
        """

        return self._call("/krstock/inquiry/v1/sellableQuantity", "SCSOS620161", {
            "act_no": account_no or self.config.account_no,
            "iem_cd": _code(code),
            "lon_dt": "",
            "cfd_lon_cd": "00",
        })

    # ------------------------------------------------------------- transport
    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        base_url: str | None = None,
    ) -> Mapping[str, Any]:
        url = f"{base_url or self.config.base_url}{path}"
        send = self.transport or self._requests_transport
        return send(method, url, dict(headers or {}), params, json_body if json_body is not None else data)

    def _requests_transport(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None,
        data: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        import requests

        from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

        # This machine sits behind a TLS-inspecting proxy; the chain is only
        # trusted by Windows' own store, not the one bundled with certifi.
        apply_system_truststore_if_available()
        # The token call is form-encoded, every business call is JSON; the
        # content-type header already says which, so it picks the body form.
        as_json = "json" in str(headers.get("Content-Type") or headers.get("content-type") or "")
        try:
            response = requests.request(
                method, url, headers=dict(headers), params=params,
                json=data if as_json else None, data=None if as_json else data,
                timeout=self.timeout,
            )
        except Exception as exc:                        # noqa: BLE001 - surfaced as NHError
            raise NHError(f"NH request failed: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            raise NHError(f"NH {method} {url} -> {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise NHError(f"NH {method} {url} returned non-JSON: {response.text[:200]}") from exc
        return payload if isinstance(payload, Mapping) else {"data": payload}


def _flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _day(value: str) -> str:
    """YYYYMMDD, however the date was written."""

    return "".join(character for character in str(value) if character.isdigit())[:8]


def _account(value: str) -> str:
    """Eleven digits, however the account was written.

    NAMUH PLUG shows 209-01-867134 on its own registration page and then
    answers IGW40011 "act_no 길이나 data type을 확인하세요" when you send it
    that way. It wants the digits only.
    """

    return "".join(character for character in str(value) if character.isdigit())


def _code(value: str) -> str:
    """Six digits, however the ticker was written."""

    digits = "".join(character for character in str(value) if character.isdigit())
    return digits.zfill(6)[:6] if digits else str(value)


def _redact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A response safe to put in an exception message."""

    hidden = {"access_token", "appkey", "appsecretkey", "token"}
    return {key: ("***" if key in hidden else value) for key, value in dict(payload).items()}


__all__ = [
    "BASE_URL",
    "ORDER_PATHS",
    "PAPER_BASE_URL",
    "NHClient",
    "NHConfig",
    "NHError",
    "NHOrdersUnavailableError",
    "TOKEN_PATH",
]

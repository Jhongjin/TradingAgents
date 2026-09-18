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
ORDER_PATHS = {
    "buy": ("/krstock/order/v1/cashBuy", "SCSOS61803A"),
    "sell": ("/krstock/order/v1/cashSell", "SCSOS61801A"),
}

# NAMUH PLUG documents ThroughputQuotaRule.requestLimit = 1 on the token
# endpoint, measured per second.
TOKEN_RATE_LIMIT_WAIT_SECONDS = 2

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

        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Authorization": f"Bearer {self.access_token()}",
            "tr_cd": tr_code,
        }
        base = self.config.quote_url if live_only else self.config.account_url
        response = self._request("POST", path, headers=headers, json_body={"Input_0": dict(payload)}, base_url=base)
        code = str(response.get("rsp_cd") or "")
        # NH answers 200 with a business code; only some of them mean success,
        # so a failure here must not look like an empty result upstream.
        if code and not code.startswith("0"):
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

    def buyable_quantity(self, code: str, price: int, account_no: str | None = None) -> Mapping[str, Any]:
        """How many the account could buy at that price, asked before offering it."""

        return self._call("/krstock/inquiry/v1/buyableQuantity", "SCIOT983691", {
            "act_no": account_no or self.config.account_no,
            "iem_cd": _code(code),
            "orr_pr": int(price),
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

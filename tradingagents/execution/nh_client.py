"""NH 나무증권 (NAMUH PLUG) REST client.

Shaped after ``kis_client`` because the two brokers authenticate the same way —
``client_credentials`` against an app key and secret, one long-lived bearer
token — but the details differ enough to burn an afternoon:

    KIS   POST /oauth2/tokenP   application/json              appsecret
    NH    POST /oauth2/token    x-www-form-urlencoded         appsecretkey, scope=oob

NH publishes a limit of one token request per second and says plainly not to
re-issue before the 24 hours are up, so the token is cached on disk and shared
across processes exactly as the KIS one is.

Order placement is deliberately not implemented here. The endpoints for it
exist in NAMUH PLUG's catalogue but were not in the group this was built from,
and a broker adapter that guesses an order path is worse than one that says it
cannot place orders yet.
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
TOKEN_PATH = "/oauth2/token"
REVOKE_PATH = "/oauth2/revoke"

# NAMUH PLUG documents ThroughputQuotaRule.requestLimit = 1 on the token
# endpoint, measured per second.
TOKEN_RATE_LIMIT_WAIT_SECONDS = 2

Transport = Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None, Mapping[str, Any] | None], Mapping[str, Any]]


class NHError(RuntimeError):
    """Raised for NH transport or API-level failures."""


class NHOrdersUnavailableError(NHError):
    """Raised when something asks this client to trade.

    Kept as its own type so the trade desk can tell "the broker refused" from
    "this half is not built", and so nobody wires an order path by accident.
    """


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

    @classmethod
    def from_env(cls) -> "NHConfig":
        return cls(
            app_key=(os.getenv("NH_APP_KEY") or "").strip(),
            app_secret_key=(os.getenv("NH_APP_SECRET_KEY") or "").strip(),
            account_no=(os.getenv("NH_ACCOUNT_NO") or "").strip(),
            base_url=(os.getenv("NH_BASE_URL") or BASE_URL).strip().rstrip("/"),
        )

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
        digest = hashlib.sha256(f"nh:{self.config.app_key}".encode("utf-8")).hexdigest()[:16]
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

    # --------------------------------------------------------------- orders
    def place_order(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
        """Not built. See the module docstring.

        Live trading also needs TRADINGAGENTS_ENABLE_LIVE_TRADING, and that
        check is here already so the gate does not have to be remembered later.
        """

        if not live_trading_enabled():
            raise LiveTradingDisabledError(
                "TRADINGAGENTS_ENABLE_LIVE_TRADING is not set; no live order will be sent"
            )
        raise NHOrdersUnavailableError(
            "NH 주문 API 명세가 아직 없습니다. nhplug.com 의 국내주식 주문 그룹 명세를 받은 뒤 구현합니다."
        )

    # ------------------------------------------------------------- transport
    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        url = f"{self.config.base_url}{path}"
        send = self.transport or self._requests_transport
        return send(method, url, dict(headers or {}), params, data)

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
        try:
            response = requests.request(method, url, headers=dict(headers), params=params, data=data, timeout=self.timeout)
        except Exception as exc:                        # noqa: BLE001 - surfaced as NHError
            raise NHError(f"NH request failed: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            raise NHError(f"NH {method} {url} -> {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise NHError(f"NH {method} {url} returned non-JSON: {response.text[:200]}") from exc
        return payload if isinstance(payload, Mapping) else {"data": payload}


def _redact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A response safe to put in an exception message."""

    hidden = {"access_token", "appkey", "appsecretkey", "token"}
    return {key: ("***" if key in hidden else value) for key, value in dict(payload).items()}


__all__ = [
    "BASE_URL",
    "NHClient",
    "NHConfig",
    "NHError",
    "NHOrdersUnavailableError",
    "TOKEN_PATH",
]

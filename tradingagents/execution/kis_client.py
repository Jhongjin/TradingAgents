"""Korea Investment & Securities (KIS) Open API client.

Scope and safety model
----------------------
* Defaults to the 모의투자 (virtual trading) server ``openapivts.koreainvestment.com``.
  This is the sanctioned "paper with real order mechanics" stage between the
  local paper broker and a live account, mirroring Binance-Agent's
  testnet → prod progression.
* The live server is used only when **all** of the following hold:
  ``KIS_IS_PAPER=false``, ``TRADINGAGENTS_ENABLE_LIVE_TRADING=true``, and the
  caller passes ``confirm_live=True`` to ``KISBrokerAdapter``. Any missing
  piece raises ``LiveTradingDisabledError`` before a request is built.
* Every order goes through ``dry_run`` first in the harness; the adapter
  itself never retries or resizes an order.

Endpoints (domestic stock, 국내주식)
-----------------------------------
* ``POST /oauth2/tokenP``                                       access token
* ``GET  /uapi/domestic-stock/v1/quotations/inquire-price``     FHKST01010100
* ``GET  /uapi/domestic-stock/v1/trading/inquire-balance``      TTTC8434R / VTTC8434R
* ``POST /uapi/domestic-stock/v1/trading/order-cash``           TTTC0802U/VTTC0802U (buy), TTTC0801U/VTTC0801U (sell)

The transport is injectable so unit tests never touch the network.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .broker import BrokerAccountSnapshot, BrokerOrderResult
from .kis import KISConfig
from .models import Fill, OrderIntent, OrderSide


PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
LIVE_BASE_URL = "https://openapi.koreainvestment.com:9443"

_TR_IDS = {
    "balance": {"paper": "VTTC8434R", "live": "TTTC8434R"},
    "buy_cash": {"paper": "VTTC0802U", "live": "TTTC0802U"},
    "sell_cash": {"paper": "VTTC0801U", "live": "TTTC0801U"},
    "price": {"paper": "FHKST01010100", "live": "FHKST01010100"},
}

ORDER_DIVISION_LIMIT = "00"
ORDER_DIVISION_MARKET = "01"


class KISError(RuntimeError):
    """Raised for KIS transport or API-level failures."""


class LiveTradingDisabledError(KISError):
    """Raised when a live-domain action is attempted without every gate open."""


Transport = Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None, Mapping[str, Any] | None], Mapping[str, Any]]


def live_trading_enabled() -> bool:
    return os.getenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", "false").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class KISClient:
    """Thin REST client. ``transport(method, url, headers, params, json)`` returns parsed JSON."""

    config: KISConfig
    transport: Transport | None = None
    timeout: float = 10.0
    _token: str | None = field(default=None, init=False, repr=False)
    _token_expires_at: float = field(default=0.0, init=False, repr=False)

    @property
    def is_paper(self) -> bool:
        return bool(self.config.is_paper)

    @property
    def base_url(self) -> str:
        return PAPER_BASE_URL if self.is_paper else LIVE_BASE_URL

    @property
    def mode(self) -> str:
        return "paper" if self.is_paper else "live"

    # ----------------------------------------------------------------- auth
    def access_token(self, *, force_refresh: bool = False) -> str:
        if self._token and not force_refresh and time.time() < self._token_expires_at - 60:
            return self._token
        if not self.config.app_key or not self.config.app_secret:
            raise KISError("KIS_APP_KEY and KIS_APP_SECRET are required")
        body = {"grant_type": "client_credentials", "appkey": self.config.app_key, "appsecret": self.config.app_secret}
        response = self._request("POST", "/oauth2/tokenP", headers={"content-type": "application/json"}, json=body)
        token = str(response.get("access_token") or "")
        if not token:
            raise KISError(f"KIS token response did not include access_token: {_redact(response)}")
        self._token = token
        self._token_expires_at = time.time() + float(response.get("expires_in") or 86_400)
        return token

    # --------------------------------------------------------------- quotes
    def current_price(self, code: str) -> dict[str, Any]:
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": _code(code)}
        response = self._api("GET", "/uapi/domestic-stock/v1/quotations/inquire-price", tr_id=_TR_IDS["price"][self.mode], params=params)
        output = response.get("output") or {}
        return {
            "code": _code(code),
            "price": _float(output.get("stck_prpr")),
            "change_rate": _float(output.get("prdy_ctrt")),
            "volume": _float(output.get("acml_vol")),
            "upper_limit": _float(output.get("stck_mxpr")),
            "lower_limit": _float(output.get("stck_llam")),
            "raw": output,
        }

    # -------------------------------------------------------------- balance
    def balance(self) -> dict[str, Any]:
        self._require_account()
        params = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        response = self._api("GET", "/uapi/domestic-stock/v1/trading/inquire-balance", tr_id=_TR_IDS["balance"][self.mode], params=params)
        holdings = []
        for row in response.get("output1") or []:
            quantity = _float(row.get("hldg_qty")) or 0.0
            if quantity <= 0:
                continue
            holdings.append(
                {
                    "code": _code(str(row.get("pdno") or "")),
                    "name": row.get("prdt_name"),
                    "quantity": quantity,
                    "average_price": _float(row.get("pchs_avg_pric")),
                    "current_price": _float(row.get("prpr")),
                    "market_value": _float(row.get("evlu_amt")),
                    "unrealized_pnl": _float(row.get("evlu_pfls_amt")),
                }
            )
        summary_rows = response.get("output2") or []
        summary = summary_rows[0] if summary_rows else {}
        return {
            "cash": _float(summary.get("dnca_tot_amt")) or 0.0,
            "orderable_cash": _float(summary.get("prvs_rcdl_excc_amt")),
            "total_equity": _float(summary.get("tot_evlu_amt")),
            "stock_value": _float(summary.get("scts_evlu_amt")),
            "holdings": holdings,
            "raw": {"output2": summary},
        }

    # --------------------------------------------------------------- orders
    def place_cash_order(
        self,
        code: str,
        side: OrderSide,
        quantity: int,
        *,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Submit a cash order. ``price=None`` sends a market order (ORD_DVSN=01)."""

        self._require_account()
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        tr_key = "buy_cash" if side == OrderSide.BUY else "sell_cash"
        body = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_product_code,
            "PDNO": _code(code),
            "ORD_DVSN": ORDER_DIVISION_MARKET if price is None else ORDER_DIVISION_LIMIT,
            "ORD_QTY": str(int(quantity)),
            "ORD_UNPR": "0" if price is None else str(int(round(price))),
        }
        response = self._api("POST", "/uapi/domestic-stock/v1/trading/order-cash", tr_id=_TR_IDS[tr_key][self.mode], json=body)
        output = response.get("output") or {}
        return {
            "order_id": str(output.get("ODNO") or "") or None,
            "krx_order_no": output.get("KRX_FWDG_ORD_ORGNO"),
            "order_time": output.get("ORD_TMD"),
            "message": str(response.get("msg1") or ""),
            "return_code": str(response.get("rt_cd") or ""),
            "raw": _redact(response),
        }

    # --------------------------------------------------------------- plumbing
    def _api(
        self,
        method: str,
        path: str,
        *,
        tr_id: str,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token()}",
            "appkey": self.config.app_key or "",
            "appsecret": self.config.app_secret or "",
            "tr_id": tr_id,
            "custtype": "P",
        }
        response = self._request(method, path, headers=headers, params=params, json=json)
        return_code = str(response.get("rt_cd") or "0")
        if return_code != "0":
            raise KISError(f"KIS API error {return_code} ({response.get('msg_cd')}): {response.get('msg1')}")
        return response

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        url = f"{self.base_url}{path}"
        transport = self.transport or self._requests_transport
        try:
            return transport(method, url, headers, params, json)
        except KISError:
            raise
        except Exception as exc:
            raise KISError(f"KIS request failed for {path}: {exc.__class__.__name__}: {exc}") from exc

    def _requests_transport(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None,
        json: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        import requests

        response = requests.request(method, url, headers=dict(headers), params=params, json=json, timeout=self.timeout)
        try:
            payload = response.json()
        except ValueError as exc:
            raise KISError(f"KIS returned non-JSON response ({response.status_code})") from exc
        if response.status_code >= 400:
            raise KISError(f"KIS HTTP {response.status_code}: {payload.get('msg1') or payload}")
        return payload

    def _require_account(self) -> None:
        if not self.config.account_no or not self.config.account_product_code:
            raise KISError("KIS_ACCOUNT_NO and KIS_ACCOUNT_PRODUCT_CODE are required")


class KISBrokerAdapter:
    """``BrokerAdapter`` implementation over ``KISClient``.

    Buy orders are sent as limit orders at the supplied price rounded to the
    KRX tick (upward for buys, downward for sells) so the harness' price
    assumption is honoured. Pass ``market_orders=True`` to send ORD_DVSN=01.
    """

    name = "kis"

    def __init__(
        self,
        client: KISClient | None = None,
        *,
        config: KISConfig | None = None,
        confirm_live: bool = False,
        market_orders: bool = False,
        execution_rules: Any | None = None,
    ):
        self.client = client or KISClient(config or KISConfig.from_env())
        self.market_orders = market_orders
        self.execution_rules = execution_rules
        if not self.client.is_paper:
            if not live_trading_enabled():
                raise LiveTradingDisabledError(
                    "KIS_IS_PAPER=false requires TRADINGAGENTS_ENABLE_LIVE_TRADING=true"
                )
            if not confirm_live:
                raise LiveTradingDisabledError("live KIS adapter requires confirm_live=True from the operator")

    @property
    def is_paper(self) -> bool:
        return self.client.is_paper

    def account_snapshot(self, prices: Mapping[str, float] | None = None) -> BrokerAccountSnapshot:
        balance = self.client.balance()
        positions: dict[str, dict[str, float]] = {}
        for holding in balance["holdings"]:
            code = holding["code"]
            price = float((prices or {}).get(code) or holding.get("current_price") or holding.get("average_price") or 0.0)
            positions[code] = {
                "quantity": float(holding["quantity"]),
                "average_price": float(holding.get("average_price") or 0.0),
                "market_value": float(holding.get("market_value") or holding["quantity"] * price),
            }
        cash = float(balance.get("cash") or 0.0)
        equity = float(balance.get("total_equity") or (cash + sum(item["market_value"] for item in positions.values())))
        return BrokerAccountSnapshot(
            broker=self.name,
            cash=cash,
            equity=equity,
            positions=positions,
            currency="KRW",
            is_paper=self.is_paper,
            raw={"mode": self.client.mode, "orderable_cash": balance.get("orderable_cash")},
        )

    def place_order(self, order: OrderIntent, *, price: float, dry_run: bool = False) -> BrokerOrderResult:
        limit_price = None
        if not self.market_orders:
            limit_price = price
            if self.execution_rules is not None and hasattr(self.execution_rules, "round_price"):
                limit_price = float(self.execution_rules.round_price(price, side=order.side))
        if dry_run:
            return BrokerOrderResult(
                status="dry_run",
                order=order,
                broker=self.name,
                message=f"dry run ({self.client.mode}), no request sent",
                raw={"mode": self.client.mode, "limit_price": limit_price},
            )
        try:
            response = self.client.place_cash_order(order.ticker, order.side, order.quantity, price=limit_price)
        except KISError as exc:
            return BrokerOrderResult(status="rejected", order=order, broker=self.name, message=str(exc), raw={"mode": self.client.mode})
        fill = None
        if limit_price is not None:
            # KIS acknowledges the order; fills arrive asynchronously. Record the
            # intended price so paper accounting can proceed; reconcile later.
            fill = Fill(order=order, price=limit_price, quantity=order.quantity)
        return BrokerOrderResult(
            status="accepted",
            order=order,
            broker=self.name,
            order_id=response.get("order_id"),
            fill=fill,
            message=response.get("message") or "order accepted",
            raw={"mode": self.client.mode, **{k: v for k, v in response.items() if k != "raw"}},
        )


def _code(value: str) -> str:
    cleaned = value.strip().upper()
    if "." in cleaned:
        cleaned = cleaned.split(".", 1)[0]
    return cleaned.zfill(6)


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _redact(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted = {}
    for key, value in payload.items():
        if key.lower() in {"access_token", "appkey", "appsecret", "authorization"}:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted

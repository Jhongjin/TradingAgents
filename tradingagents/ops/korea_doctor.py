"""Preflight checks for the Korean-market TradingAgents setup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import requests

from tradingagents.dataflows.http_trust import apply_system_truststore_if_available
from tradingagents.dataflows import krx_openapi
from tradingagents.dataflows.kr_tickers import resolve_kr_ticker
from tradingagents.execution import KISConfig

_KRX_DAILY_TRADE_DIAGNOSTIC_URL = "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"
_KRX_DAILY_TRADE_ENDPOINTS = {
    "KOSPI": "stk_bydd_trd",
    "KOSDAQ": "ksq_bydd_trd",
    "KONEX": "knx_bydd_trd",
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


def run_korea_market_checks() -> list[CheckResult]:
    """Return non-secret environment and safety checks for the KR MVP."""

    results = [
        _required_env("OPENAI_API_KEY", "LLM key is configured"),
        _required_env("DART_API_KEY", "OpenDART key is configured"),
        _paired_env("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "Naver Search credentials are configured"),
        _krx_key_check(),
        _krx_online_check(),
        _database_url_check(),
        _storage_config_check(),
        _analysis_user_id_check(),
        _ssl_config_check(),
        _kis_config_check(),
    ]
    return results


def has_failures(results: list[CheckResult]) -> bool:
    return any(result.status == "FAIL" for result in results)


def format_results(results: list[CheckResult]) -> str:
    lines = ["# Korea market doctor"]
    for result in results:
        lines.append(f"[{result.status}] {result.name}: {result.detail}")
    return "\n".join(lines)


def _required_env(name: str, ok_detail: str) -> CheckResult:
    if _env_set(name):
        return CheckResult(name, "PASS", ok_detail)
    return CheckResult(name, "FAIL", f"{name} is required")


def _optional_env(name: str, ok_detail: str, *, alias: str | None = None) -> CheckResult:
    if _env_set(name) or (alias and _env_set(alias)):
        return CheckResult(name, "PASS", ok_detail)
    suffix = f" or {alias}" if alias else ""
    return CheckResult(name, "SKIP", f"{name}{suffix} is not configured yet")


def _paired_env(left: str, right: str, ok_detail: str) -> CheckResult:
    left_set = _env_set(left)
    right_set = _env_set(right)
    if left_set and right_set:
        return CheckResult(f"{left}/{right}", "PASS", ok_detail)
    missing = [name for name, present in ((left, left_set), (right, right_set)) if not present]
    return CheckResult(f"{left}/{right}", "FAIL", "Missing " + ", ".join(missing))


def _krx_key_check() -> CheckResult:
    primary_raw = os.getenv("KRX_API_KEY")
    alias_raw = os.getenv("KRX_OPENAPI_KEY")
    primary = _clean_env("KRX_API_KEY")
    alias = _clean_env("KRX_OPENAPI_KEY")
    if not primary and not alias:
        return CheckResult("KRX_API_KEY", "SKIP", "KRX_API_KEY or KRX_OPENAPI_KEY is not configured yet")

    if _has_outer_whitespace(primary_raw) or _has_outer_whitespace(alias_raw):
        return CheckResult(
            "KRX_API_KEY",
            "WARN",
            "KRX key has leading or trailing whitespace; remove it before online diagnostics",
        )

    if primary and alias and primary != alias:
        return CheckResult(
            "KRX_API_KEY",
            "WARN",
            "Both KRX_API_KEY and KRX_OPENAPI_KEY are set with different values; KRX_API_KEY will be used",
        )
    if primary and alias:
        return CheckResult("KRX_API_KEY", "PASS", "KRX Open API key is configured; both aliases match")
    if primary:
        return CheckResult("KRX_API_KEY", "PASS", "KRX Open API key is configured via KRX_API_KEY")
    return CheckResult("KRX_API_KEY", "PASS", "KRX Open API key is configured via KRX_OPENAPI_KEY")


def _krx_online_check() -> CheckResult:
    if not _env_bool("TRADINGAGENTS_DOCTOR_CHECK_KRX_ONLINE", False):
        return CheckResult(
            "KRX Open API probe",
            "SKIP",
            "Set TRADINGAGENTS_DOCTOR_CHECK_KRX_ONLINE=true to validate KRX service approval",
        )
    if not krx_openapi.is_configured():
        return CheckResult("KRX Open API probe", "SKIP", "KRX_API_KEY or KRX_OPENAPI_KEY is not configured")

    probe_symbol = _krx_probe_symbol()
    probe_date = os.getenv("TRADINGAGENTS_DOCTOR_KRX_PROBE_DATE") or _last_business_day()
    try:
        frame = krx_openapi.get_ohlcv_frame(probe_symbol, probe_date, probe_date)
    except Exception as exc:
        detail = f"KRX probe failed: {_safe_error(exc)}"
        raw_detail = _krx_raw_unauthorized_detail(probe_symbol, probe_date)
        if raw_detail:
            detail = f"{detail}; {raw_detail}"
        return CheckResult("KRX Open API probe", "FAIL", detail)
    if frame.empty:
        return CheckResult("KRX Open API probe", "WARN", f"KRX probe returned no rows for {probe_symbol} on {probe_date}")
    return CheckResult("KRX Open API probe", "PASS", f"KRX Open API returned OHLCV for {probe_symbol} on {probe_date}")


def _krx_raw_unauthorized_detail(probe_symbol: str, probe_date: str) -> str | None:
    api_key = _clean_env("KRX_API_KEY") or _clean_env("KRX_OPENAPI_KEY")
    if not api_key:
        return None

    endpoint = _krx_daily_trade_endpoint(probe_symbol)
    apply_system_truststore_if_available()
    bas_dd = probe_date.replace("-", "")
    try:
        response = requests.get(
            _krx_diagnostic_url(endpoint),
            params={"basDd": bas_dd},
            headers={"AUTH_KEY": api_key},
            timeout=float(os.getenv("KRX_OPENAPI_TIMEOUT", "30")),
        )
    except requests.RequestException:
        return None

    if response.status_code != 401:
        return None
    try:
        payload = response.json()
    except ValueError:
        return "KRX raw 401 response could not be parsed as JSON"

    message = str(payload.get("respMsg") or "Unauthorized").strip()
    if message == "Unauthorized API Call":
        return (
            "KRX raw response=Unauthorized API Call; verify service-level approval "
            f"for sto/{endpoint} ({_krx_endpoint_label(endpoint)}) on this exact API key"
        )
    if message == "Unauthorized Key":
        return "KRX raw response=Unauthorized Key; verify the copied Open API auth key value"
    return f"KRX raw response={_safe_error(Exception(message))}"


def _krx_probe_symbol() -> str:
    return (
        os.getenv("TRADINGAGENTS_DOCTOR_KRX_PROBE_TICKER")
        or os.getenv("TRADINGAGENTS_KRX_PROBE_TICKER")
        or "005930"
    ).strip()


def _krx_daily_trade_endpoint(symbol: str) -> str:
    try:
        market = resolve_kr_ticker(symbol, lookup_pykrx=False).market
    except Exception:
        market = "KOSPI"
    return _KRX_DAILY_TRADE_ENDPOINTS.get(market, "stk_bydd_trd")


def _krx_diagnostic_url(endpoint: str) -> str:
    return _KRX_DAILY_TRADE_DIAGNOSTIC_URL.rsplit("/", 1)[0] + f"/{endpoint}"


def _krx_endpoint_label(endpoint: str) -> str:
    return {
        "stk_bydd_trd": "유가증권 일별매매정보",
        "ksq_bydd_trd": "코스닥 일별매매정보",
        "knx_bydd_trd": "코넥스 일별매매정보",
    }.get(endpoint, endpoint)


def _ssl_config_check() -> CheckResult:
    verify = os.getenv("TRADINGAGENTS_HTTP_VERIFY_SSL", "true").strip().lower()
    if verify in {"0", "false", "no"}:
        return CheckResult(
            "HTTPS verification",
            "WARN",
            "SSL verification is disabled; use this only for local debugging",
        )

    bundle = os.getenv("TRADINGAGENTS_HTTP_CA_BUNDLE") or os.getenv("NAVER_CA_BUNDLE")
    if not bundle:
        return CheckResult(
            "HTTPS CA bundle",
            "PASS",
            "Default CA trust will be used; Vercel usually needs no custom bundle",
        )

    path = Path(bundle).expanduser()
    if path.exists():
        return CheckResult("HTTPS CA bundle", "PASS", f"Custom CA bundle path exists: {path}")
    return CheckResult("HTTPS CA bundle", "FAIL", f"Custom CA bundle path does not exist: {path}")


def _database_url_check() -> CheckResult:
    value = os.getenv("DATABASE_URL")
    if not value or not value.strip():
        return CheckResult("DATABASE_URL", "SKIP", "Storage DB is not configured yet")
    prefix = value.split(":", 1)[0].lower()
    if prefix in {"postgresql", "postgres", "sqlite", "sqlite+pysqlite"}:
        return CheckResult("DATABASE_URL", "PASS", f"Storage DB URL is configured with {prefix} scheme")
    return CheckResult("DATABASE_URL", "WARN", f"Unrecognized DB URL scheme: {prefix}")


def _storage_config_check() -> CheckResult:
    if not _env_bool("TRADINGAGENTS_STORAGE_ENABLED", False):
        return CheckResult("analysis storage", "SKIP", "Analysis DB persistence is disabled")
    if not _env_set("DATABASE_URL"):
        return CheckResult(
            "analysis storage",
            "FAIL",
            "TRADINGAGENTS_STORAGE_ENABLED=true requires DATABASE_URL for durable storage",
        )
    if _env_bool("TRADINGAGENTS_STORAGE_CREATE_SCHEMA", False):
        return CheckResult(
            "analysis storage",
            "WARN",
            "Schema auto-create is enabled; use migrations for production Supabase",
        )
    return CheckResult("analysis storage", "PASS", "Completed analyses will be persisted")


def _analysis_user_id_check() -> CheckResult:
    value = os.getenv("TRADINGAGENTS_ANALYSIS_USER_ID")
    if not value or not value.strip():
        return CheckResult("analysis user", "SKIP", "No default analysis owner is configured")
    try:
        UUID(value.strip())
    except ValueError:
        return CheckResult("analysis user", "FAIL", "TRADINGAGENTS_ANALYSIS_USER_ID must be a Supabase auth UUID")
    return CheckResult("analysis user", "PASS", "Default analysis owner UUID shape is valid")


def _kis_config_check() -> CheckResult:
    configured = any(
        _env_set(name)
        for name in (
            "KIS_ACCOUNT_NO",
            "KIS_ACCOUNT_NUMBER",
            "KIS_CANO",
            "KIS_ACCOUNT_PRODUCT_CODE",
            "KIS_ACCOUNT_PRODUCT_CD",
            "KIS_ACNT_PRDT_CD",
            "KIS_ACNT_PRDT_CODE",
            "KIS_APP_KEY",
            "KIS_APPKEY",
            "KIS_APP_SECRET",
            "KIS_APP_SECRET_KEY",
            "KIS_APPSECRET",
        )
    )
    if not configured:
        return CheckResult("KIS config", "SKIP", "KIS paper credentials are not configured")

    config = KISConfig.from_env()
    errors = config.validation_errors()
    if errors:
        return CheckResult("KIS config", "FAIL", "; ".join(errors))
    return CheckResult("KIS config", "PASS", "KIS paper credential shape is valid")


def _env_set(name: str) -> bool:
    return bool(_clean_env(name))


def _clean_env(name: str) -> str:
    value = os.getenv(name)
    return "" if value is None else value.strip()


def _has_outer_whitespace(value: str | None) -> bool:
    return value is not None and value != value.strip()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _last_business_day() -> str:
    current = datetime.now(ZoneInfo("Asia/Seoul")).date() - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current.isoformat()


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:180]

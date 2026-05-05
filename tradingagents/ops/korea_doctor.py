"""Preflight checks for the Korean-market TradingAgents setup."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from tradingagents.execution import KISConfig


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
        _optional_env("KRX_API_KEY", "KRX Open API key is configured", alias="KRX_OPENAPI_KEY"),
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
    value = os.getenv(name)
    return value is not None and bool(value.strip())

"""Preflight checks for the Korean-market TradingAgents setup."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from uuid import UUID

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
    value = os.getenv(name)
    return value is not None and bool(value.strip())


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

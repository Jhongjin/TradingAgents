"""Korea Investment & Securities configuration surface.

This module only normalizes env configuration. Order placement lives in
``kis_client.KISBrokerAdapter``, which defaults to the 모의투자 server and
refuses the live server unless every safety gate is open.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, repr=False)
class KISConfig:
    account_no: str | None
    account_product_code: str | None
    app_key: str | None
    app_secret: str | None
    is_paper: bool = True

    def __repr__(self) -> str:
        """Never echo credentials into tracebacks, logs, or REPL output."""

        account = self.account_no or ""
        masked_account = (account[:2] + "*" * max(len(account) - 4, 0) + account[-2:]) if len(account) >= 4 else ("***" if account else None)
        return (
            f"KISConfig(account_no={masked_account!r}, account_product_code={self.account_product_code!r}, "
            f"app_key={'***' if self.app_key else None!r}, app_secret={'***' if self.app_secret else None!r}, "
            f"is_paper={self.is_paper!r})"
        )

    __str__ = __repr__

    @classmethod
    def from_env(cls) -> "KISConfig":
        """Read KIS credentials.

        KIS issues separate app keys for 모의투자 (virtual) and real accounts.
        When ``KIS_IS_PAPER`` is true, ``KIS_PAPER_APP_KEY`` /
        ``KIS_PAPER_APP_SECRET`` / ``KIS_PAPER_ACCOUNT_NO`` /
        ``KIS_PAPER_ACCOUNT_PRODUCT_CODE`` take precedence so both key sets can
        live in the same ``.env`` without overwriting each other.
        """

        is_paper = os.getenv("KIS_IS_PAPER", "true").strip().lower() != "false"
        paper_prefix = ("KIS_PAPER_",) if is_paper else ()
        return cls(
            account_no=_env_value(*[f"{p}ACCOUNT_NO" for p in paper_prefix], "KIS_ACCOUNT_NO", "KIS_ACCOUNT_NUMBER", "KIS_CANO"),
            account_product_code=_env_value(
                *[f"{p}ACCOUNT_PRODUCT_CODE" for p in paper_prefix],
                "KIS_ACCOUNT_PRODUCT_CODE",
                "KIS_ACCOUNT_PRODUCT_CD",
                "KIS_ACNT_PRDT_CD",
                "KIS_ACNT_PRDT_CODE",
            ),
            app_key=_env_value(*[f"{p}APP_KEY" for p in paper_prefix], "KIS_APP_KEY", "KIS_APPKEY"),
            app_secret=_env_value(*[f"{p}APP_SECRET" for p in paper_prefix], "KIS_APP_SECRET", "KIS_APP_SECRET_KEY", "KIS_APPSECRET"),
            is_paper=is_paper,
        )

    @property
    def cano(self) -> str | None:
        return self.account_no

    @property
    def acnt_prdt_cd(self) -> str | None:
        return self.account_product_code

    def is_configured(self) -> bool:
        return all([self.account_no, self.account_product_code, self.app_key, self.app_secret])

    def validation_errors(self) -> list[str]:
        errors = []
        if not self.account_no:
            errors.append("KIS_ACCOUNT_NO/KIS_CANO is required")
        elif not (self.account_no.isdigit() and len(self.account_no) == 8):
            errors.append("KIS account number must be exactly 8 digits")

        if not self.account_product_code:
            errors.append("KIS_ACCOUNT_PRODUCT_CODE/KIS_ACNT_PRDT_CD is required")
        elif not (self.account_product_code.isdigit() and len(self.account_product_code) == 2):
            errors.append("KIS account product code must be exactly 2 digits, e.g. 01")

        if not self.app_key:
            errors.append("KIS_APP_KEY is required")
        if not self.app_secret:
            errors.append("KIS_APP_SECRET is required")
        if not self.is_paper and os.getenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", "false").strip().lower() not in {"1", "true", "yes", "on"}:
            errors.append("KIS_IS_PAPER=false requires TRADINGAGENTS_ENABLE_LIVE_TRADING=true (live trading is disabled)")
        return errors

    def validate_for_paper(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ValueError("; ".join(errors))


def _env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return None

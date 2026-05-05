"""Korea Investment & Securities configuration surface.

This module deliberately does not place live orders. It only normalizes env
configuration so a future KIS adapter can be added behind explicit safety gates.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class KISConfig:
    account_no: str | None
    account_product_code: str | None
    app_key: str | None
    app_secret: str | None
    is_paper: bool = True

    @classmethod
    def from_env(cls) -> "KISConfig":
        return cls(
            account_no=_env_value("KIS_ACCOUNT_NO", "KIS_ACCOUNT_NUMBER", "KIS_CANO"),
            account_product_code=_env_value(
                "KIS_ACCOUNT_PRODUCT_CODE",
                "KIS_ACCOUNT_PRODUCT_CD",
                "KIS_ACNT_PRDT_CD",
                "KIS_ACNT_PRDT_CODE",
            ),
            app_key=_env_value("KIS_APP_KEY", "KIS_APPKEY"),
            app_secret=_env_value("KIS_APP_SECRET", "KIS_APP_SECRET_KEY", "KIS_APPSECRET"),
            is_paper=os.getenv("KIS_IS_PAPER", "true").strip().lower() != "false",
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
        if not self.is_paper:
            errors.append("Live KIS trading is disabled in this MVP")
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

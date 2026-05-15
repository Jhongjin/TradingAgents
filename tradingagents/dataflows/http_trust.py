"""HTTPS trust helpers for local corporate/Windows environments."""

from __future__ import annotations

import os
import platform


_TRUSTSTORE_APPLIED = False


def apply_system_truststore_if_available() -> bool:
    """Let Python use the OS certificate store when explicitly enabled.

    Windows users often have a trusted local security or corporate root in the
    OS store that certifi does not know about. The optional truststore package
    bridges that gap without disabling TLS verification.
    """

    global _TRUSTSTORE_APPLIED
    if _TRUSTSTORE_APPLIED:
        return True
    if not _system_truststore_enabled():
        return False
    try:
        import truststore
    except Exception:
        return False
    truststore.inject_into_ssl()
    _TRUSTSTORE_APPLIED = True
    return True


def _system_truststore_enabled() -> bool:
    default = "true" if platform.system() == "Windows" else "false"
    value = os.getenv("TRADINGAGENTS_HTTP_USE_SYSTEM_CERTS", default)
    return value.strip().lower() in {"1", "true", "yes", "on"}

"""HTTPS trust helpers for local corporate/Windows environments."""

from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path


_TRUSTSTORE_APPLIED = False
_CURL_BUNDLE: str | None = None


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


def apply_curl_truststore() -> str | None:
    """Point curl-based clients at the machine's own trusted roots.

    ``truststore`` patches Python's ssl module, which curl_cffi (used by
    yfinance) does not go through, so a network that inspects TLS breaks the
    download with a self-signed chain error. This writes the Windows root store
    to a PEM bundle once and names it in the variables curl reads. Verification
    stays on; only the list of roots changes.
    """

    global _CURL_BUNDLE
    if _CURL_BUNDLE:
        return _CURL_BUNDLE
    existing = os.getenv("CURL_CA_BUNDLE")
    if existing and Path(existing).exists():
        _CURL_BUNDLE = existing
        return existing
    if platform.system() != "Windows" or not _system_truststore_enabled():
        return None
    try:
        import ssl

        blocks = []
        for store in ("ROOT", "CA"):
            for der, _encoding, _trust in ssl.enum_certificates(store):
                try:
                    blocks.append(ssl.DER_cert_to_PEM_cert(der))
                except Exception:
                    continue
        if not blocks:
            return None
        try:
            import certifi

            blocks.append(Path(certifi.where()).read_text(encoding="utf-8"))
        except Exception:
            pass
        target = Path(tempfile.gettempdir()) / "tradingagents-system-roots.pem"
        target.write_text("\n".join(blocks), encoding="utf-8")
    except Exception:
        return None
    os.environ.setdefault("CURL_CA_BUNDLE", str(target))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", str(target))
    os.environ.setdefault("SSL_CERT_FILE", str(target))
    _CURL_BUNDLE = str(target)
    return _CURL_BUNDLE


def _system_truststore_enabled() -> bool:
    default = "true" if platform.system() == "Windows" else "false"
    value = os.getenv("TRADINGAGENTS_HTTP_USE_SYSTEM_CERTS", default)
    return value.strip().lower() in {"1", "true", "yes", "on"}

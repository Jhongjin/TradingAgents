"""Shared data-vendor exceptions."""


class VendorUnavailableError(Exception):
    """Raised when a vendor cannot serve a request and fallback is allowed."""

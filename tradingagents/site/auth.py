"""Authentication helpers for member API routes."""

from __future__ import annotations

import os
from uuid import UUID

import requests
from fastapi import HTTPException, Request


def resolve_member_user_id(request: Request, trusted_user_header: str | None) -> str:
    """Resolve the authenticated member UUID for owner-scoped API routes."""

    authorization = request.headers.get("authorization")
    if authorization:
        return _resolve_from_supabase_bearer(authorization)

    if not request.app.state.trust_member_user_header:
        raise HTTPException(
            status_code=403,
            detail="Member APIs require Supabase Bearer auth or a trusted auth layer before user headers are accepted",
        )
    return _validate_user_uuid(trusted_user_header, "X-TradingAgents-User-Id")


def _resolve_from_supabase_bearer(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Authorization must use Bearer token")

    supabase_url = _supabase_url()
    api_key = _supabase_api_key()
    if not supabase_url or not api_key:
        raise HTTPException(status_code=503, detail="Supabase Auth verification is not configured")

    try:
        response = requests.get(
            f"{supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token.strip()}",
                "apikey": api_key,
            },
            timeout=_auth_timeout_seconds(),
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Supabase Auth verification request failed") from exc

    if response.status_code in {401, 403}:
        raise HTTPException(status_code=401, detail="Invalid Supabase access token")
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail="Supabase Auth verification failed")

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Supabase Auth returned invalid JSON") from exc

    return _validate_user_uuid(payload.get("id"), "Supabase user id")


def _validate_user_uuid(value: str | None, label: str) -> str:
    if not value:
        raise HTTPException(status_code=401, detail=f"Missing {label}")
    try:
        UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be a UUID") from exc
    return value


def _supabase_url() -> str | None:
    value = os.getenv("SUPABASE_URL") or os.getenv("TRADINGAGENTS_SUPABASE_URL")
    if not value:
        return None
    return value.rstrip("/")


def _supabase_api_key() -> str | None:
    return (
        os.getenv("SUPABASE_PUBLISHABLE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    )


def _auth_timeout_seconds() -> float:
    return float(os.getenv("TRADINGAGENTS_AUTH_TIMEOUT_SECONDS", "5"))

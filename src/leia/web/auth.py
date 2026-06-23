"""Supabase login verification for the web control center.

The browser logs in with Supabase (which issues a signed JWT); this module only
*verifies* that token server-side — LEIA never stores passwords.

Supabase projects sign auth tokens with **asymmetric JWT signing keys** (ES256/RS256),
verified against the project's public JWKS endpoint. Older projects use a symmetric
**legacy JWT secret** (HS256). We try the JWKS first and fall back to the legacy
secret, so either setup works.

Local/dev behaviour: if neither ``SUPABASE_URL`` nor ``SUPABASE_JWT_SECRET`` is
configured, auth is treated as disabled (the local app binds to 127.0.0.1 anyway).
In production set both — see DEPLOY.md — so every request is gated.
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from leia.config import Settings, get_settings

_LOCAL_USER = {"id": "local", "email": "local", "auth": "disabled"}
_ALGS = ["ES256", "RS256"]


def auth_enabled() -> bool:
    s = get_settings()
    return bool(s.supabase_url or s.supabase_jwt_secret)


@lru_cache(maxsize=4)
def _jwk_client(jwks_url: str) -> PyJWKClient:
    # PyJWKClient caches the fetched keys internally; we cache the client per URL.
    return PyJWKClient(jwks_url)


def _verify(token: str, settings: Settings) -> dict:
    # 1) Preferred: asymmetric verification via the project's JWKS (new signing keys).
    if settings.supabase_url:
        jwks_url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        try:
            key = _jwk_client(jwks_url).get_signing_key_from_jwt(token)
            return jwt.decode(token, key.key, algorithms=_ALGS, audience="authenticated")
        except Exception:  # noqa: BLE001 - fall back to the legacy secret below
            pass

    # 2) Fallback: symmetric verification with the legacy JWT secret (HS256).
    if settings.supabase_jwt_secret:
        try:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.PyJWTError as e:
            raise HTTPException(status_code=401, detail="Invalid or expired session") from e

    raise HTTPException(status_code=401, detail="Invalid or expired session")


def require_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: return the logged-in user, or raise 401.

    When Supabase isn't configured (local dev), returns a synthetic local user.
    """
    settings = get_settings()
    if not (settings.supabase_url or settings.supabase_jwt_secret):
        return _LOCAL_USER

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    payload = _verify(token, settings)
    return {"id": payload.get("sub"), "email": payload.get("email")}

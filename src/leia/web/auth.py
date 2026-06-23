"""Supabase login verification for the web control center.

The browser logs in with Supabase (which issues a signed JWT); this module only
*verifies* that token server-side — LEIA never stores passwords.

Local/dev behaviour: if ``SUPABASE_JWT_SECRET`` is not configured, auth is treated
as disabled (the local app binds to 127.0.0.1 anyway). In production you MUST set
the secret — see DEPLOY.md — so every request is gated.
"""

from __future__ import annotations

import jwt
from fastapi import Header, HTTPException

from leia.config import get_settings

_LOCAL_USER = {"id": "local", "email": "local", "auth": "disabled"}


def auth_enabled() -> bool:
    return bool(get_settings().supabase_jwt_secret)


def require_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: return the logged-in user, or raise 401.

    When Supabase isn't configured (local dev), returns a synthetic local user.
    """
    settings = get_settings()
    secret = settings.supabase_jwt_secret
    if not secret:
        return _LOCAL_USER

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(
            token, secret, algorithms=["HS256"], audience="authenticated"
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from e
    return {"id": payload.get("sub"), "email": payload.get("email")}

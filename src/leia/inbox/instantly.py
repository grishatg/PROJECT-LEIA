"""Instantly email inbox: poll new inbound replies (the email side of the loop).

Mirrors ``UnipileInbox`` (LinkedIn) for email: reads Instantly's v2 emails API, keeps only
messages received FROM a lead (a reply, not one of our own sends), and normalises each to
an ``InboundReply``. Like every provider it only returns data — matching to a prospect and
the autonomy decisions happen in ``conversation.py``.

We POLL (no webhooks); re-polling is safe because ``advance_conversations`` is idempotent on
``provider_id``. Endpoint/field names vary by Instantly plan, so parsing is defensive and a
failure never crashes the tick.
"""

from __future__ import annotations

import httpx

from leia.inbox.base import InboundReply

_BASE = "https://api.instantly.ai"


def _is_inbound(m: dict) -> bool:
    """True if this email was received from a lead (a reply), not sent by us.

    Instantly marks direction with ``ue_type`` (1 = sent, 2 = received); we also accept a
    few alternative shapes seen across plans, and fall back to "not sent by us".
    """
    if m.get("ue_type") == 2:
        return True
    mtype = str(m.get("message_type") or m.get("type") or "").lower()
    if mtype in ("received", "reply"):
        return True
    if m.get("is_reply") is True or m.get("reply") is True:
        return True
    return False


def _body(m: dict) -> str:
    body = m.get("body")
    if isinstance(body, dict):
        text = body.get("text") or body.get("html") or ""
    else:
        text = body or m.get("body_text") or m.get("text") or m.get("content_preview") or ""
    return str(text).strip()


def _from_email(m: dict) -> str | None:
    val = (
        m.get("from_address_email")
        or m.get("from_email")
        or m.get("lead_email")
        or m.get("lead")
    )
    return str(val) if val else None


class InstantlyInbox:
    name = "instantly"

    def __init__(
        self,
        api_key: str,
        *,
        limit: int = 50,
        timeout: int = 20,
        client: httpx.Client | None = None,
    ):
        if not api_key:
            raise ValueError("Instantly api_key is required")
        self.api_key = api_key
        self.limit = limit
        self.timeout = timeout
        self._injected = client  # tests inject a fake client

    def _http(self) -> httpx.Client:
        return self._injected or httpx.Client(
            base_url=_BASE,
            headers={"Authorization": f"Bearer {self.api_key}", "accept": "application/json"},
            timeout=self.timeout,
        )

    def fetch_new(self) -> list[InboundReply]:
        params = {"limit": self.limit}
        try:
            client = self._http()
            try:
                resp = client.get("/api/v2/emails", params=params)
                resp.raise_for_status()
                payload = resp.json()
            finally:
                if self._injected is None:
                    client.close()
        except Exception:  # noqa: BLE001 - a provider must never crash the pipeline
            return []

        items = payload.get("items", []) if isinstance(payload, dict) else (payload or [])
        out: list[InboundReply] = []
        for m in items:
            if not isinstance(m, dict) or not _is_inbound(m):
                continue
            body = _body(m)
            mid = m.get("id") or m.get("message_id")
            frm = _from_email(m)
            if not body or not mid or not frm:
                continue
            out.append(
                InboundReply(
                    provider_id=str(mid),
                    channel="email",
                    body=body,
                    from_email=frm,
                )
            )
        return out

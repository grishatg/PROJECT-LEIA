"""Unipile LinkedIn inbox: poll new inbound replies for the connected account.

Implements the ``Inbox`` protocol. Reads via Unipile's unified messaging API
(``GET /api/v1/messages``), keeps only messages NOT sent by us
(``is_sender == false``), and normalises each to an ``InboundReply``. Like every
provider, it only ever returns data — matching to a prospect and the autonomy
decisions happen in ``conversation.py``.

We POLL rather than rely on webhooks: Unipile's webhooks are reported to drop
events, and the scheduler tick already gives us a natural cadence. Re-polling is
safe because ``advance_conversations`` is idempotent on ``provider_id``.
"""

from __future__ import annotations

import httpx

from leia.inbox.base import InboundReply


def _str_or_none(v) -> str | None:
    return str(v) if v not in (None, "") else None


def _sender_url(message: dict) -> str | None:
    """Best-effort LinkedIn profile URL for the sender, if Unipile supplies one.

    Unipile identifies senders by a provider id; when an attendee record carries a
    public identifier we can rebuild the profile URL so the engine can match by it.
    """
    attendee = message.get("sender_attendee") or {}
    url = attendee.get("profile_url") or message.get("sender_profile_url")
    if url:
        return url
    pid = attendee.get("public_identifier")
    if pid and not str(pid).isdigit():
        return f"https://www.linkedin.com/in/{pid}"
    return None


class UnipileInbox:
    name = "unipile"

    def __init__(
        self,
        api_key: str,
        dsn: str,
        account_id: str | None = None,
        *,
        limit: int = 50,
        timeout: int = 20,
        client: httpx.Client | None = None,
    ):
        if not api_key or not dsn:
            raise ValueError("Unipile api_key and dsn are required")
        self.api_key = api_key
        self.account_id = account_id
        self.limit = limit
        self.timeout = timeout
        base = dsn if str(dsn).startswith("http") else f"https://{dsn}"
        self._base = base.rstrip("/")
        self._injected = client  # tests inject a fake client

    def _http(self) -> httpx.Client:
        return self._injected or httpx.Client(
            base_url=self._base,
            headers={"X-API-KEY": self.api_key, "accept": "application/json"},
            timeout=self.timeout,
        )

    def fetch_new(self) -> list[InboundReply]:
        params: dict = {"limit": self.limit}
        if self.account_id:
            params["account_id"] = self.account_id
        try:
            client = self._http()
            try:
                resp = client.get("/api/v1/messages", params=params)
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
            if not isinstance(m, dict) or m.get("is_sender"):
                continue  # our own outbound, or malformed
            text = (m.get("text") or "").strip()
            mid = m.get("id")
            if not text or not mid:
                continue
            out.append(
                InboundReply(
                    provider_id=str(mid),
                    channel="linkedin",
                    body=text,
                    from_linkedin_url=_sender_url(m),
                    from_provider_id=_str_or_none(m.get("sender_id")),
                    provider_chat_id=_str_or_none(m.get("chat_id")),
                )
            )
        return out

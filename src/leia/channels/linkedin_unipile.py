"""LinkedIn outreach via Unipile (unified messaging API).

Unipile manages your LinkedIn account behind a clean REST API. Phase 2 MVP uses
connection-request-with-note for cold outreach (LinkedIn's 300-char limit applies).

Account setup:
  1. Connect your LinkedIn account in the Unipile dashboard (https://unipile.com).
  2. Copy the API key and DSN (e.g. api3.unipile.com:13178) into .env.

The channel auto-discovers your first connected LinkedIn account on the initial
send call (cached for subsequent calls in the same process).
"""

from __future__ import annotations

import httpx

from leia.channels.base import OutboundMessage, SendResult
from leia.models import OutreachEvent

# LinkedIn hard cap on connection-request notes.
_MAX_NOTE = 300


class UnipileLinkedInChannel:
    channel = "linkedin"
    name = "unipile"

    def __init__(self, api_key: str, dsn: str, *, timeout: float = 30.0):
        if not api_key or not dsn:
            raise ValueError("unipile_api_key and unipile_dsn are required")
        self.api_key = api_key
        dsn = dsn.strip().rstrip("/")
        self.base_url = dsn if dsn.startswith("http") else f"https://{dsn}"
        self.timeout = timeout
        self._account_id: str | None = None  # lazy-resolved on first send

    # ── Channel protocol ──────────────────────────────────────────────────

    def validate(self, message: OutboundMessage) -> list[str]:
        problems: list[str] = []
        if message.channel != self.channel:
            problems.append(f"channel mismatch: {message.channel} != {self.channel}")
        if not message.provider_chat_id and not message.to_linkedin_url:
            problems.append("missing to_linkedin_url (or provider_chat_id)")
        if not message.body or not message.body.strip():
            problems.append("empty body")
        return problems

    def send(self, message: OutboundMessage) -> SendResult:
        problems = self.validate(message)
        if problems:
            return SendResult(
                ok=False,
                event=OutreachEvent.FAILED,
                provider=self.name,
                detail="; ".join(problems),
            )
        try:
            account_id = self._resolve_account_id()
            # A continuation/reply goes INTO the existing chat; a cold opener sends an
            # invitation-with-note (no chat exists until the recipient accepts).
            if message.provider_chat_id:
                return self._send_in_chat(message.provider_chat_id, message.body)
            attendee_id = self._resolve_attendee(message.to_linkedin_url, account_id)
            return self._send_invitation(account_id, attendee_id, message.body[:_MAX_NOTE])
        except Exception as e:  # noqa: BLE001 - never crash the pipeline on provider errors
            return SendResult(
                ok=False, event=OutreachEvent.FAILED, provider=self.name, detail=str(e)
            )

    # ── Internal helpers ──────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"X-API-KEY": self.api_key, "Content-Type": "application/json"}

    def _resolve_account_id(self) -> str:
        """Get the first connected LinkedIn account ID from Unipile (cached)."""
        if self._account_id:
            return self._account_id
        resp = httpx.get(
            f"{self.base_url}/api/v1/accounts",
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        accounts: list[dict] = data.get("items") or (data if isinstance(data, list) else [])
        linkedin = [a for a in accounts if a.get("type") == "LINKEDIN"]
        if not linkedin:
            raise RuntimeError(
                "No LinkedIn account found in Unipile. "
                "Connect one at https://unipile.com before sending."
            )
        self._account_id = linkedin[0]["id"]
        return self._account_id

    def _resolve_attendee(self, linkedin_url: str, account_id: str) -> str:
        """Resolve a LinkedIn profile URL to a Unipile attendee provider ID."""
        resp = httpx.get(
            f"{self.base_url}/api/v1/providers/linkedin/profiles",
            params={"url": linkedin_url, "account_id": account_id},
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        provider_id = data.get("provider_id") or data.get("id")
        if not provider_id:
            raise RuntimeError(
                f"Unipile could not resolve LinkedIn URL to a provider ID: {linkedin_url}"
            )
        return provider_id

    def _send_invitation(
        self, account_id: str, attendee_provider_id: str, note: str
    ) -> SendResult:
        """Send a LinkedIn connection request with a personalised note."""
        resp = httpx.post(
            f"{self.base_url}/api/v1/providers/linkedin/relations",
            json={
                "account_id": account_id,
                "attendee_provider_id": attendee_provider_id,
                "message": note,
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        # The invitation id is the relation ref; there's no chat yet (created on accept).
        # We stash it as ``relation_id`` so the thread can be reconciled to a chat later.
        raw = {"relation_id": (data or {}).get("id")}
        if isinstance(data, dict):
            raw.update(data)
        return SendResult(
            ok=True,
            event=OutreachEvent.SENT,
            provider=self.name,
            provider_message_id=(data or {}).get("id"),
            raw=raw,
        )

    def _send_in_chat(self, chat_id: str, text: str) -> SendResult:
        """Send a message into an existing LinkedIn chat (a reply/continuation)."""
        resp = httpx.post(
            f"{self.base_url}/api/v1/chats/{chat_id}/messages",
            json={"text": text},
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        raw = {"chat_id": chat_id}
        if isinstance(data, dict):
            raw.update(data)
        return SendResult(
            ok=True,
            event=OutreachEvent.SENT,
            provider=self.name,
            provider_message_id=(data or {}).get("id"),
            raw=raw,
        )

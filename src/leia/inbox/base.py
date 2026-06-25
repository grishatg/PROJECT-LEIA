"""The Inbox protocol: pull new inbound replies from a channel provider.

Real implementations (Instantly replies API, Unipile LinkedIn sync) live behind
this protocol so the conversation engine never sees vendor specifics — exactly
like ``channels/`` for outbound. ``StubInbox`` (offline) seeds the engine in
tests and dry-run.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class InboundReply(BaseModel):
    """A single inbound message, normalized for the conversation engine."""

    provider_id: str
    channel: str  # "email" | "linkedin"
    body: str
    from_email: str | None = None
    from_linkedin_url: str | None = None
    # Provider-native ids — used to match LinkedIn replies back to a thread/prospect
    # when no email/profile URL is available (the conversation engine decides how).
    from_provider_id: str | None = None
    provider_chat_id: str | None = None


@runtime_checkable
class Inbox(Protocol):
    name: str

    def fetch_new(self) -> list[InboundReply]:
        """Return inbound replies not yet seen by the pipeline."""
        ...

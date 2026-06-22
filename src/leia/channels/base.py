"""The Channel protocol. Implement this to add an outreach channel.

SAFETY: a channel must only ever be called with an APPROVED draft. The pipeline
enforces this; channels themselves should also no-op loudly if asked to send
something that fails ``validate``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class OutboundMessage(BaseModel):
    channel: str  # "email" | "linkedin"
    to_email: str | None = None
    to_linkedin_url: str | None = None
    subject: str | None = None
    body: str


class SendResult(BaseModel):
    ok: bool
    event: str  # an OutreachEvent value: queued | sent | bounced | failed
    provider: str | None = None
    provider_message_id: str | None = None
    detail: str | None = None
    raw: dict = Field(default_factory=dict)


@runtime_checkable
class Channel(Protocol):
    name: str
    channel: str  # "email" | "linkedin"

    def validate(self, message: OutboundMessage) -> list[str]:
        """Return a list of problems (empty list == OK to send)."""
        ...

    def send(self, message: OutboundMessage) -> SendResult:
        """Send an approved message. Must be a no-op if ``validate`` is non-empty."""
        ...

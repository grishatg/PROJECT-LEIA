"""Offline inbox stub: returns whatever replies it was seeded with (once).

Lets tests and --dry-run drive the conversation engine deterministically with no
network. Real providers (Instantly/Unipile) implement the same ``Inbox`` protocol.
"""

from __future__ import annotations

from leia.inbox.base import InboundReply


class StubInbox:
    name = "stub"

    def __init__(self, replies: list[InboundReply] | None = None):
        self._replies = list(replies or [])

    def fetch_new(self) -> list[InboundReply]:
        # Drain once, so a second tick doesn't re-process the same messages.
        out, self._replies = self._replies, []
        return out

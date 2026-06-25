"""Compose several inboxes into one, so the tick reads LinkedIn + email in one pass.

Order-preserving and fault-isolated: if one provider errors, the others still return their
replies (a flaky inbox must not sink the whole tick).
"""

from __future__ import annotations

from leia.inbox.base import InboundReply, Inbox


class MultiInbox:
    name = "multi"

    def __init__(self, inboxes: list[Inbox]):
        self._inboxes = [ib for ib in inboxes if ib is not None]

    def fetch_new(self) -> list[InboundReply]:
        out: list[InboundReply] = []
        for ib in self._inboxes:
            try:
                out.extend(ib.fetch_new())
            except Exception:  # noqa: BLE001 - one bad provider must not sink the rest
                continue
        return out

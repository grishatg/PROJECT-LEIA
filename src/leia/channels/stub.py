"""A stub channel: validates and 'queues' a message without actually sending.

The default for --dry-run and whenever a real sender isn't configured. It records
intent (event="queued") so OutreachLog still has a trail, but nothing leaves.
"""

from __future__ import annotations

from leia.channels.base import OutboundMessage, SendResult
from leia.models import OutreachEvent


class StubChannel:
    def __init__(self, channel: str = "email"):
        self.channel = channel
        self.name = f"stub-{channel}"

    def validate(self, message: OutboundMessage) -> list[str]:
        problems: list[str] = []
        if message.channel != self.channel:
            problems.append(f"channel mismatch: {message.channel} != {self.channel}")
        if not message.body or not message.body.strip():
            problems.append("empty body")
        if self.channel == "email":
            if not message.to_email:
                problems.append("missing to_email")
            if not message.subject:
                problems.append("missing subject")
        if self.channel == "linkedin" and not message.to_linkedin_url:
            problems.append("missing to_linkedin_url")
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
        return SendResult(
            ok=True,
            event=OutreachEvent.QUEUED,
            provider=self.name,
            detail="stub: not actually sent",
        )

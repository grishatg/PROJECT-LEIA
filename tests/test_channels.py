"""StubChannel: validation rules + safe 'queued' send."""

from __future__ import annotations

from leia.channels.base import OutboundMessage
from leia.channels.stub import StubChannel


def test_valid_email_queues():
    ch = StubChannel("email")
    msg = OutboundMessage(
        channel="email", to_email="a@b.com", subject="hi", body="hello there"
    )
    assert ch.validate(msg) == []
    res = ch.send(msg)
    assert res.ok is True
    assert res.event == "queued"


def test_missing_email_fields_fail():
    ch = StubChannel("email")
    msg = OutboundMessage(channel="email", body="hello")  # no to_email, no subject
    problems = ch.validate(msg)
    assert "missing to_email" in problems
    assert "missing subject" in problems
    res = ch.send(msg)
    assert res.ok is False
    assert res.event == "failed"


def test_linkedin_requires_url():
    ch = StubChannel("linkedin")
    msg = OutboundMessage(channel="linkedin", body="hi")
    assert "missing to_linkedin_url" in ch.validate(msg)


def test_channel_mismatch_detected():
    ch = StubChannel("email")
    msg = OutboundMessage(channel="linkedin", to_linkedin_url="x", body="hi")
    assert any("channel mismatch" in p for p in ch.validate(msg))

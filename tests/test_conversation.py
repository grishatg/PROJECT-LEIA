"""Offline tests for the hybrid conversation engine (stub inbox + stub brain)."""

from __future__ import annotations

from leia.channels.base import SendResult
from leia.config import ValuePropConfig
from leia.conversation import advance_conversations
from leia.inbox.base import InboundReply
from leia.inbox.stub import StubInbox
from leia.llm.stub import StubBrain
from leia.models import (
    ConversationThread,
    EnrichedContact,
    Meeting,
    MeetingStatus,
    Message,
    MessageDirection,
    Prospect,
    ThreadStatus,
)
from leia.suppression import is_suppressed

VP = ValuePropConfig(offer="We cut energy spend.", cta="a quick call", proof_points=["£160k"])
EMAIL = "maya@northwind.com"


class _SentChannel:
    name = "fake"
    channel = "email"

    def validate(self, message):
        return []

    def send(self, message):
        return SendResult(ok=True, event="sent", provider="fake", provider_message_id="sent-1")


def _chan(_channel):
    return _SentChannel()


def _seed_prospect(session):
    p = Prospect(full_name="Maya Rao", company_name="Northwind", dedupe_key="maya")
    session.add(p)
    session.flush()
    session.add(EnrichedContact(prospect_id=p.id, email=EMAIL))
    session.commit()
    return p


def _advance(session, body, provider_id=None):
    # Distinct provider_id per body by default, so the idempotency guard doesn't
    # collapse separate turns; pass an explicit id to test re-polling.
    pid = provider_id or f"m-{abs(hash(body)) % 100000}"
    inbox = StubInbox(
        [InboundReply(provider_id=pid, channel="email", from_email=EMAIL, body=body)]
    )
    return advance_conversations(
        session, inbox=inbox, brain=StubBrain(), channel_for=_chan,
        value_prop=VP, guidelines="", booking_url="https://book.me/leia",
    )


def _outbound(session):
    return [m for m in session.query(Message).all() if m.direction == MessageDirection.OUTBOUND]


def test_continue_auto_sends(session):
    _seed_prospect(session)
    counts = _advance(session, "Thanks, tell me more about how it works.")
    assert counts["inbound"] == 1
    assert counts["auto_sent"] == 1
    out = _outbound(session)
    assert out and out[0].provider_id == "sent-1"  # actually sent
    assert session.query(ConversationThread).one().status == ThreadStatus.ACTIVE


def test_meeting_proposal_is_gated(session):
    _seed_prospect(session)
    counts = _advance(session, "Sure — can we set up a call next week?")
    assert counts["auto_sent"] == 0
    assert counts["awaiting_human"] == 1
    assert session.query(ConversationThread).one().status == ThreadStatus.MEETING_LINK_SHARED
    assert session.query(Meeting).one().status == MeetingStatus.LINK_SHARED
    out = _outbound(session)
    assert out and out[0].provider_id is None  # drafted, NOT sent — human gate holds


def test_opt_out_suppresses_and_closes(session):
    _seed_prospect(session)
    counts = _advance(session, "Please unsubscribe me from this list.")
    assert counts["suppressed"] == 1
    assert counts["auto_sent"] == 0
    assert is_suppressed(session, EMAIL) is True
    assert session.query(ConversationThread).one().status == ThreadStatus.CLOSED
    assert not _outbound(session)  # nothing sent to an opt-out


def test_unmatched_reply_is_ignored(session):
    inbox = StubInbox(
        [InboundReply(provider_id="x", channel="email", from_email="nobody@nowhere.com", body="hi")]
    )
    counts = advance_conversations(
        session, inbox=inbox, brain=StubBrain(), channel_for=_chan, value_prop=VP, guidelines=""
    )
    assert counts["unmatched"] == 1
    assert counts["inbound"] == 0
    assert session.query(ConversationThread).count() == 0


def test_thread_reused_across_two_turns(session):
    _seed_prospect(session)
    _advance(session, "Tell me more.")
    _advance(session, "Got it, thanks.")
    assert session.query(ConversationThread).count() == 1
    assert len(session.query(Message).all()) == 4  # 2 inbound + 2 outbound


def test_idempotent_on_provider_id(session):
    """Re-polling the same message (same provider_id) must not reprocess it."""
    _seed_prospect(session)
    first = _advance(session, "Tell me more.", provider_id="dup-1")
    assert first["inbound"] == 1
    second = _advance(session, "Tell me more.", provider_id="dup-1")
    assert second["skipped"] == 1
    assert second["inbound"] == 0
    inbound = [m for m in session.query(Message).all() if m.direction == MessageDirection.INBOUND]
    assert len(inbound) == 1  # recorded exactly once


def test_tick_endpoint_is_a_safe_noop():
    """The scheduler endpoint runs end-to-end with the (empty) stub inbox."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from leia.db import make_session_factory
    from leia.models import Base
    from leia.web import server

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    server.configure_factory(make_session_factory(engine))
    client = TestClient(server.app)

    r = client.post("/api/tasks/tick", json={"dry_run": True})
    assert r.status_code == 200
    assert r.json()["counts"]["inbound"] == 0

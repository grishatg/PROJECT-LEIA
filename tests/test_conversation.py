"""Offline tests for the hybrid conversation engine (stub inbox + stub brain)."""

from __future__ import annotations

from leia.channels.base import SendResult
from leia.config import ValuePropConfig
from leia.conversation import advance_conversations, initiate_conversations
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
    ScoredLead,
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


class _RecordingChannel:
    name = "rec"
    channel = "linkedin"

    def __init__(self):
        self.sent: list = []

    def validate(self, message):
        return []

    def send(self, message):
        self.sent.append(message)
        return SendResult(ok=True, event="sent", provider="rec", provider_message_id="sent-x")


def _seed_linkedin_prospect(session):
    from leia.dedupe import canonicalize_linkedin_url

    p = Prospect(
        full_name="Maya Rao",
        company_name="Northwind",
        dedupe_key="maya-li",
        linkedin_url=canonicalize_linkedin_url("https://www.linkedin.com/in/maya-rao"),
    )
    session.add(p)
    session.commit()
    return p


def _advance_linkedin(
    session, body, *, url=None, chat_id=None, provider_id=None, channel_for=_chan
):
    pid = provider_id or f"li-{abs(hash(body)) % 100000}"
    inbox = StubInbox(
        [
            InboundReply(
                provider_id=pid,
                channel="linkedin",
                body=body,
                from_linkedin_url=url,
                provider_chat_id=chat_id,
            )
        ]
    )
    return advance_conversations(
        session, inbox=inbox, brain=StubBrain(), channel_for=channel_for,
        value_prop=VP, guidelines="", booking_url="https://book.me/leia",
    )


def test_linkedin_reply_learns_chat_id(session):
    """A reply matched by profile URL teaches the thread its chat id for next time."""
    _seed_linkedin_prospect(session)
    _advance_linkedin(
        session, "Thanks, tell me more.",
        url="https://www.linkedin.com/in/maya-rao", chat_id="chat-99",
    )
    assert session.query(ConversationThread).one().provider_chat_id == "chat-99"


def test_linkedin_reply_matched_by_chat_id_without_url(session):
    """Once the chat id is known, a later message carrying only that id still matches."""
    _seed_linkedin_prospect(session)
    _advance_linkedin(
        session, "Hi there.",
        url="https://www.linkedin.com/in/maya-rao", chat_id="chat-77",
    )
    counts = _advance_linkedin(session, "Following up.", chat_id="chat-77")
    assert counts["inbound"] == 1
    assert counts["unmatched"] == 0
    assert session.query(ConversationThread).count() == 1


def test_linkedin_continuation_sends_into_the_chat(session):
    """Auto-sent continuations must target the known chat, not re-invite."""
    _seed_linkedin_prospect(session)
    rec = _RecordingChannel()
    _advance_linkedin(
        session, "Tell me more.",
        url="https://www.linkedin.com/in/maya-rao", chat_id="chat-55",
        channel_for=lambda _c: rec,
    )
    assert rec.sent and rec.sent[0].provider_chat_id == "chat-55"


def _seed_scored_linkedin(
    session, *, score=85, url="https://www.linkedin.com/in/maya-rao", key="maya-sc"
):
    from leia.config import load_icp
    from leia.dedupe import canonicalize_linkedin_url
    from leia.pipeline import ensure_icp_row

    icp_row = ensure_icp_row(session, load_icp())
    p = Prospect(
        full_name="Maya Rao",
        company_name="Northwind",
        dedupe_key=key,
        linkedin_url=canonicalize_linkedin_url(url) if url else None,
    )
    session.add(p)
    session.flush()
    session.add(ScoredLead(prospect_id=p.id, icp_id=icp_row.id, score=score, tier="A"))
    session.commit()
    return icp_row, p


def test_initiate_drafts_opener_for_approval_by_default(session):
    icp_row, _ = _seed_scored_linkedin(session)
    rec = _RecordingChannel()
    counts = initiate_conversations(
        session, brain=StubBrain(), channel_for=lambda _c: rec,
        value_prop=VP, guidelines="", icp_id=icp_row.id, score_threshold=60,
    )
    assert counts["initiated"] == 1 and counts["drafted"] == 1 and counts["sent"] == 0
    assert not rec.sent  # nothing first-touch sends unless asked
    thread = session.query(ConversationThread).one()
    assert thread.status == ThreadStatus.AWAITING_HUMAN
    out = [m for m in session.query(Message).all() if m.direction == MessageDirection.OUTBOUND]
    assert out and out[0].provider_id is None  # drafted, not sent


def test_initiate_auto_sends_when_enabled(session):
    icp_row, _ = _seed_scored_linkedin(session)
    rec = _RecordingChannel()
    counts = initiate_conversations(
        session, brain=StubBrain(), channel_for=lambda _c: rec,
        value_prop=VP, guidelines="", icp_id=icp_row.id, auto_send=True,
    )
    assert counts["sent"] == 1
    assert rec.sent and rec.sent[0].to_linkedin_url
    thread = session.query(ConversationThread).one()
    assert thread.status == ThreadStatus.ACTIVE
    assert thread.provider_thread_ref == "sent-x"


def test_initiate_skips_when_a_thread_already_exists(session):
    icp_row, p = _seed_scored_linkedin(session)
    session.add(
        ConversationThread(prospect_id=p.id, channel="linkedin", status=ThreadStatus.ACTIVE)
    )
    session.commit()
    counts = initiate_conversations(
        session, brain=StubBrain(), channel_for=_chan,
        value_prop=VP, guidelines="", icp_id=icp_row.id,
    )
    assert counts["initiated"] == 0


def test_initiate_skips_linkedin_without_a_profile_url(session):
    icp_row, _ = _seed_scored_linkedin(session, url=None)
    counts = initiate_conversations(
        session, brain=StubBrain(), channel_for=_chan,
        value_prop=VP, guidelines="", icp_id=icp_row.id,
    )
    assert counts["skipped"] == 1 and counts["initiated"] == 0


def test_initiate_respects_send_cap(session):
    icp_row, _ = _seed_scored_linkedin(session, key="p1", url="https://www.linkedin.com/in/a")
    _seed_scored_linkedin(session, key="p2", url="https://www.linkedin.com/in/b")
    rec = _RecordingChannel()
    counts = initiate_conversations(
        session, brain=StubBrain(), channel_for=lambda _c: rec,
        value_prop=VP, guidelines="", icp_id=icp_row.id, auto_send=True, send_cap=1,
    )
    assert counts["sent"] == 1  # cap honoured
    assert counts["drafted"] == 1  # the second falls through to drafted
    assert counts["initiated"] == 2


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

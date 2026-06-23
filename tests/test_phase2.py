"""Offline tests for the Phase 2 foundation: suppression, reply parsing,
the conversation stub brain, and the UK discovery stub sources."""

from __future__ import annotations

from leia.config import ValuePropConfig
from leia.llm.stub import StubBrain
from leia.models import (
    DraftMessage,
    DraftStatus,
    EnrichedContact,
    OutreachLog,
    Prospect,
    ScoredLead,
)
from leia.pipeline import ingest, send_approved
from leia.replies.parse import clean_reply, looks_like_opt_out
from leia.schemas import ProspectFacts
from leia.sources.base import RawSignal
from leia.sources.companies_house import _normalise_officer_name
from leia.sources.discovery_stub import StubCompaniesHouseSource, StubJobSpySource
from leia.suppression import add_suppression, is_suppressed

VP = ValuePropConfig(
    offer="We cut energy spend.", cta="a quick 20-minute call", proof_points=["£160k saved"]
)


class _OneSignalSource:
    name = "test"

    def __init__(self, signal: RawSignal):
        self._signals = [signal]

    def fetch(self) -> list[RawSignal]:
        return self._signals


# ── Reply parsing ───────────────────────────────────────────────────────────


def test_clean_reply_strips_quote_and_signature():
    raw = (
        "Thanks, that's helpful — let's chat next week.\n\n"
        "Best,\nAlex\n\n"
        "On Mon, 3 Jun 2026 at 14:02, LEIA <a@x.com> wrote:\n"
        "> Hi Maya, quick idea for Northwind...\n"
    )
    cleaned = clean_reply(raw)
    assert "let's chat next week" in cleaned
    assert "wrote:" not in cleaned
    assert "quick idea for Northwind" not in cleaned
    assert "Best," not in cleaned


def test_looks_like_opt_out():
    assert looks_like_opt_out("Please unsubscribe me")
    assert looks_like_opt_out("take me off your list")
    assert not looks_like_opt_out("Sounds great, let's talk")


# ── Suppression ───────────────────────────────────────────────────────────────


def test_add_and_is_suppressed(session):
    assert is_suppressed(session, "a@b.com") is False
    add_suppression(session, "A@B.com", reason="opted out")
    session.commit()
    # normalised (case-insensitive) match
    assert is_suppressed(session, "a@b.com") is True


def test_ingest_flags_suppressed_email(session):
    add_suppression(session, "blocked@acme.com")
    session.commit()
    src = _OneSignalSource(
        RawSignal(
            source="manual_csv", full_name="Pat Lee", company_name="Acme", email="blocked@acme.com"
        )
    )
    ingest(session, src)
    p = session.query(Prospect).filter_by(full_name="Pat Lee").one()
    assert p.suppressed is True


def test_send_skips_suppressed_address(session):
    p = Prospect(full_name="Sam Fox", company_name="Acme", dedupe_key="sam")
    session.add(p)
    session.flush()
    session.add(EnrichedContact(prospect_id=p.id, email="sam@acme.com"))
    lead = ScoredLead(prospect_id=p.id, icp_id="x", score=90, tier="A")
    session.add(lead)
    session.flush()
    d = DraftMessage(
        scored_lead_id=lead.id, channel="email", body="hi", status=DraftStatus.APPROVED
    )
    session.add(d)
    session.commit()

    add_suppression(session, "sam@acme.com")
    session.commit()

    report = send_approved(session, lambda ch: _NoopChannel())
    assert report.counts["sent"] == 0
    assert report.counts["skipped"] == 1
    session.refresh(d)
    assert d.status == DraftStatus.REJECTED
    log = session.query(OutreachLog).filter_by(draft_message_id=d.id).one()
    assert log.payload_json == {"skipped": "suppressed"}


class _NoopChannel:
    name = "noop"
    channel = "email"

    def validate(self, message):  # pragma: no cover - not reached for suppressed
        return []

    def send(self, message):  # pragma: no cover
        raise AssertionError("should not send to a suppressed address")


# ── Conversation stub brain ────────────────────────────────────────────────────


def _converse(body: str, booking="https://book.me/leia"):
    return StubBrain().converse(
        history=[{"direction": "inbound", "body": body}],
        facts=ProspectFacts(full_name="Maya Rao", company_name="Northwind"),
        value_prop=VP,
        guidelines="",
        booking_url=booking,
    )


def test_converse_continue():
    out = _converse("Interesting — tell me more about how it works.")
    assert out.result.intent == "continue"
    assert out.model_id == "stub"


def test_converse_proposes_meeting_with_link():
    out = _converse("Sure, happy to find a time for a quick call.")
    assert out.result.intent == "propose_meeting"
    assert "book.me/leia" in out.result.body


def test_converse_detects_opt_out():
    out = _converse("Please unsubscribe me from this.")
    assert out.result.intent == "unsubscribe"


# ── Discovery stub sources ──────────────────────────────────────────────────────


def test_discovery_stubs_carry_triggers():
    ch = StubCompaniesHouseSource().fetch()
    js = StubJobSpySource().fetch()
    assert ch and all(s.raw.get("signals") for s in ch)
    assert js and all("hiring" in s.raw["signals"][0].lower() for s in js)
    assert ch[0].source == "companies_house"
    assert js[0].source == "jobspy"


def test_officer_name_normalisation():
    assert _normalise_officer_name("WHITFIELD, Eleanor Jane") == "Eleanor Jane Whitfield"
    assert _normalise_officer_name("Raj Patel") == "Raj Patel"

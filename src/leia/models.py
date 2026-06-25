"""SQLAlchemy data model for PROJECT-LEIA.

The schema mirrors the pipeline: Signal -> Prospect -> EnrichedContact ->
ScoredLead -> DraftMessage -> ApprovalItem -> OutreachLog.

Design notes:
- SQLite for the personal MVP; Postgres-ready (swap DATABASE_URL + run Alembic).
- Every top-level table carries a nullable ``account_id`` defaulting to "local".
  This is the cheap hedge that keeps multi-tenant productization open with no rewrite.
- Status fields are plain strings with constant classes below (beginner-readable,
  portable, no enum/CHECK-constraint friction on SQLite).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    """A short, URL-safe primary key."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


# ── String constants (stored as plain VARCHAR) ─────────────────────────────


class SignalSource:
    MANUAL_CSV = "manual_csv"
    APIFY_LINKEDIN = "apify_linkedin"
    JOBCHANGE = "jobchange"
    LUSHA_PROSPECTING = "lusha_prospecting"
    LUSHA_SIGNALS = "lusha_signals"


class SignalStatus:
    NEW = "new"
    PROCESSED = "processed"
    SKIPPED = "skipped"


class EnrichmentStatus:
    PENDING = "pending"
    ENRICHED = "enriched"
    FAILED = "failed"
    NONE = "none"


class EmailStatus:
    VERIFIED = "verified"
    GUESS = "guess"
    NONE = "none"


class Tier:
    A = "A"
    B = "B"
    C = "C"


class Channel:
    EMAIL = "email"
    LINKEDIN = "linkedin"


class DraftStatus:
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    SENT = "sent"
    FAILED = "failed"


class ApprovalState:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class OutreachEvent:
    QUEUED = "queued"
    SENT = "sent"
    BOUNCED = "bounced"
    REPLIED = "replied"
    FAILED = "failed"


class ThreadStatus:
    ACTIVE = "active"
    AWAITING_HUMAN = "awaiting_human"
    MEETING_LINK_SHARED = "meeting_link_shared"
    BOOKED = "booked"
    CLOSED = "closed"


class MessageDirection:
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class ReplyIntent:
    """Classified intent of an inbound reply (Phase 2 conversation engine)."""

    CONTINUE = "continue"
    QUESTION = "question"
    NEGATIVE = "negative"
    OUT_OF_OFFICE = "out_of_office"
    UNSUBSCRIBE = "unsubscribe"
    PROPOSE_MEETING = "propose_meeting"
    CONFIRM_MEETING = "confirm_meeting"
    ESCALATE = "escalate"


class SuppressionSource:
    OPT_OUT = "opt_out"      # auto-added from an unsubscribe/negative reply
    MANUAL = "manual"
    IMPORT = "import"


class MeetingStatus:
    LINK_SHARED = "link_shared"
    BOOKED = "booked"
    CANCELLED = "cancelled"


# ── Base + mixins ──────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


class PKMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


class TenantMixin:
    # Defaults to "local" for the personal MVP; the multi-tenant hedge.
    account_id: Mapped[str] = mapped_column(String(64), default="local", index=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ── Tables ─────────────────────────────────────────────────────────────────


class ICP(PKMixin, TenantMixin, TimestampMixin, Base):
    """A versioned snapshot of the ICP config used at scoring time.

    Persisted from config/icp.yaml so a lead's score stays reproducible even
    after the user edits the ICP.
    """

    __tablename__ = "icps"

    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    criteria_json: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Signal(PKMixin, TenantMixin, TimestampMixin, Base):
    """A raw buying-intent event (a CSV row, a LinkedIn post engagement, ...)."""

    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("account_id", "dedupe_key", name="uq_signal_dedupe"),)

    source: Mapped[str] = mapped_column(String(40))
    source_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(200), index=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=SignalStatus.NEW)


class Prospect(PKMixin, TenantMixin, TimestampMixin, Base):
    """A person derived from a signal, before enrichment. The dedupe anchor."""

    __tablename__ = "prospects"
    __table_args__ = (UniqueConstraint("account_id", "dedupe_key", name="uq_prospect_dedupe"),)

    full_name: Mapped[str] = mapped_column(String(200))
    headline: Mapped[str | None] = mapped_column(String(400), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), index=True)
    origin_signal_id: Mapped[str | None] = mapped_column(
        ForeignKey("signals.id"), nullable=True
    )
    enrichment_status: Mapped[str] = mapped_column(String(20), default=EnrichmentStatus.PENDING)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)

    enrichment: Mapped[EnrichedContact | None] = relationship(
        back_populates="prospect", uselist=False, cascade="all, delete-orphan"
    )
    scored_leads: Mapped[list[ScoredLead]] = relationship(back_populates="prospect")


class EnrichedContact(PKMixin, TenantMixin, TimestampMixin, Base):
    """Provider output for a prospect (email + firmographics). 1:1 with Prospect.

    Keeps ``provider_raw_json`` so we never re-pay to re-derive a field.
    """

    __tablename__ = "enriched_contacts"

    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), unique=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_status: Mapped[str] = mapped_column(String(20), default=EmailStatus.NONE)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(60), nullable=True)
    company_domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider_raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    prospect: Mapped[Prospect] = relationship(back_populates="enrichment")


class ScoredLead(PKMixin, TenantMixin, TimestampMixin, Base):
    """Claude's verdict on a prospect against a specific ICP version."""

    __tablename__ = "scored_leads"

    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"))
    icp_id: Mapped[str] = mapped_column(ForeignKey("icps.id"))
    score: Mapped[int] = mapped_column(Integer)
    tier: Mapped[str] = mapped_column(String(2))
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_criteria_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    prospect: Mapped[Prospect] = relationship(back_populates="scored_leads")
    drafts: Mapped[list[DraftMessage]] = relationship(back_populates="scored_lead")


class DraftMessage(PKMixin, TenantMixin, TimestampMixin, Base):
    """A piece of personalized outreach awaiting approval (or sent)."""

    __tablename__ = "draft_messages"

    scored_lead_id: Mapped[str] = mapped_column(ForeignKey("scored_leads.id"))
    channel: Mapped[str] = mapped_column(String(20))
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default=DraftStatus.DRAFT)

    scored_lead: Mapped[ScoredLead] = relationship(back_populates="drafts")
    approval: Mapped[ApprovalItem | None] = relationship(
        back_populates="draft", uselist=False, cascade="all, delete-orphan"
    )
    logs: Mapped[list[OutreachLog]] = relationship(back_populates="draft")


class ApprovalItem(PKMixin, TenantMixin, TimestampMixin, Base):
    """The human gate. The dashboard reads/writes only this table + DraftMessage."""

    __tablename__ = "approval_items"

    draft_message_id: Mapped[str] = mapped_column(ForeignKey("draft_messages.id"), unique=True)
    state: Mapped[str] = mapped_column(String(20), default=ApprovalState.PENDING)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    draft: Mapped[DraftMessage] = relationship(back_populates="approval")


class OutreachLog(PKMixin, TenantMixin, Base):
    """Append-only audit of everything that left the building."""

    __tablename__ = "outreach_logs"

    draft_message_id: Mapped[str] = mapped_column(ForeignKey("draft_messages.id"))
    channel: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event: Mapped[str] = mapped_column(String(20))
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    draft: Mapped[DraftMessage] = relationship(back_populates="logs")


class Campaign(PKMixin, TenantMixin, TimestampMixin, Base):
    """A lightweight grouping that defines channel order + volume guardrails."""

    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(160))
    icp_id: Mapped[str | None] = mapped_column(ForeignKey("icps.id"), nullable=True)
    channel_sequence_json: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_cap: Mapped[int] = mapped_column(Integer, default=25)


class AppConfig(TenantMixin, TimestampMixin, Base):
    """Small key/value store for editable config that must survive redeploys.

    On a hosted, ephemeral filesystem we can't rely on writing config/icp.yaml,
    so the web Settings editor persists the ICP YAML here (key="icp_yaml").
    """

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class SuppressionList(PKMixin, TenantMixin, TimestampMixin, Base):
    """Do-not-contact list (UK PECR/GDPR backbone). Email-only granularity.

    Auto-populated when an inbound reply is classified as unsubscribe/opt-out.
    The durable, cross-run source of truth that drives ``Prospect.suppressed``;
    checked at ingest and as a hard guard before every send.
    """

    __tablename__ = "suppression_list"
    __table_args__ = (
        UniqueConstraint("account_id", "email", name="uq_suppression_email"),
    )

    email: Mapped[str] = mapped_column(String(320), index=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default=SuppressionSource.OPT_OUT)


class ConversationThread(PKMixin, TenantMixin, TimestampMixin, Base):
    """One ongoing conversation with a prospect on a channel (Phase 2)."""

    __tablename__ = "conversation_threads"

    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default=ThreadStatus.ACTIVE)
    last_intent: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Provider-native conversation id (Unipile chat_id) — the durable key that ties an
    # inbound LinkedIn reply back to this thread when no email/profile URL is available.
    provider_chat_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    # The invitation/relation id Unipile returns when we send a connection request, before
    # a chat exists. Used to reconcile to a chat_id once the connection is accepted.
    provider_thread_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)

    messages: Mapped[list[Message]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )


class Message(PKMixin, TenantMixin, TimestampMixin, Base):
    """A single inbound or outbound message within a conversation thread."""

    __tablename__ = "messages"

    thread_id: Mapped[str] = mapped_column(ForeignKey("conversation_threads.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    body: Mapped[str] = mapped_column(Text)
    provider_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(30), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    thread: Mapped[ConversationThread] = relationship(back_populates="messages")


class Meeting(PKMixin, TenantMixin, TimestampMixin, Base):
    """A meeting surfaced via the booking link (Phase 2). No calendar API."""

    __tablename__ = "meetings"

    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), index=True)
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversation_threads.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default=MeetingStatus.LINK_SHARED)
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResearchNote(PKMixin, TenantMixin, TimestampMixin, Base):
    """A researched opener hook for a prospect — one true, specific, recent fact.

    Cached so we never re-pay to re-derive it, and auditable so the user can see *why*
    an opener said what it said (and verify ``url``). Populated by the research stage,
    read by drafting to anchor the opener.
    """

    __tablename__ = "research_notes"

    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40))
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence: Mapped[str] = mapped_column(String(10), default="medium")


# All ORM tables, handy for Alembic and tests.
ALL_TABLES = [
    ICP,
    Signal,
    Prospect,
    EnrichedContact,
    ScoredLead,
    DraftMessage,
    ApprovalItem,
    OutreachLog,
    Campaign,
    AppConfig,
    SuppressionList,
    ConversationThread,
    Message,
    Meeting,
    ResearchNote,
]

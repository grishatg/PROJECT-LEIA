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
]

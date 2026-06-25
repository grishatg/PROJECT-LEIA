"""Turn ORM rows into plain dicts the web UI can render as JSON.

The approval serializer mirrors the join the old Streamlit dashboard did:
ApprovalItem -> DraftMessage -> ScoredLead -> Prospect -> EnrichedContact.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leia.models import (
    ApprovalItem,
    ApprovalState,
    DraftMessage,
    DraftStatus,
    OutreachLog,
    Prospect,
    ScoredLead,
    Signal,
)


def _initials(name: str | None) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


_EPOCH = datetime.min.replace(tzinfo=UTC)


def _latest_lead(prospect: Prospect) -> ScoredLead | None:
    leads = sorted(
        prospect.scored_leads, key=lambda lead: lead.created_at or _EPOCH, reverse=True
    )
    return leads[0] if leads else None


def _humanize(label: str) -> str:
    """'companyChange' / 'new_funding' -> 'Company change' / 'New funding'."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(label)).replace("_", " ").replace("-", " ")
    s = s.strip().lower()
    return s[:1].upper() + s[1:] if s else ""


def _signals(session: Session, prospect: Prospect) -> list[str]:
    """Best-effort human-readable signal/trigger labels from the origin signal."""
    sig_id = getattr(prospect, "origin_signal_id", None)
    sig = session.get(Signal, sig_id) if sig_id else None
    raw = (sig.raw_json or {}) if sig else {}
    out: list[str] = []
    for s in (raw.get("signals") or []):
        if isinstance(s, dict):
            label = s.get("type") or s.get("name") or s.get("signal_type") or ""
        else:
            label = str(s)
        label = _humanize(label)
        if label and label not in out:
            out.append(label)
    return out[:4]


def serialize_prospect_row(session: Session, prospect: Prospect) -> dict:
    """Compact card payload for the Prospects browse grid."""
    lead = _latest_lead(prospect)
    ec = prospect.enrichment
    drafts = (
        session.execute(
            select(DraftMessage).where(DraftMessage.scored_lead_id == lead.id)
        ).scalars().all()
        if lead
        else []
    )
    status = "Contacted" if any(d.status == DraftStatus.SENT for d in drafts) else "New"
    return {
        "id": prospect.id,
        "full_name": prospect.full_name,
        "initials": _initials(prospect.full_name),
        "company_name": prospect.company_name,
        "headline": prospect.headline,
        "title": ec.title if ec else None,
        "score": lead.score if lead else None,
        "tier": lead.tier if lead else None,
        "status": status,
        "industry": ec.industry if ec else None,
        "signals": _signals(session, prospect),
    }


def serialize_lead_detail(session: Session, prospect: Prospect) -> dict:
    """Full slide-over payload: who, why-fit, signals, outreach so far."""
    lead = _latest_lead(prospect)
    ec = prospect.enrichment
    lead_ids = [lead_row.id for lead_row in prospect.scored_leads]
    draft_ids: list[str] = []
    if lead_ids:
        draft_ids = [
            d.id
            for d in session.execute(
                select(DraftMessage).where(DraftMessage.scored_lead_id.in_(lead_ids))
            ).scalars().all()
        ]
    outreach = []
    pending = False
    if draft_ids:
        logs = session.execute(
            select(OutreachLog)
            .where(OutreachLog.draft_message_id.in_(draft_ids))
            .order_by(OutreachLog.occurred_at.desc())
        ).scalars().all()
        outreach = [
            {
                "channel": log.channel,
                "event": log.event,
                "subject": (session.get(DraftMessage, log.draft_message_id).subject or "")
                if log.draft_message_id
                else "",
                "occurred_at": log.occurred_at.isoformat() if log.occurred_at else None,
            }
            for log in logs
        ]
        pending = bool(
            session.execute(
                select(func.count())
                .select_from(ApprovalItem)
                .where(
                    ApprovalItem.draft_message_id.in_(draft_ids),
                    ApprovalItem.state == ApprovalState.PENDING,
                )
            ).scalar()
            or 0
        )
    matched = (lead.matched_criteria_json or []) if lead else []
    signals = _signals(session, prospect)
    return {
        "id": prospect.id,
        "full_name": prospect.full_name,
        "initials": _initials(prospect.full_name),
        "company_name": prospect.company_name,
        "headline": prospect.headline,
        "title": ec.title if ec else None,
        "email": ec.email if ec else None,
        "email_status": ec.email_status if ec else None,
        "score": lead.score if lead else None,
        "tier": lead.tier if lead else None,
        "rationale": lead.rationale if lead else None,
        "matched_criteria": matched if isinstance(matched, list) else [],
        "signal_summary": ", ".join(signals) if signals else None,
        "outreach": outreach,
        "pending": pending,
    }


def serialize_approval(session: Session, item: ApprovalItem) -> dict:
    """Build the full card payload for one pending ApprovalItem."""
    draft = session.get(DraftMessage, item.draft_message_id)
    lead = session.get(ScoredLead, draft.scored_lead_id) if draft else None
    prospect = session.get(Prospect, lead.prospect_id) if lead else None
    enrichment = prospect.enrichment if prospect else None

    spend = (lead.cost_usd or 0.0 if lead else 0.0) + (draft.cost_usd or 0.0 if draft else 0.0)
    cache_read = (lead.cache_read_tokens or 0 if lead else 0) + (
        draft.cache_read_tokens or 0 if draft else 0
    )
    cache_write = (lead.cache_write_tokens or 0 if lead else 0) + (
        draft.cache_write_tokens or 0 if draft else 0
    )

    return {
        "id": item.id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "full_name": prospect.full_name if prospect else "(unknown)",
        "initials": _initials(prospect.full_name if prospect else None),
        "headline": prospect.headline if prospect else None,
        "company_name": prospect.company_name if prospect else None,
        "linkedin_url": prospect.linkedin_url if prospect else None,
        "email": enrichment.email if enrichment else None,
        "email_status": enrichment.email_status if enrichment else None,
        "score": lead.score if lead else None,
        "tier": lead.tier if lead else None,
        "rationale": lead.rationale if lead else None,
        "channel": draft.channel if draft else None,
        "subject": (draft.subject or "") if draft else "",
        "body": (draft.body or "") if draft else "",
        "model_id": (draft.model_id or "stub") if draft else "stub",
        "spend_usd": round(spend, 6),
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
    }


EXPORT_COLUMNS = [
    "full_name",
    "company_name",
    "title",
    "email",
    "email_status",
    "linkedin_url",
    "score",
    "tier",
    "drafts",
    "created_at",
]


def export_prospects_csv(session: Session, account_id: str = "local") -> str:
    """Flatten every prospect (+ enrichment, latest score, draft statuses) into CSV text."""
    prospects = (
        session.execute(
            select(Prospect)
            .where(Prospect.account_id == account_id)
            .order_by(Prospect.created_at.desc())
        )
        .scalars()
        .all()
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)

    for p in prospects:
        ec = p.enrichment
        leads = sorted(
            p.scored_leads, key=lambda lead: lead.created_at or "", reverse=True
        )
        lead = leads[0] if leads else None
        drafts = ""
        if lead:
            draft_rows = (
                session.execute(
                    select(DraftMessage).where(DraftMessage.scored_lead_id == lead.id)
                )
                .scalars()
                .all()
            )
            drafts = "; ".join(f"{d.channel}:{d.status}" for d in draft_rows)

        writer.writerow(
            [
                p.full_name,
                p.company_name or "",
                (ec.title if ec else None) or "",
                (ec.email if ec else None) or "",
                (ec.email_status if ec else None) or "",
                p.linkedin_url or "",
                lead.score if lead else "",
                lead.tier if lead else "",
                drafts,
                p.created_at.isoformat() if p.created_at else "",
            ]
        )

    return buf.getvalue()


def serialize_outreach(session: Session, log: OutreachLog) -> dict:
    """Build a compact history-row payload for one OutreachLog entry."""
    draft = session.get(DraftMessage, log.draft_message_id)
    lead = session.get(ScoredLead, draft.scored_lead_id) if draft else None
    prospect = session.get(Prospect, lead.prospect_id) if lead else None
    return {
        "id": log.id,
        "occurred_at": log.occurred_at.isoformat() if log.occurred_at else None,
        "full_name": prospect.full_name if prospect else "(unknown)",
        "company_name": prospect.company_name if prospect else None,
        "channel": log.channel,
        "provider": log.provider,
        "event": log.event,
        "subject": (draft.subject or "") if draft else "",
    }

"""Turn ORM rows into plain dicts the web UI can render as JSON.

The approval serializer mirrors the join the old Streamlit dashboard did:
ApprovalItem -> DraftMessage -> ScoredLead -> Prospect -> EnrichedContact.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from leia.models import ApprovalItem, DraftMessage, OutreachLog, Prospect, ScoredLead


def _initials(name: str | None) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


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

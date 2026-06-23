"""Suppression / opt-out list — the do-not-contact backbone (UK PECR/GDPR).

Email-only granularity. Auto-populated when an inbound reply is classified as
unsubscribe/opt-out, and enforced in three places (defense in depth):

1. ``pipeline.ingest`` — a re-sourced prospect whose email is suppressed is
   flagged ``suppressed=True`` (so enrich/score/draft skip it — those stages
   already filter on that flag).
2. ``pipeline.send_approved`` — a hard guard skips any approved draft whose
   contact email is on the list.
3. anywhere else that is about to contact someone, via ``is_suppressed``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from leia.dedupe import normalize_email
from leia.models import Prospect, SuppressionList, SuppressionSource


def is_suppressed(session: Session, email: str | None, account_id: str = "local") -> bool:
    """True if this email is on the do-not-contact list."""
    if not email:
        return False
    norm = normalize_email(email)
    return (
        session.execute(
            select(SuppressionList.id).where(
                SuppressionList.account_id == account_id,
                SuppressionList.email == norm,
            )
        ).first()
        is not None
    )


def add_suppression(
    session: Session,
    email: str | None,
    *,
    reason: str | None = None,
    source: str = SuppressionSource.OPT_OUT,
    account_id: str = "local",
    flag_prospects: bool = True,
) -> SuppressionList | None:
    """Add an email to the suppression list (idempotent) and flag any matching
    prospects so the pipeline immediately excludes them. Returns the row (new or
    existing), or None if no email was given."""
    if not email:
        return None
    norm = normalize_email(email)
    existing = session.execute(
        select(SuppressionList).where(
            SuppressionList.account_id == account_id, SuppressionList.email == norm
        )
    ).scalar_one_or_none()
    row = existing or SuppressionList(
        account_id=account_id, email=norm, reason=reason, source=source
    )
    if existing is None:
        session.add(row)

    if flag_prospects:
        # Mark every prospect with this enriched email as suppressed.
        prospects = (
            session.execute(
                select(Prospect)
                .join(Prospect.enrichment)
                .where(Prospect.account_id == account_id)
            ).scalars().all()
        )
        for p in prospects:
            ec = p.enrichment
            if ec and ec.email and normalize_email(ec.email) == norm:
                p.suppressed = True

    session.flush()
    return row

"""The human approval gate. The dashboard and CLI call these.

Nothing in the pipeline sends a message unless its draft is APPROVED here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from leia.models import (
    ApprovalItem,
    ApprovalState,
    DraftMessage,
    DraftStatus,
    utcnow,
)


def enqueue_pending(session: Session, account_id: str = "local") -> int:
    """Create a pending ApprovalItem for every draft that doesn't have one yet."""
    drafts = (
        session.execute(
            select(DraftMessage).where(
                DraftMessage.account_id == account_id,
                DraftMessage.status == DraftStatus.DRAFT,
            )
        )
        .scalars()
        .all()
    )
    created = 0
    for d in drafts:
        exists = session.execute(
            select(ApprovalItem).where(ApprovalItem.draft_message_id == d.id)
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                ApprovalItem(
                    account_id=d.account_id,
                    draft_message_id=d.id,
                    state=ApprovalState.PENDING,
                )
            )
            created += 1
    session.commit()
    return created


def list_pending(session: Session, account_id: str = "local") -> list[ApprovalItem]:
    return list(
        session.execute(
            select(ApprovalItem).where(
                ApprovalItem.account_id == account_id,
                ApprovalItem.state == ApprovalState.PENDING,
            )
        )
        .scalars()
        .all()
    )


def approve(
    session: Session,
    approval_id: str,
    *,
    note: str | None = None,
    edited_subject: str | None = None,
    edited_body: str | None = None,
) -> ApprovalItem:
    """Approve a draft (optionally editing it first)."""
    item = session.get(ApprovalItem, approval_id)
    if item is None:
        raise ValueError(f"ApprovalItem not found: {approval_id}")
    draft = session.get(DraftMessage, item.draft_message_id)
    if edited_subject is not None:
        draft.subject = edited_subject
    if edited_body is not None:
        draft.body = edited_body
    # Approved (whether edited or not) means cleared to send.
    draft.status = DraftStatus.APPROVED
    item.state = ApprovalState.APPROVED
    item.reviewer_note = note
    item.decided_at = utcnow()
    session.commit()
    return item


def reject(session: Session, approval_id: str, *, note: str | None = None) -> ApprovalItem:
    item = session.get(ApprovalItem, approval_id)
    if item is None:
        raise ValueError(f"ApprovalItem not found: {approval_id}")
    draft = session.get(DraftMessage, item.draft_message_id)
    draft.status = DraftStatus.REJECTED
    item.state = ApprovalState.REJECTED
    item.reviewer_note = note
    item.decided_at = utcnow()
    session.commit()
    return item

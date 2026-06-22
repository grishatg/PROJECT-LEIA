"""Approval queue: enqueue, approve (with edits), reject."""

from __future__ import annotations

from leia.approval.queue import approve, enqueue_pending, list_pending, reject
from leia.models import (
    ApprovalState,
    DraftMessage,
    DraftStatus,
    Prospect,
    ScoredLead,
    Tier,
)


def _seed_draft(session) -> DraftMessage:
    p = Prospect(full_name="Tom Riley", company_name="GridCo", dedupe_key="li:tom")
    session.add(p)
    session.flush()
    from leia.models import ICP

    icp = ICP(name="X", version=1, criteria_json={})
    session.add(icp)
    session.flush()
    lead = ScoredLead(prospect_id=p.id, icp_id=icp.id, score=72, tier=Tier.B)
    session.add(lead)
    session.flush()
    draft = DraftMessage(
        scored_lead_id=lead.id, channel="email", subject="hi", body="original body"
    )
    session.add(draft)
    session.commit()
    return draft


def test_enqueue_is_idempotent(session):
    _seed_draft(session)
    assert enqueue_pending(session) == 1
    assert enqueue_pending(session) == 0  # no duplicate ApprovalItem
    assert len(list_pending(session)) == 1


def test_approve_marks_draft_approved(session):
    draft = _seed_draft(session)
    enqueue_pending(session)
    item = list_pending(session)[0]
    approve(session, item.id, note="looks good")
    session.refresh(item)
    session.refresh(draft)
    assert item.state == ApprovalState.APPROVED
    assert draft.status == DraftStatus.APPROVED
    assert item.reviewer_note == "looks good"


def test_approve_with_edit_persists_changes(session):
    draft = _seed_draft(session)
    enqueue_pending(session)
    item = list_pending(session)[0]
    approve(session, item.id, edited_body="edited body", edited_subject="new subject")
    session.refresh(draft)
    assert draft.body == "edited body"
    assert draft.subject == "new subject"
    assert draft.status == DraftStatus.APPROVED


def test_reject_marks_draft_rejected(session):
    draft = _seed_draft(session)
    enqueue_pending(session)
    item = list_pending(session)[0]
    reject(session, item.id, note="off-target")
    session.refresh(item)
    session.refresh(draft)
    assert item.state == ApprovalState.REJECTED
    assert draft.status == DraftStatus.REJECTED
    assert list_pending(session) == []

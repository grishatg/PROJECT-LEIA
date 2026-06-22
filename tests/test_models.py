"""The data model creates cleanly and the relationships wire up end-to-end."""

from __future__ import annotations

from leia.db import init_db, make_engine, make_session_factory
from leia.models import (
    ICP,
    ApprovalItem,
    ApprovalState,
    DraftMessage,
    EmailStatus,
    EnrichedContact,
    Prospect,
    ScoredLead,
    Tier,
)


def test_account_id_defaults_to_local(session):
    p = Prospect(full_name="Jane Carter", company_name="Northwind", dedupe_key="li:x")
    session.add(p)
    session.commit()
    assert p.account_id == "local"  # the multi-tenant hedge default


def test_full_chain(session):
    """Prospect -> Enrichment -> ICP -> ScoredLead -> Draft -> Approval all link up."""
    prospect = Prospect(
        full_name="Tom Riley",
        company_name="GridCo",
        linkedin_url="https://www.linkedin.com/in/tom-riley-gridco",
        dedupe_key="li:https://linkedin.com/in/tom-riley-gridco",
    )
    enrichment = EnrichedContact(
        prospect=prospect,
        email="tom@gridco.com",
        email_status=EmailStatus.VERIFIED,
        industry="Utilities",
        country="United Kingdom",
    )
    icp = ICP(name="UK Energy B2B", version=1, criteria_json={"industries": ["Utilities"]})
    session.add_all([prospect, enrichment, icp])
    session.commit()

    lead = ScoredLead(
        prospect_id=prospect.id,
        icp_id=icp.id,
        score=85,
        tier=Tier.A,
        rationale="Strong fit",
        matched_criteria_json=["industry: Utilities"],
    )
    session.add(lead)
    session.commit()

    draft = DraftMessage(
        scored_lead_id=lead.id, channel="email", subject="quick idea", body="Hi Tom ..."
    )
    session.add(draft)
    session.commit()

    approval = ApprovalItem(draft_message_id=draft.id, state=ApprovalState.PENDING)
    session.add(approval)
    session.commit()

    # Navigate the relationships back the other way.
    fetched = session.get(Prospect, prospect.id)
    assert fetched.enrichment.email == "tom@gridco.com"
    assert fetched.scored_leads[0].tier == "A"
    assert fetched.scored_leads[0].drafts[0].approval.state == "pending"


def test_init_db_creates_all_tables():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    factory = make_session_factory(engine)
    s = factory()
    try:
        # Every table should be queryable (no missing-table errors).
        assert s.query(Prospect).count() == 0
        assert s.query(ICP).count() == 0
        assert s.query(DraftMessage).count() == 0
    finally:
        s.close()
        engine.dispose()

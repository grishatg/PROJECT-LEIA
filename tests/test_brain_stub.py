"""StubBrain: heuristic scoring (incl. excludes) + templated drafting."""

from __future__ import annotations

from leia.config import load_icp, load_value_prop
from leia.llm.stub import StubBrain
from leia.schemas import ProspectFacts

ICP = load_icp("config/icp.yaml")
VP = load_value_prop("config/value_prop.yaml")


def test_exclude_term_scores_zero():
    brain = StubBrain()
    facts = ProspectFacts(full_name="Sam Lee", headline="Student at University")
    out = brain.score(facts, ICP, VP)
    assert out.result.score == 0
    assert out.result.tier == "C"
    assert out.cost_usd == 0.0


def test_strong_fit_scores_higher():
    brain = StubBrain()
    facts = ProspectFacts(
        full_name="Jane Carter",
        headline="Energy Manager",
        company_name="Northwind Utilities",
        title="Energy Manager",
        country="United Kingdom",
    )
    out = brain.score(facts, ICP, VP)
    assert out.result.score >= 60
    assert out.result.matched_criteria


def test_draft_email_has_subject_and_body():
    brain = StubBrain()
    facts = ProspectFacts(full_name="Tom Riley", company_name="GridCo")
    out = brain.draft(facts, VP, "be brief", "email")
    assert out.result.subject
    assert "Tom" in out.result.body
    assert out.cost_usd == 0.0


def test_draft_linkedin_has_no_subject():
    brain = StubBrain()
    facts = ProspectFacts(full_name="Tom Riley", company_name="GridCo")
    out = brain.draft(facts, VP, "be brief", "linkedin")
    assert out.result.subject is None

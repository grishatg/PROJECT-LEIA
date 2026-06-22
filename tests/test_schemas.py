"""Claude I/O schemas validate and the tier helper bands correctly."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from leia.schemas import DraftResult, ProspectFacts, ScoreResult, tier_for_score


def test_score_result_valid():
    s = ScoreResult(score=85, tier="A", rationale="Good fit", matched_criteria=["industry"])
    assert s.score == 85
    assert s.tier == "A"


def test_score_result_rejects_out_of_range():
    with pytest.raises(ValidationError):
        ScoreResult(score=150, tier="A", rationale="x")


def test_score_result_rejects_bad_tier():
    with pytest.raises(ValidationError):
        ScoreResult(score=50, tier="Z", rationale="x")


def test_tier_for_score_bands():
    assert tier_for_score(100) == "A"
    assert tier_for_score(80) == "A"
    assert tier_for_score(79) == "B"
    assert tier_for_score(60) == "B"
    assert tier_for_score(59) == "C"
    assert tier_for_score(0) == "C"


def test_draft_result_email_and_linkedin():
    email = DraftResult(subject="quick idea", body="Hi Jane, ...")
    linkedin = DraftResult(body="Hi Jane, saw your post ...")  # no subject
    assert email.subject == "quick idea"
    assert linkedin.subject is None


def test_prospect_facts_optional_fields():
    f = ProspectFacts(full_name="Jane Carter")
    assert f.company_name is None

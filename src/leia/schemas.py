"""Pydantic I/O schemas for the Claude calls (scoring + drafting).

These are the typed objects Claude must return. Using structured outputs against
these schemas means the brain returns validated data, not free text to parse.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProspectFacts(BaseModel):
    """The facts we feed Claude about a single prospect (input to scoring/drafting)."""

    full_name: str
    headline: str | None = None
    company_name: str | None = None
    title: str | None = None
    seniority: str | None = None
    industry: str | None = None
    country: str | None = None
    company_size: int | None = None
    signal_summary: str | None = None
    # A true, specific, recent fact to open on (from the research stage). When set, the
    # opener must anchor to it faithfully; when None, the writer falls back to an honest
    # sector observation rather than faking specificity.
    research_hook: str | None = None


class ScoreResult(BaseModel):
    """Claude's verdict on ICP fit (output of scoring)."""

    score: int = Field(ge=0, le=100)
    tier: Literal["A", "B", "C"]
    rationale: str
    matched_criteria: list[str] = Field(default_factory=list)


class DraftResult(BaseModel):
    """A drafted message (output of drafting). ``subject`` is None for LinkedIn."""

    subject: str | None = None
    body: str


ReplyIntentLiteral = Literal[
    "continue",
    "question",
    "negative",
    "out_of_office",
    "unsubscribe",
    "propose_meeting",
    "confirm_meeting",
    "escalate",
]


class ConversationReply(BaseModel):
    """Claude's reply within an ongoing conversation (Phase 2).

    ``intent`` drives the hybrid autonomy: ``continue`` may auto-send under caps;
    anything proposing/confirming a meeting, or ``escalate``/``unsubscribe``,
    routes to the human approval gate (or the suppression list).
    """

    body: str
    intent: ReplyIntentLiteral
    proposed_times: list[str] = Field(default_factory=list)


def tier_for_score(score: int) -> str:
    """Map a 0-100 score to a tier band (A >= 80, B >= 60, else C)."""
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    return "C"

"""A deterministic, zero-cost brain for --dry-run and tests.

Scoring is a transparent keyword heuristic against the ICP; drafting is a
template. No network, no spend. Lets you exercise the whole pipeline and see
plausible scored drafts before paying for real Claude calls.
"""

from __future__ import annotations

from leia.config import ICPConfig, ValuePropConfig
from leia.llm.base import DraftOutput, ScoreOutput
from leia.schemas import DraftResult, ProspectFacts, ScoreResult, tier_for_score

STUB_MODEL = "stub"


def _haystack(facts: ProspectFacts) -> str:
    parts = [
        facts.full_name,
        facts.headline,
        facts.company_name,
        facts.title,
        facts.seniority,
        facts.industry,
        facts.country,
        facts.signal_summary,
    ]
    return " ".join(p for p in parts if p).lower()


class StubBrain:
    def score(
        self, facts: ProspectFacts, icp: ICPConfig, value_prop: ValuePropConfig
    ) -> ScoreOutput:
        hay = _haystack(facts)
        for term in icp.exclude:
            if term and term.lower() in hay:
                result = ScoreResult(
                    score=0, tier="C", rationale=f"Excluded: matches '{term}'.", matched_criteria=[]
                )
                return ScoreOutput(result=result, model_id=STUB_MODEL)

        score = 40
        matched: list[str] = []
        for label, values, points in [
            ("industry", icp.industries, 15),
            ("geography", icp.geographies, 15),
            ("seniority", icp.seniorities, 10),
            ("keyword", icp.keywords, 10),
            ("title", icp.titles, 10),
        ]:
            for v in values:
                if v and v.lower() in hay:
                    score += points
                    matched.append(f"{label}: {v}")
                    break

        score = max(0, min(100, score))
        rationale = "Heuristic stub score based on " + (
            ", ".join(matched) if matched else "no strong ICP matches"
        )
        result = ScoreResult(
            score=score, tier=tier_for_score(score), rationale=rationale, matched_criteria=matched
        )
        return ScoreOutput(result=result, model_id=STUB_MODEL)

    def draft(
        self,
        facts: ProspectFacts,
        value_prop: ValuePropConfig,
        guidelines: str,
        channel: str,
    ) -> DraftOutput:
        first = facts.full_name.split()[0] if facts.full_name else "there"
        company = facts.company_name or "your team"
        proof = value_prop.proof_points[0] if value_prop.proof_points else value_prop.offer.strip()
        role = f" and your work as {facts.title}" if facts.title else ""
        subject = f"quick idea for {company}" if channel == "email" else None
        body = (
            f"Hi {first}, I came across {company}{role}. "
            f"{value_prop.offer.strip()} ({proof}). "
            f"Worth {value_prop.cta}?"
        )
        result = DraftResult(subject=subject, body=body)
        return DraftOutput(result=result, model_id=STUB_MODEL)

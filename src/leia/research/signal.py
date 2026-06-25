"""Derive an opener hook from the signal that surfaced the prospect.

This is the cheapest, highest-value researcher: it only reads data already captured at
ingest (the origin ``Signal``'s source + ``raw_json``), so it costs nothing and never
touches the network. The signal is *why* the prospect surfaced — a recent promotion, a
job change, an active hire — which makes it the most relevant thing to open on.

The hook is an input *fact*, not the final sentence: the writer rephrases it in Greg's
voice, so two prospects with the same signal type still get individually-worded openers.
"""

from __future__ import annotations

from leia.research.base import ResearchHook
from leia.schemas import ProspectFacts

# Lusha-style intent signal type (lower-cased) -> (template, confidence).
# {company} / {title} are filled from the prospect's facts.
_SIGNAL_HOOKS: dict[str, str] = {
    "promotion": "was recently promoted — a new remit is a natural moment to look at cost.",
    "companychange": "recently moved to {company} — likely still getting the lay of the land.",
    "jobchange": "recently moved to {company} — likely still getting the lay of the land.",
    "jobstart": "recently stepped into the {title} seat at {company}.",
    "newrole": "recently stepped into the {title} seat at {company}.",
    "funding": "{company} recently raised — growth usually means more sites and more energy load.",
}


class SignalResearcher:
    """Turn the prospect's origin signal into a true opener hook. Free + offline."""

    name = "signal"

    def find_hook(
        self,
        facts: ProspectFacts,
        *,
        signal_source: str | None = None,
        signal_raw: dict | None = None,
    ) -> ResearchHook | None:
        raw = signal_raw or {}
        company = facts.company_name or "the business"
        title = facts.title or "the role"

        # 1) Typed intent signals (Lusha carries them as a list under "signals").
        for t in (str(s).lower().replace("_", "") for s in (raw.get("signals") or [])):
            tmpl = _SIGNAL_HOOKS.get(t)
            if tmpl:
                return ResearchHook(
                    text="They " + tmpl.format(company=company, title=title),
                    source="signal",
                    confidence="high",
                )

        # 2) A job-change source even without a typed signal list (new in role).
        if signal_source == "jobchange":
            return ResearchHook(
                text=f"They recently moved into the {title} seat at {company}.",
                source="signal",
                confidence="high",
            )

        # 3) A posted role (hiring) — a softer but genuine buying-intent hook.
        role = raw.get("job_title")
        if signal_source == "jobspy" or role or raw.get("job_url"):
            what = role or "for an energy / sustainability role"
            return ResearchHook(
                text=(
                    f"{company} is hiring {what} — often a sign energy "
                    "and cost are on the agenda."
                ),
                source="signal",
                confidence="medium",
                url=raw.get("job_url"),
            )

        return None

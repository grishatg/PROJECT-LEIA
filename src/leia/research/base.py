"""The Researcher protocol + the engine that picks the best hook.

A ``Researcher`` turns what we know about a prospect into at most one ``ResearchHook``
— a single true, specific, recent fact the opener can anchor to. Researchers must be
safe: a provider error returns ``None``, never crashes the pipeline. ``research_prospect``
runs them and returns the highest-confidence hook (ties broken by researcher order, so
list cheaper/stronger sources first).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from leia.schemas import ProspectFacts

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


class ResearchHook(BaseModel):
    """One true, specific, recent fact LEIA can open a message on."""

    text: str  # one sentence, faithful to the source — no embellishment
    source: str  # "signal" | "web" | "companies_house" | ...
    url: str | None = None  # provenance the user can verify
    confidence: str = "medium"  # "high" | "medium" | "low"


@runtime_checkable
class Researcher(Protocol):
    name: str

    def find_hook(
        self,
        facts: ProspectFacts,
        *,
        signal_source: str | None = None,
        signal_raw: dict | None = None,
    ) -> ResearchHook | None:
        """Return one hook for this prospect, or None if nothing specific was found."""
        ...


def research_prospect(
    facts: ProspectFacts,
    *,
    researchers: list[Researcher],
    signal_source: str | None = None,
    signal_raw: dict | None = None,
) -> ResearchHook | None:
    """Run every researcher and return the best hook (highest confidence wins).

    A researcher that raises is treated as "found nothing" — research is best-effort and
    must never break drafting.
    """
    hooks: list[ResearchHook] = []
    for r in researchers:
        try:
            hook = r.find_hook(facts, signal_source=signal_source, signal_raw=signal_raw)
        except Exception:  # noqa: BLE001 - a researcher must never crash the pipeline
            hook = None
        if hook and hook.text.strip():
            hooks.append(hook)
    if not hooks:
        return None
    # Stable sort by confidence; equal-confidence ties keep researcher order (the caller
    # lists stronger/cheaper sources first).
    hooks.sort(key=lambda h: _CONFIDENCE_RANK.get(h.confidence, 1))
    return hooks[0]

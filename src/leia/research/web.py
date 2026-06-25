"""Web-search researcher: a true, recent fact for prospects that arrived without a signal.

A plain CSV row carries no buying-intent signal, so ``SignalResearcher`` finds nothing and
the opener would fall back to a generic sector line. This researcher runs ONE bounded
Anthropic web-search call to surface a single recent, specific fact (a new site, an
expansion, a published Net Zero/SBTi target, a results announcement, a leadership change)
with its source URL.

It is a *paid* path, so it is gated behind a settings flag and only added in real
(non-dry-run) pipelines. It is also defensive: any error or unparseable answer yields
``None`` (no hook) rather than a crash or a fabricated fact — drafting then falls back to
the honest no-hook opener. The single call uses the server-side web-search tool (no
autonomous tool loop), keeping cost bounded and predictable.

Offline + testable: ``WebResearcher`` takes an injectable ``search_fn``; tests pass a fake.
``anthropic_web_search`` builds the production ``search_fn`` from an Anthropic client.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from leia.research.base import ResearchHook
from leia.schemas import ProspectFacts

SearchFn = Callable[[ProspectFacts], ResearchHook | None]

_WEB_SYSTEM = (
    "You are a B2B sales researcher. Find ONE recent, specific, TRUE fact about the named "
    "company that would be a credible reason to reach out about energy cost and Net Zero — "
    "e.g. a new site or acquisition, expansion, a published Net Zero/SBTi target or "
    "sustainability report, a results/funding announcement, or a relevant leadership hire. "
    "Prefer facts from the last 12 months. Use web search. Do NOT invent or infer; if you "
    "cannot find something specific and verifiable, say so.\n\n"
    "Reply with EXACTLY one final line in this format and nothing else:\n"
    "HOOK: <one factual sentence> || URL: <source url> || CONFIDENCE: high|medium|low\n"
    "or, if you found nothing solid:\n"
    "HOOK: NONE"
)

_HOOK_RE = re.compile(
    r"HOOK:\s*(?P<text>.+?)\s*\|\|\s*URL:\s*(?P<url>\S+)\s*\|\|\s*CONFIDENCE:\s*(?P<conf>high|medium|low)",
    re.IGNORECASE | re.DOTALL,
)


class WebResearcher:
    """Find an opener hook via web search. Wraps an injectable ``search_fn``."""

    name = "web"

    def __init__(self, search_fn: SearchFn):
        self._search = search_fn

    def find_hook(
        self,
        facts: ProspectFacts,
        *,
        signal_source: str | None = None,
        signal_raw: dict | None = None,
    ) -> ResearchHook | None:
        if not facts.company_name:
            return None  # nothing to search on
        return self._search(facts)


def _final_text(resp) -> str:
    """Concatenate the text blocks of an Anthropic response (ignores tool blocks)."""
    parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "\n".join(parts)


def parse_hook(text: str) -> ResearchHook | None:
    """Parse the strict ``HOOK: … || URL: … || CONFIDENCE: …`` line into a hook."""
    if not text or "HOOK: NONE" in text.upper():
        return None
    m = _HOOK_RE.search(text)
    if not m:
        return None
    hook_text = m.group("text").strip()
    if not hook_text or hook_text.upper() == "NONE":
        return None
    return ResearchHook(
        text=hook_text,
        source="web",
        url=m.group("url").strip(),
        confidence=m.group("conf").lower(),
    )


def anthropic_web_search(
    client,
    *,
    model: str = "claude-haiku-4-5",
    max_uses: int = 3,
    max_tokens: int = 500,
) -> SearchFn:
    """Build the production ``search_fn``: one bounded Anthropic web-search call per prospect.

    Uses a cheap model by default (extraction, not reasoning). Any failure returns ``None``
    so a flaky search never breaks the pipeline or fabricates a fact.
    """

    def _search(facts: ProspectFacts) -> ResearchHook | None:
        who = facts.company_name or ""
        context = ", ".join(
            p for p in [facts.industry, facts.country] if p
        )
        user = f"Company: {who}" + (f" ({context})" if context else "")
        if facts.title:
            user += f"\nContact role: {facts.title}"
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=_WEB_SYSTEM,
                messages=[{"role": "user", "content": user}],
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}],
            )
        except Exception:  # noqa: BLE001 - a flaky search must never break the pipeline
            return None
        return parse_hook(_final_text(resp))

    return _search

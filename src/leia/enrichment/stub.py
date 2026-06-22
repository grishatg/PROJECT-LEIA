"""Deterministic enrichment for --dry-run and tests (no network, no spend).

Synthesizes a best-guess email from name + company so the pipeline has something
to carry forward. Never call this a verified email.
"""

from __future__ import annotations

import re

from leia.enrichment.base import EnrichmentQuery, EnrichmentResult


def _domain_from_company(company: str | None) -> str | None:
    if not company:
        return None
    slug = re.sub(r"[^a-z0-9]+", "", company.lower())
    return f"{slug}.com" if slug else None


class StubEnricher:
    name = "stub"

    def enrich(self, query: EnrichmentQuery) -> EnrichmentResult:
        domain = query.domain or _domain_from_company(query.company_name)
        email = None
        if domain and query.full_name:
            parts = query.full_name.lower().split()
            if len(parts) >= 2:
                email = f"{parts[0]}.{parts[-1]}@{domain}"
            elif parts:
                email = f"{parts[0]}@{domain}"
        return EnrichmentResult(
            email=email,
            email_status="guess" if email else "none",
            company_domain=domain,
            provider=self.name,
        )

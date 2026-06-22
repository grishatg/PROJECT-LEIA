"""The Enricher protocol. Implement this to swap enrichment providers.

Default provider (Phase 1) is Prospeo; alternatives (Dropcontact, Snov.io,
Hunter) implement the same protocol so swapping is a one-file change.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class EnrichmentQuery(BaseModel):
    """What we know about a prospect when asking a provider to enrich them."""

    full_name: str
    company_name: str | None = None
    linkedin_url: str | None = None
    domain: str | None = None


class EnrichmentResult(BaseModel):
    """Normalized provider output. ``raw`` caches the full payload."""

    email: str | None = None
    email_status: str = "none"  # verified | guess | none
    title: str | None = None
    seniority: str | None = None
    company_domain: str | None = None
    company_size: int | None = None
    industry: str | None = None
    country: str | None = None
    provider: str | None = None
    raw: dict = Field(default_factory=dict)


@runtime_checkable
class Enricher(Protocol):
    name: str

    def enrich(self, query: EnrichmentQuery) -> EnrichmentResult:
        """Look up a prospect and return normalized enrichment."""
        ...

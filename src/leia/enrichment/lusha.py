"""Lusha email-finder enrichment provider.

Implements the Enricher protocol via Lusha's Person API
(``GET https://api.lusha.com/v2/person``, verified against the live API).
Prefers LinkedIn URL lookup (most accurate); falls back to
first_name + last_name + companyName/companyDomain when no URL is available.

Parsing is defensive and degrades to email_status=none on any error rather than
crashing the pipeline.
"""

from __future__ import annotations

import httpx

from leia.enrichment.base import EnrichmentQuery, EnrichmentResult

LUSHA_PERSON_URL = "https://api.lusha.com/v2/person"


def _parse_company_size(raw) -> int | None:
    """Parse a company size into an integer upper bound.

    Handles Lusha range strings like '11-50' / '1000+', plain ints, and dicts
    such as ``{"min": 50, "max": 5000}``.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw.get("max") or raw.get("min")
    if isinstance(raw, int):
        return raw
    raw = str(raw).strip().replace("+", "")
    parts = raw.split("-")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


class LushaEnricher:
    name = "lusha"

    def __init__(self, api_key: str, *, timeout: float = 20.0):
        if not api_key:
            raise ValueError("Lusha API key is required")
        self.api_key = api_key
        self.timeout = timeout

    def enrich(self, query: EnrichmentQuery) -> EnrichmentResult:
        if query.linkedin_url:
            params: dict = {"linkedinUrl": query.linkedin_url}
        else:
            parts = (query.full_name or "").split()
            params = {
                "firstName": parts[0] if parts else "",
                "lastName": parts[-1] if len(parts) >= 2 else "",
            }
            # Person API wants companyName OR companyDomain (not a generic 'company').
            if query.company_name:
                params["companyName"] = query.company_name
            elif query.domain:
                params["companyDomain"] = query.domain

        headers = {"api_key": self.api_key, "accept": "application/json"}
        try:
            resp = httpx.get(
                LUSHA_PERSON_URL, params=params, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:  # noqa: BLE001 - never crash the pipeline on a provider error
            return EnrichmentResult(
                email=None, email_status="none", provider=self.name, raw={"error": str(e)}
            )

        # V2 nests the contact under {"contact": {"data": {...}}}.
        data = ((body or {}).get("contact") or {}).get("data") or {}
        emails: list[dict] = data.get("emailAddresses") or []

        # Prefer a work email; fall back to the first available.
        email = next(
            (e.get("email") for e in emails if e.get("emailType") == "work"),
            None,
        ) or (emails[0].get("email") if emails else None)

        email_status = "verified" if email else "none"

        job_title = data.get("jobTitle") or {}
        if isinstance(job_title, dict):
            title = job_title.get("title")
            seniority = job_title.get("seniority")
        else:
            title = job_title or None
            seniority = None

        company = data.get("company") or {}
        company_domain = (
            (company.get("domain") if isinstance(company, dict) else None) or query.domain
        )
        company_size = _parse_company_size(
            company.get("size") if isinstance(company, dict) else None
        )
        industry = company.get("industry") if isinstance(company, dict) else None

        location = data.get("location") or {}
        country = location.get("country") if isinstance(location, dict) else None

        return EnrichmentResult(
            email=email,
            email_status=email_status,
            title=title,
            seniority=seniority,
            company_domain=company_domain,
            company_size=company_size,
            industry=industry,
            country=country,
            provider=self.name,
            raw=body if isinstance(body, dict) else {},
        )

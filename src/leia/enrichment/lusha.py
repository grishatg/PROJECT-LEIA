"""Lusha email-finder enrichment provider.

Implements the Enricher protocol. Prefers LinkedIn URL lookup (most accurate);
falls back to first_name + last_name + company when no URL is available.

NOTE: verify the exact request/response shape against your Lusha account on
first real run; parsing is defensive and degrades to email_status=none on any
error rather than crashing the pipeline.
"""

from __future__ import annotations

import httpx

from leia.enrichment.base import EnrichmentQuery, EnrichmentResult

LUSHA_PERSON_URL = "https://api.lusha.com/person"


def _parse_company_size(raw: str | None) -> int | None:
    """Parse Lusha's range strings like '11-50' or '1000+' to an integer (upper bound)."""
    if not raw:
        return None
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
            payload: dict = {"linkedInUrl": query.linkedin_url}
        else:
            parts = (query.full_name or "").split()
            payload = {
                "firstName": parts[0] if parts else "",
                "lastName": parts[-1] if len(parts) >= 2 else "",
                "company": query.company_name or query.domain or "",
            }

        headers = {"api_key": self.api_key, "Content-Type": "application/json"}
        try:
            resp = httpx.post(
                LUSHA_PERSON_URL, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:  # noqa: BLE001 - never crash the pipeline on a provider error
            return EnrichmentResult(
                email=None, email_status="none", provider=self.name, raw={"error": str(e)}
            )

        data = (body or {}).get("data") or {}
        emails: list[dict] = data.get("emails") or []

        # Prefer a professional email; fall back to first available.
        email = next(
            (e.get("emailAddress") for e in emails if e.get("type") == "professional"),
            None,
        ) or (emails[0].get("emailAddress") if emails else None)

        email_status = "verified" if email else "none"

        return EnrichmentResult(
            email=email,
            email_status=email_status,
            title=data.get("jobTitle"),
            seniority=data.get("seniority"),
            company_domain=data.get("companyDomain") or query.domain,
            company_size=_parse_company_size(data.get("companySize")),
            industry=data.get("industry"),
            country=data.get("country"),
            provider=self.name,
            raw=body if isinstance(body, dict) else {},
        )

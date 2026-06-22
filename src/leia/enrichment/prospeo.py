"""Prospeo email-finder enrichment (the default real provider).

Cheaper-than-Apollo email lookup. Swap for Dropcontact/Snov.io/Hunter by writing
another class implementing the Enricher protocol.

NOTE: verify the exact request/response shape against your Prospeo account on
first real run; the parsing below is defensive and degrades to email_status=none
on any error rather than crashing the pipeline.
"""

from __future__ import annotations

import httpx

from leia.enrichment.base import EnrichmentQuery, EnrichmentResult

PROSPEO_EMAIL_FINDER_URL = "https://api.prospeo.io/email-finder"


class ProspeoEnricher:
    name = "prospeo"

    def __init__(self, api_key: str, *, timeout: float = 20.0):
        if not api_key:
            raise ValueError("Prospeo API key is required")
        self.api_key = api_key
        self.timeout = timeout

    def enrich(self, query: EnrichmentQuery) -> EnrichmentResult:
        parts = (query.full_name or "").split()
        payload: dict = {
            "first_name": parts[0] if parts else "",
            "last_name": parts[-1] if len(parts) >= 2 else "",
        }
        # Prospeo accepts a company name or domain to disambiguate.
        if query.domain:
            payload["company"] = query.domain
        elif query.company_name:
            payload["company"] = query.company_name

        headers = {"Content-Type": "application/json", "X-KEY": self.api_key}
        try:
            resp = httpx.post(
                PROSPEO_EMAIL_FINDER_URL, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001 - never crash the pipeline on a provider error
            return EnrichmentResult(
                email=None, email_status="none", provider=self.name, raw={"error": str(e)}
            )

        response = (data or {}).get("response") or {}
        email = response.get("email")
        verification = response.get("email_status") or response.get("verification")
        if email and str(verification).lower() in {"valid", "true"}:
            status = "verified"
        elif email:
            status = "guess"
        else:
            status = "none"

        return EnrichmentResult(
            email=email,
            email_status=status,
            company_domain=response.get("domain") or query.domain,
            provider=self.name,
            raw=data if isinstance(data, dict) else {},
        )

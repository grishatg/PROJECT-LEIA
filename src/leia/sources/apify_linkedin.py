"""LinkedIn prospect source via an existing Apify dataset.

The user runs an Apify actor separately (e.g. the LinkedIn Profile Scraper or a
Sales Navigator export) and provides the resulting dataset ID. This source fetches
those items into the pipeline — no actor runtime inside the pipeline itself.

Common actors that work with this source:
  - apify/linkedin-profile-scraper
  - curious_coder/linkedin-people-search-scraper

Usage:
  leia run --source apify_linkedin --dataset <DATASET_ID>
"""

from __future__ import annotations

import httpx

from leia.models import SignalSource as SignalSourceConst
from leia.sources.base import RawSignal

APIFY_DATASET_URL = "https://api.apify.com/v2/datasets/{dataset_id}/items"


def _extract_fields(item: dict) -> dict:
    """Normalize common Apify LinkedIn scraper output to our field names.

    Different actors use different key names for the same data. This tries the most
    common patterns in priority order so the source works out of the box with the
    most popular actors.
    """
    # Name
    first = item.get("firstName", "")
    last = item.get("lastName", "")
    full_name = (
        item.get("full_name")
        or item.get("name")
        or f"{first} {last}".strip()
        or None
    )

    # Headline / bio line
    headline = item.get("headline") or item.get("summary") or None

    # Current company
    company_name = (
        item.get("company_name")
        or item.get("currentPositionCompanyName")
        or (item.get("currentCompany") or {}).get("name")
        or None
    )
    if not company_name:
        exps: list = item.get("experiences") or item.get("jobs") or []
        if exps and isinstance(exps[0], dict):
            company_name = (
                exps[0].get("companyName") or exps[0].get("company") or None
            )

    # LinkedIn profile URL
    linkedin_url = (
        item.get("linkedin_url")
        or item.get("profileUrl")
        or item.get("linkedinUrl")
        or item.get("url")
        or None
    )

    # Email (some scrapers surface it; skip enrichment if present)
    email = item.get("email") or item.get("emailAddress") or None

    return {
        "full_name": full_name,
        "headline": headline,
        "company_name": company_name,
        "linkedin_url": linkedin_url,
        "email": email,
    }


class ApifyLinkedInSource:
    """Fetch LinkedIn prospects from an Apify dataset (read-only, no actor run)."""

    name = SignalSourceConst.APIFY_LINKEDIN

    def __init__(self, api_token: str, dataset_id: str, *, timeout: float = 30.0):
        if not api_token:
            raise ValueError("APIFY_TOKEN is required for the apify_linkedin source")
        if not dataset_id:
            raise ValueError("--dataset <id> is required for the apify_linkedin source")
        self.api_token = api_token
        self.dataset_id = dataset_id
        self.timeout = timeout

    def fetch(self) -> list[RawSignal]:
        url = APIFY_DATASET_URL.format(dataset_id=self.dataset_id)
        try:
            resp = httpx.get(
                url,
                params={"token": self.api_token, "format": "json"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Apify dataset fetch failed ({e.response.status_code}): {e.response.text[:200]}"
            ) from e

        items: list[dict] = resp.json() or []

        signals: list[RawSignal] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            fields = _extract_fields(item)
            if not fields["full_name"] and not fields["linkedin_url"]:
                continue  # skip items with no usable identity
            signals.append(
                RawSignal(
                    source=self.name,
                    source_ref=f"apify:{self.dataset_id}",
                    full_name=fields["full_name"] or "(unknown)",
                    headline=fields["headline"],
                    company_name=fields["company_name"],
                    linkedin_url=fields["linkedin_url"],
                    email=fields["email"],
                    raw=item,
                )
            )
        return signals

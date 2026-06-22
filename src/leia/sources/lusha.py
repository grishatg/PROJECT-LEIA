"""Lusha signal sources: ICP-driven contact discovery and intent-signal detection.

Two sources share this file because both call the same Lusha prospecting endpoint —
the signals source simply adds a ``signals`` filter to narrow results to contacts who
had a recent buying-intent event (promotion, company change).

Endpoint URL: https://api.lusha.com/prospecting/contacts
Confirm the exact path against https://docs.lusha.com/apis/openapi on first real run.
Auth header: api_key (same as the person-enrichment endpoint).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from leia.config import ICPConfig
from leia.models import SignalSource as SignalSourceConst
from leia.sources.base import RawSignal

logger = logging.getLogger(__name__)

# Confirm this URL against Lusha's OpenAPI spec before the first real run.
_LUSHA_PROSPECTING_URL = "https://api.lusha.com/prospecting/contacts"

# Map common ICP geography labels to ISO-3166-1 alpha-2 codes that Lusha accepts.
_GEO_ISO2: dict[str, str] = {
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "northern ireland": "GB",
    "ireland": "IE",
    "republic of ireland": "IE",
    "united states": "US",
    "usa": "US",
    "us": "US",
    "canada": "CA",
    "germany": "DE",
    "france": "FR",
    "netherlands": "NL",
    "australia": "AU",
    "new zealand": "NZ",
}

_DEFAULT_SIGNAL_TYPES = ["promotion", "companyChange"]


def _to_iso2(geography: str) -> str | None:
    return _GEO_ISO2.get(geography.strip().lower())


def _extract_contacts(body: dict) -> list[dict]:
    """Defensive extraction: handles multiple possible Lusha response shapes."""
    data = (body or {}).get("data") or {}
    if isinstance(data, list):
        return data
    for key in ("contacts", "results", "items"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


def _contact_to_signal(contact: dict, source_name: str) -> RawSignal | None:
    """Normalize a Lusha contact dict into a RawSignal. Returns None if no usable name."""
    first = (contact.get("firstName") or contact.get("first_name") or "").strip()
    last = (contact.get("lastName") or contact.get("last_name") or "").strip()
    full_name = f"{first} {last}".strip()
    if not full_name:
        return None

    lusha_id = str(contact.get("id") or contact.get("contactId") or "").strip() or None
    linkedin_url = (
        contact.get("linkedinUrl")
        or contact.get("linkedInUrl")
        or contact.get("linkedin_url")
    )
    headline = (
        contact.get("jobTitle")
        or contact.get("currentJobTitle")
        or contact.get("job_title")
    )
    company_name = (
        contact.get("companyName")
        or contact.get("currentCompanyName")
        or contact.get("company_name")
    )

    raw: dict = {"lusha_id": lusha_id}
    if company_domain := contact.get("companyDomain") or contact.get("currentCompanyDomain"):
        raw["company_domain"] = company_domain

    return RawSignal(
        source=source_name,
        source_ref=lusha_id,
        full_name=full_name,
        headline=headline,
        company_name=company_name,
        linkedin_url=linkedin_url,
        raw=raw,
    )


def _icp_base_payload(icp: ICPConfig, page: int, page_size: int) -> dict:
    """Build the ICP-driven filter payload shared by both sources."""
    payload: dict = {"page": page, "page_size": page_size}

    if icp.titles:
        payload["jobTitles"] = icp.titles

    countries = [c for geo in icp.geographies if (c := _to_iso2(geo))]
    if countries:
        payload["countries"] = countries

    size = icp.company_size
    if size.min is not None or size.max is not None:
        entry: dict = {}
        if size.min is not None:
            entry["min"] = size.min
        if size.max is not None:
            entry["max"] = size.max
        payload["sizesFilterOption"] = [entry]

    # Industry names + keywords as a free-text relevance hint (structured industry IDs
    # require a filter-discovery call; searchText is the zero-setup fallback).
    hints = list(icp.industries) + list(icp.keywords)
    if hints:
        payload["searchText"] = " ".join(hints[:15])

    return payload


# ── Sources ────────────────────────────────────────────────────────────────


class LushaProspectingSource:
    """Discover contacts matching your ICP without a manual CSV.

    Calls Lusha's prospecting search and pages through results, filtering by
    job titles, countries, company size, and industry keywords from icp.yaml.
    """

    name = SignalSourceConst.LUSHA_PROSPECTING

    def __init__(
        self,
        api_key: str,
        icp: ICPConfig,
        *,
        max_results: int = 100,
        page_size: int = 25,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Lusha API key is required")
        self.api_key = api_key
        self.icp = icp
        self.max_results = max_results
        self.page_size = min(max(10, page_size), 50)  # Lusha enforces 10-50
        self.timeout = timeout

    def fetch(self) -> list[RawSignal]:
        headers = {"api_key": self.api_key, "Content-Type": "application/json"}
        signals: list[RawSignal] = []
        pages_needed = (self.max_results + self.page_size - 1) // self.page_size

        for page in range(pages_needed):
            if len(signals) >= self.max_results:
                break
            payload = _icp_base_payload(self.icp, page, self.page_size)
            try:
                resp = httpx.post(
                    _LUSHA_PROSPECTING_URL, json=payload, headers=headers, timeout=self.timeout
                )
                resp.raise_for_status()
                body = resp.json()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Lusha prospecting error (page %d): %s", page, exc)
                break

            contacts = _extract_contacts(body)
            if not contacts:
                break

            for c in contacts:
                if len(signals) >= self.max_results:
                    break
                sig = _contact_to_signal(c, self.name)
                if sig:
                    signals.append(sig)

        return signals


class LushaSignalsSource:
    """Discover contacts with recent buying-intent signals matching your ICP.

    Adds a ``signals`` filter to the prospecting search so only contacts who were
    recently promoted or changed company are returned. The signal types are stored
    in ``raw["signals"]`` and surface as ``signal_summary`` in Claude's scoring and
    drafting prompts for more personalized outreach.
    """

    name = SignalSourceConst.LUSHA_SIGNALS

    def __init__(
        self,
        api_key: str,
        icp: ICPConfig,
        *,
        days_back: int = 90,
        signal_types: list[str] | None = None,
        max_results: int = 100,
        page_size: int = 25,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Lusha API key is required")
        self.api_key = api_key
        self.icp = icp
        self.days_back = days_back
        self.signal_types = signal_types or _DEFAULT_SIGNAL_TYPES
        self.max_results = max_results
        self.page_size = min(max(10, page_size), 50)
        self.timeout = timeout

    def fetch(self) -> list[RawSignal]:
        start_date = (datetime.now(UTC) - timedelta(days=self.days_back)).strftime("%Y-%m-%d")
        headers = {"api_key": self.api_key, "Content-Type": "application/json"}
        signals: list[RawSignal] = []
        pages_needed = (self.max_results + self.page_size - 1) // self.page_size

        for page in range(pages_needed):
            if len(signals) >= self.max_results:
                break
            payload = _icp_base_payload(self.icp, page, self.page_size)
            payload["signals"] = {"names": self.signal_types, "startDate": start_date}

            try:
                resp = httpx.post(
                    _LUSHA_PROSPECTING_URL, json=payload, headers=headers, timeout=self.timeout
                )
                resp.raise_for_status()
                body = resp.json()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Lusha signals error (page %d): %s", page, exc)
                break

            contacts = _extract_contacts(body)
            if not contacts:
                break

            for c in contacts:
                if len(signals) >= self.max_results:
                    break
                sig = _contact_to_signal(c, self.name)
                if sig:
                    sig.raw["signals"] = self.signal_types
                    sig.raw["signal_start_date"] = start_date
                    signals.append(sig)

        return signals

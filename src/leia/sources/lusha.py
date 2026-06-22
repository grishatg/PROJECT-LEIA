"""Lusha signal sources: ICP-driven contact discovery and intent-signal detection.

Two sources share this file because both call the same Lusha prospecting endpoint —
the signals source adds a ``signals`` filter to narrow results to contacts who had a
recent buying-intent event (promotion, company change).

Endpoint (verified against the live API): POST https://api.lusha.com/v3/contacts/prospecting
Auth header: api_key. Body uses a nested ``filters.contacts.include`` shape with a
``pagination`` block. The prospecting search returns contact identity (name, title,
company, LinkedIn); emails are resolved separately by the enrichment stage.

Note: the ``signals`` filter requires Lusha's Signals add-on. When the account lacks it
the API rejects the property with a 400; the signals source detects this and degrades to
a plain prospecting search (still returns prospects) rather than failing the run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from leia.config import ICPConfig
from leia.models import SignalSource as SignalSourceConst
from leia.sources.base import RawSignal

logger = logging.getLogger(__name__)

_LUSHA_PROSPECTING_URL = "https://api.lusha.com/v3/contacts/prospecting"

# Map common ICP geography labels to the canonical country names the V3 API accepts.
_GEO_NAME: dict[str, str] = {
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "northern ireland": "United Kingdom",
    "ireland": "Ireland",
    "republic of ireland": "Ireland",
    "united states": "United States",
    "usa": "United States",
    "us": "United States",
    "canada": "Canada",
    "germany": "Germany",
    "france": "France",
    "netherlands": "Netherlands",
    "australia": "Australia",
    "new zealand": "New Zealand",
}

_DEFAULT_SIGNAL_TYPES = ["promotion", "companyChange"]

# Lusha's company-size filter matches against these fixed employee-count buckets;
# arbitrary min/max ranges silently return zero results. We map the ICP's range to
# whichever standard buckets overlap it. The open-ended top bucket has no max.
_SIZE_BUCKETS: list[tuple[int, int | None]] = [
    (1, 10),
    (11, 50),
    (51, 200),
    (201, 500),
    (501, 1000),
    (1001, 5000),
    (5001, 10000),
    (10001, None),
]


def _to_country(geography: str) -> str | None:
    return _GEO_NAME.get(geography.strip().lower())


def _size_buckets(min_size: int | None, max_size: int | None) -> list[dict]:
    """Return the standard Lusha size buckets overlapping the ICP's [min, max] range."""
    lo = min_size if min_size is not None else 0
    hi = max_size if max_size is not None else float("inf")
    out: list[dict] = []
    for bmin, bmax in _SIZE_BUCKETS:
        top = bmax if bmax is not None else float("inf")
        if top >= lo and bmin <= hi:
            out.append({"min": bmin} if bmax is None else {"min": bmin, "max": bmax})
    return out


def _extract_contacts(body: dict) -> list[dict]:
    """V3 returns matches under ``results``. Defensive against older shapes."""
    if not isinstance(body, dict):
        return []
    for key in ("results", "contacts", "items"):
        if isinstance(body.get(key), list):
            return body[key]
    data = body.get("data") or {}
    if isinstance(data, list):
        return data
    for key in ("contacts", "results", "items"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


def _first(*vals):
    for v in vals:
        if v:
            return v
    return None


def _contact_to_signal(contact: dict, source_name: str) -> RawSignal | None:
    """Normalize a Lusha V3 contact dict into a RawSignal. Returns None without a name."""
    first = (contact.get("firstName") or contact.get("first_name") or "").strip()
    last = (contact.get("lastName") or contact.get("last_name") or "").strip()
    full_name = f"{first} {last}".strip()
    if not full_name:
        return None

    lusha_id = str(contact.get("id") or contact.get("contactId") or "").strip() or None

    # jobTitle is an object in V3 ({"title": ...}) but tolerate a plain string.
    job = contact.get("jobTitle")
    if isinstance(job, dict):
        headline = job.get("title")
    else:
        headline = job or contact.get("currentJobTitle") or contact.get("job_title")

    # company is an object in V3 ({"name", "domain"}) but tolerate flat fields.
    company = contact.get("company")
    if isinstance(company, dict):
        company_name = company.get("name")
        company_domain = company.get("domain")
    else:
        company_name = _first(contact.get("companyName"), contact.get("currentCompanyName"))
        company_domain = _first(contact.get("companyDomain"), contact.get("currentCompanyDomain"))

    social = contact.get("socialLinks") or {}
    linkedin_url = _first(
        social.get("linkedin"),
        contact.get("linkedinUrl"),
        contact.get("linkedInUrl"),
        contact.get("linkedin_url"),
    )

    raw: dict = {"lusha_id": lusha_id}
    if company_domain:
        raw["company_domain"] = company_domain
    location = contact.get("location") or {}
    if isinstance(location, dict) and location.get("country"):
        raw["country"] = location["country"]

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
    """Build the V3 ICP-driven filter payload shared by both sources."""
    contacts_include: dict = {}

    if icp.titles:
        contacts_include["jobTitles"] = icp.titles

    countries = [c for geo in icp.geographies if (c := _to_country(geo))]
    if countries:
        # De-duplicate while preserving order (UK aliases collapse to one entry).
        seen: list[str] = []
        for c in countries:
            if c not in seen:
                seen.append(c)
        contacts_include["locations"] = [{"country": c} for c in seen]

    # Only surface contacts Lusha can reach by work email — keeps enrichment hit-rate high.
    contacts_include["existingDataPoints"] = ["work_email"]

    filters: dict = {"contacts": {"include": contacts_include}}

    size = icp.company_size
    if size.min is not None or size.max is not None:
        buckets = _size_buckets(size.min, size.max)
        if buckets:
            filters["companies"] = {"include": {"sizes": buckets}}

    return {"pagination": {"page": page, "size": page_size}, "filters": filters}


# ── Sources ────────────────────────────────────────────────────────────────


class LushaProspectingSource:
    """Discover contacts matching your ICP without a manual CSV.

    Calls Lusha's V3 prospecting search and pages through results, filtering by
    job titles, countries, and company size from icp.yaml.
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
        # Never request a larger page than we intend to keep — credits are charged
        # per result returned, so a --limit 3 run must not pull a full page of 25.
        self.page_size = min(self.page_size, max(10, max_results))
        self.timeout = timeout

    def _build_payload(self, page: int) -> dict:
        return _icp_base_payload(self.icp, page, self.page_size)

    def fetch(self) -> list[RawSignal]:
        headers = {"api_key": self.api_key, "Content-Type": "application/json"}
        signals: list[RawSignal] = []
        pages_needed = (self.max_results + self.page_size - 1) // self.page_size

        for page in range(pages_needed):
            if len(signals) >= self.max_results:
                break
            payload = self._build_payload(page)
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

    Adds a ``signals`` block to the prospecting search so only contacts who were
    recently promoted or changed company are returned. Requires Lusha's Signals
    add-on; if the account lacks it the API rejects the property and this source
    transparently degrades to a plain prospecting search.

    The requested signal types are recorded in ``raw["signals"]`` and surface as
    ``signal_summary`` in Claude's scoring and drafting prompts.
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
        self.page_size = min(self.page_size, max(10, max_results))
        self.timeout = timeout
        self._signals_unavailable = False

    def fetch(self) -> list[RawSignal]:
        start_date = (datetime.now(UTC) - timedelta(days=self.days_back)).strftime("%Y-%m-%d")
        headers = {"api_key": self.api_key, "Content-Type": "application/json"}
        signals: list[RawSignal] = []
        pages_needed = (self.max_results + self.page_size - 1) // self.page_size

        for page in range(pages_needed):
            if len(signals) >= self.max_results:
                break
            payload = _icp_base_payload(self.icp, page, self.page_size)
            # Signals live at the request body level (sibling to filters/pagination).
            if not self._signals_unavailable:
                payload["signals"] = {"names": self.signal_types, "startDate": start_date}

            try:
                resp = httpx.post(
                    _LUSHA_PROSPECTING_URL, json=payload, headers=headers, timeout=self.timeout
                )
                # If the plan lacks the Signals add-on, retry this page without it.
                if (
                    resp.status_code == 400
                    and not self._signals_unavailable
                    and "signals" in resp.text.lower()
                ):
                    logger.warning(
                        "Lusha Signals add-on not enabled; returning prospects without the "
                        "intent filter. Confirm the add-on to use lusha_signals fully."
                    )
                    self._signals_unavailable = True
                    payload.pop("signals", None)
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

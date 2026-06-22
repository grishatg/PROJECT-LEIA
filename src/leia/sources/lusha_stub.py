"""Deterministic stub sources for --dry-run and tests (no network, no Lusha credits).

Returns hardcoded UK energy contacts so the full pipeline can run offline.
"""

from __future__ import annotations

from leia.models import SignalSource as SignalSourceConst
from leia.sources.base import RawSignal

_SAMPLE_CONTACTS = [
    {
        "full_name": "Sarah Mitchell",
        "headline": "Head of Procurement",
        "company_name": "Octopus Energy",
        "linkedin_url": "https://www.linkedin.com/in/sarah-mitchell-procurement",
        "lusha_id": "stub-001",
        "company_domain": "octopusenergy.com",
    },
    {
        "full_name": "James Holloway",
        "headline": "Director of Energy Sourcing",
        "company_name": "SSE plc",
        "linkedin_url": "https://www.linkedin.com/in/james-holloway-sse",
        "lusha_id": "stub-002",
        "company_domain": "sse.com",
    },
    {
        "full_name": "Claire Donovan",
        "headline": "VP Sustainability & Procurement",
        "company_name": "National Grid",
        "linkedin_url": "https://www.linkedin.com/in/claire-donovan-ng",
        "lusha_id": "stub-003",
        "company_domain": "nationalgrid.com",
    },
    {
        "full_name": "Tom Reeves",
        "headline": "Energy Manager",
        "company_name": "British Gas",
        "linkedin_url": "https://www.linkedin.com/in/tom-reeves-bg",
        "lusha_id": "stub-004",
        "company_domain": "britishgas.co.uk",
    },
    {
        "full_name": "Niamh O'Sullivan",
        "headline": "Head of Net Zero Strategy",
        "company_name": "ESB Energy",
        "linkedin_url": "https://www.linkedin.com/in/niamh-osullivan-esb",
        "lusha_id": "stub-005",
        "company_domain": "esb.ie",
    },
]


class StubLushaProspectingSource:
    name = SignalSourceConst.LUSHA_PROSPECTING

    def fetch(self) -> list[RawSignal]:
        return [
            RawSignal(
                source=self.name,
                source_ref=c["lusha_id"],
                full_name=c["full_name"],
                headline=c["headline"],
                company_name=c["company_name"],
                linkedin_url=c["linkedin_url"],
                raw={"lusha_id": c["lusha_id"], "company_domain": c["company_domain"]},
            )
            for c in _SAMPLE_CONTACTS
        ]


class StubLushaSignalsSource:
    name = SignalSourceConst.LUSHA_SIGNALS

    def __init__(self, signal_types: list[str] | None = None) -> None:
        self.signal_types = signal_types or ["promotion", "companyChange"]

    def fetch(self) -> list[RawSignal]:
        return [
            RawSignal(
                source=self.name,
                source_ref=c["lusha_id"],
                full_name=c["full_name"],
                headline=c["headline"],
                company_name=c["company_name"],
                linkedin_url=c["linkedin_url"],
                raw={
                    "lusha_id": c["lusha_id"],
                    "company_domain": c["company_domain"],
                    "signals": self.signal_types,
                    "signal_start_date": "2026-03-23",
                },
            )
            for c in _SAMPLE_CONTACTS
        ]

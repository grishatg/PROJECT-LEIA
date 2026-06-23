"""Offline stubs for the UK discovery sources (Companies House + JobSpy).

Hardcoded UK signals with "why-now" triggers so the discovery sources can run in
--dry-run and tests with no network or API key.
"""

from __future__ import annotations

from leia.sources.base import RawSignal

_CH_SAMPLE = [
    {
        "full_name": "Eleanor Whitfield",
        "headline": "Director",
        "company_name": "Northmill Foods Ltd",
        "trigger": "new incorporation",
    },
    {
        "full_name": "Raj Patel",
        "headline": "Managing Director",
        "company_name": "Brightline Logistics Ltd",
        "trigger": "active UK company",
    },
]

_JOBSPY_SAMPLE = [
    {
        "company_name": "Pennine Cold Storage",
        "title": "Energy & Sustainability Manager",
    },
    {
        "company_name": "Halewood Beverages",
        "title": "Head of Procurement",
    },
]


class StubCompaniesHouseSource:
    name = "companies_house"

    def fetch(self) -> list[RawSignal]:
        return [
            RawSignal(
                source="companies_house",
                source_ref=f"stub-ch-{i}",
                full_name=c["full_name"],
                headline=c["headline"],
                company_name=c["company_name"],
                raw={"signals": [c["trigger"]]},
            )
            for i, c in enumerate(_CH_SAMPLE)
        ]


class StubJobSpySource:
    name = "jobspy"

    def fetch(self) -> list[RawSignal]:
        return [
            RawSignal(
                source="jobspy",
                source_ref=f"stub-jobspy-{i}",
                full_name=j["company_name"],
                headline=f"Hiring: {j['title']}",
                company_name=j["company_name"],
                raw={"signals": [f"hiring: {j['title']}"]},
            )
            for i, j in enumerate(_JOBSPY_SAMPLE)
        ]

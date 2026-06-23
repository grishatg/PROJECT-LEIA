"""Companies House (UK) discovery source — free public API.

Two-stage discovery (plan §G): find UK companies by SIC code / location /
incorporation recency, then emit their **officers** (named directors) as
RawSignals carrying a "why-now" trigger. Lusha enrichment then finds the buyer
contacts; the trigger flows through ``Signal.raw_json`` into the draft opener.

Free API, but rate-limited to 600 requests / 5 minutes — keep ``max_companies``
modest. Network failures degrade gracefully to an empty batch (never crash the run).
"""

from __future__ import annotations

import httpx

from leia.sources.base import RawSignal

_BASE = "https://api.company-information.service.gov.uk"


class CompaniesHouseSource:
    name = "companies_house"

    def __init__(
        self,
        api_key: str,
        *,
        sic_codes: list[str] | None = None,
        location: str | None = None,
        max_companies: int = 20,
        officers_per_company: int = 2,
        timeout: int = 20,
    ):
        self.api_key = api_key
        self.sic_codes = sic_codes or []
        self.location = location
        self.max_companies = max_companies
        self.officers_per_company = officers_per_company
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        # Companies House uses HTTP basic auth: API key as username, blank password.
        return httpx.Client(base_url=_BASE, auth=(self.api_key, ""), timeout=self.timeout)

    def fetch(self) -> list[RawSignal]:
        try:
            with self._client() as client:
                companies = self._search_companies(client)
                signals: list[RawSignal] = []
                for co in companies:
                    signals.extend(self._officers_as_signals(client, co))
                return signals
        except Exception:  # noqa: BLE001 - a source must never crash the pipeline
            return []

    def _search_companies(self, client: httpx.Client) -> list[dict]:
        params: dict = {"size": self.max_companies}
        if self.sic_codes:
            params["sic_codes"] = ",".join(self.sic_codes)
        if self.location:
            params["location"] = self.location
        r = client.get("/advanced-search/companies", params=params)
        r.raise_for_status()
        return r.json().get("items", [])

    def _officers_as_signals(self, client: httpx.Client, company: dict) -> list[RawSignal]:
        number = company.get("company_number")
        company_name = (company.get("company_name") or "").title()
        if not number:
            return []
        trigger = self._trigger(company)
        r = client.get(f"/company/{number}/officers", params={"items_per_page": 10})
        if r.status_code != 200:
            return []
        out: list[RawSignal] = []
        for officer in r.json().get("items", []):
            if officer.get("resigned_on"):
                continue
            name = _normalise_officer_name(officer.get("name", ""))
            if not name:
                continue
            out.append(
                RawSignal(
                    source="companies_house",
                    source_ref=f"{number}:{officer.get('officer_role', '')}",
                    full_name=name,
                    headline=(officer.get("officer_role") or "").replace("-", " ").title() or None,
                    company_name=company_name or None,
                    raw={
                        "company_number": number,
                        "sic_codes": company.get("sic_codes"),
                        "signals": [trigger] if trigger else [],
                    },
                )
            )
            if len(out) >= self.officers_per_company:
                break
        return out

    @staticmethod
    def _trigger(company: dict) -> str | None:
        date = company.get("date_of_creation")
        if date and date >= "2024-01-01":
            return "new incorporation"
        if company.get("company_status") == "active":
            return "active UK company"
        return None


def _normalise_officer_name(name: str) -> str:
    """Companies House returns 'SURNAME, Forename' — flip to 'Forename Surname'."""
    name = name.strip()
    if "," in name:
        surname, _, forename = name.partition(",")
        return f"{forename.strip().title()} {surname.strip().title()}".strip()
    return name.title()

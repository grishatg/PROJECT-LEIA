"""JobSpy hiring-signal source — public job postings as a "why-now" trigger.

Wraps the optional ``python-jobspy`` package (MIT) lazily: a hiring surge in an
ICP sector is a strong buying signal and far lower-risk than profile scraping.
The posting reveals the company + role; Lusha then finds the buyer contact.

``python-jobspy`` is a heavy dependency (pandas + scrapers), so it is NOT a hard
requirement — install it only if you use this source live. Dry-run / tests use
``StubJobSpySource``. If the package is missing, ``fetch`` returns an empty batch
with no crash.
"""

from __future__ import annotations

from leia.sources.base import RawSignal


class JobSpySource:
    name = "jobspy"

    def __init__(
        self,
        *,
        search_terms: list[str] | None = None,
        location: str = "United Kingdom",
        sites: list[str] | None = None,
        results: int = 20,
    ):
        self.search_terms = search_terms or ["energy manager"]
        self.location = location
        self.sites = sites or ["indeed", "linkedin"]
        self.results = results

    def fetch(self) -> list[RawSignal]:
        try:
            from jobspy import scrape_jobs  # type: ignore
        except Exception:  # noqa: BLE001 - optional dep; never crash the pipeline
            return []
        out: list[RawSignal] = []
        try:
            for term in self.search_terms:
                df = scrape_jobs(
                    site_name=self.sites,
                    search_term=term,
                    location=self.location,
                    results_wanted=self.results,
                )
                for _, row in df.iterrows():
                    company = str(row.get("company") or "").strip()
                    title = str(row.get("title") or "").strip()
                    if not company:
                        continue
                    out.append(
                        RawSignal(
                            source="jobspy",
                            source_ref=str(row.get("job_url") or "") or None,
                            # No named contact in a posting — the company is the unit;
                            # Lusha prospecting fans out to the buyer persona later.
                            full_name=company,
                            headline=f"Hiring: {title}" if title else "Hiring",
                            company_name=company,
                            raw={"signals": [f"hiring: {title}".strip()], "search_term": term},
                        )
                    )
        except Exception:  # noqa: BLE001
            return out
        return out

"""Read a CSV of prospects into RawSignals. The Phase-1 zero-risk source.

Accepts flexible/forgiving column names (case-insensitive). A ``full_name`` (or
``name``) column is the only hard requirement; everything else is optional.
"""

from __future__ import annotations

import csv
from pathlib import Path

from leia.models import SignalSource as SignalSourceConst
from leia.sources.base import RawSignal

# Map our fields to the column-name variants we'll accept from a CSV.
_ALIASES: dict[str, list[str]] = {
    "full_name": ["full_name", "name", "fullname", "full name"],
    "headline": ["headline", "title_headline", "summary"],
    "company_name": ["company_name", "company", "organization", "organisation"],
    "linkedin_url": ["linkedin_url", "linkedin", "profile_url", "linkedin profile"],
    "email": ["email", "email_address", "e-mail"],
}


def _pick(row: dict[str, str], field: str) -> str | None:
    for alias in _ALIASES[field]:
        if alias in row and row[alias] and row[alias].strip():
            return row[alias].strip()
    return None


class ManualCSVSource:
    name = SignalSourceConst.MANUAL_CSV

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch(self) -> list[RawSignal]:
        if not self.path.exists():
            raise FileNotFoundError(f"CSV not found: {self.path}")

        signals: list[RawSignal] = []
        with self.path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for raw_row in reader:
                # Normalize keys to lowercase/stripped so aliases match.
                row = {
                    (k or "").strip().lower(): (v or "") for k, v in raw_row.items() if k
                }
                full_name = _pick(row, "full_name")
                if not full_name:
                    continue  # skip rows with no person
                signals.append(
                    RawSignal(
                        source=self.name,
                        source_ref=str(self.path),
                        full_name=full_name,
                        headline=_pick(row, "headline"),
                        company_name=_pick(row, "company_name"),
                        linkedin_url=_pick(row, "linkedin_url"),
                        email=_pick(row, "email"),
                        raw=dict(row),
                    )
                )
        return signals

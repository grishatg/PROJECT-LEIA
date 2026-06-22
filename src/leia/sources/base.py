"""The SignalSource protocol. Implement this to add a new prospect source.

A source fetches raw signals (people + the event that surfaced them). Keep the
provider-specific code here, behind ``RawSignal``, so the pipeline never sees it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RawSignal(BaseModel):
    """A single buying-intent event normalized for the pipeline."""

    source: str
    source_ref: str | None = None
    full_name: str
    headline: str | None = None
    company_name: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    raw: dict = Field(default_factory=dict)


@runtime_checkable
class SignalSource(Protocol):
    name: str

    def fetch(self) -> list[RawSignal]:
        """Return the current batch of raw signals from this source."""
        ...

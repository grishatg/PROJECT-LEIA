"""Offline researcher for tests + dry-run: returns a fixed hook (or none)."""

from __future__ import annotations

from leia.research.base import ResearchHook
from leia.schemas import ProspectFacts


class StubResearcher:
    name = "stub"

    def __init__(self, hook: ResearchHook | None = None):
        self._hook = hook

    def find_hook(
        self,
        facts: ProspectFacts,
        *,
        signal_source: str | None = None,
        signal_raw: dict | None = None,
    ) -> ResearchHook | None:
        return self._hook

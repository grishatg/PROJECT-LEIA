"""Shared types + the Brain protocol.

A "brain" turns prospect facts into a score or a drafted message. There are two
implementations: ``LLMBrain`` (real Claude) and ``StubBrain`` (deterministic,
zero-cost, used for --dry-run and tests). The pipeline depends only on this
protocol, so it never cares which one it's using.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from leia.config import ICPConfig, ValuePropConfig
from leia.schemas import DraftResult, ProspectFacts, ScoreResult


class ScoreOutput(BaseModel):
    result: ScoreResult
    model_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


class DraftOutput(BaseModel):
    result: DraftResult
    model_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


@runtime_checkable
class Brain(Protocol):
    def score(
        self, facts: ProspectFacts, icp: ICPConfig, value_prop: ValuePropConfig
    ) -> ScoreOutput:
        """Score a prospect against the ICP + value proposition."""
        ...

    def draft(
        self,
        facts: ProspectFacts,
        value_prop: ValuePropConfig,
        guidelines: str,
        channel: str,
    ) -> DraftOutput:
        """Write a personalized message for the given channel."""
        ...

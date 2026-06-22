"""LLMBrain: parses tool-use structured output, sets caching + cost (offline)."""

from __future__ import annotations

import types

from leia.config import load_icp, load_value_prop
from leia.llm.client import LLMBrain
from leia.schemas import ProspectFacts


def _fake_response(
    tool_input: dict,
    tokens_in: int = 100,
    tokens_out: int = 20,
    cache_read: int = 0,
    cache_write: int = 0,
):
    block = types.SimpleNamespace(type="tool_use", input=tool_input)
    usage = types.SimpleNamespace(
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )
    return types.SimpleNamespace(content=[block], usage=usage)


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _brain(response):
    return LLMBrain(
        _FakeClient(response),
        brain_model="claude-opus-4-8",
        score_system_md="score system",
        draft_system_md="draft system",
    )


def test_score_parses_tool_use_and_costs():
    brain = _brain(
        _fake_response(
            {"score": 82, "tier": "A", "rationale": "Strong fit", "matched_criteria": ["industry"]}
        )
    )
    out = brain.score(ProspectFacts(full_name="Tom Riley"), load_icp(), load_value_prop())
    assert out.result.score == 82
    assert out.result.tier == "A"
    assert out.model_id == "claude-opus-4-8"
    assert out.cost_usd == 0.001

    kwargs = brain.client.messages.last_kwargs
    # Forced the structured tool, and set a cache breakpoint on the stable system prefix.
    assert kwargs["tool_choice"] == {"type": "tool", "name": "record_score"}
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_score_captures_cache_tokens_and_costs_them():
    brain = _brain(
        _fake_response(
            {"score": 50, "tier": "B", "rationale": "ok", "matched_criteria": []},
            tokens_in=100,
            tokens_out=20,
            cache_read=4000,
        )
    )
    out = brain.score(ProspectFacts(full_name="Tom Riley"), load_icp(), load_value_prop())
    assert out.cache_read_tokens == 4000
    assert out.cache_write_tokens == 0
    # 100 in + 20 out at $5/$25, plus 4000 cache-read at 0.1x of $5/MTok:
    # 0.0005 + 0.0005 + (4000/1e6)*5*0.1 = 0.001 + 0.002
    assert out.cost_usd == 0.003


def test_draft_parses_tool_use():
    brain = _brain(_fake_response({"subject": "quick idea", "body": "Hi Tom ..."}))
    out = brain.draft(
        ProspectFacts(full_name="Tom Riley"), load_value_prop(), "be brief", "email"
    )
    assert out.result.subject == "quick idea"
    assert out.result.body.startswith("Hi Tom")
    assert brain.client.messages.last_kwargs["tool_choice"]["name"] == "record_draft"

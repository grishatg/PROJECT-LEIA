"""The real brain: Claude via the Anthropic SDK.

Structured output is obtained with the tool-use pattern: we expose a single tool
whose input schema is the Pydantic model, and force the model to call it. This is
robust across SDK versions and yields a validated object, not free text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anthropic

from leia.config import ICPConfig, ValuePropConfig
from leia.llm.base import DraftOutput, ScoreOutput
from leia.llm.pricing import cost_usd
from leia.llm.prompts import render_draft_system, render_facts, render_score_system
from leia.schemas import DraftResult, ProspectFacts, ScoreResult

PROMPTS_DIR = Path("prompts")


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


class LLMBrain:
    """Real Claude brain. Inject an ``anthropic.Anthropic`` (or a fake in tests)."""

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        *,
        brain_model: str = "claude-opus-4-8",
        score_system_md: str | None = None,
        draft_system_md: str | None = None,
        max_tokens: int = 1024,
    ):
        self.client = client or anthropic.Anthropic()
        self.brain_model = brain_model
        self.max_tokens = max_tokens
        self._score_md = score_system_md if score_system_md is not None else _load_prompt(
            "score_system.md"
        )
        self._draft_md = draft_system_md if draft_system_md is not None else _load_prompt(
            "draft_system.md"
        )

    def _structured(
        self, *, system_text: str, user_text: str, schema_model: type, tool_name: str
    ) -> tuple[Any, Any]:
        tool = {
            "name": tool_name,
            "description": f"Record the {tool_name.replace('_', ' ')} result.",
            "input_schema": schema_model.model_json_schema(),
        }
        resp = self.client.messages.create(
            model=self.brain_model,
            max_tokens=self.max_tokens,
            # Stable, cacheable prefix in `system`; volatile per-lead facts in `messages`.
            # NOTE: Anthropic only caches a prefix once it clears the model minimum
            # (4096 tokens for Opus/Haiku, 2048 for Sonnet). Our rendered system
            # prompts sit well under that today, so this marker is a no-op until the
            # ICP / value-prop / guidelines prefix grows past the threshold. The
            # cache_read/write token fields below make it observable when it engages.
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_text}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
        )
        data = None
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                data = block.input
                break
        if data is None:
            raise RuntimeError(f"Model returned no structured '{tool_name}' tool call")
        return schema_model.model_validate(data), resp.usage

    def _usage_fields(self, usage: Any) -> dict:
        """Token + cache counts off the Anthropic usage object, plus the call cost.

        Shared by ``score`` and ``draft`` so metering lives in exactly one place.
        ``cache_*`` are absent on older usage objects, hence the defensive getattr.
        """
        ti, to = usage.input_tokens, usage.output_tokens
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
        return {
            "model_id": self.brain_model,
            "tokens_in": ti,
            "tokens_out": to,
            "cache_read_tokens": cr,
            "cache_write_tokens": cw,
            "cost_usd": cost_usd(self.brain_model, ti, to, cr, cw),
        }

    def score(
        self, facts: ProspectFacts, icp: ICPConfig, value_prop: ValuePropConfig
    ) -> ScoreOutput:
        system_text = render_score_system(self._score_md, icp, value_prop)
        result, usage = self._structured(
            system_text=system_text,
            user_text=render_facts(facts),
            schema_model=ScoreResult,
            tool_name="record_score",
        )
        return ScoreOutput(result=result, **self._usage_fields(usage))

    def draft(
        self,
        facts: ProspectFacts,
        value_prop: ValuePropConfig,
        guidelines: str,
        channel: str,
    ) -> DraftOutput:
        system_text = render_draft_system(self._draft_md, value_prop, guidelines, channel)
        result, usage = self._structured(
            system_text=system_text,
            user_text=render_facts(facts),
            schema_model=DraftResult,
            tool_name="record_draft",
        )
        return DraftOutput(result=result, **self._usage_fields(usage))

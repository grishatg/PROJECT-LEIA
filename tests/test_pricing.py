"""Cost helper."""

from __future__ import annotations

from leia.llm.pricing import cost_usd


def test_opus_cost():
    # 100 in + 20 out at $5/$25 per MTok = 0.0005 + 0.0005
    assert cost_usd("claude-opus-4-8", 100, 20) == 0.001


def test_stub_is_free():
    assert cost_usd("stub", 1000, 1000) == 0.0


def test_unknown_model_uses_default():
    assert cost_usd("mystery-model", 1_000_000, 0) == 5.0

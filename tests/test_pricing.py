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


def test_cache_read_is_discounted():
    # 1M cache-read tokens at 0.1x of $5/MTok = $0.50
    assert cost_usd("claude-opus-4-8", 0, 0, cache_read_tokens=1_000_000) == 0.5


def test_cache_write_is_premium():
    # 1M cache-write tokens at 1.25x of $5/MTok = $6.25
    assert cost_usd("claude-opus-4-8", 0, 0, cache_write_tokens=1_000_000) == 6.25

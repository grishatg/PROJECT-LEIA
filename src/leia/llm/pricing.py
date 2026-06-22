"""Claude model pricing + a cost helper, so every call's cost is recorded.

Prices are USD per 1,000,000 tokens (input, output). Update if Anthropic's
pricing changes. ``stub`` is free (the dry-run brain).
"""

from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "stub": (0.0, 0.0),
}

# Used when a model isn't in the table (be conservative: assume the priciest tier).
DEFAULT_PRICE = (5.0, 25.0)


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    in_price, out_price = PRICES.get(model, DEFAULT_PRICE)
    return round((tokens_in / 1_000_000) * in_price + (tokens_out / 1_000_000) * out_price, 6)

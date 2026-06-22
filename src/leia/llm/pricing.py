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

# Ephemeral (5-minute) prompt-cache multipliers, relative to the input rate:
# cache reads bill at ~0.1x, cache writes at ~1.25x.
CACHE_READ_MULT = 0.1
CACHE_WRITE_MULT = 1.25


def cost_usd(
    model: str,
    tokens_in: int,
    tokens_out: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """USD for one call.

    ``tokens_in`` is the *uncached* input remainder (billed at full rate); cache
    reads and writes bill separately at their discounted / premium rates.
    """
    in_price, out_price = PRICES.get(model, DEFAULT_PRICE)
    return round(
        (tokens_in / 1_000_000) * in_price
        + (tokens_out / 1_000_000) * out_price
        + (cache_read_tokens / 1_000_000) * in_price * CACHE_READ_MULT
        + (cache_write_tokens / 1_000_000) * in_price * CACHE_WRITE_MULT,
        6,
    )

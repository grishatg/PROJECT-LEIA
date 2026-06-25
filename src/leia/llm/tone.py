"""Tone presets + adjustments, shared by the Settings page and the Adjust-tone chips.

Kept in one place so the Settings "Default tone" dropdown, the drafting prompt, and the
Outreach "Adjust tone" buttons all speak the same language. Each value is a short nudge
appended to the writer's instructions — never a rewrite of Greg's voice, just a lean.
"""

from __future__ import annotations

# key -> (human label, prompt nudge). Order is the dropdown order; first is the default.
TONES: dict[str, tuple[str, str]] = {
    "warm_concise": (
        "Warm & concise",
        "Warm on the open, then concise and direct — Greg's default register.",
    ),
    "direct": ("Direct", "Lead with the point, minimal preamble, keep it short."),
    "friendly": ("Friendly", "A touch more relaxed and personable, conversational warmth."),
    "formal": ("Formal", "A little more buttoned-up and professional; no slang."),
}

DEFAULT_TONE = "warm_concise"

# Adjust-tone chips in the Outreach review queue -> the nudge applied on re-draft.
ADJUSTMENTS: dict[str, str] = {
    "warmer": "Rewrite it warmer and more personable, without going soft on the ask.",
    "shorter": "Rewrite it noticeably shorter — cut to the essentials, keep the hook and the ask.",
    "more_direct": "Rewrite it more direct — lead with the point and trim any hedging.",
}


def tone_nudge(key: str | None) -> str:
    """The prompt nudge for a tone key (empty string if unknown/None)."""
    if not key:
        return ""
    pair = TONES.get(key)
    return pair[1] if pair else ""


def tone_options() -> list[dict]:
    """[{value,label}] for the Settings dropdown, in display order."""
    return [{"value": k, "label": label} for k, (label, _) in TONES.items()]

"""Render system/user prompts for scoring and drafting (pure functions).

The system text is byte-stable across leads in a run (built only from static
config + prompt files), which is what lets Anthropic prompt-cache the big prefix.
Per-lead facts go in the user turn, after the cached prefix.
"""

from __future__ import annotations

from leia.config import ICPConfig, ValuePropConfig
from leia.schemas import ProspectFacts


def _join(items: list[str]) -> str:
    return ", ".join(items) if items else "(none specified)"


def render_icp_block(icp: ICPConfig) -> str:
    cs = icp.company_size
    size = f"{cs.min or 'any'} to {cs.max or 'any'} employees"
    return (
        f"Name: {icp.name}\n"
        f"Industries: {_join(icp.industries)}\n"
        f"Company size: {size}\n"
        f"Seniorities: {_join(icp.seniorities)}\n"
        f"Titles: {_join(icp.titles)}\n"
        f"Geographies: {_join(icp.geographies)}\n"
        f"Keywords: {_join(icp.keywords)}\n"
        f"Hard excludes: {_join(icp.exclude)}\n"
        f"Score threshold: {icp.score_threshold}"
    )


def render_value_prop_block(vp: ValuePropConfig) -> str:
    return (
        f"Offer: {vp.offer.strip()}\n"
        f"Proof points: {_join(vp.proof_points)}\n"
        f"Differentiators: {_join(vp.differentiators)}\n"
        f"Pain points: {_join(vp.pain_points)}\n"
        f"Call to action: {vp.cta}"
    )


def render_score_system(score_system_md: str, icp: ICPConfig, vp: ValuePropConfig) -> str:
    return (
        f"{score_system_md.strip()}\n\n"
        f"## Ideal Customer Profile\n{render_icp_block(icp)}\n\n"
        f"## Value proposition\n{render_value_prop_block(vp)}"
    )


def render_signature_block(vp: ValuePropConfig, channel: str) -> str:
    """Sign-off guidance. Email signs in full; LinkedIn stays short (first name)."""
    if channel == "email" and vp.signature:
        return (
            "\n\n## Email signature\n"
            "End the email with this exact sign-off block (after your closing line):\n"
            f"{vp.signature.strip()}"
        )
    if channel == "linkedin":
        return (
            "\n\n## Sign-off\n"
            "LinkedIn — keep it short and conversational. Sign with first name only "
            "('Greg'). Never paste the full email signature block."
        )
    return ""


def render_draft_system(
    draft_system_md: str, vp: ValuePropConfig, guidelines: str, channel: str
) -> str:
    return (
        f"{draft_system_md.strip()}\n\n"
        f"## Channel\n{channel}\n\n"
        f"## Value proposition\n{render_value_prop_block(vp)}\n\n"
        f"## Message guidelines\n{guidelines.strip()}"
        f"{render_signature_block(vp, channel)}"
    )


def render_converse_system(
    converse_system_md: str,
    vp: ValuePropConfig,
    guidelines: str,
    booking_url: str | None,
) -> str:
    booking = booking_url or "(no booking link configured — propose times in prose)"
    return (
        f"{converse_system_md.strip()}\n\n"
        f"## Booking link\n{booking}\n\n"
        f"## Value proposition\n{render_value_prop_block(vp)}\n\n"
        f"## Message guidelines\n{guidelines.strip()}"
    )


def render_history(history: list[dict], facts: ProspectFacts) -> str:
    """Render the conversation so far for the user turn (newest last)."""
    lines = [f"Conversation with {facts.full_name}"]
    if facts.company_name:
        lines[0] += f" ({facts.company_name})"
    lines.append("")
    for turn in history:
        who = "Them" if turn.get("direction") == "inbound" else "You"
        lines.append(f"{who}: {turn.get('body', '').strip()}")
    lines.append("\nWrite the next reply from You.")
    return "\n".join(lines)


def render_facts(facts: ProspectFacts) -> str:
    lines = [f"Full name: {facts.full_name}"]
    optional = [
        ("Headline", facts.headline),
        ("Company", facts.company_name),
        ("Title", facts.title),
        ("Seniority", facts.seniority),
        ("Industry", facts.industry),
        ("Country", facts.country),
        ("Company size", facts.company_size),
        ("Signal", facts.signal_summary),
    ]
    lines.extend(f"{label}: {value}" for label, value in optional if value)
    return "\n".join(lines)

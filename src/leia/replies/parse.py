"""Strip quoted history + signatures from an inbound email reply.

A lightweight, dependency-free parser so tests run offline and the hosted app
stays slim. `talon` (mailgun) is the heavier ML upgrade noted in the plan; this
covers the common cases — quoted history (``>`` lines, "On … wrote:" headers,
Outlook "From:" blocks) and trailing signatures — well enough to feed Claude the
*actual* reply text. LinkedIn (Unipile) messages arrive clean and need no parsing.
"""

from __future__ import annotations

import re

# "On Mon, 3 Jun 2026 at 14:02, Alex <a@x.com> wrote:" and localized variants.
_ON_WROTE = re.compile(r"\n?On .{0,200}? wrote:.*", re.IGNORECASE | re.DOTALL)
# Outlook / Gmail forwarded-header blocks.
_HEADER_BLOCK = re.compile(
    r"\n-{2,}\s*(Original Message|Forwarded message)\s*-{2,}.*", re.IGNORECASE | re.DOTALL
)
_FROM_BLOCK = re.compile(r"\n\s*From:\s.*\n\s*Sent:\s.*", re.IGNORECASE | re.DOTALL)

# Common signature delimiters; everything after the first match is dropped.
_SIG_DELIMS = (
    "\n-- \n",
    "\n--\n",
    "\nSent from my iPhone",
    "\nSent from my mobile",
    "\nGet Outlook for",
)
_SIG_OPENERS = re.compile(
    r"\n(?:Best|Kind regards|Regards|Many thanks|Thanks|Cheers|Sincerely|"
    r"Warm regards|All the best)[,!.]?\s*\n",
    re.IGNORECASE,
)

_OPT_OUT = re.compile(
    r"\b(unsubscribe|opt[\s-]?out|remove me|take me off|stop emailing|"
    r"do not (?:contact|email)|no longer interested|not interested)\b",
    re.IGNORECASE,
)


def clean_reply(raw: str | None) -> str:
    """Return just the new reply text: quoted history and signature removed."""
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    # Drop quoted-history blocks (keep whatever precedes them).
    for pat in (_ON_WROTE, _HEADER_BLOCK, _FROM_BLOCK):
        text = pat.sub("", text)

    # Drop lines that are purely quoted (start with ">").
    kept: list[str] = []
    for line in text.split("\n"):
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    text = "\n".join(kept)

    # Trim a trailing signature (first delimiter / sign-off wins).
    cut = len(text)
    for delim in _SIG_DELIMS:
        i = text.find(delim)
        if i != -1:
            cut = min(cut, i)
    m = _SIG_OPENERS.search(text)
    if m:
        cut = min(cut, m.start())
    text = text[:cut]

    return text.strip()


def looks_like_opt_out(text: str | None) -> bool:
    """Cheap pre-check for an unsubscribe/opt-out intent (before any LLM call)."""
    return bool(text and _OPT_OUT.search(text))

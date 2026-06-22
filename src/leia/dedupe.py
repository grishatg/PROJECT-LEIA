"""Canonicalization + idempotency keys (pure logic, no I/O).

The pipeline uses these to collapse duplicate signals/prospects and to make
re-running ingestion idempotent.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


def canonicalize_linkedin_url(url: str | None) -> str | None:
    """Normalize a LinkedIn profile URL so variants compare equal.

    Strips scheme differences, ``www.``/regional hosts, query/fragment, trailing
    slash, and lowercases. Returns None for empty input.

    >>> canonicalize_linkedin_url("http://uk.linkedin.com/in/JaneDoe/?trk=x")
    'https://linkedin.com/in/janedoe'
    """
    if not url or not url.strip():
        return None
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host.endswith("linkedin.com"):
        host = "linkedin.com"
    path = parsed.path.rstrip("/").lower()
    return urlunparse(("https", host, path, "", "", ""))


def normalize_email(email: str | None) -> str | None:
    if not email or not email.strip():
        return None
    return email.strip().lower()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def prospect_dedupe_key(
    *,
    linkedin_url: str | None = None,
    email: str | None = None,
    full_name: str | None = None,
    company_name: str | None = None,
) -> str:
    """A stable identity key for a prospect.

    Prefers LinkedIn URL, then email, then a name+company slug. The prefix
    (``li:``/``em:``/``nc:``) records which signal produced the identity.
    """
    canon = canonicalize_linkedin_url(linkedin_url)
    if canon:
        return f"li:{canon}"
    email_n = normalize_email(email)
    if email_n:
        return f"em:{email_n}"
    return f"nc:{_slug(full_name or '')}|{_slug(company_name or '')}"


def signal_dedupe_key(source: str, source_ref: str | None, identity: str) -> str:
    """A stable key for a raw signal (so re-ingesting the same event is a no-op)."""
    ref = (source_ref or "").strip().lower()
    return f"{source}:{ref}:{identity}"

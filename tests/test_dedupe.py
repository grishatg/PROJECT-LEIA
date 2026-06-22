"""Canonicalization + dedupe key logic."""

from __future__ import annotations

from leia.dedupe import (
    canonicalize_linkedin_url,
    normalize_email,
    prospect_dedupe_key,
    signal_dedupe_key,
)


def test_linkedin_url_variants_canonicalize_equal():
    a = canonicalize_linkedin_url("https://www.linkedin.com/in/JaneDoe/")
    b = canonicalize_linkedin_url("http://uk.linkedin.com/in/janedoe?trk=abc")
    c = canonicalize_linkedin_url("linkedin.com/in/janedoe")
    assert a == b == c == "https://linkedin.com/in/janedoe"


def test_canonicalize_empty_is_none():
    assert canonicalize_linkedin_url(None) is None
    assert canonicalize_linkedin_url("   ") is None


def test_normalize_email():
    assert normalize_email("  Jane@Acme.COM ") == "jane@acme.com"
    assert normalize_email(None) is None
    assert normalize_email("") is None


def test_dedupe_key_prefers_linkedin():
    key = prospect_dedupe_key(
        linkedin_url="https://www.linkedin.com/in/janedoe/",
        email="Jane@Acme.com",
        full_name="Jane Doe",
        company_name="Acme",
    )
    assert key == "li:https://linkedin.com/in/janedoe"


def test_dedupe_key_email_fallback():
    key = prospect_dedupe_key(email="Jane@Acme.com", full_name="Jane", company_name="Acme")
    assert key == "em:jane@acme.com"


def test_dedupe_key_name_company_fallback():
    key = prospect_dedupe_key(full_name="Jane Doe", company_name="Acme Energy")
    assert key == "nc:jane-doe|acme-energy"


def test_signal_dedupe_key_is_stable():
    k1 = signal_dedupe_key("apify_linkedin", "https://x/POST", "li:https://linkedin.com/in/j")
    k2 = signal_dedupe_key("apify_linkedin", "https://x/post", "li:https://linkedin.com/in/j")
    assert k1 == k2  # source_ref is lowercased for stability

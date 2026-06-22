"""ApifyLinkedInSource: field normalisation, HTTP fetch, guard rails."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from leia.sources.apify_linkedin import ApifyLinkedInSource, _extract_fields  # noqa: I001

# ── _extract_fields unit tests (pure function, no network) ────────────────────


def test_extract_standard_scraper_output():
    """apify/linkedin-profile-scraper style keys."""
    item = {
        "firstName": "Jane",
        "lastName": "Carter",
        "headline": "VP Sales at Northwind",
        "profileUrl": "https://linkedin.com/in/janecarter",
        "currentPositionCompanyName": "Northwind",
    }
    f = _extract_fields(item)
    assert f["full_name"] == "Jane Carter"
    assert f["headline"] == "VP Sales at Northwind"
    assert f["company_name"] == "Northwind"
    assert f["linkedin_url"] == "https://linkedin.com/in/janecarter"
    assert f["email"] is None


def test_extract_flat_name_fields():
    """Some scrapers return full_name / name / url directly."""
    item = {"name": "Tom Riley", "company_name": "GridCo", "url": "https://linkedin.com/in/tom"}
    f = _extract_fields(item)
    assert f["full_name"] == "Tom Riley"
    assert f["company_name"] == "GridCo"
    assert f["linkedin_url"] == "https://linkedin.com/in/tom"


def test_extract_experiences_fallback():
    """Company from experiences[] when no currentPosition field."""
    item = {
        "full_name": "Alex Smith",
        "experiences": [{"companyName": "Acme"}, {"companyName": "OldCo"}],
    }
    f = _extract_fields(item)
    assert f["company_name"] == "Acme"


def test_extract_email_surfaced():
    item = {"full_name": "Dana Lee", "emailAddress": "dana@acme.com"}
    f = _extract_fields(item)
    assert f["email"] == "dana@acme.com"


def test_extract_all_missing_returns_nones():
    f = _extract_fields({})
    assert f["full_name"] is None
    assert f["company_name"] is None
    assert f["linkedin_url"] is None


# ── ApifyLinkedInSource.fetch() (HTTP mocked) ─────────────────────────────────


def _mock_response(items: list[dict], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = items
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_returns_signals():
    items = [
        {
            "firstName": "Jane",
            "lastName": "Carter",
            "headline": "VP Sales",
            "profileUrl": "https://linkedin.com/in/jane",
            "currentPositionCompanyName": "Acme",
        }
    ]
    with patch("leia.sources.apify_linkedin.httpx.get", return_value=_mock_response(items)):
        signals = ApifyLinkedInSource("tok", "ds1").fetch()
    assert len(signals) == 1
    s = signals[0]
    assert s.full_name == "Jane Carter"
    assert s.headline == "VP Sales"
    assert s.source == "apify_linkedin"
    assert s.source_ref == "apify:ds1"


def test_fetch_skips_items_with_no_identity():
    items = [
        {},  # nothing useful
        {"firstName": "Jo"},  # name only — no linkedin_url → still kept (full_name set)
        {"profileUrl": "https://linkedin.com/in/anon"},  # URL only → kept
    ]
    with patch("leia.sources.apify_linkedin.httpx.get", return_value=_mock_response(items)):
        signals = ApifyLinkedInSource("tok", "ds1").fetch()
    # empty item dropped; name-only and url-only kept
    assert len(signals) == 2


def test_fetch_raises_on_http_error():
    import httpx as _httpx

    resp = MagicMock()
    resp.status_code = 401
    resp.text = "Unauthorized"
    resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "401", request=MagicMock(), response=resp
    )
    with patch("leia.sources.apify_linkedin.httpx.get", return_value=resp):
        with pytest.raises(RuntimeError, match="401"):
            ApifyLinkedInSource("bad_tok", "ds1").fetch()


def test_constructor_requires_token():
    with pytest.raises(ValueError, match="APIFY_TOKEN"):
        ApifyLinkedInSource("", "ds1")


def test_constructor_requires_dataset():
    with pytest.raises(ValueError, match="--dataset"):
        ApifyLinkedInSource("tok", "")

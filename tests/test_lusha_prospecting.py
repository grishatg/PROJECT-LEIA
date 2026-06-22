"""Tests for the Lusha prospecting and signals sources.

All tests run offline (httpx calls are monkeypatched). No real network, no credits.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from leia.config import CompanySize, ICPConfig
from leia.sources.lusha import (
    LushaProspectingSource,
    LushaSignalsSource,
    _icp_base_payload,
    _size_buckets,
)
from leia.sources.lusha_stub import StubLushaProspectingSource, StubLushaSignalsSource


@pytest.fixture()
def icp() -> ICPConfig:
    return ICPConfig(
        name="Test ICP",
        version=1,
        industries=["Renewable energy", "Utilities"],
        company_size=CompanySize(min=50, max=5000),
        seniorities=["Director", "VP", "Head"],
        titles=["Head of Procurement", "Energy Manager"],
        geographies=["United Kingdom", "Ireland"],
        keywords=["net zero", "solar"],
    )


# ── Payload builder ────────────────────────────────────────────────────────


def _include(payload: dict) -> dict:
    return payload["filters"]["contacts"]["include"]


def test_icp_base_payload_titles(icp):
    payload = _icp_base_payload(icp, page=0, page_size=25)
    assert _include(payload)["jobTitles"] == ["Head of Procurement", "Energy Manager"]


def test_icp_base_payload_countries(icp):
    payload = _icp_base_payload(icp, page=0, page_size=25)
    countries = {loc["country"] for loc in _include(payload)["locations"]}
    assert countries == {"United Kingdom", "Ireland"}


def test_icp_base_payload_size(icp):
    # min=50, max=5000 overlaps Lusha buckets 11-50 through 1001-5000.
    payload = _icp_base_payload(icp, page=0, page_size=25)
    assert payload["filters"]["companies"]["include"]["sizes"] == [
        {"min": 11, "max": 50},
        {"min": 51, "max": 200},
        {"min": 201, "max": 500},
        {"min": 501, "max": 1000},
        {"min": 1001, "max": 5000},
    ]


def test_size_buckets_overlap():
    assert _size_buckets(50, 5000) == [
        {"min": 11, "max": 50},
        {"min": 51, "max": 200},
        {"min": 201, "max": 500},
        {"min": 501, "max": 1000},
        {"min": 1001, "max": 5000},
    ]
    # Open-ended top bucket has no max.
    assert {"min": 10001} in _size_buckets(20000, None)
    # A tiny range maps to a single bucket.
    assert _size_buckets(60, 90) == [{"min": 51, "max": 200}]


def test_icp_base_payload_requires_work_email(icp):
    payload = _icp_base_payload(icp, page=0, page_size=25)
    assert _include(payload)["existingDataPoints"] == ["work_email"]


def test_icp_base_payload_pagination(icp):
    payload = _icp_base_payload(icp, page=2, page_size=20)
    assert payload["pagination"]["page"] == 2
    assert payload["pagination"]["size"] == 20


def test_icp_base_payload_no_size_when_unset():
    icp_no_size = ICPConfig(name="X", titles=["CEO"], geographies=["UK"])
    payload = _icp_base_payload(icp_no_size, page=0, page_size=25)
    assert "companies" not in payload["filters"]


def test_icp_base_payload_unknown_geo_skipped():
    icp_unknown = ICPConfig(name="X", geographies=["Narnia", "United Kingdom"])
    payload = _icp_base_payload(icp_unknown, page=0, page_size=25)
    assert _include(payload)["locations"] == [{"country": "United Kingdom"}]


def test_icp_base_payload_uk_aliases_dedupe():
    icp_dupes = ICPConfig(name="X", geographies=["UK", "England", "Scotland"])
    payload = _icp_base_payload(icp_dupes, page=0, page_size=25)
    assert _include(payload)["locations"] == [{"country": "United Kingdom"}]


# ── LushaProspectingSource ─────────────────────────────────────────────────


def _make_response(contacts: list[dict], status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {"results": contacts}
    mock.raise_for_status = MagicMock()
    return mock


_SAMPLE_CONTACT = {
    "id": "v1.abc123",
    "firstName": "Jane",
    "lastName": "Smith",
    "jobTitle": {"title": "Head of Procurement", "seniority": "director"},
    "company": {"name": "Acme Energy", "domain": "acmeenergy.com"},
    "socialLinks": {"linkedin": "https://linkedin.com/in/janesmith"},
    "location": {"country": "United Kingdom"},
}


def test_prospecting_source_returns_signals(icp):
    with patch("httpx.post", return_value=_make_response([_SAMPLE_CONTACT])):
        source = LushaProspectingSource("test-key", icp, max_results=5)
        signals = source.fetch()

    assert len(signals) == 1
    s = signals[0]
    assert s.full_name == "Jane Smith"
    assert s.headline == "Head of Procurement"
    assert s.company_name == "Acme Energy"
    assert s.linkedin_url == "https://linkedin.com/in/janesmith"
    assert s.source == "lusha_prospecting"
    assert s.raw["lusha_id"] == "v1.abc123"
    assert s.raw["company_domain"] == "acmeenergy.com"


def test_prospecting_source_skips_nameless_contacts(icp):
    nameless = {"id": "v1.xyz", "firstName": "", "lastName": "", "companyName": "X"}
    with patch("httpx.post", return_value=_make_response([nameless, _SAMPLE_CONTACT])):
        source = LushaProspectingSource("test-key", icp, max_results=5)
        signals = source.fetch()

    assert len(signals) == 1
    assert signals[0].full_name == "Jane Smith"


def test_prospecting_source_stops_on_empty_page(icp):
    responses = [_make_response([_SAMPLE_CONTACT]), _make_response([])]
    with patch("httpx.post", side_effect=responses):
        source = LushaProspectingSource("test-key", icp, max_results=50, page_size=10)
        signals = source.fetch()

    assert len(signals) == 1


def test_prospecting_source_degrades_on_http_error(icp):
    mock = MagicMock()
    mock.raise_for_status.side_effect = Exception("HTTP 429")
    with patch("httpx.post", return_value=mock):
        source = LushaProspectingSource("test-key", icp)
        signals = source.fetch()

    assert signals == []


def test_prospecting_source_respects_max_results(icp):
    contacts = [
        {**_SAMPLE_CONTACT, "id": f"v1.{i}", "firstName": f"Person{i}", "lastName": "Test"}
        for i in range(30)
    ]
    with patch("httpx.post", return_value=_make_response(contacts)):
        source = LushaProspectingSource("test-key", icp, max_results=5, page_size=10)
        signals = source.fetch()

    assert len(signals) == 5


def test_prospecting_page_size_clamped(icp):
    source = LushaProspectingSource("key", icp, page_size=3)
    assert source.page_size == 10  # clamped to Lusha min

    source2 = LushaProspectingSource("key", icp, page_size=99)
    assert source2.page_size == 50  # clamped to Lusha max


# ── LushaSignalsSource ─────────────────────────────────────────────────────


def test_signals_source_includes_signal_types_in_raw(icp):
    with patch("httpx.post", return_value=_make_response([_SAMPLE_CONTACT])):
        source = LushaSignalsSource("test-key", icp, signal_types=["promotion"])
        signals = source.fetch()

    assert signals[0].raw["signals"] == ["promotion"]
    assert "signal_start_date" in signals[0].raw


def test_signals_source_payload_includes_signals_filter(icp):
    captured = {}

    def capture(url, json, **kwargs):
        captured["payload"] = json
        return _make_response([])

    with patch("httpx.post", side_effect=capture):
        source = LushaSignalsSource("test-key", icp, signal_types=["promotion", "companyChange"])
        source.fetch()

    assert "signals" in captured["payload"]
    assert captured["payload"]["signals"]["names"] == ["promotion", "companyChange"]
    assert "startDate" in captured["payload"]["signals"]


def test_signals_source_uses_lusha_signals_source_name(icp):
    with patch("httpx.post", return_value=_make_response([_SAMPLE_CONTACT])):
        source = LushaSignalsSource("test-key", icp)
        signals = source.fetch()

    assert signals[0].source == "lusha_signals"


# ── Stubs ──────────────────────────────────────────────────────────────────


def test_stub_prospecting_returns_five_contacts():
    signals = StubLushaProspectingSource().fetch()
    assert len(signals) == 5
    assert all(s.source == "lusha_prospecting" for s in signals)
    assert all(s.full_name for s in signals)
    assert all(s.raw.get("lusha_id") for s in signals)


def test_stub_signals_returns_five_contacts_with_signal_metadata():
    signals = StubLushaSignalsSource().fetch()
    assert len(signals) == 5
    assert all(s.source == "lusha_signals" for s in signals)
    assert all("signals" in s.raw for s in signals)
    assert all("signal_start_date" in s.raw for s in signals)


def test_stub_signals_custom_signal_types():
    signals = StubLushaSignalsSource(signal_types=["promotion"]).fetch()
    assert signals[0].raw["signals"] == ["promotion"]

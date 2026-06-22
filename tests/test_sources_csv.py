"""ManualCSVSource: flexible columns, skips rows with no person."""

from __future__ import annotations

import pytest

from leia.sources.manual_csv import ManualCSVSource


def test_reads_standard_columns(tmp_path):
    csv = tmp_path / "p.csv"
    csv.write_text(
        "full_name,company,linkedin_url,email\n"
        "Jane Carter,Northwind,https://linkedin.com/in/jane,jane@northwind.com\n",
        encoding="utf-8",
    )
    signals = ManualCSVSource(csv).fetch()
    assert len(signals) == 1
    s = signals[0]
    assert s.full_name == "Jane Carter"
    assert s.company_name == "Northwind"
    assert s.email == "jane@northwind.com"
    assert s.source == "manual_csv"


def test_alias_and_case_insensitive_headers(tmp_path):
    csv = tmp_path / "p.csv"
    csv.write_text("Name,Organisation\nTom Riley,GridCo\n", encoding="utf-8")
    signals = ManualCSVSource(csv).fetch()
    assert signals[0].full_name == "Tom Riley"
    assert signals[0].company_name == "GridCo"


def test_skips_rows_without_name(tmp_path):
    csv = tmp_path / "p.csv"
    csv.write_text("full_name,company\n,Acme\nReal Person,Acme\n", encoding="utf-8")
    signals = ManualCSVSource(csv).fetch()
    assert len(signals) == 1
    assert signals[0].full_name == "Real Person"


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ManualCSVSource(tmp_path / "nope.csv").fetch()


def test_sample_fixture_loads():
    signals = ManualCSVSource("data/fixtures/contacts.sample.csv").fetch()
    assert len(signals) == 5

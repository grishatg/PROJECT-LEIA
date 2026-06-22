"""StubEnricher: synthesize a best-guess email from name + company."""

from __future__ import annotations

from leia.enrichment.base import EnrichmentQuery
from leia.enrichment.stub import StubEnricher


def test_synthesizes_email():
    res = StubEnricher().enrich(
        EnrichmentQuery(full_name="Jane Carter", company_name="Northwind Utilities")
    )
    assert res.email == "jane.carter@northwindutilities.com"
    assert res.email_status == "guess"
    assert res.provider == "stub"


def test_no_company_no_email():
    res = StubEnricher().enrich(EnrichmentQuery(full_name="Jane Carter"))
    assert res.email is None
    assert res.email_status == "none"


def test_explicit_domain_used():
    res = StubEnricher().enrich(
        EnrichmentQuery(full_name="Tom Riley", company_name="GridCo", domain="grid.co")
    )
    assert res.email == "tom.riley@grid.co"

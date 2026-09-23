from datetime import date

from ted_procurement_mcp.models import TedSearchRequest
from ted_procurement_mcp.query_builder import (
    build_procurement_query,
    normalise_country_codes,
)


def test_normalise_country_codes_accepts_iso2_and_iso3():
    assert normalise_country_codes(["DE", "FRA", "pl"]) == ["DEU", "FRA", "POL"]


def test_build_procurement_query_combines_filters():
    query = build_procurement_query(
        keywords="GPS tracker",
        cpv_codes=["32522000", "302*"],
        buyer_countries=["DE", "FR"],
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 16),
        form_type="competition",
    )
    assert 'FT ~ (GPS tracker)' in query
    assert 'classification-cpv = (32522000 OR 302*)' in query
    assert 'buyer-country IN (DEU FRA)' in query
    assert 'publication-date = (20260901 <> 20260916)' in query
    assert 'form-type = competition' in query


def test_build_procurement_query_escapes_parentheses_and_quotes():
    query = build_procurement_query(keywords='smart "GPS" (dog)')
    assert 'FT ~ (smart GPS dog)' in query


def test_search_request_serializes_ted_camel_case_fields():
    req = TedSearchRequest(
        query="OJ = ()",
        fields=["publication-number"],
        page=2,
        limit=50,
        pagination_mode="ITERATION",
        iteration_next_token="abc",
    )
    payload = req.to_payload()
    assert payload["paginationMode"] == "ITERATION"
    assert payload["iterationNextToken"] == "abc"
    assert payload["onlyLatestVersions"] is True
    assert payload["checkQuerySyntax"] is False
    assert payload["page"] == 2
    assert payload["limit"] == 50


def test_search_request_rejects_page_size_over_250():
    try:
        TedSearchRequest(query="OJ = ()", fields=["publication-number"], limit=251)
    except ValueError as exc:
        assert "250" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_search_request_rejects_invalid_scope():
    try:
        TedSearchRequest(query="OJ = ()", fields=["publication-number"], scope="ARCHIVE")
    except ValueError as exc:
        assert "scope" in str(exc).lower()
    else:
        raise AssertionError("expected validation error")


def test_search_request_rejects_field_page_budget_over_10000():
    fields = [f"field-{i}" for i in range(41)]
    try:
        TedSearchRequest(query="OJ = ()", fields=fields, limit=250)
    except ValueError as exc:
        assert "10,000" in str(exc)
    else:
        raise AssertionError("expected validation error")

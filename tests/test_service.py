import asyncio
from datetime import date

from ted_procurement_mcp.service import ProcurementService


class FakeTedClient:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def search(self, request):
        self.requests.append(request)
        return self.payload


def run(coro):
    return asyncio.run(coro)


def test_get_notice_builds_exact_query_and_normalizes():
    client = FakeTedClient({
        "totalNoticeCount": 1,
        "notices": [{
            "publication-number": "123456-2026",
            "notice-title": {"eng": "Test notice"},
            "buyer-name": "Buyer A",
        }],
    })
    service = ProcurementService(client)
    result = run(service.get_notice("123456-2026"))

    assert client.requests[0].query == "publication-number = 123456-2026"
    assert client.requests[0].only_latest_versions is False
    assert result["notice"]["title"] == "Test notice"


def test_find_buyers_aggregates_same_buyer():
    client = FakeTedClient({
        "totalNoticeCount": 2,
        "notices": [
            {
                "publication-number": "1-2026",
                "publication-date": "2026-09-10",
                "notice-title": {"eng": "GPS devices"},
                "buyer-name": "City Alpha",
                "buyer-country": "DEU",
                "buyer-email": "buy@alpha.example",
            },
            {
                "publication-number": "2-2026",
                "publication-date": "2026-09-15",
                "notice-title": {"eng": "More GPS devices"},
                "buyer-name": "City Alpha",
                "buyer-country": "DEU",
            },
        ],
    })
    service = ProcurementService(client)
    result = run(service.find_buyers(product="GPS", limit=20))

    assert result["buyers"][0]["buyer_name"] == "City Alpha"
    assert result["buyers"][0]["notice_count"] == 2
    assert result["buyers"][0]["latest_publication_date"] == "2026-09-15"
    assert result["buyers"][0]["buyer_emails"] == ["buy@alpha.example"]
    assert result["reported_total_matches"] == 2
    assert result["analysed_notice_count"] == 2


def test_find_awards_uses_result_form_and_surfaces_winner():
    client = FakeTedClient({
        "totalNoticeCount": 1,
        "notices": [{
            "publication-number": "3-2026",
            "notice-title": {"eng": "Award GPS"},
            "form-type": "result",
            "winner-name": {"eng": "Supplier One"},
            "winner-country": "FRA",
        }],
    })
    service = ProcurementService(client)
    result = run(service.find_awards(product="GPS", limit=10))

    assert "form-type = result" in client.requests[0].query
    assert client.requests[0].scope == "ALL"
    assert result["awards"][0]["winner_names"] == ["Supplier One"]


def test_market_stats_aggregates_notice_dimensions_and_values():
    client = FakeTedClient({
        "totalNoticeCount": 2,
        "notices": [
            {
                "publication-number": "4-2026",
                "buyer-country": "DEU",
                "buyer-name": "Buyer A",
                "classification-cpv": "32522000",
                "form-type": "competition",
                "estimated-value-proc": 1000,
                "estimated-value-cur-proc": "EUR",
            },
            {
                "publication-number": "5-2026",
                "buyer-country": "FRA",
                "buyer-name": "Buyer B",
                "classification-cpv": "32522000",
                "form-type": "competition",
                "estimated-value-proc": 2500,
                "estimated-value-cur-proc": "EUR",
            },
        ],
    })
    service = ProcurementService(client)
    result = run(service.market_stats(product="GPS", limit=100))

    assert result["notice_count"] == 2
    assert result["by_country"] == {"DEU": 1, "FRA": 1}
    assert result["by_cpv"] == {"32522000": 2}
    assert result["reported_estimated_values_by_currency"] == {"EUR": 3500.0}


def test_find_opportunities_scores_and_sorts_descending():
    client = FakeTedClient({
        "totalNoticeCount": 2,
        "notices": [
            {
                "publication-number": "6-2026",
                "publication-date": "2026-09-15",
                "notice-title": {"eng": "GPS tracker purchase"},
                "buyer-country": "DEU",
                "classification-cpv": "32522000",
                "form-type": "competition",
                "deadline-receipt-tender-date-lot": "2026-10-15",
            },
            {
                "publication-number": "7-2026",
                "publication-date": "2026-08-01",
                "notice-title": {"eng": "General electronics"},
                "buyer-country": "FRA",
                "classification-cpv": "30000000",
                "form-type": "competition",
            },
        ],
    })
    service = ProcurementService(client)
    result = run(service.find_opportunities(
        product="GPS tracker",
        cpv_codes=["32522000"],
        countries=["DE"],
        days=60,
        limit=20,
        today=date(2026, 9, 16),
    ))

    assert "form-type = competition" in client.requests[0].query
    assert client.requests[0].scope == "ACTIVE"
    assert result["opportunities"][0]["publication_number"] == "6-2026"
    assert result["opportunities"][0]["opportunity_score"] == 100
    assert result["opportunities"][0]["score_components"]["cpv_match"] == 25


def test_raw_ted_search_can_request_syntax_validation():
    client = FakeTedClient({"notices": [], "totalNoticeCount": None})
    service = ProcurementService(client)
    run(service.raw_ted_search(
        query="FT ~ GPS",
        fields=["publication-number"],
        check_query_syntax=True,
    ))
    assert client.requests[0].check_query_syntax is True

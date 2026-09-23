import asyncio
from datetime import date

from ted_procurement_mcp.cpv_discovery import CpvDiscoveryService


class FakeTedClient:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def search(self, request):
        self.requests.append(request)
        return self.payload


def run(coro):
    return asyncio.run(coro)


def test_suggest_cpv_ranks_frequency_and_keeps_samples():
    client = FakeTedClient({
        "totalNoticeCount": 3,
        "notices": [
            {"publication-number": "1-2026", "publication-date": "2026-09-10", "notice-title": {"eng": "GPS trackers"}, "classification-cpv": ["32522000", "38112100"]},
            {"publication-number": "2-2026", "publication-date": "2026-09-11", "notice-title": {"eng": "Vehicle GPS"}, "classification-cpv": "32522000"},
            {"publication-number": "3-2026", "publication-date": "2026-09-12", "notice-title": {"eng": "Positioning devices"}, "classification-cpv": "38112100"},
        ],
    })
    service = CpvDiscoveryService(client)
    result = run(service.suggest("GPS tracker", countries=["DE"], days=90, limit=50, today=date(2026, 9, 16)))

    assert result["suggestions"][0]["cpv_code"] == "32522000"
    assert result["suggestions"][0]["support_count"] == 2
    assert len(result["suggestions"][0]["sample_notices"]) == 2
    assert "buyer-country" in client.requests[0].query
    assert result["method"] == "TED notice frequency inference"


def test_suggest_cpv_handles_no_matching_codes():
    client = FakeTedClient({"totalNoticeCount": 0, "notices": []})
    result = run(CpvDiscoveryService(client).suggest("rare widget"))
    assert result["suggestions"] == []
    assert result["analysed_notice_count"] == 0

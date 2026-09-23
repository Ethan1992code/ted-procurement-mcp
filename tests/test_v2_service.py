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


class MemoryStore:
    def __init__(self):
        self.profiles = {}
        self.notices = []
        self.state = {}

    def upsert_supplier_profile(self, profile):
        self.profiles[profile["profile_id"]] = profile

    def get_supplier_profile(self, profile_id):
        return self.profiles.get(profile_id)

    def list_notices_since(self, date_from, *, limit=1000):
        return [n for n in self.notices if (n.get("publication_date") or "") >= date_from][:limit]

    def upsert_notices(self, notices):
        self.notices.extend(notices)
        return len(notices)

    def get_sync_state(self, key):
        return self.state.get(key)

    def set_sync_state(self, key, token):
        self.state[key] = token

    def stats(self):
        return {"backend": "memory", "notice_count": len(self.notices), "supplier_profile_count": len(self.profiles), "latest_publication_date": None}


def run(coro):
    return asyncio.run(coro)


def test_v2_service_profile_round_trip_and_daily_feed():
    store = MemoryStore()
    service = ProcurementService(FakeTedClient({"notices": []}), store=store)
    profile = run(service.upsert_supplier_profile(
        profile_id="gps-factory",
        products=["GPS tracker"],
        cpv_codes=["32522000"],
        target_countries=["DE"],
        certifications=["CE"],
    ))
    assert profile["profile_id"] == "gps-factory"
    assert run(service.get_supplier_profile("gps-factory"))["products"] == ["GPS tracker"]

    store.notices = [{
        "publication_number": "1-2026",
        "publication_date": "2026-09-16",
        "title": "GPS tracker devices with CE compliance",
        "descriptions": ["GPS tracking devices"],
        "cpv_codes": ["32522000"],
        "buyer_countries": ["DEU"],
        "deadlines": ["2026-10-01"],
    }]
    result = run(service.daily_opportunities("gps-factory", since_hours=24, limit=10, now=date(2026, 9, 16)))
    assert result["profile_id"] == "gps-factory"
    assert result["opportunities"][0]["publication_number"] == "1-2026"
    assert result["opportunities"][0]["supplier_match_score"] > 0
    assert result["source"] == "warehouse"


def test_match_supplier_opportunities_uses_profile_and_sorts():
    payload = {
        "totalNoticeCount": 2,
        "notices": [
            {
                "publication-number": "1-2026",
                "publication-date": "2026-09-16",
                "notice-title": {"eng": "GPS tracker with CE"},
                "classification-cpv": "32522000",
                "buyer-country": "DEU",
                "deadline-receipt-tender-date-lot": "2026-10-01",
            },
            {
                "publication-number": "2-2026",
                "publication-date": "2026-09-10",
                "notice-title": {"eng": "Other equipment"},
                "classification-cpv": "32522000",
                "buyer-country": "DEU",
            },
        ],
    }
    store = MemoryStore()
    store.profiles["gps-factory"] = {
        "profile_id": "gps-factory",
        "products": ["GPS tracker"],
        "cpv_codes": ["32522000"],
        "target_countries": ["DE"],
        "excluded_countries": [],
        "certifications": ["CE"],
    }
    service = ProcurementService(FakeTedClient(payload), store=store)
    result = run(service.match_supplier_opportunities("gps-factory", days=30, limit=10, today=date(2026, 9, 16)))
    assert result["opportunities"][0]["publication_number"] == "1-2026"
    assert result["opportunities"][0]["supplier_match_score"] > result["opportunities"][1]["supplier_match_score"]
    assert "classification-cpv = 32522000" in service.client.requests[0].query


def test_v2_service_requires_store_for_persistent_tools():
    service = ProcurementService(FakeTedClient({"notices": []}))
    try:
        run(service.get_supplier_profile("missing"))
    except RuntimeError as exc:
        assert "warehouse" in str(exc).lower()
    else:
        raise AssertionError("expected persistent tool to require a store")

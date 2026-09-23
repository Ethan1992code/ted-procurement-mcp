import json

import httpx

from ted_procurement_mcp.auth import hash_api_key
from ted_procurement_mcp.storage import SupabaseNoticeStore


def test_supabase_store_upserts_profile_and_api_key_without_raw_secret():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(201, json={})

    store = SupabaseNoticeStore(
        "https://project.supabase.co",
        "service-role-secret",
        transport=httpx.MockTransport(handler),
    )
    store.upsert_supplier_profile({"profile_id": "factory-a", "products": ["GPS"]})
    store.put_api_key("ted_live_secret", name="Client A", daily_quota=50)

    assert seen[0].url.path.endswith("/rest/v1/supplier_profiles")
    key_body = json.loads(seen[1].content)
    assert key_body["key_hash"] == hash_api_key("ted_live_secret")
    assert "ted_live_secret" not in seen[1].content.decode()
    assert key_body["daily_quota"] == 50


def test_supabase_store_reads_recent_notice_payloads():
    def handler(request: httpx.Request):
        assert request.url.path.endswith("/rest/v1/notices")
        return httpx.Response(200, json=[{"payload": {"publication_number": "1-2026"}}])

    store = SupabaseNoticeStore(
        "https://project.supabase.co",
        "service-role-secret",
        transport=httpx.MockTransport(handler),
    )
    rows = store.list_notices_since("2026-09-15", limit=10)
    assert rows == [{"publication_number": "1-2026"}]

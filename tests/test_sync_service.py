import asyncio

import pytest

from ted_procurement_mcp.sync_service import SyncService


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    async def search(self, request):
        self.requests.append(request)
        return self.payloads.pop(0)


class FakeStore:
    def __init__(self):
        self.rows = []
        self.state = {}

    def upsert_notices(self, notices):
        self.rows.extend(notices)
        return len(notices)

    def set_sync_state(self, key, token):
        self.state[key] = token

    def get_sync_state(self, key):
        return self.state.get(key)


def run(coro):
    return asyncio.run(coro)


def test_sync_uses_iteration_and_persists_cursor():
    client = FakeClient([
        {"notices": [{"publication-number": "1-2026"}], "iterationNextToken": "abc"},
        {"notices": [{"publication-number": "2-2026"}], "iterationNextToken": None},
    ])
    store = FakeStore()
    result = run(SyncService(client, store).sync(query="publication-date >= 20260901", fields=["publication-number"], max_pages=3, page_size=100))

    assert result["pages_fetched"] == 2
    assert result["notices_upserted"] == 2
    assert client.requests[0].pagination_mode == "ITERATION"
    assert client.requests[1].iteration_next_token == "abc"
    assert store.state[result["sync_key"]] is None


def test_sync_rejects_unbounded_page_count():
    with pytest.raises(ValueError, match="max_pages"):
        run(SyncService(FakeClient([]), FakeStore()).sync(query="x", fields=["publication-number"], max_pages=21))

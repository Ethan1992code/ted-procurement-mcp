import asyncio
import json

import httpx

from ted_procurement_mcp.models import TedSearchRequest
from ted_procurement_mcp.ted_client import TedApiError, TedClient


def test_ted_client_posts_search_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"totalNoticeCount": 1, "notices": [{"publication-number": "1-2026"}]})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.ted.europa.eu")
    client = TedClient(http_client=http)
    req = TedSearchRequest(query="OJ = ()", fields=["publication-number"], limit=1)

    result = asyncio.run(client.search(req))
    asyncio.run(http.aclose())

    assert result["totalNoticeCount"] == 1
    assert seen["method"] == "POST"
    assert seen["path"] == "/v3/notices/search"
    assert seen["body"]["query"] == "OJ = ()"
    assert seen["body"]["limit"] == 1


def test_ted_client_raises_readable_error_on_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "bad expert query"})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.ted.europa.eu")
    client = TedClient(http_client=http)
    req = TedSearchRequest(query="bad", fields=["publication-number"])

    try:
        asyncio.run(client.search(req))
    except TedApiError as exc:
        assert "400" in str(exc)
        assert "bad expert query" in str(exc)
    else:
        raise AssertionError("expected TedApiError")
    finally:
        asyncio.run(http.aclose())


def test_ted_client_rejects_timed_out_partial_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"timedOut": True, "notices": [{"publication-number": "partial"}]})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.ted.europa.eu")
    client = TedClient(http_client=http)
    req = TedSearchRequest(query="OJ = ()", fields=["publication-number"])

    try:
        asyncio.run(client.search(req))
    except TedApiError as exc:
        assert "timed out" in str(exc).lower()
    else:
        raise AssertionError("expected TedApiError")
    finally:
        asyncio.run(http.aclose())

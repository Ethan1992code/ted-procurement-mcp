from __future__ import annotations

import httpx

from .models import TedSearchRequest


class TedApiError(RuntimeError):
    """Raised when TED Search API cannot satisfy a request."""


class TedClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.ted.europa.eu",
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": "ted-procurement-mcp/0.1"},
        )

    async def search(self, request: TedSearchRequest) -> dict:
        try:
            response = await self._client.post(
                "/v3/notices/search",
                json=request.to_payload(),
            )
        except httpx.HTTPError as exc:
            raise TedApiError(f"TED Search API request failed: {exc}") from exc

        if response.status_code >= 400:
            body = response.text[:2000]
            raise TedApiError(
                f"TED Search API returned HTTP {response.status_code}: {body}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise TedApiError("TED Search API returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise TedApiError("TED Search API returned an unexpected JSON shape")
        if data.get("timedOut") is True:
            raise TedApiError(
                "TED Search API timed out and may have returned partial results; retry with a narrower query"
            )
        return data

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import TedSearchRequest
from .normalizer import DEFAULT_NOTICE_FIELDS, extract_notice_rows, normalise_notice


class SyncService:
    def __init__(self, client: Any, store: Any) -> None:
        self.client = client
        self.store = store

    @staticmethod
    def make_sync_key(query: str, fields: list[str]) -> str:
        blob = json.dumps({"query": query, "fields": sorted(fields)}, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:24]

    async def sync(
        self,
        *,
        query: str,
        fields: list[str] | None = None,
        max_pages: int = 4,
        page_size: int = 250,
    ) -> dict[str, Any]:
        if not 1 <= max_pages <= 20:
            raise ValueError("max_pages must be between 1 and 20")
        if not 1 <= page_size <= 250:
            raise ValueError("page_size must be between 1 and 250")
        fields = fields or DEFAULT_NOTICE_FIELDS
        sync_key = self.make_sync_key(query, fields)
        token = self.store.get_sync_state(sync_key)
        pages = 0
        upserted = 0
        finished = False

        for _ in range(max_pages):
            request = TedSearchRequest(
                query=query,
                fields=fields,
                limit=page_size,
                scope="ALL",
                pagination_mode="ITERATION",
                iteration_next_token=token,
            )
            payload = await self.client.search(request)
            notices = [normalise_notice(row) for row in extract_notice_rows(payload)]
            upserted += self.store.upsert_notices(notices)
            pages += 1
            token = payload.get("iterationNextToken")
            self.store.set_sync_state(sync_key, token)
            if not token:
                finished = True
                break

        return {
            "sync_key": sync_key,
            "pages_fetched": pages,
            "notices_upserted": upserted,
            "iteration_next_token": token,
            "finished_current_iteration": finished,
            "bounded": True,
        }

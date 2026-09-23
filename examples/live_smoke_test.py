"""Opt-in live smoke test. Requires internet access; no TED API key is needed."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from ted_procurement_mcp.models import TedSearchRequest
from ted_procurement_mcp.normalizer import extract_notice_rows, normalise_notice
from ted_procurement_mcp.ted_client import TedClient


async def main() -> None:
    today = date.today()
    start = today - timedelta(days=7)
    query = f"publication-date = ({start:%Y%m%d} <> {today:%Y%m%d})"
    request = TedSearchRequest(
        query=query,
        fields=[
            "publication-number",
            "publication-date",
            "notice-title",
            "buyer-name",
            "buyer-country",
            "classification-cpv",
            "form-type",
        ],
        limit=3,
        scope="ALL",
        only_latest_versions=True,
    )
    client = TedClient()
    try:
        payload = await client.search(request)
        rows = extract_notice_rows(payload)
        print(f"TED live smoke OK: {len(rows)} rows returned")
        for row in rows:
            notice = normalise_notice(row)
            print(notice["publication_number"], "|", notice["title"])
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from .models import TedSearchRequest
from .normalizer import extract_notice_rows, normalise_notice
from .query_builder import build_procurement_query


CPV_DISCOVERY_FIELDS = [
    "publication-number",
    "publication-date",
    "notice-title",
    "classification-cpv",
    "buyer-country",
]


class CpvDiscoveryService:
    """Infer likely CPV codes from TED notices matching a supplier product phrase."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def suggest(
        self,
        product: str,
        *,
        countries: list[str] | None = None,
        days: int = 365,
        limit: int = 100,
        today: date | None = None,
    ) -> dict[str, Any]:
        if days < 1:
            raise ValueError("days must be >= 1")
        today = today or date.today()
        query = build_procurement_query(
            keywords=product,
            buyer_countries=countries,
            date_from=today - timedelta(days=days),
            date_to=today,
        )
        request = TedSearchRequest(
            query=query,
            fields=CPV_DISCOVERY_FIELDS,
            limit=min(limit, 250),
            scope="ALL",
        )
        payload = await self.client.search(request)
        notices = [normalise_notice(row) for row in extract_notice_rows(payload)]

        counts: Counter[str] = Counter()
        samples: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for notice in notices:
            for code in notice.get("cpv_codes") or []:
                counts[code] += 1
                if len(samples[code]) < 3:
                    samples[code].append(
                        {
                            "publication_number": notice.get("publication_number"),
                            "publication_date": notice.get("publication_date"),
                            "title": notice.get("title"),
                        }
                    )

        suggestions = [
            {
                "cpv_code": code,
                "support_count": count,
                "support_share": round(count / len(notices), 4) if notices else 0.0,
                "sample_notices": samples[code],
            }
            for code, count in counts.most_common()
        ]
        return {
            "product": product,
            "query": query,
            "analysed_notice_count": len(notices),
            "suggestions": suggestions,
            "method": "TED notice frequency inference",
            "caveat": (
                "CPV suggestions are inferred from matching TED notices, not a legal or "
                "technical classification guarantee. Verify the final CPV for tender use."
            ),
        }

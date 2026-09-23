from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from .models import TedSearchRequest
from .normalizer import (
    AWARD_FIELDS,
    DEFAULT_NOTICE_FIELDS,
    extract_notice_rows,
    extract_total,
    normalise_notice,
)
from .query_builder import build_procurement_query
from .scoring import score_opportunity
from .ted_client import TedClient
from .cpv_discovery import CpvDiscoveryService
from .supplier_matcher import match_notice_to_profile
from .supplier_profiles import SupplierProfileService
from .sync_service import SyncService


class ProcurementService:
    """Business-level TED procurement intelligence operations."""

    def __init__(self, client: TedClient, store: Any | None = None) -> None:
        self.client = client
        self.store = store

    def _require_store(self) -> Any:
        if self.store is None:
            raise RuntimeError("A warehouse store is required for this V2 tool")
        return self.store

    async def _normalised_search(
        self,
        *,
        query: str,
        fields: list[str] | None = None,
        limit: int = 25,
        page: int = 1,
        scope: str = "ALL",
        pagination_mode: str = "PAGE_NUMBER",
        iteration_next_token: str | None = None,
        only_latest_versions: bool = True,
        check_query_syntax: bool = False,
    ) -> dict[str, Any]:
        request = TedSearchRequest(
            query=query,
            fields=fields or DEFAULT_NOTICE_FIELDS,
            page=page,
            limit=limit,
            scope=scope,
            pagination_mode=pagination_mode,
            iteration_next_token=iteration_next_token,
            only_latest_versions=only_latest_versions,
            check_query_syntax=check_query_syntax,
        )
        payload = await self.client.search(request)
        notices = [normalise_notice(row) for row in extract_notice_rows(payload)]
        return {
            "query": query,
            "total": extract_total(payload),
            "notices": notices,
            "iteration_next_token": payload.get("iterationNextToken"),
            "timed_out": bool(payload.get("timedOut", False)),
        }

    async def raw_ted_search(
        self,
        *,
        query: str,
        fields: list[str],
        limit: int = 25,
        page: int = 1,
        scope: str = "ALL",
        pagination_mode: str = "PAGE_NUMBER",
        iteration_next_token: str | None = None,
        only_latest_versions: bool = True,
        check_query_syntax: bool = False,
    ) -> dict[str, Any]:
        request = TedSearchRequest(
            query=query,
            fields=fields,
            page=page,
            limit=limit,
            scope=scope,
            pagination_mode=pagination_mode,
            iteration_next_token=iteration_next_token,
            only_latest_versions=only_latest_versions,
            check_query_syntax=check_query_syntax,
        )
        return await self.client.search(request)

    async def search_procurements(
        self,
        *,
        keywords: str | None = None,
        cpv_codes: list[str] | None = None,
        countries: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        form_type: str | None = None,
        limit: int = 25,
        page: int = 1,
        scope: str = "ACTIVE",
    ) -> dict[str, Any]:
        query = build_procurement_query(
            keywords=keywords,
            cpv_codes=cpv_codes,
            buyer_countries=countries,
            date_from=date_from,
            date_to=date_to,
            form_type=form_type,
        )
        return await self._normalised_search(
            query=query,
            fields=DEFAULT_NOTICE_FIELDS,
            limit=limit,
            page=page,
            scope=scope,
        )

    async def find_opportunities(
        self,
        *,
        product: str,
        cpv_codes: list[str] | None = None,
        countries: list[str] | None = None,
        days: int = 30,
        limit: int = 25,
        today: date | None = None,
    ) -> dict[str, Any]:
        if days < 1:
            raise ValueError("days must be >= 1")
        today = today or date.today()
        date_from = today - timedelta(days=days)
        query = build_procurement_query(
            keywords=product,
            cpv_codes=cpv_codes,
            buyer_countries=countries,
            date_from=date_from,
            date_to=today,
            form_type="competition",
        )
        result = await self._normalised_search(
            query=query,
            fields=DEFAULT_NOTICE_FIELDS,
            limit=limit,
            scope="ACTIVE",
        )
        opportunities: list[dict[str, Any]] = []
        for notice in result["notices"]:
            score = score_opportunity(
                notice,
                product=product,
                requested_cpv=cpv_codes,
                requested_countries=countries,
                today=today,
            )
            enriched = dict(notice)
            enriched["opportunity_score"] = score["score"]
            enriched["score_components"] = score["components"]
            opportunities.append(enriched)
        opportunities.sort(
            key=lambda item: (
                item.get("opportunity_score", 0),
                item.get("publication_date") or "",
            ),
            reverse=True,
        )
        return {
            "query": query,
            "total": result["total"],
            "opportunities": opportunities,
            "scoring_note": (
                "Rule-based relevance score only; verify technical fit, certification, "
                "delivery, eligibility and tender conditions separately."
            ),
        }

    async def get_notice(self, publication_number: str) -> dict[str, Any]:
        query = build_procurement_query(publication_number=publication_number)
        result = await self._normalised_search(
            query=query,
            fields=AWARD_FIELDS,
            limit=5,
            scope="ALL",
            only_latest_versions=False,
        )
        notice = result["notices"][0] if result["notices"] else None
        return {"query": query, "notice": notice, "match_count": result["total"]}

    async def find_buyers(
        self,
        *,
        product: str | None = None,
        cpv_codes: list[str] | None = None,
        countries: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        query = build_procurement_query(
            keywords=product,
            cpv_codes=cpv_codes,
            buyer_countries=countries,
            date_from=date_from,
            date_to=date_to,
        )
        result = await self._normalised_search(
            query=query,
            fields=DEFAULT_NOTICE_FIELDS,
            limit=limit,
            scope="ALL",
        )
        buyers: dict[str, dict[str, Any]] = {}
        for notice in result["notices"]:
            for name in notice.get("buyer_names") or []:
                entry = buyers.setdefault(
                    name,
                    {
                        "buyer_name": name,
                        "buyer_countries": set(),
                        "buyer_emails": set(),
                        "buyer_websites": set(),
                        "notice_count": 0,
                        "latest_publication_date": None,
                        "sample_notices": [],
                    },
                )
                entry["notice_count"] += 1
                entry["buyer_countries"].update(notice.get("buyer_countries") or [])
                entry["buyer_emails"].update(notice.get("buyer_emails") or [])
                entry["buyer_websites"].update(notice.get("buyer_websites") or [])
                published = notice.get("publication_date")
                if published and (
                    not entry["latest_publication_date"]
                    or published > entry["latest_publication_date"]
                ):
                    entry["latest_publication_date"] = published
                if len(entry["sample_notices"]) < 3:
                    entry["sample_notices"].append(
                        {
                            "publication_number": notice.get("publication_number"),
                            "publication_date": published,
                            "title": notice.get("title"),
                        }
                    )
        serialised: list[dict[str, Any]] = []
        for entry in buyers.values():
            entry = dict(entry)
            entry["buyer_countries"] = sorted(entry["buyer_countries"])
            entry["buyer_emails"] = sorted(entry["buyer_emails"])
            entry["buyer_websites"] = sorted(entry["buyer_websites"])
            serialised.append(entry)
        serialised.sort(
            key=lambda item: (item["notice_count"], item["latest_publication_date"] or ""),
            reverse=True,
        )
        return {
            "query": query,
            "reported_total_matches": result["total"],
            "analysed_notice_count": len(result["notices"]),
            "buyers": serialised,
        }

    async def buyer_history(
        self,
        *,
        buyer_name: str,
        years: int = 3,
        limit: int = 100,
        today: date | None = None,
    ) -> dict[str, Any]:
        if years < 1:
            raise ValueError("years must be >= 1")
        today = today or date.today()
        date_from = today - timedelta(days=365 * years)
        query = build_procurement_query(
            buyer_name=buyer_name,
            date_from=date_from,
            date_to=today,
        )
        result = await self._normalised_search(
            query=query,
            fields=AWARD_FIELDS,
            limit=limit,
            scope="ALL",
        )
        result["buyer_name"] = buyer_name
        return result

    async def find_awards(
        self,
        *,
        product: str | None = None,
        cpv_codes: list[str] | None = None,
        countries: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        query = build_procurement_query(
            keywords=product,
            cpv_codes=cpv_codes,
            buyer_countries=countries,
            date_from=date_from,
            date_to=date_to,
            form_type="result",
        )
        result = await self._normalised_search(
            query=query,
            fields=AWARD_FIELDS,
            limit=limit,
            scope="ALL",
        )
        return {
            "query": query,
            "total": result["total"],
            "awards": result["notices"],
            "data_caveat": "Some TED result notices may not contain winner information.",
        }

    async def market_stats(
        self,
        *,
        product: str | None = None,
        cpv_codes: list[str] | None = None,
        countries: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        query = build_procurement_query(
            keywords=product,
            cpv_codes=cpv_codes,
            buyer_countries=countries,
            date_from=date_from,
            date_to=date_to,
        )
        result = await self._normalised_search(
            query=query,
            fields=DEFAULT_NOTICE_FIELDS,
            limit=limit,
            scope="ALL",
        )
        country_counts: Counter[str] = Counter()
        cpv_counts: Counter[str] = Counter()
        form_counts: Counter[str] = Counter()
        buyer_counts: Counter[str] = Counter()
        value_by_currency: defaultdict[str, float] = defaultdict(float)

        for notice in result["notices"]:
            country_counts.update(notice.get("buyer_countries") or [])
            cpv_counts.update(notice.get("cpv_codes") or [])
            if notice.get("form_type"):
                form_counts[notice["form_type"]] += 1
            buyer_counts.update(notice.get("buyer_names") or [])
            for value in notice.get("estimated_values") or []:
                currency = value.get("currency") or "UNKNOWN"
                amount = value.get("amount")
                if isinstance(amount, (int, float)):
                    value_by_currency[currency] += float(amount)

        return {
            "query": query,
            "notice_count": len(result["notices"]),
            "reported_total_matches": result["total"],
            "by_country": dict(country_counts.most_common()),
            "by_cpv": dict(cpv_counts.most_common()),
            "by_form_type": dict(form_counts.most_common()),
            "top_buyers": dict(buyer_counts.most_common(20)),
            "reported_estimated_values_by_currency": dict(value_by_currency),
            "aggregation_caveat": (
                "Values are sums of reported notice-level/lot-level fields in this page, "
                "not a deduplicated market-size estimate."
            ),
        }

    async def suggest_cpv(
        self,
        product: str,
        *,
        countries: list[str] | None = None,
        days: int = 365,
        limit: int = 100,
    ) -> dict[str, Any]:
        return await CpvDiscoveryService(self.client).suggest(
            product, countries=countries, days=days, limit=limit
        )

    async def upsert_supplier_profile(
        self,
        *,
        profile_id: str,
        products: list[str],
        cpv_codes: list[str] | None = None,
        target_countries: list[str] | None = None,
        excluded_countries: list[str] | None = None,
        certifications: list[str] | None = None,
        moq: int | None = None,
        lead_time_days: int | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        store = self._require_store()
        return SupplierProfileService(store).upsert(
            profile_id=profile_id,
            products=products,
            cpv_codes=cpv_codes or [],
            target_countries=target_countries or [],
            excluded_countries=excluded_countries or [],
            certifications=certifications or [],
            moq=moq,
            lead_time_days=lead_time_days,
            notes=notes,
        )

    async def get_supplier_profile(self, profile_id: str) -> dict[str, Any] | None:
        store = self._require_store()
        return SupplierProfileService(store).get(profile_id)

    async def match_supplier_opportunities(
        self,
        profile_id: str,
        *,
        days: int = 30,
        limit: int = 50,
        today: date | None = None,
    ) -> dict[str, Any]:
        if days < 1:
            raise ValueError("days must be >= 1")
        if not 1 <= limit <= 250:
            raise ValueError("limit must be between 1 and 250")
        store = self._require_store()
        profile = SupplierProfileService(store).get(profile_id)
        if profile is None:
            raise ValueError(f"supplier profile not found: {profile_id}")

        today = today or date.today()
        date_from = today - timedelta(days=days)
        notices_by_number: dict[str, dict[str, Any]] = {}

        if profile.get("cpv_codes"):
            query = build_procurement_query(
                cpv_codes=profile.get("cpv_codes"),
                buyer_countries=profile.get("target_countries"),
                date_from=date_from,
                date_to=today,
                form_type="competition",
            )
            result = await self._normalised_search(
                query=query, fields=DEFAULT_NOTICE_FIELDS, limit=limit, scope="ACTIVE"
            )
            for notice in result["notices"]:
                number = notice.get("publication_number") or repr(notice)
                notices_by_number[number] = notice
        else:
            products = (profile.get("products") or [])[:5]
            for product in products:
                query = build_procurement_query(
                    keywords=product,
                    buyer_countries=profile.get("target_countries"),
                    date_from=date_from,
                    date_to=today,
                    form_type="competition",
                )
                result = await self._normalised_search(
                    query=query, fields=DEFAULT_NOTICE_FIELDS, limit=limit, scope="ACTIVE"
                )
                for notice in result["notices"]:
                    number = notice.get("publication_number") or repr(notice)
                    notices_by_number[number] = notice

        opportunities: list[dict[str, Any]] = []
        for notice in notices_by_number.values():
            matched = match_notice_to_profile(notice, profile, today=today)
            enriched = dict(notice)
            enriched["supplier_match_score"] = matched["score"]
            enriched["supplier_match_components"] = matched["components"]
            enriched["constraints_to_verify"] = matched["constraints_to_verify"]
            enriched["excluded_market"] = matched["excluded_market"]
            opportunities.append(enriched)
        opportunities.sort(
            key=lambda item: (item.get("supplier_match_score", 0), item.get("publication_date") or ""),
            reverse=True,
        )
        return {
            "profile_id": profile_id,
            "source": "TED live search",
            "opportunities": opportunities[:limit],
            "scoring_note": "Profile-aware rule score; tender eligibility and specifications still require verification.",
        }

    async def sync_notices(
        self,
        *,
        query: str,
        fields: list[str] | None = None,
        max_pages: int = 4,
        page_size: int = 250,
    ) -> dict[str, Any]:
        store = self._require_store()
        return await SyncService(self.client, store).sync(
            query=query, fields=fields, max_pages=max_pages, page_size=page_size
        )

    async def daily_opportunities(
        self,
        profile_id: str,
        *,
        since_hours: int = 24,
        limit: int = 50,
        now: date | datetime | None = None,
    ) -> dict[str, Any]:
        if not 1 <= since_hours <= 24 * 31:
            raise ValueError("since_hours must be between 1 and 744")
        if not 1 <= limit <= 250:
            raise ValueError("limit must be between 1 and 250")
        store = self._require_store()
        profile = SupplierProfileService(store).get(profile_id)
        if profile is None:
            raise ValueError(f"supplier profile not found: {profile_id}")

        current = now or datetime.now()
        if isinstance(current, date) and not isinstance(current, datetime):
            current_dt = datetime.combine(current, time.min)
        else:
            current_dt = current
        cutoff_date = (current_dt - timedelta(hours=since_hours)).date().isoformat()
        candidates = store.list_notices_since(cutoff_date, limit=2000)
        opportunities: list[dict[str, Any]] = []
        for notice in candidates:
            matched = match_notice_to_profile(notice, profile, today=current_dt.date())
            if matched["score"] <= 0 or matched["excluded_market"]:
                continue
            enriched = dict(notice)
            enriched["supplier_match_score"] = matched["score"]
            enriched["supplier_match_components"] = matched["components"]
            enriched["constraints_to_verify"] = matched["constraints_to_verify"]
            opportunities.append(enriched)
        opportunities.sort(
            key=lambda item: (item.get("supplier_match_score", 0), item.get("publication_date") or ""),
            reverse=True,
        )
        return {
            "profile_id": profile_id,
            "source": "warehouse",
            "since_hours": since_hours,
            "date_precision_note": "TED publication-date is day-level, so hour windows are conservatively rounded to a date cutoff.",
            "opportunities": opportunities[:limit],
            "warehouse_stats": store.stats(),
            "completeness_caveat": "Results reflect only notices already synchronized into this warehouse.",
        }

    async def warehouse_stats(self) -> dict[str, Any]:
        return self._require_store().stats()

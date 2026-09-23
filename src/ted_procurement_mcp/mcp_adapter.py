from __future__ import annotations

from typing import Any

from .service import ProcurementService


def register_tools(server: Any, service: ProcurementService) -> None:
    """Register read-only procurement intelligence tools on an MCP-like server."""

    @server.tool(name="raw_ted_search", title="Raw TED expert search", structured_output=True)
    async def raw_ted_search(
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
        """Run a TED Expert Search query directly. Use for advanced fields or iteration paging."""
        return await service.raw_ted_search(
            query=query,
            fields=fields,
            limit=limit,
            page=page,
            scope=scope,
            pagination_mode=pagination_mode,
            iteration_next_token=iteration_next_token,
            only_latest_versions=only_latest_versions,
            check_query_syntax=check_query_syntax,
        )

    @server.tool(name="search_procurements", title="Search EU procurements", structured_output=True)
    async def search_procurements(
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
        """Search TED notices by product keywords, CPV, buyer countries, dates and form type."""
        return await service.search_procurements(
            keywords=keywords,
            cpv_codes=cpv_codes,
            countries=countries,
            date_from=date_from,
            date_to=date_to,
            form_type=form_type,
            limit=limit,
            page=page,
            scope=scope,
        )

    @server.tool(name="find_opportunities", title="Find supplier opportunities", structured_output=True)
    async def find_opportunities(
        product: str,
        cpv_codes: list[str] | None = None,
        countries: list[str] | None = None,
        days: int = 30,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Find recent competition notices and rank them with a transparent supplier relevance score."""
        return await service.find_opportunities(
            product=product,
            cpv_codes=cpv_codes,
            countries=countries,
            days=days,
            limit=limit,
        )

    @server.tool(name="get_notice", title="Get TED notice", structured_output=True)
    async def get_notice(publication_number: str) -> dict[str, Any]:
        """Retrieve a TED notice by publication number such as 123456-2026."""
        return await service.get_notice(publication_number)

    @server.tool(name="find_buyers", title="Find public buyers", structured_output=True)
    async def find_buyers(
        product: str | None = None,
        cpv_codes: list[str] | None = None,
        countries: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Aggregate public buyers that published matching TED procurement notices."""
        return await service.find_buyers(
            product=product,
            cpv_codes=cpv_codes,
            countries=countries,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    @server.tool(name="buyer_history", title="Buyer procurement history", structured_output=True)
    async def buyer_history(
        buyer_name: str,
        years: int = 3,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Retrieve recent TED procurement/result notices for a named public buyer."""
        return await service.buyer_history(
            buyer_name=buyer_name,
            years=years,
            limit=limit,
        )

    @server.tool(name="find_awards", title="Find contract awards", structured_output=True)
    async def find_awards(
        product: str | None = None,
        cpv_codes: list[str] | None = None,
        countries: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Search TED result notices and return winner/value fields when the notice reports them."""
        return await service.find_awards(
            product=product,
            cpv_codes=cpv_codes,
            countries=countries,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    @server.tool(name="market_stats", title="TED market statistics", structured_output=True)
    async def market_stats(
        product: str | None = None,
        cpv_codes: list[str] | None = None,
        countries: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        """Aggregate one TED result page by country, CPV, form type, buyer and reported values."""
        return await service.market_stats(
            product=product,
            cpv_codes=cpv_codes,
            countries=countries,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    @server.tool(name="suggest_cpv", title="Suggest likely CPV codes", structured_output=True)
    async def suggest_cpv(
        product: str,
        countries: list[str] | None = None,
        days: int = 365,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Infer likely CPV codes from recent TED notices matching a supplier product phrase."""
        return await service.suggest_cpv(
            product=product,
            countries=countries,
            days=days,
            limit=limit,
        )

    @server.tool(name="upsert_supplier_profile", title="Save supplier profile", structured_output=True)
    async def upsert_supplier_profile(
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
        """Create or update a supplier profile used for procurement matching."""
        return await service.upsert_supplier_profile(
            profile_id=profile_id,
            products=products,
            cpv_codes=cpv_codes,
            target_countries=target_countries,
            excluded_countries=excluded_countries,
            certifications=certifications,
            moq=moq,
            lead_time_days=lead_time_days,
            notes=notes,
        )

    @server.tool(name="get_supplier_profile", title="Get supplier profile", structured_output=True)
    async def get_supplier_profile(profile_id: str) -> dict[str, Any] | None:
        """Retrieve one persisted supplier profile by ID."""
        return await service.get_supplier_profile(profile_id)

    @server.tool(name="match_supplier_opportunities", title="Match live opportunities to supplier", structured_output=True)
    async def match_supplier_opportunities(
        profile_id: str,
        days: int = 30,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search live TED notices and rank them against a persisted supplier profile."""
        return await service.match_supplier_opportunities(
            profile_id=profile_id,
            days=days,
            limit=limit,
        )

    @server.tool(name="sync_notices", title="Sync TED notices to warehouse", structured_output=True)
    async def sync_notices(
        query: str,
        fields: list[str] | None = None,
        max_pages: int = 4,
        page_size: int = 250,
    ) -> dict[str, Any]:
        """Bounded incremental TED ITERATION sync into the configured warehouse."""
        return await service.sync_notices(
            query=query,
            fields=fields,
            max_pages=max_pages,
            page_size=page_size,
        )

    @server.tool(name="daily_opportunities", title="Daily stored opportunities", structured_output=True)
    async def daily_opportunities(
        profile_id: str,
        since_hours: int = 24,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Rank recently synchronized warehouse notices for a supplier profile."""
        return await service.daily_opportunities(
            profile_id=profile_id,
            since_hours=since_hours,
            limit=limit,
        )

    @server.tool(name="warehouse_stats", title="Warehouse statistics", structured_output=True)
    async def warehouse_stats() -> dict[str, Any]:
        """Return basic completeness and freshness statistics for the configured warehouse."""
        return await service.warehouse_stats()

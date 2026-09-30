from __future__ import annotations

import os
from typing import Any

from . import __version__
from .auth import ApiKeyGate
from .mcp_adapter import register_tools
from .service import ProcurementService
from .storage import SQLiteNoticeStore, SupabaseNoticeStore
from .ted_client import TedClient


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def build_store_from_env() -> Any | None:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and supabase_key:
        return SupabaseNoticeStore(supabase_url, supabase_key)
    if bool(supabase_url) != bool(supabase_key):
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured together")

    # Vercel's local filesystem is ephemeral; do not imply SQLite is durable there.
    if _truthy(os.getenv("VERCEL")):
        return None
    return SQLiteNoticeStore(os.getenv("TED_DB_PATH", "ted_procurement.db"))


def _warehouse_backend(store: Any | None) -> str:
    if store is None:
        return "none"
    if isinstance(store, SupabaseNoticeStore):
        return "supabase"
    if isinstance(store, SQLiteNoticeStore):
        return "sqlite"
    return store.__class__.__name__.lower()


def create_server(*, store: Any | None = None):
    """Create the MCP SDK v2 server lazily so core modules remain testable without MCP installed."""
    try:
        from mcp.server import MCPServer
        from starlette.responses import JSONResponse
    except ImportError as exc:
        raise RuntimeError(
            "MCP SDK is not installed. Install project dependencies with: pip install -e ."
        ) from exc

    if store is None:
        store = build_store_from_env()

    server = MCPServer("TED Procurement Intelligence")
    service = ProcurementService(TedClient(), store=store)
    register_tools(server, service)
    if _truthy(os.getenv("MCP_EVENTS_ENABLED")):
        if store is None or not _truthy(os.getenv("MCP_REQUIRE_API_KEY")):
            raise RuntimeError("MCP Events requires durable storage and authentication")
        from .event_store import EventStore
        from .events import EventService
        from .event_scanner import EventScanner, owner_authorized
        import hmac
        event_store = EventStore(store)
        server.ted_events = EventService(event_store)

        @server.custom_route("/internal/events/scan", methods=["GET"])
        async def scan_events(request):
            secret = os.getenv("CRON_SECRET", "").strip()
            if not secret:
                return JSONResponse({"error": "cron_not_configured"}, status_code=503)
            if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + secret):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            async def authorized(owner):
                return await owner_authorized(store, owner)
            import asyncio
            client = TedClient(timeout_seconds=10)
            try:
                scanner = EventScanner(event_store, client, authorized=authorized)
                return JSONResponse(await asyncio.wait_for(scanner.run(), timeout=50))
            except TimeoutError:
                return JSONResponse({"status": "bounded_scan_timeout", "retry_on_next_scan": True}, status_code=202)
            finally:
                await client.aclose()
    from .aipay import register_paid_search
    register_paid_search(server, service)
    from .web_shop import register_web_shop
    register_web_shop(server, service)
    from .oauth_page import consent_page
    server.custom_route("/oauth/consent", methods=["GET"])(consent_page)
    from .oauth_auth import RESOURCE, ISSUER

    @server.custom_route("/.well-known/oauth-protected-resource/mcp", methods=["GET", "OPTIONS"])
    async def oauth_metadata(_request):
        return JSONResponse({"resource": RESOURCE, "authorization_servers": [ISSUER],
                             "bearer_methods_supported": ["header"],
                             "scopes_supported": ["openid", "email", "offline_access"]},
                            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    @server.custom_route("/health", methods=["GET"])
    async def health(_request):
        return JSONResponse(
            {
                "status": "ok",
                "service": "ted-procurement-mcp",
                "version": __version__,
                "warehouse": _warehouse_backend(store),
            }
        )

    return server, store


def _transport_security_settings():
    try:
        from mcp.server.transport_security import TransportSecuritySettings
    except ImportError as exc:
        raise RuntimeError("MCP SDK v2 is required for HTTP deployment") from exc

    hosts: list[str] = []
    for raw in os.getenv("MCP_ALLOWED_HOSTS", "").split(","):
        host = raw.strip()
        if host:
            hosts.extend([host, f"{host}:*"] if ":" not in host else [host])

    vercel_url = os.getenv("VERCEL_URL", "").strip()
    if vercel_url:
        hosts.extend([vercel_url, f"{vercel_url}:*"])

    # Keep local access valid for smoke tests and local reverse proxies.
    hosts.extend(["127.0.0.1:*", "localhost:*", "[::1]:*"])
    hosts = list(dict.fromkeys(hosts))

    origins = [x.strip() for x in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if x.strip()]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def create_http_app(*, store: Any | None = None):
    from .asgi import ApiKeyASGIMiddleware, MCPBrowserAccess

    server, store = create_server(store=store)
    app = server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        transport_security=_transport_security_settings(),
    )
    require_api_key = _truthy(os.getenv("MCP_REQUIRE_API_KEY"))
    gate = ApiKeyGate(store) if store is not None else None
    if hasattr(server, "ted_events"):
        from .events_asgi import EventsASGI
        app = EventsASGI(app, server.ted_events)
    from .oauth_auth import verifier_from_env
    protected = ApiKeyASGIMiddleware(app, gate, required=require_api_key, oauth_verifier=verifier_from_env())
    origins = [x.strip() for x in os.getenv('MCP_ALLOWED_ORIGINS', '').split(',') if x.strip() and x.strip() != '*']
    return MCPBrowserAccess(protected, origins)


def main() -> None:
    server, _store = create_server()
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport in {"streamable-http", "http"}:
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8000"))
        server.run(
            transport="streamable-http",
            host=host,
            port=port,
            json_response=True,
            stateless_http=True,
            transport_security=_transport_security_settings(),
        )
    elif transport == "stdio":
        server.run(transport="stdio")
    else:
        raise ValueError("MCP_TRANSPORT must be 'stdio' or 'streamable-http'")


if __name__ == "__main__":
    main()

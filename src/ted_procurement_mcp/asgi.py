from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware

from .auth import ApiKeyGate


class MCPBrowserAccess:
    """Handle browser preflight before authentication, only on the MCP endpoint."""

    def __init__(self, app: Any, origins: list[str]) -> None:
        self.app = app
        self.cors = CORSMiddleware(
            app, allow_origins=origins,
            allow_methods=['GET', 'POST', 'DELETE'],
            allow_headers=['Authorization', 'X-API-Key', 'Content-Type',
                           'MCP-Protocol-Version', 'Mcp-Session-Id', 'Last-Event-ID'],
            expose_headers=['WWW-Authenticate', 'Mcp-Session-Id', 'MCP-Protocol-Version'],
            allow_credentials=False,
        )

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        target = self.cors if scope.get('type') == 'http' and scope.get('path') == '/mcp' else self.app
        await target(scope, receive, send)


class ApiKeyASGIMiddleware:
    """Protect only the MCP HTTP endpoint while leaving liveness routes public."""

    def __init__(self, app: Any, gate: ApiKeyGate | None, *, required: bool = False, oauth_verifier: Any = None) -> None:
        self.app = app
        self.gate = gate
        self.required = required
        self.oauth_verifier = oauth_verifier

    @staticmethod
    def _headers(scope: dict[str, Any]) -> dict[str, str]:
        return {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }

    @staticmethod
    def _extract_key(headers: dict[str, str]) -> str | None:
        value = headers.get("authorization", "")
        if value.lower().startswith("bearer "):
            return value[7:].strip() or None
        return headers.get("x-api-key") or None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/mcp" or not self.required:
            await self.app(scope, receive, send)
            return

        if self.gate is None:
            response = JSONResponse({"error": "api_key_auth_not_configured"}, status_code=503)
            await response(scope, receive, send)
            return

        token = self._extract_key(self._headers(scope))
        if token and token.count(".") == 2 and self.oauth_verifier:
            if await self.oauth_verifier.verify(token):
                await self.app(scope, receive, send)
                return
            result = {"allowed": False, "reason": "invalid_oauth_token"}
        else:
            result = self.gate.authorize(token)
        if not result.get("allowed"):
            status = 429 if result.get("reason") == "quota_exceeded" else 401
            response = JSONResponse(
                {"error": result.get("reason", "unauthorized"), "remaining": result.get("remaining")},
                status_code=status,
                headers={"WWW-Authenticate": 'Bearer resource_metadata="https://ted-procurement-mcp.vercel.app/.well-known/oauth-protected-resource/mcp"'} if self.oauth_verifier and status == 401 else None,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def create_health_app(*, version: str, warehouse_backend: str) -> Starlette:
    async def health(_request: Any) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "service": "ted-procurement-mcp",
            "version": version,
            "warehouse": warehouse_backend,
        })

    return Starlette(routes=[Route("/health", health, methods=["GET"])])

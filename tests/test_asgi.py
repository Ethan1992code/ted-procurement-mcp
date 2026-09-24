from pathlib import Path

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.applications import Starlette
from starlette.testclient import TestClient

from ted_procurement_mcp.asgi import ApiKeyASGIMiddleware, create_health_app
from ted_procurement_mcp.auth import ApiKeyGate, hash_api_key


class MemoryAuthStore:
    def __init__(self):
        self.count = 0
        self.row = {"key_hash": hash_api_key("secret"), "name": "client", "daily_quota": 5, "enabled": True}

    def get_api_key(self, key_hash):
        return self.row if key_hash == self.row["key_hash"] else None

    def increment_api_usage(self, key_hash, usage_date):
        self.count += 1
        return self.count


def test_api_key_asgi_middleware_protects_mcp_but_not_health():
    async def mcp_endpoint(request):
        return JSONResponse({"ok": True})

    inner = Starlette(routes=[Route("/mcp", mcp_endpoint, methods=["POST"])])
    app = ApiKeyASGIMiddleware(inner, ApiKeyGate(MemoryAuthStore()), required=True)
    client = TestClient(app)

    assert client.post("/mcp").status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_health_app_reports_service_without_secrets():
    app = create_health_app(version="0.2.0", warehouse_backend="supabase")
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ted-procurement-mcp", "version": "0.2.0", "warehouse": "supabase"}

def test_mcp_cors_preflight_does_not_bypass_auth_or_cover_shop():
    from ted_procurement_mcp.asgi import MCPBrowserAccess
    async def endpoint(request):return JSONResponse({'ok':True})
    inner=Starlette(routes=[Route('/mcp',endpoint,methods=['POST']),Route('/shop',endpoint)])
    store=MemoryAuthStore()
    client=TestClient(MCPBrowserAccess(ApiKeyASGIMiddleware(inner,ApiKeyGate(store),required=True),['https://mcpize.com']))
    headers={'Origin':'https://mcpize.com','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,authorization,mcp-protocol-version'}
    preflight=client.options('/mcp',headers=headers)
    assert preflight.status_code==200
    assert preflight.headers['access-control-allow-origin']=='https://mcpize.com'
    assert store.count==0
    response=client.post('/mcp',headers={'Origin':'https://mcpize.com'})
    assert response.status_code==401
    assert response.headers['access-control-allow-origin']=='https://mcpize.com'
    assert 'WWW-Authenticate' in response.headers['access-control-expose-headers']
    assert client.post('/mcp',headers={'Origin':'https://mcpize.com','Authorization':'Bearer secret'}).status_code==200
    assert client.options('/mcp',headers={**headers,'Origin':'https://evil.example'}).status_code==400
    assert 'access-control-allow-origin' not in client.get('/shop',headers={'Origin':'https://mcpize.com'}).headers

import asyncio
import base64
import hashlib
import hmac
import json

import pytest

from ted_procurement_mcp.events import EventService, EventError, subscription_id
from ted_procurement_mcp.event_store import EventStore
from ted_procurement_mcp.storage import SQLiteNoticeStore
from ted_procurement_mcp.webhook_delivery import signed_body, public_addresses

SECRET = 'whsec_' + base64.b64encode(b'x' * 32).decode()
PARAMS = {'name': 'tender.created', 'arguments': {'keywords': 'GPS'},
          'delivery': {'mode': 'webhook', 'url': 'https://receiver.example/cb', 'secret': SECRET}}

@pytest.fixture
def service(tmp_path):
    store = EventStore(SQLiteNoticeStore(tmp_path / 'events.db'))
    async def verify(sub):
        return None
    return EventService(store, verify=verify)

def test_subscription_is_idempotent_persistent_and_owner_scoped(service):
    a = asyncio.run(service.subscribe('api:one', PARAMS))
    b = asyncio.run(service.subscribe('api:one', PARAMS))
    c = asyncio.run(service.subscribe('api:two', PARAMS))
    assert a['id'] == b['id'] != c['id']
    assert a['cursor'] is None
    assert len(service.store.active()) == 2
    service.unsubscribe('api:two', PARAMS)
    assert [s['id'] for s in service.store.active()] == [a['id']]
    assert EventStore(service.store.backend).get(a['id'])['owner'] == 'api:one'

@pytest.mark.parametrize('change', [
    {'name': 'bad'}, {'arguments': {'unknown': 1}},
    {'delivery': {'mode': 'webhook', 'url': 'https://receiver.example', 'secret': 'bad'}},
    {'arguments': {}}, {'ttlMs': -1}, {'cursor': 'unsupported'},
])
def test_reject_invalid_subscription(service, change):
    with pytest.raises(EventError):
        asyncio.run(service.subscribe('api:one', {**PARAMS, **change}))
    assert service.store.active() == []

def test_callback_failure_does_not_persist(service):
    async def fail(sub):
        raise EventError(-32015, 'Callback verification failed', 'challenge_failed')
    service.verify = fail
    with pytest.raises(EventError):
        asyncio.run(service.subscribe('api:one', PARAMS))
    assert service.store.active() == []

def test_identity_uses_canonical_arguments():
    p = {**PARAMS, 'arguments': {'keywords': 'GPS', 'countries': ['PL']}}
    q = {**p, 'arguments': {'countries': ['PL'], 'keywords': 'GPS'}}
    assert subscription_id('one', p) == subscription_id('one', q)

def test_sign_exact_bytes():
    body, headers = signed_body('sub_1', SECRET, {'eventId': 'evt_1', 'data': {'title': '中文'}}, timestamp=123)
    expected = base64.b64encode(hmac.new(b'x'*32, b'evt_1.123.' + body, hashlib.sha256).digest()).decode()
    assert headers['webhook-signature'] == 'v1,' + expected
    assert headers['X-MCP-Subscription-Id'] == 'sub_1'
    assert json.loads(body)['data']['title'] == '中文'

@pytest.mark.parametrize('ip', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1', '224.0.0.1'])
def test_block_non_public_callbacks(ip):
    with pytest.raises(ValueError):
        public_addresses('https://' + ('[' + ip + ']' if ':' in ip else ip) + '/cb')

def test_queue_deduplication_and_baseline(service):
    sub = asyncio.run(service.subscribe('api:one', PARAMS))['id']
    event = {'eventId': 'evt_one', 'name': 'tender.created', 'data': {}}
    service.store.enqueue(sub, event, baseline=True)
    service.store.enqueue(sub, event, baseline=False)
    assert service.store.pending(sub) == []
    service.store.enqueue(sub, {**event, 'eventId': 'evt_two'}, baseline=False)
    assert len(service.store.pending(sub)) == 1
    service.store.complete(sub, 'evt_two', 'delivered', 1, 0)
    assert service.store.pending(sub) == []

def test_scanner_baseline_new_notice_retry_and_owner_revocation(service):
    from ted_procurement_mcp.event_scanner import EventScanner
    sub = asyncio.run(service.subscribe('api:one', PARAMS))['id']
    class Client:
        number = '100-2026'
        async def search(self, request):
            return {'notices': [{'publication-number': self.number, 'notice-title': {'eng': 'GPS supply'}, 'publication-date': '20260930'}]}
    client = Client()
    deliveries = []
    async def send(s, e):
        deliveries.append(e)
        return 503 if len(deliveries) == 1 else 200, b''
    async def authorized(owner):
        return True
    scanner = EventScanner(service.store, client, send=send, authorized=authorized)
    asyncio.run(scanner.run())
    assert deliveries == []
    client.number = '101-2026'
    asyncio.run(scanner.run())
    assert len(deliveries) == 1
    assert deliveries[0]['data']['publication_number'] == '101-2026'
    event_id = deliveries[0]['eventId']
    service.store.complete(sub, event_id, 'pending', 1, 0)
    asyncio.run(scanner.run())
    assert [e['eventId'] for e in deliveries] == [event_id, event_id]
    async def revoked(owner):
        return False
    scanner.authorized = revoked
    client.number = '102-2026'
    asyncio.run(scanner.run())
    assert len(deliveries) == 2
    assert service.store.active() == []


def test_event_endpoint_auth_discovery_and_unsubscribe(service):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient
    from ted_procurement_mcp.events_asgi import EventsASGI
    from ted_procurement_mcp.asgi import ApiKeyASGIMiddleware
    from ted_procurement_mcp.auth import ApiKeyGate
    service.store.backend.put_api_key('key', name='test')
    async def inner(request):
        data = await request.json()
        return JSONResponse({'jsonrpc': '2.0', 'id': data['id'], 'result': {'capabilities': {'tools': {}}, 'supportedVersions': ['2026-07-28'], 'resultType': 'complete'}})
    app = ApiKeyASGIMiddleware(EventsASGI(Starlette(routes=[Route('/mcp', inner, methods=['POST'])]), service), ApiKeyGate(service.store.backend), required=True)
    client = TestClient(app)
    def call(method, params=None, authenticated=True):
        return client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}, headers={'X-API-Key': 'key'} if authenticated else {})
    assert call('events/list', authenticated=False).status_code == 401
    assert call('server/discover').json()['result']['capabilities']['events'] == {}
    assert call('events/list').json()['result']['events'][0]['name'] == 'tender.created'
    assert call('events/subscribe', PARAMS).json()['result']['id'].startswith('sub_')
    assert call('events/unsubscribe', PARAMS).json()['result'] == {}
    assert service.store.active() == []
    assert call('events/subscribe', {'name': 'bad'}).json()['error']['code'] == -32602

def test_feature_flag_requires_durable_store_and_auth(monkeypatch, tmp_path):
    from ted_procurement_mcp.server import create_http_app
    monkeypatch.setenv('MCP_EVENTS_ENABLED', '1')
    monkeypatch.delenv('MCP_REQUIRE_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='authentication'):
        create_http_app(store=SQLiteNoticeStore(tmp_path / 'config.db'))


def test_actual_sdk_discovery_with_events(monkeypatch, tmp_path):
    from ted_procurement_mcp.server import create_http_app
    from starlette.testclient import TestClient
    monkeypatch.setenv('MCP_EVENTS_ENABLED', '1')
    monkeypatch.setenv('MCP_REQUIRE_API_KEY', '1')
    monkeypatch.setenv('MCP_ALLOWED_HOSTS', 'testserver')
    backend = SQLiteNoticeStore(tmp_path / 'sdk.db')
    backend.put_api_key('key', name='test')
    with TestClient(create_http_app(store=backend)) as client:
        response = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'server/discover', 'params': {'_meta': {'io.modelcontextprotocol/protocolVersion': '2026-07-28', 'io.modelcontextprotocol/clientCapabilities': {}}}}, headers={'X-API-Key': 'key', 'mcp-method': 'server/discover', 'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2026-07-28'})
        assert response.status_code == 200, response.text
        assert response.json()['result']['capabilities']['events'] == {}
        assert client.get('/internal/events/scan').status_code == 503


def test_supabase_store_uses_private_tables_and_conflict_ignore():
    import httpx
    from ted_procurement_mcp.storage import SupabaseNoticeStore
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == 'GET':
            return httpx.Response(200, json=[])
        return httpx.Response(201)
    store = EventStore(SupabaseNoticeStore('https://project.supabase.co', 'secret', transport=httpx.MockTransport(handler)))
    store.put({'id': 'sub_a', 'owner': 'api:a'})
    assert store.get('sub_a') is None
    assert store.active() == []
    store.enqueue('sub_a', {'eventId': 'evt_a'}, baseline=False)
    assert 'resolution=ignore-duplicates' in requests[-1].headers['Prefer']
    assert requests[-1].url.path.endswith('/event_deliveries')

def test_scan_cannot_reactivate_concurrently_cancelled_subscription(service):
    identity = asyncio.run(service.subscribe('api:one', PARAMS))['id']
    stale = service.store.get(identity)
    service.unsubscribe('api:one', PARAMS)
    replacement = {**stale, 'baseline': True}
    assert service.store.replace(stale, replacement) is False
    assert service.store.get(identity)['active'] is False

def test_secret_rotation_signs_with_both_keys(service):
    first = asyncio.run(service.subscribe('api:one', PARAMS))
    replacement = 'whsec_' + base64.b64encode(b'y' * 32).decode()
    second = asyncio.run(service.subscribe('api:one', {**PARAMS, 'delivery': {**PARAMS['delivery'], 'secret': replacement}}))
    assert second['id'] == first['id']
    sub = service.store.get(first['id'])
    body, headers = signed_body(sub['id'], sub['secret'], {'eventId': 'evt_a'}, timestamp=123, old_secret=sub['old_secret'])
    signatures = headers['webhook-signature'].split()
    for key in [b'y'*32, b'x'*32]:
        expected = 'v1,' + base64.b64encode(hmac.new(key, b'evt_a.123.' + body, hashlib.sha256).digest()).decode()
        assert expected in signatures


def test_verify_callback_checks_echo_and_blocks_redirect(monkeypatch):
    from ted_procurement_mcp import webhook_delivery as module
    async def good(sub, event):
        assert event['type'] == 'verification'
        return 200, json.dumps({'challenge': event['challenge']}).encode()
    monkeypatch.setattr(module, 'deliver', good)
    asyncio.run(module.verify_callback({'id': 'sub_a'}))
    async def redirect(sub, event):
        return 302, json.dumps({'challenge': event['challenge']}).encode()
    monkeypatch.setattr(module, 'deliver', redirect)
    with pytest.raises(EventError) as caught:
        asyncio.run(module.verify_callback({'id': 'sub_a'}))
    assert caught.value.code == -32015


def test_dns_public_then_private_is_rejected(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ValueError, match='Non-public'):
        public_addresses('https://receiver.example/callback')

"""Optional Events draft adapter around the existing SDK HTTP transport.

SDK 2.2 does not yet expose application webhook events natively. Only events/*
are handled here; all tool and discovery requests still go through the SDK.
"""
import json
from starlette.responses import JSONResponse
from .events import EVENT, EventError


class EventsASGI:
    def __init__(self, app, service):
        self.app, self.service = app, service

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or scope.get('path') != '/mcp' or scope.get('method') != 'POST':
            await self.app(scope, receive, send)
            return
        parts, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            parts.append(message)
            size += len(message.get('body', b''))
            if size > 1048576:
                await JSONResponse({'error': 'request_too_large'}, status_code=413)(scope, receive, send)
                return
            if not message.get('more_body'):
                break
        body = b''.join(p.get('body', b'') for p in parts)
        try:
            request = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            request = {}
        if not isinstance(request, dict):
            request = {}
        method = request.get('method', '')
        async def replay():
            return parts.pop(0) if parts else await receive()
        if isinstance(method, str) and method.startswith('events/'):
            try:
                if request.get('jsonrpc') != '2.0' or 'id' not in request or not isinstance(request.get('params', {}), dict):
                    raise EventError(-32600, 'Invalid request')
                owner = scope.get('mcp_event_owner')
                if not owner:
                    raise EventError(-32001, 'Authentication required')
                params = request.get('params', {})
                if method == 'events/list':
                    result = {'events': [EVENT]}
                elif method == 'events/subscribe':
                    result = await self.service.subscribe(owner, params)
                elif method == 'events/unsubscribe':
                    result = self.service.unsubscribe(owner, params)
                else:
                    raise EventError(-32601, 'Method not found')
                response = {'jsonrpc': '2.0', 'id': request.get('id'), 'result': result}
            except EventError as exc:
                error = {'code': exc.code, 'message': str(exc)}
                if exc.reason:
                    error['data'] = {'reason': exc.reason}
                response = {'jsonrpc': '2.0', 'id': request.get('id'), 'error': error}
            except Exception:
                response = {'jsonrpc': '2.0', 'id': request.get('id'), 'error': {'code': -32603, 'message': 'Event storage unavailable'}}
            await JSONResponse(response)(scope, receive, send)
            return
        if method != 'server/discover':
            await self.app(scope, replay, send)
            return
        messages = []
        async def capture(message):
            messages.append(message)
        await self.app(scope, replay, capture)
        try:
            start = next(m for m in messages if m['type'] == 'http.response.start')
            result = json.loads(b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body'))
            if start['status'] == 200 and isinstance(result.get('result'), dict):
                result['result'].setdefault('capabilities', {})['events'] = {}
                payload = json.dumps(result).encode()
                headers = [(k, v) for k, v in start.get('headers', []) if k.lower() != b'content-length']
                headers.append((b'content-length', str(len(payload)).encode()))
                await send({**start, 'headers': headers})
                await send({'type': 'http.response.body', 'body': payload})
                return
        except (ValueError, StopIteration, KeyError, TypeError):
            pass
        for message in messages:
            await send(message)

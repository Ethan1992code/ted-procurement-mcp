"""Standard Webhooks delivery with DNS-pinned HTTPS and no redirects/proxies."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import secrets
import socket
import ssl
import time
from urllib.parse import urlsplit


def secret_key(secret):
    if not isinstance(secret, str) or not secret.startswith('whsec_'):
        raise ValueError('Invalid signing secret')
    key = base64.b64decode(secret[6:], validate=True)
    if not 24 <= len(key) <= 64:
        raise ValueError('Invalid signing key length')
    return key


def public_addresses(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Callback must be an HTTPS URL without credentials or fragment')
    if parsed.port not in (None, 443):
        raise ValueError('Callback must use port 443')
    addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)))
    if not addresses:
        raise ValueError('No callback addresses')
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or (getattr(ip, 'ipv4_mapped', None) and not ip.ipv4_mapped.is_global):
            raise ValueError('Non-public callback address')
    return parsed, addresses


def signed_body(subscription, secret, event, *, timestamp=None, old_secret=None):
    body = json.dumps(event, ensure_ascii=False, separators=(',', ':')).encode()
    if len(body) > 262144:
        raise ValueError('Event payload exceeds 256 KiB')
    event_id = event.get('eventId') or 'msg_verification_' + secrets.token_hex(16)
    timestamp = int(time.time()) if timestamp is None else timestamp
    signatures = []
    for value in [secret] + ([old_secret] if old_secret else []):
        signature = hmac.new(secret_key(value), f'{event_id}.{timestamp}.'.encode() + body, hashlib.sha256).digest()
        signatures.append('v1,' + base64.b64encode(signature).decode())
    return body, {'Content-Type': 'application/json', 'webhook-id': event_id,
                  'webhook-timestamp': str(timestamp), 'webhook-signature': ' '.join(signatures),
                  'X-MCP-Subscription-Id': subscription}


def _post(url, body, headers):
    parsed, addresses = public_addresses(url)
    # Connect directly to the validated IP, preserving original host for TLS and Host.
    conn = http.client.HTTPSConnection(parsed.hostname, timeout=10, context=ssl.create_default_context())
    raw = socket.create_connection((addresses[0], 443), timeout=10)
    try:
        conn.sock = conn._context.wrap_socket(raw, server_hostname=parsed.hostname)
        conn.request('POST', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''), body=body, headers=headers)
        response = conn.getresponse()
        return response.status, response.read(262145)
    finally:
        conn.close()
        raw.close()


async def deliver(subscription, event):
    old = subscription.get('old_secret') if subscription.get('rotation_until', 0) > time.time() else None
    body, headers = signed_body(subscription['id'], subscription['secret'], event, old_secret=old)
    return await asyncio.to_thread(_post, subscription['url'], body, headers)


async def verify_callback(subscription):
    from .events import EventError
    challenge = secrets.token_urlsafe(32)
    try:
        status, body = await deliver(subscription, {'type': 'verification', 'challenge': challenge})
        answer = json.loads(body).get('challenge', '')
        if not 200 <= status < 300 or not isinstance(answer, str) or not hmac.compare_digest(answer, challenge):
            raise ValueError('Challenge mismatch')
    except (TimeoutError, socket.timeout):
        raise EventError(-32015, 'Callback verification failed', 'timeout') from None
    except (ValueError, OSError, http.client.HTTPException):
        raise EventError(-32015, 'Callback verification failed', 'challenge_failed') from None

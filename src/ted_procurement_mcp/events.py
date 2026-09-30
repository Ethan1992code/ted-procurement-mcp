"""ChatGPT MCP Events draft: tender.created with webhook subscriptions."""
import hashlib
import json
import time
from datetime import datetime, timezone
from jsonschema import validate, ValidationError
from .webhook_delivery import secret_key, verify_callback

FILTER_SCHEMA = {'type': 'object', 'properties': {
    'keywords': {'type': 'string', 'minLength': 1, 'maxLength': 300},
    'cpv_codes': {'type': 'array', 'maxItems': 30, 'items': {'type': 'string', 'pattern': '^[0-9]{2,8}[*]?$'}},
    'countries': {'type': 'array', 'maxItems': 30, 'items': {'type': 'string', 'pattern': '^[A-Z]{2,3}$'}},
    'form_type': {'type': 'string', 'enum': ['competition']}}, 'additionalProperties': False,
    'anyOf': [{'required': ['keywords']}, {'required': ['cpv_codes'], 'properties': {'cpv_codes': {'minItems': 1}}}]}
PAYLOAD_SCHEMA = {'type': 'object', 'properties': {
    'publication_number': {'type': 'string'}, 'title': {'type': ['string', 'null']},
    'publication_date': {'type': ['string', 'null']}, 'ted_url': {'type': 'string'},
    **{k: {'type': 'array'} for k in ['buyer_names', 'buyer_countries', 'cpv_codes', 'deadlines', 'estimated_values']}},
    'required': ['publication_number', 'ted_url'], 'additionalProperties': False}
EVENT = {'name': 'tender.created', 'description': 'New TED competition notices matching supplier keywords (implicit AND), CPV and buyer countries. First scan establishes a silent baseline. Detected at the next configured scan; no replay.', 'delivery': ['webhook'], 'inputSchema': FILTER_SCHEMA, 'payloadSchema': PAYLOAD_SCHEMA}


class EventError(Exception):
    def __init__(self, code, message, reason=None):
        super().__init__(message)
        self.code, self.reason = code, reason


def subscription_id(owner, params):
    identity = [owner, params['delivery']['url'], params['name'], params.get('arguments', {})]
    return 'sub_' + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class EventService:
    def __init__(self, store, *, verify=verify_callback):
        self.store, self.verify = store, verify

    def _validate(self, owner, params, *, signing):
        if not owner:
            raise EventError(-32001, 'Authentication required')
        try:
            if params['name'] != EVENT['name'] or params['delivery']['mode'] != 'webhook':
                raise ValueError()
            validate(params.get('arguments', {}), FILTER_SCHEMA)
            from urllib.parse import urlsplit
            url = urlsplit(params['delivery']['url'])
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment or url.port not in (None, 443):
                raise ValueError()
            if signing:
                secret_key(params['delivery']['secret'])
            if params.get('cursor') is not None:
                raise ValueError()
            ttl = params.get('ttlMs', 86400000)
            if ttl is not None and (type(ttl) is not int or ttl <= 0):
                raise ValueError()
        except (KeyError, TypeError, ValueError, ValidationError):
            raise EventError(-32602, 'Invalid event subscription arguments') from None

    async def subscribe(self, owner, params):
        self._validate(owner, params, signing=True)
        identity = subscription_id(owner, params)
        old = self.store.get(identity)
        now = time.time()
        ttl = params.get('ttlMs', 86400000)
        expires = now + min(ttl if ttl is not None else 86400000, 86400000) / 1000
        sub = {'id': identity, 'owner': owner, 'arguments': params.get('arguments', {}),
               'url': params['delivery']['url'], 'secret': params['delivery']['secret'],
               'expires': expires, 'active': True, 'created': now, 'baseline': False, 'scan_token': None}
        if old and old.get('active') and old['expires'] > now:
            sub.update({k: old[k] for k in ['created', 'baseline', 'scan_token']})
            if old['secret'] != sub['secret']:
                sub.update(old_secret=old['secret'], rotation_until=now + 300)
        # Always verify before storing: secrets/URLs are never trusted without challenge.
        await self.verify(sub)
        self.store.put(sub)
        return {'id': identity, 'refreshBefore': datetime.fromtimestamp(expires, timezone.utc).isoformat(), 'cursor': None, 'truncated': False}

    def unsubscribe(self, owner, params):
        self._validate(owner, params, signing=False)
        sub = self.store.get(subscription_id(owner, params))
        if sub:
            sub['active'] = False
            self.store.put(sub)
        return {}

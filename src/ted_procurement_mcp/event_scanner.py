"""Bounded TED scans and durable webhook retries, run from a protected cron."""
import asyncio
import hashlib
import time
from datetime import datetime, timezone
from .models import TedSearchRequest
from .normalizer import DEFAULT_NOTICE_FIELDS, extract_notice_rows, normalise_notice
from .query_builder import build_procurement_query
from .webhook_delivery import deliver


class EventScanner:
    def __init__(self, store, client, *, authorized, send=deliver):
        self.store, self.client, self.authorized, self.send = store, client, authorized, send

    async def run(self):
        counts = {'subscriptions_scanned': 0, 'delivered': 0, 'failed': 0}
        deadline = time.monotonic() + 40
        for sub in self.store.active():
            if time.monotonic() > deadline:
                break
            if not await self.authorized(sub['owner']):
                self.store.replace(sub, {**sub, 'active': False})
                continue
            args = sub['arguments']
            query = build_procurement_query(keywords=args.get('keywords'), cpv_codes=args.get('cpv_codes'),
                buyer_countries=args.get('countries'), form_type='competition',
                date_from=datetime.fromtimestamp(sub['created'], timezone.utc).date())
            # Resume an unfinished iteration; suppress all baseline pages, not only page 1.
            try:
                request = TedSearchRequest(query=query, fields=DEFAULT_NOTICE_FIELDS, limit=100,
                    scope='ALL', pagination_mode='ITERATION', iteration_next_token=sub.get('scan_token'))
                payload = await self.client.search(request)
                for row in extract_notice_rows(payload):
                    notice = normalise_notice(row)
                    number = notice.get('publication_number')
                    if not number:
                        continue
                    data = {k: notice.get(k) for k in ['publication_number', 'title', 'publication_date']}
                    data.update({k: notice.get(k) or [] for k in ['buyer_names', 'buyer_countries', 'cpv_codes', 'deadlines', 'estimated_values']})
                    data['ted_url'] = 'https://ted.europa.eu/en/notice/-/detail/' + number
                    event = {'eventId': 'evt_' + hashlib.sha256(number.encode()).hexdigest(), 'name': 'tender.created',
                        'timestamp': datetime.now(timezone.utc).isoformat(), 'data': data, 'cursor': None}
                    self.store.enqueue(sub['id'], event, baseline=not sub['baseline'])
                # Never overwrite a concurrently refreshed or cancelled subscription.
                current = self.store.get(sub['id'])
                if not current or not current['active'] or current['expires'] <= time.time():
                    continue
                updated = {**current, 'scan_token': payload.get('iterationNextToken')}
                if not updated['scan_token']:
                    updated['baseline'] = True
                if not self.store.replace(current, updated):
                    continue
                counts['subscriptions_scanned'] += 1
            except Exception:
                counts['failed'] += 1
                # Drain any already queued records even if TED is temporarily unavailable.
            for pending in self.store.pending(sub['id']):
                if time.monotonic() > deadline:
                    break
                current = self.store.get(sub['id'])
                if not current or not current['active'] or current['expires'] <= time.time():
                    break
                if not await self.authorized(current['owner']):
                    self.store.replace(current, {**current, 'active': False})
                    break
                attempts = pending['attempts'] + 1
                try:
                    status, _ = await self.send(current, pending['event'])
                except (OSError, ValueError, TimeoutError):
                    status = 503
                if 200 <= status < 300:
                    state, next_attempt = 'delivered', 0
                    counts['delivered'] += 1
                else:
                    transient = status in [408, 429] or status >= 500
                    state = 'pending' if transient and attempts < 6 else 'failed'
                    next_attempt = time.time() + min(60 * 2 ** attempts, 3600)
                    counts['failed'] += 1
                    if status == 410:
                        self.store.replace(current, {**current, 'active': False})
                self.store.complete(sub['id'], pending['event_id'], state, attempts, next_attempt)
        return counts


async def owner_authorized(backend, owner):
    if owner.startswith('api:'):
        row = await asyncio.to_thread(backend.get_api_key, owner[4:])
        return bool(row and row.get('enabled'))
    if owner.startswith('oauth:') and hasattr(backend, 'client'):
        from .oauth_auth import verifier_from_env
        verifier = verifier_from_env()
        if not verifier:
            return False
        response = await asyncio.to_thread(backend.client.get,
            backend.base.replace('/rest/v1', '/auth/v1/admin/users/') + owner[6:])
        if response.status_code != 200:
            return False
        user = response.json()
        banned = user.get('banned_until')
        return bool(user.get('email', '').lower() == verifier.owner_email and user.get('email_confirmed_at')
            and not user.get('is_anonymous') and (not banned or datetime.fromisoformat(banned.replace('Z', '+00:00')).timestamp() <= time.time()))
    return False

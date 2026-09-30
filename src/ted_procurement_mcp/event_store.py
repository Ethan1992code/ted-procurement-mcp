"""Durable subscriptions and a deduplicated outbox; secrets stay server-side."""
import json
import time
import secrets


class EventStore:
    def __init__(self, backend):
        self.backend = backend
        self.local = hasattr(backend, '_connect')
        if self.local:
            with backend._connect() as conn:
                conn.executescript('''
                CREATE TABLE IF NOT EXISTS event_subscriptions(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS event_deliveries(
                    subscription_id TEXT NOT NULL, event_id TEXT NOT NULL, event TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(subscription_id,event_id));
                ''')

    def _request(self, method, table, **kwargs):
        response = self.backend.client.request(method, self.backend.base + '/' + table, **kwargs)
        self.backend._raise(response)
        return response.json() if response.content else None

    def get(self, identity):
        if self.local:
            with self.backend._connect() as conn:
                row = conn.execute('SELECT payload FROM event_subscriptions WHERE id=?', (identity,)).fetchone()
            return json.loads(row['payload']) if row else None
        rows = self._request('GET', 'event_subscriptions', params={'id': 'eq.' + identity, 'select': 'payload'})
        return rows[0]['payload'] if rows else None

    def put(self, sub):
        sub['revision'] = secrets.token_hex(16)
        if self.local:
            with self.backend._connect() as conn:
                conn.execute('INSERT INTO event_subscriptions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (sub['id'], json.dumps(sub)))
        else:
            self._request('POST', 'event_subscriptions?on_conflict=id', headers={'Prefer': 'resolution=merge-duplicates,return=minimal'}, json={'id': sub['id'], 'payload': sub})

    def replace(self, previous, replacement):
        """Optimistic update; a scan must not undo cancellation or secret refresh."""
        replacement['revision'] = secrets.token_hex(16)
        if self.local:
            with self.backend._connect() as conn:
                result = conn.execute('UPDATE event_subscriptions SET payload=? WHERE id=? AND json_extract(payload,\'$.revision\')=?',
                    (json.dumps(replacement), previous['id'], previous['revision']))
            return result.rowcount == 1
        rows = self._request('PATCH', 'event_subscriptions', params={'id': 'eq.' + previous['id'], 'payload->>revision': 'eq.' + previous['revision']},
            headers={'Prefer': 'return=representation'}, json={'payload': replacement})
        return bool(rows)

    def active(self):
        if self.local:
            with self.backend._connect() as conn:
                rows = [json.loads(r['payload']) for r in conn.execute('SELECT payload FROM event_subscriptions').fetchall()]
        else:
            rows = []
            offset = 0
            while True:
                page = self._request('GET', 'event_subscriptions', params={'select': 'payload', 'order': 'id.asc', 'limit': '1000', 'offset': str(offset)})
                rows.extend(r['payload'] for r in page)
                if len(page) < 1000:
                    break
                offset += 1000
        now = time.time()
        return [r for r in rows if r.get('active') and r['expires'] > now]

    def enqueue(self, sub, event, *, baseline):
        status = 'baseline' if baseline else 'pending'
        if self.local:
            with self.backend._connect() as conn:
                conn.execute('INSERT OR IGNORE INTO event_deliveries(subscription_id,event_id,event,status) VALUES (?,?,?,?)', (sub, event['eventId'], json.dumps(event), status))
        else:
            self._request('POST', 'event_deliveries?on_conflict=subscription_id,event_id', headers={'Prefer': 'resolution=ignore-duplicates,return=minimal'}, json={'subscription_id': sub, 'event_id': event['eventId'], 'event': event, 'status': status})

    def pending(self, sub):
        if self.local:
            with self.backend._connect() as conn:
                rows = conn.execute("SELECT * FROM event_deliveries WHERE subscription_id=? AND status='pending' AND next_attempt<=? ORDER BY event_id LIMIT 20", (sub, time.time())).fetchall()
            return [{**dict(r), 'event': json.loads(r['event'])} for r in rows]
        return self._request('GET', 'event_deliveries', params={'subscription_id': 'eq.' + sub, 'status': 'eq.pending', 'next_attempt': 'lte.' + str(time.time()), 'order': 'event_id.asc', 'limit': '20'})

    def complete(self, sub, event, status, attempts, next_attempt):
        if self.local:
            with self.backend._connect() as conn:
                conn.execute('UPDATE event_deliveries SET status=?, attempts=?, next_attempt=? WHERE subscription_id=? AND event_id=?', (status, attempts, next_attempt, sub, event))
        else:
            self._request('PATCH', 'event_deliveries', params={'subscription_id': 'eq.' + sub, 'event_id': 'eq.' + event}, json={'status': status, 'attempts': attempts, 'next_attempt': next_attempt})

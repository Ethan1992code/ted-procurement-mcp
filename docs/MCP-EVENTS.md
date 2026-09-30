# TED tender.created Events

## Status and rollout

Implemented behind `MCP_EVENTS_ENABLED=1`; OFF by default. This branch is not proof
of a deployed or subscribed ChatGPT automation. Production database migration,
environment configuration, deployment, plugin rescan and a real callback test
must complete before advertising live monitoring.

1. Apply `schema/events.sql` to the database named by the deployment's
   `SUPABASE_URL`. The connected Supabase account must have access to that project.
   Do not use the OAuth issuer project unless it is also the warehouse database.
2. Set `MCP_REQUIRE_API_KEY=1`, keep existing Supabase warehouse and OAuth settings,
   set a fresh `CRON_SECRET`, and set `MCP_EVENTS_ENABLED=1` only after the schema
   succeeds. Neither the signing secret nor service-role key goes into frontend code.
3. Deploy this branch. Configure a scheduler to GET `/internal/events/scan` with
   `Authorization: Bearer <CRON_SECRET>`. Vercel Cron can use the same path and
   inject the configured secret. Choose frequency for your Vercel plan; hourly
   example below requires a plan that permits it. No scheduler is added automatically.

   ```json
   {"crons": [{"path": "/internal/events/scan", "schedule": "0 * * * *"}]}
   ```
4. Rescan the MCP endpoint in the ChatGPT plugin configuration. Confirm
   `tender.created` appears alongside tools. Ask ChatGPT to monitor a narrow product
   keyword and specify its analysis/notification instructions.
5. Confirm callback verification, stored subscription, first silent baseline scan,
   then a matching newly published notice and an acknowledged signed delivery.
   Verify ChatGPT actually runs the instructions. Finally cancel monitoring and
   confirm no further deliveries. Never push fabricated tenders into a real chat.

## Protocol and behavior

- Same authenticated `/mcp` endpoint: `events/list`, `events/subscribe`,
  `events/unsubscribe`. `server/discover` retains SDK capabilities and adds events.
- MCP SDK 2.2 lacks native application webhook event handlers, so the optional ASGI
  adapter implements the draft methods. Existing SDK tools and discovery remain
  delegated to the SDK. HTTP only; the CLI stdio mode does not advertise this adapter.
- Requires MCP protocol `2026-07-28` for discovery and the normal protocol request
  envelope and `mcp-method` header. Events requests accept the draft examples with
  or without envelope metadata; the plugin client provides its own transport headers.
- Filters: `keywords` (TED implicit AND), `cpv_codes`, `countries` (ISO2/ISO3),
  `form_type` (`competition` only). At least one keyword or CPV filter is required.
  TED applies filters to full notices before summaries are produced. Alternatives
  such as GPS versus animal tracking should use separate subscriptions.
- Deterministic subscription identity includes authenticated account, callback,
  event name and canonical arguments. Refreshes preserve the scan position.
- Finite lifetime: at most 24 hours; clients refresh before expiration. A null TTL
  request is granted a finite 24-hour expiration. No replay; cursor is always null.
- First iteration after subscription is a silent baseline. This prevents old
  notices from generating a notification flood. Notices that appear during an
  unfinished baseline are also suppressed. Baseline completion depends on result size.
- One 100-notice ITERATION page per subscription per scan; scan token persists.
  Completed iterations restart to discover additions. Event is **first detection**
  of a publication number after the baseline, not a guarantee of immediate TED
  publication delivery. No tender updates, awards or deadline changes in this MVP.
- Durable outbox uses `(subscription_id,event_id)` uniqueness. Delivery is at least
  once; overlapping scans or acknowledgment loss can repeat the same ID. Receiving
  clients should deduplicate IDs. Transient failures retry on the next scheduled
  scan, with exponential backoff and at most six attempts. 410 disables the
  subscription; 413 and other permanent errors are not retried.
- HMAC SHA256 Standard Webhooks over the exact transmitted bytes. Refresh secret
  rotation signs with old and new keys for five minutes. Callback ownership is
  challenged before every subscription acceptance (no verification cache yet).
- HTTPS public destinations only, port 443, DNS validation at connection time,
  direct connection to a validated IP with original TLS hostname, no redirect or
  proxy following. Maximum payload 256 KiB; 10-second callback timeout.
- Ownership is rechecked before delivery: API key still enabled; OAuth owner's
  current verified email matches the configured single-owner verifier and the
  account is not anonymous or banned. OAuth client/session revocation beyond these
  account checks is not yet implemented. Stop subscriptions explicitly when
  disconnecting a client. Pending rows remain stored but cannot deliver after expiry.
- Tables have RLS and no anon/authenticated grants. Only server `service_role`
  accesses subscription signing secrets and the outbox. No secrets in cron results.

## Verification

Run `pytest` after installing `pip install -e '.[dev]'`. Tests cover identity,
account isolation, persistent restart state, invalid subscriptions, callback
failure, signatures, private address rejection, baseline/deduplication, retries,
owner revocation, cancellation races, Supabase REST adapter requests, actual SDK
discovery and the disabled-by-default rollout requirements.

Production Supabase schema and a genuine ChatGPT callback remain separate live
acceptance checks; local tests cannot establish them.

Official protocol reference: https://developers.openai.com/plugins/build/mcp-events

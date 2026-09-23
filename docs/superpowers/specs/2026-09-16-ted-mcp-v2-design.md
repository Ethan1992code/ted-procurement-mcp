# TED Procurement Intelligence MCP V2 Design

## Goal
Turn the V1 read-through TED MCP into a deployable data product that can automatically infer likely CPV codes from live TED evidence, persist procurement intelligence, match supplier profiles, expose daily opportunity feeds, and support API-key/quota controls.

## Architecture
V2 keeps TED Search API v3 as the authoritative source and preserves the V1 read-only tools. New components are isolated behind service interfaces:

1. `CpvDiscoveryService` derives likely CPV codes from recent TED notices that match a product phrase. It ranks codes by frequency and supporting sample notices rather than relying on an LLM or a hand-maintained taxonomy.
2. `NoticeStore` persists normalized notices, supplier profiles, API keys/usage, and sync cursors. The default local implementation uses SQLite. A Supabase REST implementation is provided for production deployments and requires only HTTPS + env vars.
3. `SyncService` iterates TED using `ITERATION`, upserts normalized notices, and records sync state. It has hard page/item caps per run so a single MCP call cannot accidentally perform an unbounded crawl.
4. `SupplierMatcher` enriches V1 rule scoring with supplier profile constraints such as products, target countries, CPV preferences, certifications, MOQ, lead time, and excluded markets. Facts that cannot be verified from TED remain advisory signals, not eligibility claims.
5. `ApiKeyGate` protects remote `/mcp` requests when configured, tracks request counts, and applies simple per-key daily quotas. It is disabled for local stdio and may be disabled explicitly for a public demo.
6. `asgi.py` exposes the MCP server as a standard ASGI app for production hosts. `/health` remains unauthenticated; `/mcp` is protected when API keys are configured.

## V2 MCP Tools
Existing eight V1 tools remain. Add:

- `suggest_cpv(product, countries?, days=365, limit=100)`
- `upsert_supplier_profile(profile_id, ...)`
- `get_supplier_profile(profile_id)`
- `match_supplier_opportunities(profile_id, days=30, limit=50)`
- `sync_notices(query, fields?, max_pages=4, page_size=250)`
- `daily_opportunities(profile_id, since_hours=24, limit=50)`
- `warehouse_stats()`

## Persistence
SQLite tables:

- `notices(publication_number PRIMARY KEY, publication_date, title, buyer_names_json, buyer_countries_json, cpv_codes_json, payload_json, updated_at)`
- `supplier_profiles(profile_id PRIMARY KEY, profile_json, updated_at)`
- `sync_state(sync_key PRIMARY KEY, iteration_next_token, updated_at)`
- `api_keys(key_hash PRIMARY KEY, name, daily_quota, enabled, created_at)`
- `api_usage(key_hash, usage_date, request_count, PRIMARY KEY(key_hash, usage_date))`

Supabase uses tables with the same logical fields; `schema/supabase.sql` is the canonical setup script.

## Deployment
Primary target: Vercel-compatible ASGI deployment if the project can be deployed through the connected Vercel account. The Python MCP SDK's `streamable_http_app()` is used with stateless JSON responses. A host allowlist is configured from `MCP_ALLOWED_HOSTS`; production deployments must set the Vercel hostname or custom domain. If direct deployment cannot ingest this generated sandbox project, the deliverable still includes the complete deployment files plus one minimal manual import path.

## Safety / correctness constraints
- TED remains the source of procurement facts; V2 does not fabricate missing tender values, winners, deadlines, certifications, or eligibility.
- CPV suggestions are labeled as inferred from matching TED notices and include support counts/examples.
- Sync operations are bounded by `max_pages <= 20`, `page_size <= 250`.
- Quota/auth logic never logs raw API keys.
- Production database secrets are environment variables only.
- `daily_opportunities` reports only stored records newer than the requested cutoff; it never implies the warehouse is complete unless a successful sync window covers that period.

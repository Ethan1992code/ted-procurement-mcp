# TED Procurement Intelligence MCP Design

## Goal
Build a small, sellable data MCP that turns the EU TED public procurement Search API into structured procurement intelligence for suppliers and AI agents.

## V1 scope
The server exposes eight read-only tools:

1. `raw_ted_search` — execute an expert query against TED Search API v3.
2. `search_procurements` — search procurement notices by keywords, CPV, buyer country, date range and form type.
3. `find_opportunities` — search recent competition notices and attach a transparent rule-based opportunity score.
4. `get_notice` — retrieve a notice by publication number.
5. `find_buyers` — aggregate buyers that recently procured a product/category.
6. `buyer_history` — retrieve recent notices for one buyer.
7. `find_awards` — search result notices and surface winner information where TED contains it.
8. `market_stats` — aggregate notices by buyer country, CPV, form type, buyer and estimated value currency.

## Architecture
- `TedClient` owns HTTP communication with `POST https://api.ted.europa.eu/v3/notices/search`.
- `query_builder.py` creates valid TED Expert Search strings and normalises EU country codes.
- `normalizer.py` converts TED's field-oriented responses into stable internal notice dictionaries while tolerating scalar, list and multilingual value shapes.
- `scoring.py` provides explainable opportunity scores; it does not use an LLM and does not claim business suitability beyond the supplied criteria.
- `service.py` implements the eight business-level operations and aggregations.
- `mcp_adapter.py` registers service operations as MCP tools without depending on the MCP SDK itself, enabling offline unit tests.
- `server.py` is the thin MCP SDK v2 entry point. It supports stdio and Streamable HTTP.

## Data policy
TED Search API is an anonymous public API for published notices. V1 is read-only and stores no personal data or notices in a database. It returns source fields supplied by TED plus derived counts/scores. Missing source data remains missing; no values are fabricated.

## Request strategy
Default fields stay under TED's 10k-fields-per-page limit. Normal queries use `PAGE_NUMBER`; raw search also accepts `ITERATION` and an iteration token for bulk retrieval. Page size is capped at 250.

## Query strategy
- Full text uses `FT ~ (...)`.
- CPV supports exact/prefix matching via `classification-cpv = (...)`.
- Countries use `buyer-country IN (...)` and accept ISO-2 or ISO-3 input for EU/EEA/common TED countries.
- Date ranges use `publication-date = (YYYYMMDD <> YYYYMMDD)`.
- Award searches use `form-type = result`.
- Active opportunities use `form-type = competition` plus TED request scope `ACTIVE`.

## Opportunity score
Score is 0–100 and is intentionally transparent:
- keyword overlap: up to 35
- requested CPV overlap: up to 25
- requested country match: up to 15
- freshness: up to 15
- future tender deadline present: up to 10

The result includes the score components so downstream agents can override or re-rank.

## Non-goals for V1
No database, scheduler, billing, API keys, vector search, LLM enrichment, supplier profile persistence, email alerts, or automated bid submission. Those are V2+ concerns after the data product proves demand.

## Testing
Unit tests cover query building, payload serialization, response row extraction/normalization, scoring, aggregations, MCP registration, and HTTP client error handling via `httpx.MockTransport`. A live smoke test is included but is opt-in because it requires internet access.

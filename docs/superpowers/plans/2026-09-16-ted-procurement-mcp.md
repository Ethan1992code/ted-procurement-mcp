# TED Procurement Intelligence MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested Python MCP server that converts TED Search API v3 procurement notices into structured supplier-facing intelligence.

**Architecture:** Keep TED transport, query construction, normalization, scoring, aggregation, and MCP registration isolated. The MCP layer is a thin adapter over a testable service so most tests can run without the MCP SDK or network access.

**Tech Stack:** Python 3.11+, httpx, Pydantic 2, MCP Python SDK 2.x, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-ted-procurement-mcp-design.md`

## Global Constraints
- TED Search endpoint: `POST https://api.ted.europa.eu/v3/notices/search`.
- Search API does not require authentication for published notices.
- Page size must be 1–250.
- Support both `PAGE_NUMBER` and `ITERATION` pagination modes.
- V1 is read-only and has no persistent database.
- All derived scores must expose components and never invent source values.

---

### Task 1: Query builder and request model

**Files:**
- Create: `src/ted_procurement_mcp/models.py`
- Create: `src/ted_procurement_mcp/query_builder.py`
- Test: `tests/test_query_builder.py`

**Interfaces:**
- Produces: `TedSearchRequest.to_payload()`, `build_procurement_query(...)`, `normalise_country_codes(...)`.

- [ ] Write tests for keyword, CPV, country, date and form-type clauses and request serialization.
- [ ] Run tests and confirm they fail because modules are missing.
- [ ] Implement the minimal models/query builder.
- [ ] Re-run targeted tests until green.

### Task 2: TED HTTP client and response row extraction

**Files:**
- Create: `src/ted_procurement_mcp/ted_client.py`
- Create: `src/ted_procurement_mcp/normalizer.py`
- Test: `tests/test_ted_client.py`
- Test: `tests/test_normalizer.py`

**Interfaces:**
- Consumes: `TedSearchRequest`.
- Produces: `TedClient.search()`, `extract_notice_rows()`, `normalise_notice()`.

- [ ] Write failing tests using `httpx.MockTransport`, including a non-200 error and multiple possible TED response row keys.
- [ ] Implement async POST, timeout/error handling, row extraction and stable field normalization.
- [ ] Run targeted tests until green.

### Task 3: Explainable scoring

**Files:**
- Create: `src/ted_procurement_mcp/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Produces: `score_opportunity(notice, product, requested_cpv, requested_countries, today)`.

- [ ] Write failing tests for exact keyword/CPV/country matches, freshness and future deadline.
- [ ] Implement a capped 0–100 score plus component dictionary.
- [ ] Run targeted tests until green.

### Task 4: Procurement intelligence service

**Files:**
- Create: `src/ted_procurement_mcp/service.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `TedClient`, query builder, normalizer, scoring.
- Produces eight async methods matching the MCP tools in the spec.

- [ ] Write failing tests with a fake TED client for buyer aggregation, awards, stats, notice lookup and opportunity scoring.
- [ ] Implement the smallest service methods that satisfy those behaviours.
- [ ] Run targeted tests until green.

### Task 5: MCP adapter and server entry point

**Files:**
- Create: `src/ted_procurement_mcp/mcp_adapter.py`
- Create: `src/ted_procurement_mcp/server.py`
- Create: `src/ted_procurement_mcp/__init__.py`
- Test: `tests/test_mcp_adapter.py`

**Interfaces:**
- Consumes: `ProcurementService`.
- Produces: `register_tools(server, service)` and executable `ted-procurement-mcp` entry point.

- [ ] Write a failing fake-server registration test asserting all eight tool names.
- [ ] Implement decorator registration without importing MCP SDK in the adapter.
- [ ] Add thin SDK v2 server entry point supporting stdio and Streamable HTTP `/mcp`.
- [ ] Run targeted tests until green and compile all Python files.

### Task 6: Packaging, examples and offline/live verification

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `Dockerfile`
- Create: `README.md`
- Create: `examples/live_smoke_test.py`
- Create: `examples/mcp_config_example.json`

**Interfaces:**
- Produces: installable package, Docker build recipe, local stdio/HTTP usage, live TED smoke test.

- [ ] Document installation, tool inputs, architecture, limits and data caveats.
- [ ] Run `pytest -q` and `python -m compileall src examples`.
- [ ] Run smoke test only if network is available; otherwise record the environmental limitation without claiming it passed.
- [ ] Create a distributable zip archive.

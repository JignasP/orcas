# ADR 0001 — Retrieval service API contract (`contracts/retrieval.openapi.yaml`)

- **Status:** Proposed (awaiting Day-3 freeze sign-off from Mitesh, Tahir, Jignas)
- **Date:** 2026-10-12
- **Owner:** Tahir (retrieval producer); co-authored with Mitesh (consumer) and Jignas (contracts editor)
- **Requirements:** F4, L1, D2, D7

## Context
The agent worker (Mitesh) and the evaluation harness / web client (Tahir) need a frozen,
read-only retrieval interface to build against independently before the service exists.
Per the collaboration rules, `contracts/` changes need an ADR and three approvals.

## Decision
Adopt `contracts/retrieval.openapi.yaml` (OpenAPI 3.0.3) with these endpoints:

| Endpoint | Purpose | Consumer |
|---|---|---|
| `POST /v1/search` | dense/hybrid search, filters: framework, doc_id, entity_type, product_type, chunk_type | worker, eval |
| `GET /v1/clauses/{doc_id}/{clause_id}` | fetch a clause for cross-reference following | worker |
| `GET /v1/chunks/{chunk_id}` | resolve a chunk; optional `quote_span` verified as substring | verifier, eval |
| `GET /v1/index/info` | freshness: `index_version`, build time, per-doc versions, chunk counts, model tag | dashboard, determination stamp |
| `GET /health`, `GET /metrics` | ops | compose, Prometheus |

Key contract rules baked in:
- `entity_type` enum is aligned with `determination.v1` (broker, mutual_fund, registrar,
  listed_company, depository, bank, other, unknown).
- `chunk_type` distinguishes `clause` (citable) from `scope_card` (finding aid only). A
  scope-card passage carries `source_clause_chunk_id` so the agent cites the clause, not the card.
- Search responses expose `cache_hit`, `index_version` and `query_normalized` to support the
  D7 retrieval-cache key = (normalised query, filters, index_version).

## Alternatives considered
- **GraphQL / a single generic `/query`** — rejected: the four access patterns are distinct and
  benefit from typed, separately-mockable endpoints.
- **Returning scope cards as first-class citations** — rejected: violates the "citations must
  resolve to a source clause" rule; scope cards are derived summaries.

## Consequences
- Mitesh can build `FakeRetrievalClient` directly from this schema immediately.
- Hybrid mode is specified but `hybrid_enabled` defaults to the A/B outcome (Slice 4); until then
  callers pass `mode: dense`.
- Any later change (e.g. new filter) requires a new ADR + three approvals.

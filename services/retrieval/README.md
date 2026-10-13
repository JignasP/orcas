# services/retrieval — FastAPI retrieval service (v0)

Read-only search/lookup over Chroma + MiniLM, implementing `contracts/retrieval.openapi.yaml`.

## Run
```bash
# from repo root, venv active (index must be built first: python -m services.ingest)
uvicorn services.retrieval.app:app --port 8001
```

## Endpoints (v0)
| Endpoint | Status |
|---|---|
| `POST /v1/search` | dense search; filters `framework`, `doc_id`, `chunk_type` pushed to Chroma |
| `GET /v1/chunks/{chunk_id}` | resolve a chunk; `?quote_span=` verifies the span is a substring |
| `GET /v1/clauses/{doc_id}/{clause_id}` | fetch by positional clause id |
| `GET /v1/index/info` | freshness + per-doc info from `index_info.json` |
| `GET /health` | **liveness** — always 200 while the process is up (never flaps during ingest) |
| `GET /ready` | **readiness** — 200 only once the index is openable and non-empty (what compose waits on) |

## Hardening (Slice 7)
Every `/v1/search` is bounded by `RETRIEVAL_TIMEOUT_S` (default 10s) → 504 on overrun. An empty
index is handled gracefully (search returns `count: 0`, lookups 404; `/ready` stays 503). The
Dockerfile healthcheck probes `/ready`.

## Metrics
`GET /metrics` exposes Prometheus series (`orcas_` prefix): `orcas_retrieval_requests_total`,
`orcas_retrieval_latency_seconds`, `orcas_retrieval_results_per_query`,
`orcas_retrieval_cache_{hits,misses}_total` (always a miss until the Slice-6 cache),
`orcas_index_chunks`, `orcas_index_built_timestamp`.

## Docker
Built from the repo root; the embedding model is baked in at build time (no runtime download).
The Chroma index is read from the `/data` volume that `ingest` writes.
```bash
docker build -f services/ingest/Dockerfile    -t orcas-ingest .
docker build -f services/retrieval/Dockerfile -t orcas-retrieval .
docker volume create orcas-data
docker run --rm -v orcas-data:/data orcas-ingest                 # populate the index
docker run --rm -p 8001:8001 -v orcas-data:/data orcas-retrieval # serve
curl -s localhost:8001/health && curl -s localhost:8001/metrics | head
```
`/health` returns 503 until the index volume is populated, then 200.

## Filters & modes (Slice 4)
- Scalar filters `framework` / `doc_id` / `chunk_type` are pushed to Chroma.
- `entity_type` / `product_type` are **post-filters** (they are list-valued metadata; Chroma
  equality can't express them) — the service over-fetches, then filters.
- `mode=dense` (default) or `mode=hybrid` (dense + BM25, reciprocal-rank fused). Per the Slice-4
  A/B, hybrid showed no recall gain on this corpus, so `index/info.hybrid_enabled=false`; it stays
  available via `mode`. See `docs/work/tahir/chunking.md`.
- Scores are cosine similarity (`1 - distance`) for dense; RRF fusion scores for hybrid.

## Cache (D7, Slice 6)
`search()` is cached by `sha256(normalised_query | filters | mode | k | index_version)`
(`services/retrieval/cache.py`). Backend: Redis when `REDIS_URL` is set (shared across workers),
otherwise a process-local TTL dict. `cache_hit` is reported per response and counted in
`orcas_retrieval_cache_{hits,misses}_total`. Measured effect: `python -m eval.cache_effect`
(warm p95 ≈ 0.1 ms vs cold ≈ 42 ms on the scenario set).

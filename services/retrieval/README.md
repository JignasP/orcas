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
| `GET /health` | ok once the index is openable and non-empty |

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

## v0 limitations (resolved in later slices)
- `mode=hybrid` and `entity_type`/`product_type` filters are accepted but not yet effective —
  entity/product metadata and BM25 hybrid land in **Slice 4**.
- `/metrics` (Prometheus) and the Redis retrieval cache land in **Slice 4 / Slice 6**.
- Scores are cosine similarity (`1 - distance`).

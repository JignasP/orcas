# services/ingest — `orcas-ingest` (v0)

Idempotent corpus pipeline: **parse → naive chunk → MiniLM embed → upsert to Chroma** (D2, L1).

## Run
```bash
# from repo root, venv active
python -m services.ingest                      # index all indexed_ready docs in corpus/MANIFEST.yaml
python -m services.ingest --reindex-if-changed # idempotent full pass (no-op when unchanged)
python -m services.ingest --re-embed --model-tag minilm-l6-v2
```

## Design
- **Idempotent:** chunk `id = sha256(doc_id | clause_id | text | model_tag)`. A second run upserts the
  same ids and reports `no changes (idempotent)`; re-chunking deletes a document's stale ids.
- **Chunking strategies** (`--strategy`):
  - `clause` (default): structure-aware, clause-aligned — real `clause_id` + `heading_path`,
    preamble captured, long clauses split into `#k` sub-chunks, plus one **scope card** per framework.
    Chunks tagged with inferred `entity_types[]` / `product_types[]`. See `docs/work/tahir/chunking.md`.
  - `fixed`: fixed-size word windows (`--chunk-words`/`--overlap`), positional `clause_id` — the A/B baseline.
- **Re-embedding (no re-parse):** `--re-embed --model-tag X` re-embeds the stored chunk texts under
  tag `X` by id. Same tag → vectors replaced in place (ids/count stable); a new tag → new id set,
  old-tag chunks removed. No PDF is re-parsed.
- **Freshness:** writes `data/index_info.json` (built_at, model_tag, per-doc chunk counts, throughput,
  `index_version`) which the retrieval service serves at `/v1/index/info`.
- Chroma persistence dir: `ORCAS_CHROMA_DIR` (default `./data/chroma`). Nothing hard-codes paths/model ids.

Current corpus → 606 chunks: SEBI MF Regs 539, RBI IOS 39, SEBI SCORES 28.

## Docker
```bash
docker build -f services/ingest/Dockerfile -t orcas-ingest .
docker run --rm -v orcas-data:/data orcas-ingest   # writes Chroma index + index_info.json to /data
```
The embedding model and the corpus PDFs are baked into the image; it writes to the `/data`
volume the retrieval service reads. Idempotent: re-running on the same corpus is a no-op.

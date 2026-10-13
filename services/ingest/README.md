# services/ingest — `orcas-ingest` (v0)

Idempotent corpus pipeline: **parse → naive chunk → MiniLM embed → upsert to Chroma** (D2, L1).

## Run
```bash
# from repo root, venv active
python -m services.ingest                      # index all indexed_ready docs in corpus/MANIFEST.yaml
python -m services.ingest --reindex-if-changed # idempotent full pass (no-op when unchanged)
python -m services.ingest --re-embed --model-tag minilm-l6-v2
```

## Design (v0)
- **Idempotent:** chunk `id = sha256(doc_id | clause_id | text | model_tag)`. A second run upserts the
  same ids and reports `no changes (idempotent)`; re-chunking deletes a document's stale ids.
- **Naive chunking:** fixed-size word windows (default 180 words, 40 overlap) with a positional
  `clause_id` (`p{page}w{window}`). Structure-aware, clause-aligned segmentation with heading paths,
  scope cards and entity/product metadata is **Slice 4**.
- **Freshness:** writes `data/index_info.json` (built_at, model_tag, per-doc chunk counts, throughput,
  `index_version`) which the retrieval service serves at `/v1/index/info`.
- Chroma persistence dir: `ORCAS_CHROMA_DIR` (default `./data/chroma`). Nothing hard-codes paths/model ids.

Current corpus → 606 chunks: SEBI MF Regs 539, RBI IOS 39, SEBI SCORES 28.

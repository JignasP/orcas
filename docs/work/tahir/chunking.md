# Chunking & retrieval strategy (L1 — documented, assessed)

How ORCAS segments the corpus and why, with the Slice-4 benchmark that justifies the choice.

## Strategies
- **fixed** (`--strategy fixed`): fixed-size word windows (180 words, 40 overlap), positional
  `clause_id` (`p{page}w{n}`). The v0 baseline, kept for the A/B.
- **clause** (`--strategy clause`, default): structure-aware, clause-aligned segmentation —
  detect top-level clause anchors (`9. Grounds of Complaint`) and `CHAPTER` headings in the
  extracted text, cut into clause-aligned chunks each carrying a real `clause_id` (e.g. `9`,
  `7B`, `preamble`) and a `heading_path` (`[chapter, clause-title]`). Preamble text before clause 1
  is captured (the RBI scope sentence lives there). Long clauses are split into `<id>#k` sub-chunks
  with overlap. Each chunk is tagged with inferred `entity_types[]` / `product_types[]`.
- **scope cards** (`chunk_type=scope_card`): one short "what this framework covers" finding aid per
  framework, each carrying `source_clause_chunk_id` → **citations resolve to the source clause, never
  to the card.**

## Benchmark (`python -m eval.benchmark_chunking`)
6 topical, framework-filtered probes (the kind of query the agent issues after reflection):

| strategy / mode | recall@5 | recall@10 | mean_hit_score | chunks |
|---|---|---|---|---|
| fixed / dense  | 1.00 | 1.00 | 0.650 | 606 |
| clause / dense | 0.833 | 0.833 | **0.719** | 637 |
| clause / hybrid | 0.833 | 0.833 | n/a (RRF) | 637 |

`mean_hit_score` = dense cosine similarity of the first correct hit (ranking sharpness).

## Findings (honest — for the report's "what did not work")
- **Fixed-window wins raw recall@k** by a small margin, for an unglamorous reason: bigger chunks
  contain more text, so a target phrase is more likely to fall inside *some* top-k chunk. This is a
  recall-vs-granularity artefact, not better retrieval.
- **Clause-aligned wins ranking sharpness** (0.719 vs 0.650) — e.g. the RBI "Grounds of Complaint"
  provision retrieves at **0.809** clause-aligned vs ~0.63 fixed — and, decisively, it produces
  **clause-level citations that resolve** (`doc_id`/`clause_id`/`quote_span`), which is what the
  Verifier's grounding check needs. Fixed-window positional ids (`p6w0`) are not citable provisions.
- **Hybrid (dense + BM25, RRF) showed no recall gain** on these probes. Per the plan's tier-3 rule
  ("keep hybrid only if the A/B shows gain"), **`hybrid_enabled=false` by default**; it remains
  available via `mode=hybrid` and will be re-tested on the full ≥20-scenario set in Slice 5.

**Decision:** ship **clause-aligned** as the production default — the marginal recall dip is
outweighed by citable, grounded provisions and sharper ranking, which is what verification and the
§4.1 case depend on.

## Caveats
Segmentation is a regex heuristic, not a legal parser: dense index pages (e.g. the MF Regulations
"arrangement of regulations") produce some noisy clause titles, and annexure numbering restarts
(disambiguated with `-2` suffixes). Documented here deliberately; refinement is possible but not
required for the routing task.

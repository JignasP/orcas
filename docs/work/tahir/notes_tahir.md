# Tahir — Running Log (notes)

> Running log of what I tried, what I rejected, and the numbers. The **"what did not work"** section of the final report is built from this file, so I log as I go — not at the end. Newest entries at the top within each slice.
>
> Convention: one dated entry per working session. Record decisions, dead ends, and measured values (recall@k, latencies, metric scores). Link commits/PRs where relevant.

---

## How to use this log
- **Date** every entry (`YYYY-MM-DD`).
- Separate **what I did** from **what I concluded**.
- Always write down **numbers** (even bad ones) — benchmarks, metric scores, cache hit ratios.
- When I reject an approach, say **why** in one line — that sentence goes straight into the report.
- Cross-link the slice in [`build-plan.md`](build-plan.md) and tick its checkbox when the slice is done.

---

## Slice 0 — Contract + corpus foundation (Days 1–3)

### 2026-10-12 — contract drafted; corpus 1/3 landed, 2/3 blocked

**Did**
- Wrote `contracts/retrieval.openapi.yaml` (OpenAPI 3.0.3): `POST /v1/search`, `GET /v1/clauses/{doc_id}/{clause_id}`, `GET /v1/chunks/{chunk_id}` (optional `quote_span` verify), `GET /v1/index/info`, `/health`, `/metrics`. `entity_type` enum aligned to `determination.v1`; `chunk_type` separates citable `clause` from `scope_card` finding aids.
- Wrote ADR `docs/decisions/0001-retrieval-contract.md` (needs 3 approvals at the Day-3 freeze).
- Downloaded **SEBI (Mutual Funds) Regulations, 1996** (consolidated to Jan 2026, 162 pp.) → `corpus/raw/`. Verified: valid PDF, text layer present (~438k chars), `sha256 79ca5ef1…230043`. Pinned in `MANIFEST.yaml`.

**Blocked / what did not work**
- **RBI Integrated Ombudsman Scheme 2021** — `rbidocs.rbi.org.in` and `website.rbi.org.in` sit behind a bot-protection WAF (TSPD/Imperva). Every `curl` variant (UA spoof, Referer, Accept headers, alt host) returned a JS challenge page or an empty reply, not the PDF. Cannot fetch programmatically.
- **SEBI SCORES master circular** — the Nov-2022 master circular page now 404s (superseded by SCORES 2.0: circular 2023/156 of 20-Sep-2023 + the April-2024 master circular). Need to pin the *current* consolidated one.
- Firecrawl MCP is out of credits (402) — used built-in WebSearch/WebFetch instead.

**Next (needs Tahir, one-time manual download — then I finish the manifest)**
Run these in your own session (the `!` prefix runs in-shell), or download via browser into `corpus/raw/`:

```
# RBI Integrated Ombudsman Scheme 2021 (base) — from a browser or your shell:
!curl -L -A "Mozilla/5.0" -o corpus/raw/rbi_integrated_ombudsman_scheme_2021.pdf \
  "https://rbidocs.rbi.org.in/rdocs/content/pdfs/RBIOS2021_121121.pdf"
# If the WAF still blocks curl, open the URL in a browser and Save As into corpus/raw/.
# Decide: base 2021 scheme, the 05-Aug-2022 amended version, or both.

# SEBI SCORES master circular (CURRENT): sebi.gov.in -> Legal -> Master Circulars,
# find the current "...Redressal of Investor Grievances through SCORES" master circular,
# Save the PDF as corpus/raw/sebi_scores_master_circular.pdf, and note its circular no./date.
```
Then tell me and I'll compute SHA-256 + text-layer, fill `MANIFEST.yaml`, and tick the Slice-0 box.

**Decision noted (provisional):** the SEBI SCORES master circular is expected to cover registrar/RTA, listed company and depository (all SEBI-regulated, all routed via SCORES), so no extra F3 source is likely needed — confirm when the PDF is in hand.

### 2026-10-13 — corpus complete (3/3), Slice 0 done

**Did**
- **RBI Integrated Ombudsman Scheme, 2021** downloaded via browser (WAF beat curl). Verified: valid 18-page PDF, text layer (~32k chars), confirmed Regulated Entity / grounds-of-complaint content. `sha256 a354a73b…d69a3e`. Pinned (base 2021 scheme; 05-Aug-2022 amendment noted but not indexed).
- **SEBI SCORES Master Circular** placed by Tahir: `SEBI/HO/OIAE/IGRD/P/CIR/2022/0150`, 07-Nov-2022, 11 pp. Verified valid PDF + text layer (~23k chars). `sha256 78a729d8…25f8b`. Pinned.

**Decisions**
- **Coverage (F3) — CONFIRMED:** the SCORES master circular covers listed companies, registered intermediaries (brokers, DPs, MFs/AMCs, registrars/RTAs), stock exchanges, depositories. One SEBI doc covers registrar/listed-co/depository → **no extra SEBI source for v0.**
- **Version — accepted the 2022 master circular** over chasing SCORES 2.0 (2023/156). Rationale: it is a clean, self-contained consolidated *Master Circular* (good for clause-aligned chunking) and fully sufficient for §4.1 jurisdiction reasoning. It is superseded by 2023/156 (timelines later cut to 21 days). **Flagged for Slice 5:** verify current SEBI timelines against 2023/156 before labelling any timeline-sensitive scenario; citations still resolve to corpus text.

**Corpus final state (all status: indexed_ready)**
| doc_id | pages | sha256 (short) |
|---|---|---|
| sebi_mutual_funds_regulations_1996 | 162 | 79ca5ef1…230043 |
| rbi_integrated_ombudsman_scheme_2021 | 18 | a354a73b…d69a3e |
| sebi_scores_master_circular (2022/0150) | 11 | 78a729d8…25f8b |

**Slice 0 = DONE.** Open follow-up: `contracts/retrieval.openapi.yaml` + ADR 0001 still need the 3-way Day-3 freeze sign-off (Mitesh + Jignas); `contracts/` is Jignas's editing domain → route via PR, not direct to main.

## Slice 1 — Ingest v0 + Retrieval v0 + §4.1 fixtures (Days 4–8)

### 2026-10-13 — ingest + retrieval working end-to-end; fixtures delivered

**Stack:** Python 3.12 venv; chromadb 0.5.23, sentence-transformers 3.4.1, torch 2.14.1, fastapi 0.143, pypdf 6.20.1. Embedding `all-MiniLM-L6-v2` (model_tag `minilm-l6-v2`), cosine space, normalised vectors.

**Built**
- `services/corpus_common/` — shared primitives so ingest+retrieval can't drift: chunk-id rule, embedding, Chroma access + metadata (de)serialisation (list fields JSON-encoded because Chroma metadata must be scalar), `index_info.json` read/write.
- `services/ingest/` — `orcas-ingest` CLI: parse (pypdf, page tracking) → naive word-window chunking (180/40) → MiniLM → Chroma upsert. **606 chunks** (SEBI MF 539, RBI 39, SEBI SCORES 28) in ~19s.
- `services/retrieval/` — FastAPI implementing the contract: `/v1/search` (framework/doc_id/chunk_type filters), `/v1/chunks/{id}` (+`quote_span` verify), `/v1/clauses/{doc}/{clause}`, `/v1/index/info`, `/health`.

**Idempotency (D2) — confirmed:** second ingest run reported `+0 new, 0 stale, no changes (idempotent)`, collection steady at 606.

**§4.1 passages located (the whole point of this slice):**
- *Apparent (SEBI, what a naive single search returns):* `sebi_scores_master_circular` `p1w1` — "listed companies, registered intermediaries and recognised MIIs…".
- *Deciding (RBI, after framework swap):* `rbi_integrated_ombudsman_scheme_2021` `p1w0` (scope: "services provided by entities **regulated by Reserve Bank**") + `p6w0` (**Grounds of Complaint** / "deficiency in service").
- Verified live: RBI-filtered search surfaces p6w0/p6w1 + scope; SEBI-filtered surfaces the SCORES passage. `/v1/search` + `/v1/chunks?quote_span=` round-trip works on the real uvicorn server.

**Deliverable:** `tests/fixtures/retrieval_fixtures.json` — 9 fixtures (ref 4.1 + 2 paraphrases, MF, broker, registrar, depository, listed-company, RBI payment). Each passage has a full `chunk_id` + an **exact-substring quote** (so `resolve_citation`/`quote_span` checks pass). **→ Mitesh handoff (Day 8).**

**Tests:** `tests/retrieval/` — 16 pass. Per-doc parse regression (page counts + markers), chunk-id idempotency + re-embed-tag disjointness, recall@k on §4.1, every fixture citation resolves w/ quote verify, HTTP smoke incl. 404 + 422.

**Decisions / deferred (as planned)**
- Naive chunking only; clause-aligned segmentation, heading paths, scope cards, entity/product metadata → **Slice 4**.
- `mode=hybrid` + `entity_type`/`product_type` filters accepted but inert in v0 (need Slice-4 metadata/BM25).
- `/metrics` + Redis retrieval cache → Slice 4 / Slice 6.
- **Weak label flagged:** `mf_redemption_delay` fixture landed on a registrar-appointment clause (`p101w2`); fine as a real passage for FakeRetrievalClient, but re-pick before using as an eval label in Slice 5.
- Build artifacts (`data/`) git-ignored — rebuilt by ingest, never committed.

## Slice 2 — Evaluation 1 package + retrieval containerized (Days 9–13)

### 2026-10-13 — Eval-1 package + containerization

**Did**
- **`docs/work/tahir/evaluation-1-package.md`** — the graded deliverable: corpus confirmation table (versions/SHA/text-layer, F3 coverage confirmed, SCORES 2.0 supersession caveat), the §4.1 apparent passage (SEBI SCORES `p1w1`) + two deciding RBI passages (`p1w0` scope, `p6w0` grounds) with exact quotes + chunk_ids, the reference `determination.v1` answer/test values, project plan + status, reproduce commands.
- **`/metrics`** on retrieval (prometheus-client): `orcas_retrieval_requests_total`, `_latency_seconds`, `_results_per_query`, `_cache_{hits,misses}_total` (miss-only until Slice 6), `orcas_index_chunks`, `orcas_index_built_timestamp`. 2 new tests → **18 pass**.
- **Dockerfiles** `services/retrieval/Dockerfile` + `services/ingest/Dockerfile` (+ root `.dockerignore`): python:3.11-slim, `libgomp1`, **embedding model baked at build** (`RUN python -c "SentenceTransformer(...)"`) so no runtime download; retrieval reads the Chroma index from the `/data` volume ingest writes; retrieval HEALTHCHECK on `/health`. Build/run documented in service READMEs.

**Validated**
- Container env wiring: `ORCAS_DATA_DIR=/data` (ingest) and `ORCAS_CHROMA_DIR`/`ORCAS_INDEX_INFO` (retrieval) resolve to `/data/chroma` + `/data/index_info.json`.
- **Image NOT built here** — Docker daemon offline + only ~15 GiB free (a torch image is ~5-6 GB). Build on a Docker host / CI. Model-bake command itself is proven (same call works locally).

**Handoff:** this satisfies the Day-12 "retrieval container with health + /metrics" handoff to Mitesh + Jignas (compose wiring is Jignas's).

## Slice 3 — Web client v0 (Days 11–14)
_No entries yet._

## Slice 4 — Structure-aware ingestion + retrieval hardening (Days 15–22)
_No entries yet._

## Slice 5 — Evaluation harness + baseline numbers (Days 23–30)
_No entries yet._

## Slice 6 — Experiments, retrieval cache, live scoring (Days 31–36)
_No entries yet._

## Slice 7 — Web client finish + retrieval hardening (Days 37–40)
_No entries yet._

## Slice 8 — Report sections + freeze (Days 41–43)
_No entries yet._

## Slice 9 — Rehearsal (Days 44–50)
_No entries yet._

---

## Benchmark & metric ledger (quick reference)
Keep the headline numbers here so they're easy to find at report time.

| Date | What was measured | Setting | Number |
|---|---|---|---|
| | | | |

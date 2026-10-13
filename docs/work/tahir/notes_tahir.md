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

### 2026-10-13 — web client + fake gateway, end-to-end verified

**Did**
- `services/web/static/` — vanilla-JS single page (no build step): demo presets (#10 §4.1 bank FD, MF redemption, insurance/out-of-corpus), complaint form, submit → poll (`GET /v1/runs/{id}` every 1s to terminal) → renders determination (route, regulator, entity, basis, citations with doc/clause/chunk/quote, escalation, verification). Gateway base URL configurable (localStorage / input), defaults to same-origin.
- `services/web/fake_gateway.py` — dev-only FastAPI fake of the gateway contract (`POST /v1/complaints` → 202 `{run_id,status_url}`; `GET /v1/runs/{id}` → `run_status.v1` with `determination.v1`). Time-based queued→running→completed (no threads). Canned determinations keyed on text; the §4.1 case returns the **real pinned citations** (p1w1 / p1w0 / p6w0). Serves the static client same-origin (no CORS) so it runs with zero other services.
- `services/web/Dockerfile` (nginx:alpine serving static) + README.

**Why a fake gateway:** the real gateway (Jignas) has no committed schema yet (`contracts/` holds only my `retrieval.openapi.yaml`). Built against the documented contract per the plan ("20-line fake server").

**Verified (real uvicorn server, not just TestClient):** `GET /` serves the page; POST bank-FD complaint → poll `queued→running→completed` → `refer_to_other_regulator / RBI / bank` with citations `[p1w1, p1w0, p6w0]`. 6 web tests + 18 retrieval = **24 pass**.

**Deferred to Slice 7 (as planned):** expandable full passage text, escalation-path detail, feedback buttons (`POST /v1/runs/{id}/feedback`). Browser visual check is for the user to eyeball; data path is verified.

**Day-14 skeleton note:** against the real stack, serve `static/` (nginx image) and set the gateway base to the published gateway (e.g. `http://localhost:8000`); cross-origin needs CORS on Jignas's gateway.

## Slice 4 — Structure-aware ingestion + retrieval hardening (Days 15–22)

### 2026-10-13 — clause-aligned retrieval, scope cards, hybrid A/B, re-embed, scenarios v0

**Built**
- `services/ingest/segment.py` — clause-aligned segmentation: regex clause anchors (`9. Grounds…`, `7B.`) + `CHAPTER` detection over flowing extracted text; real `clause_id` + `heading_path`; **preamble captured** (RBI scope sentence lives there); long clauses → `#k` sub-chunks; duplicate clause nums disambiguated (`-2`).
- `services/ingest/metadata.py` — keyword `entity_types`/`product_types` inference; **scope cards** (one per framework, `chunk_type=scope_card`, carry `source_clause_chunk_id` → citations resolve to the clause, not the card).
- `services/ingest/cli.py` — `--strategy clause|fixed` (clause default); scope-card generation; **real `--re-embed --model-tag X`** (reads stored chunks, re-embeds by id, no re-parse; same tag → in-place, new tag → migrate + drop old).
- `services/retrieval/hybrid.py` + `service.py` — entity/product **post-filters** (list-valued metadata can't use Chroma equality), `mode=hybrid` (dense+BM25, RRF).
- Production index migrated naive→clause: **637 chunks** (+2 scope cards). Fixtures regenerated with real clause ids (SEBI `2` apparent; RBI `preamble` scope + `9` grounds). RBI grounds now retrieves at **0.809** (was ~0.63 naive).

**Chunking A/B (`python -m eval.benchmark_chunking`)** — 6 topical framework-filtered probes:
| strategy/mode | recall@5 | recall@10 | mean_hit_score |
|---|---|---|---|
| fixed/dense | 1.00 | 1.00 | 0.650 |
| clause/dense | 0.833 | 0.833 | **0.719** |
| clause/hybrid | 0.833 | 0.833 | n/a |

Honest finding (→ report "what didn't work"): fixed-window wins *raw* recall@k (bigger chunks contain more text), but clause-aligned wins **ranking sharpness** + gives **citable clause-level provisions** (what verification/§4.1 need). **Hybrid: no recall gain → `hybrid_enabled=false` default** (tier-3 "keep only if gain"), still available via `mode`. Full write-up in `docs/work/tahir/chunking.md`. Decision: ship clause-aligned.

**Deliverable:** `eval/scenarios.yaml` v0 — 10 scenarios (8 from fixtures + out-of-corpus insurance + prompt-injection), each with supporting_passage (clause id + quote) where applicable. **→ Mitesh (dev) + Jignas (load-test payloads), Day 20.**

**Tests:** +11 (segment/metadata/scope-cards, entity/product filters, hybrid, re-embed in-place, scenarios resolve). **35 total pass.**

**Notes / follow-ups**
- Eval-1 package (merged) still cites the old naive ids `p1w0/p6w0`; live source of truth is now the clause index (`preamble`/`9`). Not rewriting the merged point-in-time doc; scenarios + fixtures are current.
- `mf_redemption_delay` supporting passage still weak (clause `24-2#15`) — re-pick in Slice 5.
- Segmentation is a heuristic (noisy titles on dense index pages) — documented in `chunking.md`.

## Slice 5 — Evaluation harness + baseline numbers (Days 23–30)

### 2026-10-13 — eval harness + Day-30 baseline

**Built**
- `eval/scenarios.yaml` — **22 scenarios**, full category coverage (§4.1×3, MF×2, broker×2, registrar×2, listed×2, depository×2, RBI payment×2, split×2, out-of-corpus×2, injection×2, ambiguous×1). **6 held_out** (excluded from tuning, reported separately). Supporting passages pinned from the clause index.
- `eval/judge.py` — deterministic **embedding (NLI-substitute) judge** (cosine thresholds: support 0.45 / relevance 0.32 / infer 0.40), temp-0 + cached. Pluggable LLM-judge interface for L2.
- `eval/metrics.py` — groundedness, context_relevance, faithfulness, hallucination_rate (claim-level) + route/regulator/entity accuracy + escalation P/R (label-based). Exact computations documented in `evaluation.md`.
- `eval/sut.py` — baseline rule+retrieval answerer (transparent keyword classifier + framework-filtered retrieval), agent-pluggable later.
- `eval/run_eval.py` + `Makefile` (`make eval` / `ingest` / `test`). Writes `eval/results/*.json`.
- `eval/trulens_eval.py` — TruLens 2.15 integration: custom embedding **Provider** subclass + `Feedback` objects + persisted `TruSession` (no serialization warnings once the Provider is module-level). Native claim-level metrics remain primary (per README).

**Baseline (Day-30 milestone — `make eval`):**
| metric | all (22) | held-out (6) |
|---|---|---|
| groundedness | 0.911 | 0.917 |
| context_relevance | 0.907 | 1.000 |
| faithfulness | 0.933 | 0.917 |
| hallucination_rate | 0.267 | 0.250 |
| route/regulator/entity acc | 1.0 | 1.0 |
| escalation P / R | 1.0 / 1.0 | 1.0 / 1.0 |

**Honesty (logged for report):** label metrics are perfect only because the baseline classifier mirrors the label scheme — *not* independent; the real label numbers come when Mitesh's agent is the SUT. RAG metrics are the meaningful baseline (retrieval-dependent). Groundedness≈faithfulness by construction. 22 scenarios → wide CIs.

**Tests:** +9 (metrics with fake judge, SUT classify, run_eval smoke, TruLens availability). **47 total pass.** Renamed eval metrics test to avoid basename clash with retrieval test_metrics.

**Deps:** added `trulens-core` (2.15). TruLens sqlite git-ignored.

**Follow-ups:** peer-review labels with a teammate before final; `mf_redemption_delay` supporting passage still loose (route/entity labels fine); deliberate-change before/after is Slice 6.

## Slice 6 — Experiments, retrieval cache, live scoring (Days 31–36)

### 2026-10-13 — before/after, variant harness, cache, live scorer

**Deliberate change (framework filter OFF→ON, 22 scenarios, `eval/experiment.py`):**
groundedness 0.889→0.911 (+0.022), faithfulness 0.911→0.933 (+0.022), hallucination 0.333→0.267 (−0.066), context_relevance 0.973→0.907 (−0.066), route_acc 1.0. **Honest:** filter improves grounding + cuts hallucination (the §4.1 fix) at a small context-relevance cost (unfiltered retrieval returns the most query-similar passages regardless of regulator). Reported as a worthwhile trade.

**Variant harness (L2):** same engine runs ≥2 named configs; Mitesh's reflect-prompt variants plug in as configs when his agent is the SUT. Validated on dense vs hybrid → dense wins (CR 0.907 vs 0.760), consistent with Slice-4.

**Retrieval cache (D7, `services/retrieval/cache.py`):** key = sha256(norm query | filters | mode | k | index_version). Redis if `REDIS_URL` else in-process TTL dict. Wired into `Retriever.search`; `cache_hit` + `orcas_retrieval_cache_{hits,misses}_total`. Effect (`eval/cache_effect.py`): cold p95 41.96ms / warm p95 0.12ms (hit ratio 0→1). index_version in the key → re-index invalidates stale entries.

**Live scorer (L6, `eval/live_scorer.py`):** deterministic 20% sampling of completed runs, scores with the same judge/metrics, writes `eval_scores`; feedback up/down aggregated. In-memory RunStore/EvalScoreStore/FeedbackStore seams matching Jignas's Postgres shape. Demo: 15 completed→3 sampled, feedback up-rate 0.727.

**Tests:** +6 (cache key/TTL/hit-path, experiment run_configs, live scorer sampling/scoring/feedback). **53 pass.** Added `redis` (optional). Cache is per-Retriever injectable; default process-wide singleton.

**Follow-ups:** wire live scorer to Jignas's real RunStore/eval_scores + Grafana; swap Mitesh's agent in as SUT for independent label metrics; final scenario payloads → Jignas (Slice 7).

## Slice 7 — Web client finish + retrieval hardening (Days 37–40)

### 2026-10-13 — web client finished, retrieval hardened, payloads handoff

**Web client (A8 finished):** expandable citations (`<details>` → full `passage_text` when present, else quote), escalation path (reason_code + reason + partial findings), verification block (passed, claims supported/checked, attempts), timeline; **feedback buttons** 👍/👎 + optional reason → `POST /v1/runs/{id}/feedback`. Fake gateway gained the feedback endpoint (stores `_FEEDBACK`) and `passage_text` on the §4.1 RBI citations. Live-smoked: determination shows 2/3 citations with passage_text; feedback recorded.

**Retrieval hardening:**
- `/health` → **liveness** (always 200, never flaps while ingest builds); `/ready` → **readiness** (200 only when index openable & non-empty, else 503). Dockerfile HEALTHCHECK → `/ready`.
- Per-request **timeout** (`RETRIEVAL_TIMEOUT_S`, default 10s) via a ThreadPool future → **504** on overrun (`with_timeout` helper, unit-tested).
- **Graceful empty-index:** search returns `count:0` (no crash), lookups 404, `/ready` 503 — tested on a fresh empty collection.

**Handoff:** `loadtest/payloads.json` — 22 valid `complaint.v1` bodies derived from scenarios, for Jignas's Locust. `loadtest/README.md` explains usage. (This is the Day-28 "final scenario payloads → Jignas" handoff.)

**Tests:** +7 (web feedback + passage_text; `/health`/`/ready`, `with_timeout` 504, empty-index). **60 total pass.** Live smoke: retrieval /health 200 + /ready 200; web submit→feedback OK.

**Demo readiness:** items #2 (valid request, citations resolve), #10 (§4.1 passages + routed answer) and the #5 answerable/unanswerable are all drivable from the client now.

## Slice 8 — Report sections + freeze (Days 41–43)

### 2026-10-13 — report consolidated + freeze

**Did:** wrote `docs/work/tahir/report-sections.md` consolidating the freeze-ready report: (A) corpus, (B) chunking + benchmark, (C) evaluation (baseline + deliberate-change before/after + cache + live), (D) **what did not work** (honest failures/tradeoffs), (E) DoD checklist.

**DoD verified at freeze:** `make test` → 60 passed; `make eval` → four metrics + route accuracy reproduce (G 0.911 / CR 0.907 / F 0.933 / halluc 0.267); running log complete; `make ingest|eval|test` single-target reproducible.

**Freeze:** slices 0–7 shipped (PRs #2–#9). Open items are joint integration/handoffs, logged, not blocking Tahir's deliverables: wire live scorer → Jignas's Postgres/Grafana; swap Mitesh's agent in as the eval SUT (independent label metrics); build retrieval Docker image in CI; peer-review scenario labels; re-pick the MF servicing supporting passage.

**Next:** Slice 9 = rehearsal / bug-fixes only (no new features).

## Slice 9 — Rehearsal (Days 44–50)
_No entries yet._

---

## Benchmark & metric ledger (quick reference)
Keep the headline numbers here so they're easy to find at report time.

| Date | What was measured | Setting | Number |
|---|---|---|---|
| | | | |

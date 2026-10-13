# Tahir — Build Plan (Data, Retrieval & Quality)

> Slice-by-slice plan for building my part of ORCAS. Each **slice is a vertical increment**: something runnable and demonstrable on its own, with explicit acceptance criteria, the mocks that let me build without waiting on teammates, and the handoffs I owe others.
>
> Source of truth: [`docs/work/TAHIR.md`](../TAHIR.md), [`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md), [`docs/PROJECT_DOCUMENTATION.md`](../../PROJECT_DOCUMENTATION.md). This file is the *how/when*; those are the *what/why*.

## What I own (recap)

| Area | Directory | Key requirements |
|---|---|---|
| Corpus | `corpus/` | Eval 1, R2 |
| Ingestion pipeline | `services/ingest/` | D2, L1 |
| Retrieval service | `services/retrieval/` | F4, L1, D7 |
| Evaluation + metrics | `eval/` | L3, L2 (harness), L6 |
| Live quality scoring | `eval/live_scorer.py` | L6 |
| Web client | `services/web/` | A8 |
| Retrieval tests | `tests/retrieval/` | — |

## Independence rule (how I never block)

Everything I build must run with these stand-ins until the real thing exists:

- **LLM judge** (for eval metrics) → `llm_stub`, or a thin local provider interface. Never hard-depend on Mitesh's live llm-gateway.
- **RunStore / `runs` / `feedback` tables** (for live scorer) → in-memory `RunStore` impl until Jignas ships Postgres.
- **Gateway REST** (for web client) → a ~20-line fake gateway server; contract frozen Day 3.
- My own retrieval service has **no upstream dependency** — it is a leaf I can build immediately after the corpus lands.

---

## Slice 0 — Contract + corpus foundation
**Days 1–3 · unblocks everyone downstream**

- [x] **Slice complete** — contract + ADR drafted; 3/3 corpus docs downloaded, verified & pinned in MANIFEST.yaml (2026-10-13). Contract still needs the 3-way Day-3 freeze sign-off.

**Goal:** freeze the retrieval contract and get a verified corpus into the repo.

- Co-author `contracts/retrieval.openapi.yaml` with Mitesh (consumer) and Jignas (contracts editor): `POST /v1/search`, `GET /v1/clauses/{doc_id}/{clause_id}`, `GET /v1/chunks/{chunk_id}`, `GET /v1/index/info`, `/metrics`, `/health`.
- Download the 3 baseline documents into `corpus/raw/`:
  - SEBI master circular on investor grievance redressal,
  - SEBI (Mutual Funds) Regulations — investor servicing chapter,
  - RBI Integrated Ombudsman Scheme.
- Write `corpus/MANIFEST.yaml`: title, issuer, source URL, version/date, SHA-256, **has-text-layer flag** per doc.
- Eyeball each PDF: confirm text layer; flag any scanned doc for OCR (Tesseract) later.
- Check whether the SEBI master circular covers registrar / listed company / depository. If not, record the gap (F3 may need one extra justified source — do not add unjustified docs).

**Mocks/deps:** none (this is the root).
**Done when:** `retrieval.openapi.yaml` signed off at the Day-3 freeze; `corpus/raw/` + `MANIFEST.yaml` committed with real checksums; text-layer status known per doc.
**Handoff:** frozen contract to Mitesh + Jignas.
**Risk guard (R2):** if a doc has no text layer or the coverage gap is real, surface it in the daily sync *now*, not at Day 8.

---

## Slice 1 — Ingest v0 + Retrieval v0 + the §4.1 fixtures
**Days 4–8 · the first end-to-end "search works" slice**

- [x] **Slice complete** — ingest v0 (606 chunks, idempotent) + retrieval v0 (`/v1/search`, `/v1/chunks`, `/v1/clauses`, `/v1/index/info`, `/health`) built & tested (16 tests pass); §4.1 passages located; `tests/fixtures/retrieval_fixtures.json` (9 fixtures) delivered for Mitesh. Structure-aware chunking/metadata/hybrid deferred to Slice 4 as planned.

**Goal:** a naive but real pipeline that indexes the corpus and answers a search query, plus the real §4.1 passages handed to Mitesh.

- `orcas-ingest` v0 (`services/ingest/`): read → parse (PDF text, page/section tracking) → **naive chunking** → embed (MiniLM, local) → upsert to Chroma.
  - Chunk `id = sha256(doc_id + clause_id + text + model_tag)` from the start, even with naive chunking (idempotency is cheaper to bake in than to retrofit).
- Retrieval service v0 (`services/retrieval/`, FastAPI): `POST /v1/search` (query, k) and `GET /v1/chunks/{chunk_id}`.
- **Locate and record the §4.1 supporting passages by reading the actual clauses:**
  - the SEBI passage a naive search returns (the "looks like SEBI" trap), and
  - the RBI Integrated Ombudsman Scheme passage that *actually* decides it (regulated entity = bank, grounds for complaint).
- Create `tests/fixtures/retrieval_fixtures.json`: real passages for the 4.1 case + ≥5 others (doc_id, clause_id, exact quote span, chunk_id).
- Parse sanity check by eye (R: PDF parsing mangles tables/numbering) + one regression test per document.

**Mocks/deps:** embedding model is local (no mock needed). No LLM yet.
**Done when:** `orcas-ingest` builds the index from `corpus/`; `/v1/search` returns the §4.1 SEBI + RBI passages for appropriate queries; fixtures committed.
**Handoff (Day 8, hard):** `retrieval_fixtures.json` to Mitesh — his agent work is blocked without it.
**Note:** keep clause numbers/wording **only** from the downloaded docs — never from memory (per project rule).

---

## Slice 2 — Evaluation 1 package + retrieval containerized
**Days 9–13 · the graded milestone, Eval 1**

- [x] **Slice complete** — `evaluation-1-package.md` written (corpus confirmation, §4.1 apparent+deciding passages, reference determination, project plan); retrieval + ingest Dockerfiles (model baked at build, `/health`, `/metrics`); `/metrics` added (18 tests pass). Image not built locally (Docker offline/disk) — build on a Docker host/CI. Confirm real Eval-1 date with faculty.

**Goal:** the deliverable faculty reviews at Evaluation 1, and retrieval running as a container for the team.

- Evaluation 1 package (docs): corpus confirmation; the §4.1 passages (both the SEBI-returned one and the RBI deciding one); test values / expected answer for the reference case; project plan.
- Containerize retrieval: Dockerfile with the **embedding model baked in at build time** (no runtime download), `/health`, `/metrics`.
- Confirm the real Evaluation 1 date with faculty; target ≤ Day 13 and shift if needed.

**Mocks/deps:** builds on Slice 1.
**Done when:** Eval-1 package ready and reviewed; retrieval image builds and serves `/health` green.
**Handoff (Day 12):** retrieval container with health check + `/metrics` to Mitesh + Jignas.

---

## Slice 3 — Web client v0 (submit / poll / display)
**Days 11–14 · joins the Day-14 walking skeleton**

- [x] **Slice complete** — static web client (`services/web/static/`: presets, submit, poll, render determination w/ citations+escalation) built against a dev `fake_gateway.py` (documented contract, serves the page same-origin). nginx Dockerfile. Live end-to-end verified (§4.1 preset → RBI referral). 6 web tests (24 total pass). Expandable passages + feedback buttons deferred to Slice 7 as planned.

**Goal:** a static page that drives a complaint through the gateway contract and shows the result.

- `services/web/`: single static page — submit form (with demo complaints as presets), poll status, render the determination JSON.
- Build against a **~20-line fake gateway** implementing the frozen gateway contract (`POST /v1/complaints`, `GET /v1/runs/{id}`); swap to the real gateway at Day 14.
- Keep it plain: **no marks for appearance, budget ≤2 days total across slices 3 + 7.**

**Mocks/deps:** fake gateway server (contract frozen Day 3).
**Done when:** the page submits a preset, polls to a terminal state, and displays the determination against the fake gateway; wires to the real gateway at the Day-14 integration.
**Risk guard (R7):** this is my contribution to the Day-14 end-to-end gate — don't let it slip.

---

## Slice 4 — Structure-aware ingestion + retrieval hardening
**Days 15–22 · the "real" retrieval, where L1 is earned**

- [x] **Slice complete** — clause-aligned segmentation (real clause_id + heading_path + preamble), entity/product metadata, scope cards (→ source clause), `--strategy clause|fixed`, real `--re-embed` (by id, no re-parse), entity/product post-filters + hybrid (BM25+RRF) via `mode`. Chunking A/B benchmarked + documented (`chunking.md`): clause-aligned shipped as default (sharper ranking + citable provisions; hybrid no gain → off by default). `eval/scenarios.yaml` v0 (10). 35 tests pass. Freshness metrics already from Slices 1–2.

**Goal:** clause-aligned retrieval with metadata, scope cards, idempotency, re-embedding, and freshness metrics — plus the first 10 scenarios.

- **Segmentation:** clause/paragraph tree from numbering + heading patterns; chunks carry heading path (Chapter → Section → Clause) and neighbour context.
- **Metadata per chunk:** `doc_id, version, framework (SEBI|RBI), clause_id, heading_path, entity_types[], product_types[]`.
- **Scope cards:** short "what this framework covers" chunks, each pointing to a source clause + quote span. **Rule to communicate to Mitesh: scope cards are finding aids; citations must resolve to the source-clause chunk, never the card.**
- **Chunking benchmark:** ≥2 settings (e.g. fixed-500-token vs clause-aligned); recall@k on the §4.1 case + eval set; record numbers (feeds the "what didn't work" report section).
- **Hybrid A/B:** dense vs dense+BM25; keep hybrid only if the A/B shows gain (this resolves the `[TBD by Tahir]` in ARCHITECTURE §5).
- **Idempotency:** second `orcas-ingest` run changes nothing and says so (test it).
- **Re-embedding:** `--re-embed --model-tag X` re-embeds only that tag's chunks by id; no full rebuild (test it).
- **Freshness metrics:** build timestamp, per-doc version, chunk count per doc, throughput (chunks/s, pages/s) via `/metrics` and `GET /v1/index/info`.
- Add remaining retrieval endpoints: `GET /v1/clauses/{doc_id}/{clause_id}`, `GET /v1/index/info`.
- `eval/scenarios.yaml` **v0 — first 10 scenarios** (so Mitesh/Jignas have real payloads).
- Filters on `/v1/search`: `framework`, `doc_id`, `entity_type`, `mode=dense|hybrid`.

**Mocks/deps:** none external; this is all my domain.
**Done when:** re-run changes nothing; `--re-embed` works for one tag; `/v1/index/info` reports freshness; chunking benchmark numbers recorded; 10 scenarios committed.
**Handoffs:** scenarios v0 to Mitesh (dev) and Jignas (load-test payloads, Day 20).

---

## Slice 5 — Evaluation harness + baseline numbers
**Days 23–30 · the biggest piece; baseline is a hard Day-30 milestone**

- [x] **Slice complete** — `eval/scenarios.yaml` (22, 6 held-out, full category coverage), `judge.py` (deterministic embedding/NLI judge, pluggable LLM judge), `metrics.py` (groundedness/context-relevance/faithfulness/hallucination + route acc + escalation P/R), `sut.py` (baseline rule+retrieval, agent-pluggable), `run_eval.py` + `make eval`, TruLens integration (custom Provider + Feedback + TruSession). **Baseline recorded** (G 0.911 / CR 0.907 / F 0.933 / halluc 0.267). 47 tests pass. Full write-up: `evaluation.md`. (Label metrics perfect because baseline mirrors labels — real signal is RAG metrics / agent SUT; documented.)

**Goal:** `make eval` runs ≥20 scenarios and prints the four metrics + route accuracy, with trustworthy labels.

- Complete **≥20 scenarios** in `scenarios.yaml`, each with `id, complaint_text, expected_route, expected_regulator, expected_entity_type, expected_escalation, supporting_passage (doc_id+clause_id+quote), notes`. Coverage per the TAHIR.md category table (§4.1 ×3, MF ×2, broker ×2, registrar, listed co., depository, RBI-payment ×2, split-regulator ×2, out-of-corpus ×2, injection ×2, ambiguous). **Synthetic complaints only.**
- **Peer-review labels** with a teammate — a wrong label corrupts every metric (R: eval labels wrong).
- Hold out ≥5 scenarios from any tuning; report them separately (R: scenario overfitting).
- `eval/metrics.py` — document the exact computation of each in the report:
  - Groundedness (claim-level, LLM-judge or NLI),
  - Context relevance (per-passage judge),
  - Faithfulness (RAGAS-style inferable fraction; honestly note overlap with groundedness),
  - Hallucination rate (from claim-level groundedness),
  - plus label-based Route accuracy + escalation precision/recall (no LLM — more trustworthy).
- `eval/run_eval.py` batch CLI + `make eval`.
- TruLens integration (verify its feedback functions work with the free-tier judge, else a custom provider wrapper — open question #7).
- **LLM-judge hygiene:** temperature 0, cache judge calls, spot-check 20% of verdicts by hand; state all of this in the report (R6).
- **Record baseline numbers** for all metrics.

**Mocks/deps:** LLM judge via `llm_stub` or thin provider interface; `RunStore` in-memory if needed.
**Done when (Day-30 gate):** `make eval` prints four metrics + route accuracy on ≥20 scenarios; baseline recorded; labels peer-reviewed.

---

## Slice 6 — Experiments, retrieval cache, live scoring
**Days 31–36 · the before/after evidence the report needs**

- [x] **Slice complete** — deliberate-change before/after (framework filter off→on: groundedness +0.022, faithfulness +0.022, hallucination −0.066, context-relevance −0.066 honest cost); variant-comparison harness (dense vs hybrid; prompt variants plug in as configs); retrieval cache (D7, key incl index_version; Redis-or-in-memory; warm p95 ~0.1ms vs cold ~42ms); live scorer (L6, 20% sampling, eval_scores + feedback aggregation, in-memory RunStore seam). 53 tests pass; results in `evaluation.md`.

**Goal:** one deliberate-change experiment, the prompt-variant comparison, measured cache effect, and live quality scoring.

- **Deliberate-change experiment:** pick one change with a hypothesis (e.g. framework-swap retry strategy, or clause-aligned vs fixed chunking). Run all four metrics before/after on the same set. **Report honestly even if it got worse.**
- **Prompt-variant comparison (L2 harness):** run Mitesh's ≥2 reflect-prompt variants on the same eval set; report winner, metric, delta (say so if within noise).
- **Retrieval cache (D7):** Redis cache for embeddings + retrievals, keyed by (normalised query, filters, `index_version`). Measure hit ratio, latency, results/query effect — coordinate with Jignas's load tests.
- **Live scorer (L6):** `eval/live_scorer.py` samples N% (config `LIVE_SCORE_SAMPLE_RATE`) of completed runs, scores with the same metrics, writes `eval_scores` in Postgres; surface feedback aggregation alongside. Jignas charts quality-over-time.

**Mocks/deps:** Mitesh's prompt variants (handoff Day 35); Jignas's `eval_scores` table + Grafana panel (Day 36); LLM judge via stub.
**Done when:** before/after table exists; prompt-variant result written up; cache-effect numbers recorded; `live_scorer.py` writes `eval_scores` and a chart renders.

---

## Slice 7 — Web client finish + retrieval hardening
**Days 37–40 · make the demo items I drive bulletproof**

- [x] **Slice complete** — web client finished (expandable citations w/ full passage text, escalation path + reason + partial findings, verification block, 👍/👎 feedback → `POST /v1/runs/{id}/feedback`); retrieval hardened (`/ready` readiness + `/health` liveness split, per-request 504 timeout, graceful empty-index; Dockerfile healthcheck → `/ready`); final scenario payloads delivered to Jignas (`loadtest/payloads.json`, 22 complaint.v1 bodies). 60 tests pass; live-smoked.

**Goal:** the web client shows everything the demo needs; retrieval is production-hardened.

- Web client: render citations with **expandable passage text**, escalation path + reason, verification outcome, feedback buttons (up/down + reason → gateway feedback endpoint).
- Retrieval hardening: request timeouts, `/health` + `/ready`, graceful empty-index behaviour.
- Deliver final scenario payloads to Jignas for load testing (originally due Day 28 — pull earlier if Jignas needs them sooner).

**Mocks/deps:** real gateway by now; otherwise fake gateway.
**Done when:** web client shows everything demo items **#2, #5, #10** need; citations resolve to retrieved text live; retrieval survives timeouts/empty index.
**Handoff:** final scenario payloads to Jignas (load testing).

---

## Slice 8 — Report sections + freeze
**Days 41–43**

- [ ] **Slice complete**

**Goal:** write my report sections and freeze.

- Report sections: **corpus** (what/why/versions), **chunking** (strategy + benchmark numbers), **evaluation** (metric definitions, baseline, before/after), **what did not work** (built from `docs/work/notes_tahir.md`).
- Confirm every "Definition of done" item: unit + recall tests pass; metrics exposed; single `make` target reproduces; running log complete.
- Freeze — no new features after Day 43.

**Done when:** report sections + repo submitted; `make eval` and retrieval reproduce from a clean clone.

---

## Slice 9 — Rehearsal
**Days 44–50 · bug fixes only**

- [ ] **Slice complete**

**Goal:** demo items I drive run live, twice.

- Drive demo **#2** (valid request → citations resolve), **#10** (§4.1 passages + routed answer, with Mitesh); supply the answerable/unanswerable requests for **#5**; have evaluation numbers ready for the viva.
- Dress rehearsal #1 (Day 47) and #2 (Day 49) — bug fixes only, no new work.

---

## Running thread across all slices

- **Running log:** keep `docs/work/notes_tahir.md` updated every slice (what I tried, what I rejected, numbers). The "what didn't work" report section is built from it — not logging costs marks.
- **Tests:** every slice ships with unit tests; retrieval slices add recall@k checks on the scenario set (`tests/retrieval/`).
- **Handoff calendar:** fixtures→Mitesh (D8) · retrieval container→Mitesh+Jignas (D12) · sample payloads→Jignas (D6) · scenarios v0→Mitesh+Jignas (D20) · final scenario payloads→Jignas (D28) · report sections→all (D42).
- **Cut order if behind (Day 30):** hybrid retrieval → L6 live scoring chart → retrieval cache. **Never cut:** the §4.1 corpus proof, the ≥20-scenario eval, label correctness.

## Open items to confirm (not blocking the build)

1. Real Evaluation 1 date (affects Slice 2 target).
2. Whether the SEBI master circular covers registrar / listed company / depository, or an extra source is justified (Slice 0).
3. Whether TruLens' feedback functions work with the chosen free-tier judge or need a custom wrapper (Slice 5).
4. Final hybrid-retrieval decision — settled by the Slice 4 A/B, not assumed.

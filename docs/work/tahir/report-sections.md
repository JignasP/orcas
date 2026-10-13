# Report sections — Data, Retrieval & Quality (Tahir)

Consolidated, freeze-ready report sections for Tahir's part of ORCAS. Detailed sources:
[`chunking.md`](chunking.md), [`evaluation.md`](evaluation.md),
[`evaluation-1-package.md`](evaluation-1-package.md), [`corpus/MANIFEST.yaml`](../../../corpus/MANIFEST.yaml),
running log [`notes_tahir.md`](notes_tahir.md).

---

## A. Corpus

Three regulatory documents, downloaded and pinned in `corpus/MANIFEST.yaml` with real SHA-256 and a
text-layer flag (all have a text layer; no OCR needed).

| doc_id | Title | Issuer | Version pinned | Pages |
|---|---|---|---|---|
| `sebi_mutual_funds_regulations_1996` | SEBI (Mutual Funds) Regulations, 1996 | SEBI | consolidated to Jan 2026 | 162 |
| `rbi_integrated_ombudsman_scheme_2021` | Reserve Bank – Integrated Ombudsman Scheme, 2021 | RBI | base 2021 (12-Nov-2021) | 18 |
| `sebi_scores_master_circular` | Master Circular on redressal of investor grievances through SCORES | SEBI | `…/CIR/2022/0150`, 07-Nov-2022 | 11 |

- **F3 coverage confirmed:** the SCORES master circular covers listed companies, brokers, depository
  participants, mutual funds/AMCs, registrars/RTAs and depositories — one SEBI document covers the
  registrar/listed-company/depository categories; no extra source needed.
- **Supersession (honest):** the 2022 SCORES master circular was later superseded by SCORES 2.0
  (circular `2023/156`, 20-Sep-2023), which changed operational *timelines*. We index the 2022 master
  circular (clean, self-contained, sufficient for §4.1 jurisdiction); timeline-sensitive eval labels
  are checked against 2023/156. Recorded in the manifest's `superseded_by`.
- The §4.1 deciding provisions are pinned: SEBI SCORES clause 2 (apparent) and RBI **preamble** (scope:
  "entities regulated by Reserve Bank") + RBI clause **9** (Grounds of Complaint, "deficiency in service").

## B. Chunking & retrieval (L1)

Clause-aligned segmentation is the production default: regex clause/`CHAPTER` detection → chunks with a
real `clause_id` + `heading_path`, preamble captured, long clauses split into `#k` sub-chunks, each
tagged with inferred `entity_types`/`product_types`. Scope cards (one per framework) are finding aids
that carry `source_clause_chunk_id` — **citations resolve to the source clause, never the card.**
Retrieval: dense (MiniLM, cosine) with `framework`/`doc_id`/`chunk_type` filters pushed to Chroma and
`entity_type`/`product_type` post-filters; optional hybrid (dense+BM25, RRF); Redis-or-in-memory cache
keyed by `(norm query, filters, mode, k, index_version)`.

**Benchmark (`python -m eval.benchmark_chunking`), 6 topical framework-filtered probes:**

| strategy / mode | recall@5 | recall@10 | mean_hit_score |
|---|---|---|---|
| fixed / dense | 1.00 | 1.00 | 0.650 |
| clause / dense | 0.833 | 0.833 | **0.719** |
| clause / hybrid | 0.833 | 0.833 | n/a |

Decision: ship **clause-aligned** — it trades a marginal raw-recall dip (fixed-window chunks are bigger,
so they trivially contain more phrases) for sharper ranking (0.719 vs 0.650; the RBI grounds provision
retrieves at 0.809 vs ~0.63 naive) and **citable clause-level provisions**, which is what verification
needs. Hybrid showed no recall gain → off by default, available via `mode`.

## C. Evaluation (L3)

- **22 synthetic scenarios** (`eval/scenarios.yaml`), full category coverage, **6 held out** from tuning.
- **Judge:** deterministic embedding (NLI-substitute) judge (temperature-0, cached). LLM judge is
  pluggable with the same interface; hygiene = temp 0, cached verdicts, 20% manual spot-check.
- **Metrics (exact computations in `evaluation.md`):** groundedness, context relevance, faithfulness,
  hallucination rate (claim-level) + route/regulator/entity accuracy and escalation precision/recall.

**Baseline (`make eval`):**

| metric | all (22) | held-out (6) |
|---|---|---|
| groundedness | 0.911 | 0.917 |
| context_relevance | 0.907 | 1.000 |
| faithfulness | 0.933 | 0.917 |
| hallucination_rate | 0.267 | 0.250 |
| route / regulator / entity acc | 1.0 | 1.0 |
| escalation precision / recall | 1.0 / 1.0 | 1.0 / 1.0 |

**Deliberate change — framework filter OFF → ON (same set, all four metrics):**

| metric | before | after | delta |
|---|---|---|---|
| groundedness | 0.889 | 0.911 | +0.022 |
| faithfulness | 0.911 | 0.933 | +0.022 |
| hallucination_rate | 0.333 | 0.267 | −0.066 |
| context_relevance | 0.973 | 0.907 | −0.066 |

The "framework swap" (the mechanism that fixes §4.1) improves grounding and cuts hallucination at a small
context-relevance cost — reported honestly, including the metric that regressed.

- **Variant harness (L2):** runs ≥2 named configs; Mitesh's reflect-prompt variants plug in as configs.
- **Retrieval cache (D7):** warm p95 ≈ 0.1 ms vs cold ≈ 42 ms; `index_version` in the key invalidates
  stale entries on re-index.
- **Live scoring (L6):** `eval/live_scorer.py` samples N% of completed runs, scores with the same metrics,
  writes `eval_scores`; feedback aggregated alongside (in-memory seams → Jignas's Postgres).

## D. What did not work (honest)

- **Automated corpus download hit walls:** Firecrawl ran out of credits; the RBI document host WAF-blocks
  `curl` (every variant returned a JS challenge). RBI + the SEBI master circular were fetched via browser;
  provenance recorded in the manifest.
- **Fixed-window chunking "won" raw recall@k** — an artefact of larger chunks, not better retrieval. We did
  not chase that number; clause-aligned is the right choice for grounded citations.
- **Hybrid retrieval gave no measurable recall gain** on this corpus, so it is off by default (not deleted
  — it stays available and is re-tested in Slice 5's set).
- **Label metrics read 1.0 but are not independent** — the baseline SUT is a rule classifier that mirrors
  the label scheme. The meaningful baseline signal is the RAG metrics; real label numbers require Mitesh's
  agent as the SUT. Stated wherever the numbers appear.
- **No free LLM judge was wired** (no API key); the embedding/NLI judge stands in. Groundedness and
  faithfulness are consequently highly correlated. 22 scenarios give wide confidence intervals.
- **The mutual-fund servicing supporting passage is weak** — the MF Regulations don't expose a clean
  "redemption/NAV grievance" clause to naive retrieval; flagged for a re-pick.
- **Segmentation is a regex heuristic**, not a legal parser — dense index pages produce some noisy clause
  titles; documented, not hidden.
- **The retrieval Docker image was not built in-repo** (Docker daemon offline, limited disk) — Dockerfiles
  and env wiring are validated; the image must be built on a Docker host / CI.

## E. Definition of done (verified at freeze)

| DoD item | Status |
|---|---|
| Unit tests + recall checks | ✅ `make test` → 60 passed |
| Metrics exposed | ✅ retrieval `/metrics` (`orcas_*`); `make eval` prints the four metrics + route accuracy |
| Running log kept | ✅ `notes_tahir.md` (per-slice) |
| Reproducible with a single `make` target | ✅ `make ingest` / `make eval` / `make test` |

**Freeze:** Slices 0–7 shipped (PRs #2–#9 merged). Remaining open items are handoffs/integration owned
jointly (wire live scorer to Jignas's Postgres + Grafana; swap Mitesh's agent in as the eval SUT; build
the retrieval image in CI) — tracked in `notes_tahir.md`, not blocking Tahir's deliverables.

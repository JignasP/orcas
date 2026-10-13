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
_No entries yet._

## Slice 2 — Evaluation 1 package + retrieval containerized (Days 9–13)
_No entries yet._

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

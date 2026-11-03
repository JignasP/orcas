# Evaluation (L3) — design, metrics, results

How ORCAS's quality is measured, the exact metric computations, and the current results.
Run: `make eval` (the agent, stub replies → `eval/results/agent-stub.json`), `make eval-live`
(the agent, live model → `agent-gateway.json`), `make eval-baseline` (keyword reference →
`baseline.json`).

## 1. Scenarios
`eval/scenarios.yaml` — **22 synthetic scenarios** (coverage below), each with `expected_route`,
`expected_regulator`, `expected_entity_type`, `expected_escalation`, and a `supporting_passage`
(doc_id + clause_id + exact quote) where a provision applies (15 of 22). **6 are `held_out: true`**
and excluded from any tuning, reported separately (anti-overfitting).

| Category | n | Category | n |
|---|---|---|---|
| §4.1 bank FD (+2 paraphrases) | 3 | RBI payment/ATM | 2 |
| Mutual fund servicing | 2 | Split regulators → escalate | 2 |
| Broker | 2 | Out-of-corpus (insurer/pension) → escalate | 2 |
| Registrar / share transfer | 2 | Prompt injection → escalate | 2 |
| Listed company | 2 | Ambiguous / vague → escalate | 1 |
| Depository / demat | 2 | | |

Labels are pinned from the actual clauses (not memory); every pinned supporting clause resolves to
an indexed chunk containing its quote. Labels should still be **peer-reviewed with a teammate**
before the final run (a wrong label corrupts every metric).

## 2. System under test (SUT)
**Default: the shipped agent** (`eval/agent_sut.py`). It runs the worker's
`run_complaint_pipeline` (Researcher → Verifier → output filter) with the real retrieval app:
- **stub** (`make eval`): LLM replies from the `llm_stub` app, exactly what `llm-gateway` returns in
  `ORCAS_STUB_MODE`. Needs only the local index. It measures the pipeline with canned replies, **not
  model quality**.
- **live** (`make eval-live`): LLM calls go to `LLM_GATEWAY_URL`.
- **via gateway** (`--via-gateway URL`): a running stack through its public API.

**Reference only: the keyword baseline** (`eval/sut.py`), a transparent rule classifier plus
framework-filtered retrieval. Its label metrics are perfect by construction (it mirrors the label
scheme), so it is not evidence of system quality.

## 3. Judge
A **deterministic embedding (NLI-substitute) judge** (`eval/judge.py`): claim support / passage
relevance / inferability are decided by cosine similarity of local MiniLM embeddings against
explicit thresholds — **support 0.45, relevance 0.32, infer 0.40** (also written into every results
file as `judge_thresholds`). It is reproducible, free and not rate-limited. No LLM judge is used.

Its known weakness: a short, generic sentence ("…should be routed under the cited RBI provision")
can clear the support threshold against any on-topic passage. Groundedness is therefore read
together with the label-based supporting-passage metrics below, which need no judge.

## 4. Metric definitions (exact)
**Claims** are the sentences of the answer's own text — for the agent, the `basis` of a completed
determination (citation tags removed); for the baseline, its routing conclusion. Sentences copied
from the retrieved passages are *not* claims: they are supported by construction.
**Contexts** are the passages the run retrieved (for the agent, its `tool_call` events), not the
ones it chose to cite.

RAG metrics are computed only over **answered** scenarios (escalations assert nothing):
- **Groundedness** = supported_claims / total_claims, claim-level (`judge.supports`), macro-averaged.
- **Context relevance** = relevant_passages / retrieved_passages (`judge.relevant`), macro-averaged.
- **Faithfulness** = inferable_claims / total_claims (`judge.inferable`, a *looser* bar than support,
  RAGAS-style). It is **highly correlated with groundedness by construction** — reported honestly.
- **Hallucination rate** = share of answered scenarios with ≥1 unsupported claim.

Label metrics are computed over **all** scenarios (no judge → more trustworthy):
- **Route / regulator / entity accuracy** = exact match vs expected.
- **Escalation precision / recall** = escalation as the positive class.

Supporting-passage metrics are computed over the 15 scenarios that pin a passage (no judge):
- **Supporting passage retrieved** = share where a retrieved chunk is the pinned clause's chunk.
- **Supporting passage cited** = share where a cited chunk is the pinned clause's chunk (not
  applicable to the baseline, which does not cite).

## 5. Results (2026-11-03)

### 5.1 The agent, stub mode — `eval/results/agent-stub.json`

| Metric | All (22) | Held-out (6) |
|---|---|---|
| answered (non-escalated) | 5 | 2 |
| groundedness | 1.000 | 1.000 |
| context_relevance | 0.360 | 0.400 |
| faithfulness | 1.000 | 1.000 |
| hallucination_rate | 0.000 | 0.000 |
| route_accuracy | 0.409 | 0.500 |
| regulator_accuracy | 0.273 | 0.167 |
| entity_accuracy | 0.273 | 0.333 |
| escalation_precision / recall | 0.353 / 0.857 | 0.500 / 1.000 |
| supporting passage retrieved | 0.000 | 0.000 |
| supporting passage cited | 0.000 | 0.000 |

Reading: 17 of 22 runs escalated (11 `out_of_corpus`, 6 `unverified`), mostly because the stub's
keyword classifier and draft step misroute (tracked in Mitesh's M4). The 1.0 groundedness covers
only 5 answers whose single generic sentence the embedding judge accepts — it is not a quality
signal. The supporting-passage metrics show what the judge misses: **no run retrieved its pinned
clause**. For §4.1 the agent's query ranks RBI clause 10 ("Grounds for non-maintainability") first
and the deciding clause 9 seventh, so the agent's `k=5` never sees clause 9 and it cites clause 10.

**Live-model results:** pending a reachable model (Mitesh's M2, Jignas's J3); `make eval-live`
produces them.

### 5.2 Keyword baseline (reference only) — `eval/results/baseline.json`

| Metric | All (22) | Held-out (6) |
|---|---|---|
| groundedness | 0.733 | 0.750 |
| context_relevance | 0.907 | 1.000 |
| faithfulness | 0.800 | 0.750 |
| hallucination_rate | 0.267 | 0.250 |
| route / regulator / entity accuracy | 1.000 | 1.000 |
| escalation_precision / recall | 1.000 / 1.000 | 1.000 / 1.000 |
| supporting passage retrieved | 0.333 | 0.250 |

### 5.3 Superseded: the Day-30 baseline
The Day-30 table (groundedness 0.911, context relevance 0.907, faithfulness 0.933, hallucination
0.267) **is withdrawn**. It scored the keyword baseline, not the agent, and two of its three claims
per answer were sentences copied from the retrieved passages, which are supported by construction.
With claims restricted to the answer's own text, the same baseline scores groundedness 0.733 and
faithfulness 0.800 (§5.2). Recorded in `notes_tahir.md` under "what didn't work".

## 6. Honesty notes (for the report)
- Stub-mode agent numbers measure the pipeline with canned replies, not model quality.
- The baseline's perfect label metrics are by construction; they are not an independent measurement.
- Groundedness and faithfulness track each other closely (same embedding judge, nearby thresholds),
  and the judge accepts generic sentences — read them with the supporting-passage metrics.
- **22 scenarios give wide confidence intervals** — treat deltas smaller than a few points as noise.
- TruLens: `python -m eval.trulens_eval` wires a custom embedding feedback **Provider** + `Feedback`
  objects + a persisted `TruSession`; the claim-level metrics in `metrics.py` remain primary.

## 7. Experiments, cache, live scoring (Slice 6)

### 7.1 Deliberate change (L3) and prompt comparison (L2): pre-registered, on the agent
The old framework-filter before/after and dense-vs-hybrid comparison ran on the keyword baseline with
copied-passage claims; they are withdrawn and their results file removed. Hybrid retrieval was also
re-checked against the pinned supporting passages (complaint text as query, top 5): dense and hybrid
both find 5 of 15, so it is not a useful deliberate change.

Both experiments are now **pre-registered** in `eval/experiments.yaml`: change, hypothesis and primary
metric were committed before any result exists, and git history shows the order.

| Experiment | Requirement | Change | Primary metric |
|---|---|---|---|
| `l2-reflect-prompt` | L2 | reflect prompt v1 vs v2 (modifier and exclusion hunt) | route accuracy |
| `l3-cite-by-evidence-number` | L3 | draft prompt v1 (copy chunk ids) vs v2 (cite numbered evidence) | supporting passage cited |

`python -m eval.experiment run <name> --llm gateway` evaluates both configurations on the same 22
scenarios and model, each in a fresh process with its environment overrides, and writes
`eval/results/exp-<name>.json` with all four RAG metrics, the label metrics, supporting-passage hits,
LLM call counts and a verdict on the primary metric (deltas of one or two scenarios are flagged as
within noise). `compare <name> before.json after.json` does the same for two existing results files.

**Status:** both need a live model (stub replies do not depend on prompt wording; the harness refuses
stub mode unless `--allow-stub`) and Mitesh's prompt-version switch (M13; L3 also needs M3's draft v2).
A stub-mode plumbing run gave identical results and the harness warned that the override had no
effect, as expected before M13.

**Budget:** one configuration is 22 scenarios × roughly 4–11 LLM calls, so one experiment is about
180–480 calls. Check the hosted free tier's daily quota first; if it does not fit, run against an
Ollama-backed gateway and say so in the report.

### 7.3 Retrieval cache effect (D7) (`python -m eval.cache_effect`)
Key = `sha256(normalised_query | filters | mode | k | index_version)`; Redis when `REDIS_URL` set,
else in-process TTL dict.

| | hit ratio | p50 | p95 |
|---|---|---|---|
| cold | 0.00 | 17.76 ms | 41.96 ms |
| warm | 1.00 | 0.09 ms | 0.12 ms |

Warm p95 ≈ **0.1 ms** vs cold ≈ 42 ms. The `index_version` in the key means a re-index transparently
invalidates stale entries. (Coordinate the production Redis numbers with Jignas's load test.)

### 7.4 Live scoring (L6)
`eval/live_scorer.py` is currently an in-memory demo: it seeds runs from the keyword baseline and uses
synthetic feedback, so its output is **not** a measurement and is not reported. Scoring real runs
from Postgres into `eval_scores` is T6.

## 8. Next
T3: run the two pre-registered experiments once M13 and a live model are available. T6: live scoring on real runs.
Live-model results once a model is reachable.

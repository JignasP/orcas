# Evaluation (L3) — design, metrics, baseline

How ORCAS's quality is measured, the exact metric computations, and the Day-30 baseline.
Run: `make eval` (writes `eval/results/latest.json`).

## 1. Scenarios
`eval/scenarios.yaml` — **22 synthetic scenarios** (coverage below), each with `expected_route`,
`expected_regulator`, `expected_entity_type`, `expected_escalation`, and a `supporting_passage`
(doc_id + clause_id + exact quote) where a provision applies. **6 are `held_out: true`** and
excluded from any tuning, reported separately (anti-overfitting).

| Category | n | Category | n |
|---|---|---|---|
| §4.1 bank FD (+2 paraphrases) | 3 | RBI payment/ATM | 2 |
| Mutual fund servicing | 2 | Split regulators → escalate | 2 |
| Broker | 2 | Out-of-corpus (insurer/pension) → escalate | 2 |
| Registrar / share transfer | 2 | Prompt injection → escalate | 2 |
| Listed company | 2 | Ambiguous / vague → escalate | 1 |
| Depository / demat | 2 | | |

Labels are pinned from the actual clauses (not memory) and should be **peer-reviewed with a
teammate** before the final run (a wrong label corrupts every metric).

## 2. System under test (SUT)
The harness scores whatever emits a determination. Today it scores a **baseline rule+retrieval
answerer** (`eval/sut.py`): a transparent keyword classifier picks route/regulator/entity,
framework-filtered retrieval supplies grounding contexts, and the answer's claims are the routing
conclusion + the top retrieved provisions. **Mitesh's agent drops in later as an alternative SUT**
(reads determinations from RunStore/gateway) with no change to the metric code.

## 3. Judge
Default is a **deterministic embedding (NLI-substitute) judge** (`eval/judge.py`): claim support /
passage relevance / inferability are decided by cosine similarity of local MiniLM embeddings vs an
explicit threshold (support 0.45, relevance 0.32, infer 0.40). It is temperature-0 by construction,
free, not rate-limited, and cached — which is why it is the baseline. A pluggable **LLM judge** (same
interface) is used for the L2 prompt comparison; its hygiene is: **temperature 0, cache every verdict,
and hand-spot-check 20% of verdicts** — stated in the report alongside the numbers.

## 4. Metric definitions (exact)
RAG metrics are computed only over **answered** scenarios (escalations assert nothing):
- **Groundedness** = supported_claims / total_claims, claim-level (`judge.supports`), macro-averaged.
- **Context relevance** = relevant_passages / retrieved_passages (`judge.relevant`), macro-averaged.
- **Faithfulness** = inferable_claims / total_claims (`judge.inferable`, a *looser* bar than support,
  RAGAS-style). It is **highly correlated with groundedness by construction** — reported honestly.
- **Hallucination rate** = share of answered scenarios with ≥1 unsupported claim.

Label metrics are computed over **all** scenarios (no judge → more trustworthy):
- **Route / regulator / entity accuracy** = exact match vs expected.
- **Escalation precision / recall** = escalation as the positive class.

## 5. Baseline (Day-30) — `SUT=baseline-rule+retrieval`, judge=embedding-minilm-l6-v2

| Metric | All (22) | Held-out (6) |
|---|---|---|
| groundedness | 0.911 | 0.917 |
| context_relevance | 0.907 | 1.000 |
| faithfulness | 0.933 | 0.917 |
| hallucination_rate | 0.267 | 0.250 |
| route_accuracy | 1.000 | 1.000 |
| regulator_accuracy | 1.000 | 1.000 |
| entity_accuracy | 1.000 | 1.000 |
| escalation_precision / recall | 1.000 / 1.000 | 1.000 / 1.000 |

## 6. Honesty notes (for the report)
- **Label metrics are perfect because the baseline classifier mirrors the label scheme** — they are
  *not* an independent measurement yet. The meaningful baseline signal is the **RAG metrics**, which
  depend on retrieval quality. The real, independent label numbers arrive when **Mitesh's agent** is
  the SUT; the before/after experiment (Slice 6) is where these numbers get interesting.
- Groundedness and faithfulness track each other closely (same embedding judge, nearby thresholds).
- **22 scenarios give wide confidence intervals** — treat deltas smaller than a few points as noise.
- Hallucination ~0.27 comes from the routing-conclusion claim not always being strongly supported by
  the retrieved provisions — a realistic, improvable baseline.
- TruLens: `python -m eval.trulens_eval` wires a custom embedding feedback **Provider** + `Feedback`
  objects + a persisted `TruSession`; the claim-level metrics in `metrics.py` remain primary (per the
  README). Whether TruLens' built-in feedback functions work with the chosen free-tier LLM judge, or
  need the custom provider wrapper, is settled here in favour of the custom provider.

## 7. Deliberate change, variants, cache, live scoring (Slice 6)

### 7.1 Deliberate change — retrieval framework filter OFF → ON (`python -m eval.experiment`)
**Hypothesis:** filtering retrieval to the responsible regulator (the "framework swap" that fixes
§4.1) raises groundedness / faithfulness and lowers hallucination — because unfiltered search
surfaces the *wrong* framework for bank cases (SEBI for a bank-FD complaint), so the RBI routing
claim isn't supported. Same 22 scenarios, all four metrics:

| metric | before (filter off) | after (filter on) | delta |
|---|---|---|---|
| groundedness | 0.889 | 0.911 | **+0.022** |
| faithfulness | 0.911 | 0.933 | **+0.022** |
| hallucination_rate | 0.333 | 0.267 | **−0.066** |
| context_relevance | 0.973 | 0.907 | −0.066 |
| route_accuracy | 1.000 | 1.000 | 0.000 |

**Honest reading:** the filter does what we hoped for the grounding-relevant metrics (groundedness
up, hallucination down) but *costs* a little context relevance — unfiltered retrieval returns the
most query-similar passages regardless of regulator, which scores as "relevant" even when it is the
wrong framework. Net: the change is worth it (grounding + hallucination are what verification cares
about), and the context-relevance dip is the honest cost. This is the §4.1 difficulty, quantified.

### 7.2 Variant comparison (L2 harness) — dense vs hybrid
The same harness runs ≥2 named configs; **Mitesh's reflect-prompt variants plug in as configs when
his agent is the SUT**. Validated here on retrieval mode: dense wins (groundedness tie 0.911/0.911,
but context_relevance 0.907 vs 0.760 and no hallucination change) — consistent with the Slice-4
decision to keep hybrid off by default.

### 7.3 Retrieval cache effect (D7) (`python -m eval.cache_effect`)
Key = `sha256(normalised_query | filters | mode | k | index_version)`; Redis when `REDIS_URL` set,
else in-process TTL dict.

| | hit ratio | p50 | p95 |
|---|---|---|---|
| cold | 0.00 | 17.76 ms | 41.96 ms |
| warm | 1.00 | 0.09 ms | 0.12 ms |

Warm p95 ≈ **0.1 ms** vs cold ≈ 42 ms. The `index_version` in the key means a re-index transparently
invalidates stale entries. (Coordinate the production Redis numbers with Jignas's load test.)

### 7.4 Live scoring (L6) (`python -m eval.live_scorer`)
`live_scorer.py` samples `LIVE_SCORE_SAMPLE_RATE` (default 20%) of **completed** runs
(deterministic stable-hash sampling), scores each with the same judge/metrics, and writes rows to an
`eval_scores` store; feedback (up/down) is aggregated alongside. RunStore / EvalScoreStore /
FeedbackStore are in-memory seams with the shape of Jignas's Postgres tables (the brief: run against
an in-memory RunStore until the DB exists). Demo over the scenarios: 15 completed → 3 sampled,
mean groundedness 1.0, hallucination 0.0, feedback up-rate 0.727. Jignas charts `eval_scores` as
"quality over time".

## 8. Next
Hand Jignas the final scenario payloads (Slice 7 handoff) and wire the live scorer to the real
RunStore / `eval_scores` table once Jignas's Postgres lands; swap Mitesh's agent in as the SUT for
independent label metrics.

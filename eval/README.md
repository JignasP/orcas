# eval — evaluation harness (L3)

```bash
make eval                      # the agent, in-process stub replies  -> eval/results/agent-stub.json
make eval-live                 # the agent, live model behind LLM_GATEWAY_URL -> agent-gateway.json
make eval-baseline             # keyword baseline (reference only)   -> eval/results/baseline.json
python -m eval.run_eval --via-gateway http://localhost:8000   # a running Compose stack -> agent-compose.json
python -m eval.benchmark_chunking   # Slice-4 chunking A/B
python -m eval.experiment list      # pre-registered agent experiments (L2, L3)
python -m eval.experiment run l2-reflect-prompt --llm gateway   # before/after on a live model
python -m eval.cache_effect         # retrieval cache hit ratio + latency (cold vs warm)
python -m eval.live_scorer          # L6 live sampled scoring + feedback aggregation
python -m eval.trulens_eval         # TruLens feedback-provider integration (optional)
```

## Pieces
- `scenarios.yaml` — ≥20 labelled synthetic scenarios with supporting passages; `held_out: true`
  marks scenarios excluded from tuning (reported separately).
- `judge.py` — deterministic embedding (NLI-substitute) judge (cached); thresholds are written into
  every results file. No LLM judge is used.
- `metrics.py` — groundedness, context relevance, faithfulness, hallucination rate (claim-level;
  claims are the answer's own sentences) + route accuracy and escalation precision/recall + supporting
  passage retrieved/cited (label-based, from each scenario's pinned clause).
- `agent_sut.py` — the default system-under-test: the shipped worker pipeline
  (`run_complaint_pipeline`) with the real retrieval app. Contexts are the passages the run
  retrieved (its `tool_call` events); claims are the sentences of a completed determination's
  basis. Stub mode reflects the stub's canned replies, not model quality.
- `sut.py` — keyword baseline answerer, kept only as a reference point.
- `experiments.yaml` + `experiment.py` — pre-registered agent experiments: hypothesis and primary
  metric are committed before running; each configuration runs in a fresh process with its env overrides.
- `run_eval.py` — batch CLI (prints a per-scenario table for the agent); `benchmark_chunking.py` —
  chunking A/B; `trulens_eval.py` — TruLens wiring.

Full write-up + baseline numbers + honesty notes: `docs/work/tahir/evaluation.md`.

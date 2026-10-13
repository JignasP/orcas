# eval — evaluation harness (L3)

```bash
make eval                      # or: python -m eval.run_eval  (writes eval/results/latest.json)
python -m eval.run_eval --tag baseline
python -m eval.benchmark_chunking   # Slice-4 chunking A/B
python -m eval.trulens_eval         # TruLens feedback-provider integration (optional)
```

## Pieces
- `scenarios.yaml` — ≥20 labelled synthetic scenarios with supporting passages; `held_out: true`
  marks scenarios excluded from tuning (reported separately).
- `judge.py` — deterministic embedding (NLI-substitute) judge (temperature-0, cached). Pluggable:
  an LLM judge with the same interface swaps in for the L2 prompt comparison.
- `metrics.py` — groundedness, context relevance, faithfulness, hallucination rate (claim-level)
  + route accuracy and escalation precision/recall (label-based).
- `sut.py` — system-under-test: a baseline rule+retrieval answerer now; Mitesh's agent drops in later.
- `run_eval.py` — batch CLI; `benchmark_chunking.py` — chunking A/B; `trulens_eval.py` — TruLens wiring.

Full write-up + baseline numbers + honesty notes: `docs/work/tahir/evaluation.md`.

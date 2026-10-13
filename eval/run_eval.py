"""Batch evaluation CLI (L3): `make eval` / `python -m eval.run_eval`.

Loads eval/scenarios.yaml, runs the system-under-test on each scenario, computes the four
RAG metrics + label metrics (route accuracy, escalation P/R), prints a table, and writes
eval/results/latest.json. Held-out scenarios are reported separately (anti-overfitting).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import yaml

from services.corpus_common.constants import repo_root

from .judge import EmbeddingJudge
from .metrics import EvalResult, compute
from .sut import BaselineSUT

SCEN = repo_root() / "eval" / "scenarios.yaml"
RESULTS = repo_root() / "eval" / "results"

_ORDER = ["n_scenarios", "n_answered", "groundedness", "context_relevance", "faithfulness",
          "hallucination_rate", "route_accuracy", "regulator_accuracy", "entity_accuracy",
          "escalation_precision", "escalation_recall"]


def _print_table(title: str, m: dict) -> None:
    print(f"\n=== {title} (judge={m['judge']}) ===")
    for key in _ORDER:
        print(f"  {key:<22} {m.get(key)}")


def run(args) -> int:
    scenarios = yaml.safe_load(SCEN.read_text())["scenarios"]
    sut = BaselineSUT(k=args.k)
    judge = EmbeddingJudge()

    results: List[EvalResult] = [sut.run(s) for s in scenarios]
    overall = compute(results, judge)
    held = compute([r for r in results if r.held_out], judge)

    _print_table(f"ALL scenarios · SUT={sut.name}", overall)
    _print_table("HELD-OUT only (not used for tuning)", held)

    # per-scenario route hits for quick inspection
    misses = [r.scenario_id for r in results if r.route != r.expected_route]
    if misses:
        print(f"\nroute mispredictions: {misses}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sut": sut.name,
        "tag": args.tag,
        "k": args.k,
        "overall": overall,
        "held_out": held,
        "route_mispredictions": misses,
        "per_scenario": [
            {"id": r.scenario_id, "route": r.route, "expected_route": r.expected_route,
             "escalated": r.escalated, "expected_escalation": r.expected_escalation,
             "held_out": r.held_out, "n_claims": len(r.claims), "n_contexts": len(r.contexts)}
            for r in results
        ],
    }
    out = Path(args.out) if args.out else (RESULTS / f"{args.tag}.json")
    out.write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orcas-eval", description="ORCAS batch evaluation")
    p.add_argument("--k", type=int, default=5, help="retrieved contexts per scenario")
    p.add_argument("--tag", default="latest", help="results filename stem under eval/results/")
    p.add_argument("--out", default=None, help="explicit output path")
    return p


def main(argv=None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

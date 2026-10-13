"""Experiments (Slice 6): the deliberate-change before/after + the L2 variant comparison.

Both reuse one engine: run a set of named system configurations over the SAME scenarios and
tabulate the four RAG metrics + route accuracy, then print deltas. This is the harness the L2
prompt variants plug into — each prompt variant is just another named config once Mitesh's
agent is the SUT; here we validate it on retrieval-side configurations.

Run:  python -m eval.experiment
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import yaml

from services.corpus_common.constants import repo_root

from .judge import EmbeddingJudge
from .metrics import compute
from .sut import BaselineSUT

SCEN = repo_root() / "eval" / "scenarios.yaml"
RESULTS = repo_root() / "eval" / "results"
_METRICS = ["groundedness", "context_relevance", "faithfulness", "hallucination_rate",
            "route_accuracy"]


def _scenarios():
    return yaml.safe_load(SCEN.read_text())["scenarios"]


def run_configs(configs: Dict[str, dict], scenarios=None) -> Dict[str, dict]:
    scenarios = scenarios if scenarios is not None else _scenarios()
    judge = EmbeddingJudge()
    out = {}
    for name, kwargs in configs.items():
        sut = BaselineSUT(**kwargs)
        results = [sut.run(s) for s in scenarios]
        out[name] = compute(results, judge)
    return out


def _print_comparison(title: str, before_name: str, after_name: str, m: Dict[str, dict]):
    b, a = m[before_name], m[after_name]
    print(f"\n=== {title} ===")
    print(f"{'metric':<20}{'before':>10}{'after':>10}{'delta':>10}")
    for k in _METRICS:
        bv, av = b.get(k), a.get(k)
        if bv is None or av is None:
            print(f"{k:<20}{str(bv):>10}{str(av):>10}{'--':>10}")
        else:
            print(f"{k:<20}{bv:>10}{av:>10}{av - bv:>+10.3f}")
    print(f"before = {before_name}\nafter  = {after_name}")


def main(argv=None) -> int:
    # Deliberate change: the retrieval framework filter (the "framework swap" that fixes §4.1).
    # Hypothesis: filtering to the responsible regulator raises groundedness / context relevance
    # and lowers hallucination (unfiltered search surfaces the wrong framework for bank cases).
    change = run_configs({
        "filter_off": {"use_framework_filter": False},
        "filter_on": {"use_framework_filter": True},
    })
    # L2-style variant comparison (retrieval mode as a stand-in for Mitesh's prompt variants).
    variants = run_configs({
        "dense": {"mode": "dense"},
        "hybrid": {"mode": "hybrid"},
    })

    _print_comparison("Deliberate change — framework filter OFF -> ON", "filter_off", "filter_on", change)
    _print_comparison("Variant comparison — dense vs hybrid", "dense", "hybrid", variants)

    # winner of the variant comparison by groundedness (tie-break context_relevance)
    def score(m):
        return (m.get("groundedness") or 0, m.get("context_relevance") or 0)
    winner = max(variants, key=lambda n: score(variants[n]))
    print(f"\nvariant winner (by groundedness): {winner}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "experiment.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deliberate_change": change,
        "variants": variants,
        "variant_winner": winner,
    }, indent=2))
    print(f"\nwrote {RESULTS / 'experiment.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

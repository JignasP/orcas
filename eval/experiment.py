"""Pre-registered experiments on the agent (T3): the L3 deliberate change and the L2 prompt comparison.

Each experiment in eval/experiments.yaml states its change, hypothesis, primary metric and two
configurations (environment overrides) before any result exists. `run` evaluates each configuration
with `eval.run_eval` in a fresh process, so overrides read at import time take effect, then compares.
`compare` makes the same comparison from two existing results files, e.g. `make eval` before and
after a code change lands.

  python -m eval.experiment list
  python -m eval.experiment run l2-reflect-prompt --llm gateway --sleep 2
  python -m eval.experiment compare l3-cite-by-evidence-number before.json after.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import yaml

from services.corpus_common.constants import repo_root

EXPERIMENTS = repo_root() / "eval" / "experiments.yaml"
RESULTS = repo_root() / "eval" / "results"

RAG_METRICS = ["groundedness", "context_relevance", "faithfulness", "hallucination_rate"]
LABEL_METRICS = ["route_accuracy", "regulator_accuracy", "entity_accuracy",
                 "escalation_precision", "escalation_recall"]
PASSAGE_METRICS = ["supporting_passage_retrieved", "supporting_passage_cited"]
COUNT_METRICS = ["n_answered"]


def load_experiments() -> Dict[str, dict]:
    return yaml.safe_load(EXPERIMENTS.read_text())["experiments"]


def _llm_calls(results: dict) -> int:
    return sum(s.get("llm_calls", 0) for s in results.get("per_scenario", []))


def compare(name: str, spec: dict, before: dict, after: dict) -> dict:
    """Before/after table over the same scenarios, with the primary-metric verdict."""
    b, a = before["overall"], after["overall"]
    n = b.get("n_scenarios") or 0
    rows = []
    for metric in RAG_METRICS + LABEL_METRICS + PASSAGE_METRICS + COUNT_METRICS:
        bv, av = b.get(metric), a.get(metric)
        delta = round(av - bv, 3) if bv is not None and av is not None else None
        rows.append({"metric": metric, "before": bv, "after": av, "delta": delta})

    primary = spec["primary_metric"]
    row = next(r for r in rows if r["metric"] == primary)
    if row["delta"] is None:
        verdict = f"{primary}: not comparable (missing in one run)"
    else:
        verdict = f"{primary}: {row['before']} -> {row['after']} ({row['delta']:+.3f})"
        if primary in LABEL_METRICS and n:
            verdict += f", i.e. {round(row['delta'] * n):+d} of {n} scenarios"
        if abs(row["delta"]) * max(n, 1) < 2:
            verdict += "; within noise for a set of this size"

    warnings = []
    overrides_prompts = any(k.startswith("PROMPT_") for c in spec.get("configs", {}).values() for k in c)
    if overrides_prompts and before.get("prompt_versions") == after.get("prompt_versions"):
        warnings.append("both runs recorded the same prompt versions: the override had no effect "
                        "(is the prompt-version switch, M13, merged?)")
    if before.get("models") != after.get("models"):
        warnings.append(f"runs used different models: {before.get('models')} vs {after.get('models')}")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment": name, "requirement": spec.get("requirement"), "change": spec.get("change"),
        "hypothesis": spec.get("hypothesis"), "primary_metric": primary,
        "before": {k: before.get(k) for k in ("tag", "sut", "models", "prompt_versions", "index_versions")}
                  | {"llm_calls": _llm_calls(before)},
        "after": {k: after.get(k) for k in ("tag", "sut", "models", "prompt_versions", "index_versions")}
                 | {"llm_calls": _llm_calls(after)},
        "judge": b.get("judge"), "judge_thresholds": b.get("judge_thresholds"),
        "n_scenarios": n, "table": rows, "verdict": verdict, "warnings": warnings,
    }


def print_comparison(report: dict) -> None:
    print(f"\n=== {report['experiment']} ({report['requirement']}): {report['change']} ===")
    print(f"{'metric':<30}{'before':>10}{'after':>10}{'delta':>10}")
    for r in report["table"]:
        cells = [str(r[k]) if r[k] is not None else "--" for k in ("before", "after")]
        delta = f"{r['delta']:+.3f}" if r["delta"] is not None else "--"
        print(f"{r['metric']:<30}{cells[0]:>10}{cells[1]:>10}{delta:>10}")
    print(f"\nverdict: {report['verdict']}")
    print(f"LLM calls: before {report['before']['llm_calls']}, after {report['after']['llm_calls']}")
    for w in report["warnings"]:
        print(f"WARNING: {w}")


def run_config(name: str, config: str, overrides: Dict[str, str], args) -> Path:
    tag = f"exp-{name}-{config}"
    cmd = [sys.executable, "-m", "eval.run_eval", "--llm", args.llm, "--sleep", str(args.sleep),
           "--tag", tag]
    if args.retrieval_url:
        cmd += ["--retrieval-url", args.retrieval_url]
    env = {**os.environ, **{k: str(v) for k, v in overrides.items()}}
    print(f"\n--- {name}: {config} with {overrides}")
    subprocess.run(cmd, env=env, check=True, cwd=repo_root())
    return RESULTS / f"{tag}.json"


def _write(report: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"exp-{report['experiment']}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {out}")
    return out


def cmd_list(args) -> int:
    for name, spec in load_experiments().items():
        print(f"{name} ({spec['requirement']}): {spec['change']}")
        print(f"  primary metric: {spec['primary_metric']}; needs: {', '.join(spec.get('needs', [])) or '-'}")
    return 0


def cmd_run(args) -> int:
    spec = load_experiments()[args.name]
    if spec.get("needs_live_model") and args.llm == "stub" and not args.allow_stub:
        print(f"{args.name} needs a live model: stub replies do not depend on what it changes. "
              "Use --llm gateway (or --allow-stub to check the plumbing).", file=sys.stderr)
        return 2
    configs: List[str] = list(spec["configs"])
    if len(configs) != 2:
        raise ValueError("an experiment compares exactly two configurations")
    paths = [run_config(args.name, c, spec["configs"][c], args) for c in configs]
    before, after = (json.loads(p.read_text()) for p in paths)
    report = compare(args.name, spec, before, after)
    print_comparison(report)
    _write(report)
    return 0


def cmd_compare(args) -> int:
    spec = load_experiments()[args.name]
    before, after = (json.loads(Path(p).read_text()) for p in (args.before, args.after))
    report = compare(args.name, spec, before, after)
    print_comparison(report)
    _write(report)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orcas-experiment", description="Pre-registered agent experiments")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show the pre-registered experiments").set_defaults(func=cmd_list)

    run = sub.add_parser("run", help="evaluate both configurations and compare")
    run.add_argument("name")
    run.add_argument("--llm", choices=["stub", "gateway"], default="gateway")
    run.add_argument("--sleep", type=float, default=2.0, help="seconds between scenarios")
    run.add_argument("--retrieval-url", default=None)
    run.add_argument("--allow-stub", action="store_true")
    run.set_defaults(func=cmd_run)

    cmp_ = sub.add_parser("compare", help="compare two existing results files")
    cmp_.add_argument("name")
    cmp_.add_argument("before")
    cmp_.add_argument("after")
    cmp_.set_defaults(func=cmd_compare)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Batch evaluation CLI (L3): `make eval` / `python -m eval.run_eval`.

Loads eval/scenarios.yaml, runs the system-under-test on each scenario, computes the four
RAG metrics + label metrics (route accuracy, escalation P/R), prints a table, and writes
eval/results/<tag>.json. Held-out scenarios are reported separately (anti-overfitting).

The default SUT is the shipped agent (eval/agent_sut.py). `--sut baseline` runs the keyword
baseline (eval/sut.py), kept only as a reference point.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import yaml

from services.corpus_common.constants import repo_root

from .agent_sut import HEURISTIC_MODEL, AgentSUT
from .judge import EmbeddingJudge
from .metrics import EvalResult, compute
from .sut import BaselineSUT

SCEN = repo_root() / "eval" / "scenarios.yaml"
RESULTS = repo_root() / "eval" / "results"

_ORDER = ["n_scenarios", "n_answered", "groundedness", "context_relevance", "faithfulness",
          "hallucination_rate", "route_accuracy", "regulator_accuracy", "entity_accuracy",
          "escalation_precision", "escalation_recall", "n_with_supporting_passage",
          "supporting_passage_retrieved", "supporting_passage_cited"]


def _print_table(title: str, m: dict) -> None:
    print(f"\n=== {title} (judge={m['judge']} {m.get('judge_thresholds', {})}) ===")
    for key in _ORDER:
        print(f"  {key:<28} {m.get(key)}")


def supporting_chunk_ids(scenarios: List[dict]) -> dict:
    """Map scenario id -> chunk ids of its pinned supporting clause, read from the local index."""
    from services.retrieval.service import Retriever

    retriever, out = Retriever(use_cache=False), {}
    for s in scenarios:
        sp = s.get("supporting_passage")
        if not sp:
            continue
        clause = retriever.get_clause(sp["doc_id"], str(sp["clause_id"]))
        if clause is None:
            print(f"WARNING: {s['id']}: supporting clause {sp['doc_id']}/{sp['clause_id']} "
                  "is not in the index; its label needs re-pinning")
        out[s["id"]] = clause.chunk_ids if clause else []
    return out


def _print_scenarios(results: List[EvalResult]) -> None:
    print("\n=== per scenario ===")
    for r in results:
        ok = "OK " if r.route == r.expected_route else "BAD"
        d = r.details
        cites = ",".join(f"{c['doc_id'][:4]}:{c['clause']}" for c in d.get("citations", [])) or "-"
        print(f"{ok} {r.scenario_id:<28} expected {r.expected_route}/{r.expected_regulator}"
              f" | got {r.route}/{r.regulator} status={d.get('status')}"
              f" reason={d.get('reason_code')} cites={cites}")


def build_sut(args):
    if args.sut == "baseline":
        return BaselineSUT(k=args.k)
    return AgentSUT(llm=args.llm, retrieval_url=args.retrieval_url,
                    via_gateway=args.via_gateway, timeout_s=args.timeout)


def run(args) -> int:
    scenarios = yaml.safe_load(SCEN.read_text())["scenarios"]
    sut = build_sut(args)
    judge = EmbeddingJudge()

    supporting = supporting_chunk_ids(scenarios)
    results: List[EvalResult] = []
    for i, scenario in enumerate(scenarios):
        if i and args.sleep:
            time.sleep(args.sleep)  # free-tier providers limit requests per minute
        result = sut.run(scenario)
        result.supporting_chunk_ids = supporting.get(scenario["id"], [])
        results.append(result)
    overall = compute(results, judge)
    held = compute([r for r in results if r.held_out], judge)

    _print_table(f"ALL scenarios · SUT={sut.name}", overall)
    _print_table("HELD-OUT only (not used for tuning)", held)

    misses = [r.scenario_id for r in results if r.route != r.expected_route]
    models = sorted({m for r in results for m in r.details.get("models", [])})
    if args.sut == "agent":
        _print_scenarios(results)
        statuses = Counter(r.details.get("status") for r in results)
        reasons = Counter(r.details.get("reason_code") for r in results if r.details.get("reason_code"))
        print(f"\nstatuses: {dict(statuses)}  escalation reasons: {dict(reasons)}  models: {models}")
        if HEURISTIC_MODEL in models:
            print("WARNING: the LLM gateway was unreachable for some calls; those answers came "
                  "from the worker's local heuristic, not a model.")
    elif misses:
        print(f"\nroute mispredictions: {misses}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sut": sut.name,
        "tag": args.tag or getattr(sut, "tag", "baseline"),
        "k": args.k,
        "models": models,
        "prompt_versions": sorted({f"{k}:{v}" for r in results
                                   for k, v in r.details.get("prompt_versions", {}).items()}),
        "index_versions": sorted({r.details["index_version"] for r in results
                                  if r.details.get("index_version")}),
        "overall": overall,
        "held_out": held,
        "route_mispredictions": misses,
        "per_scenario": [
            {"id": r.scenario_id, "route": r.route, "expected_route": r.expected_route,
             "regulator": r.regulator, "expected_regulator": r.expected_regulator,
             "entity_type": r.entity_type, "expected_entity_type": r.expected_entity_type,
             "escalated": r.escalated, "expected_escalation": r.expected_escalation,
             "held_out": r.held_out, "n_claims": len(r.claims), "n_contexts": len(r.contexts),
             "supporting_retrieved": (bool(set(r.retrieved_chunk_ids) & set(r.supporting_chunk_ids))
                                      if r.supporting_chunk_ids else None),
             "supporting_cited": (bool(set(r.cited_chunk_ids) & set(r.supporting_chunk_ids))
                                  if r.supporting_chunk_ids and r.cited_chunk_ids is not None else None),
             **{k: v for k, v in r.details.items() if k not in ("prompt_versions", "index_version")}}
            for r in results
        ],
    }
    out = Path(args.out) if args.out else (RESULTS / f"{payload['tag']}.json")
    out.write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orcas-eval", description="ORCAS batch evaluation")
    p.add_argument("--sut", choices=["agent", "baseline"], default="agent",
                   help="agent = the shipped worker pipeline; baseline = keyword reference")
    p.add_argument("--llm", choices=["stub", "gateway"], default="stub",
                   help="agent only: in-process stub replies, or the model behind LLM_GATEWAY_URL")
    p.add_argument("--via-gateway", metavar="URL", default=None,
                   help="agent only: evaluate a running stack through its public API instead")
    p.add_argument("--retrieval-url", default=None,
                   help="agent only: use a running retrieval service instead of the in-process app")
    p.add_argument("--sleep", type=float, default=0.0, help="seconds between scenarios")
    p.add_argument("--timeout", type=float, default=180.0, help="via-gateway: seconds per run")
    p.add_argument("--k", type=int, default=5, help="baseline only: retrieved contexts per scenario")
    p.add_argument("--tag", default=None, help="results filename stem (default: from the SUT)")
    p.add_argument("--out", default=None, help="explicit output path")
    return p


def main(argv=None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

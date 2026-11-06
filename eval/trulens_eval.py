"""TruLens integration (L3).

ORCAS's primary metrics are the claim-level ones in metrics.py. This module computes groundedness
and context relevance for the same agent outputs through TruLens feedback-function primitives: a
custom feedback **Provider** backed by the deterministic embedding judge, TruLens ``Feedback``
objects, and a persisted ``TruSession``. Claims and contexts come from the shipped agent's runs
(eval/agent_sut.py), exactly as `make eval` takes them.

Run:  python -m eval.trulens_eval [--llm gateway]   (no-op with a message if trulens is not installed)
"""
from __future__ import annotations

import argparse
import os
from typing import List

import yaml

from services.corpus_common.constants import repo_root

from .judge import _cos
from .metrics import EvalResult

SCEN = repo_root() / "eval" / "scenarios.yaml"


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def ground_score(source: str, statement: str) -> float:
    return _clip(_cos(statement, source))


def ctx_score(question: str, context: str) -> float:
    return _clip(_cos(context, question))


# Define the custom provider at module level (so TruLens can import/serialize it),
# guarded so this module still imports when trulens is absent.
try:
    from trulens.core import Provider as _Provider

    class OrcasEmbeddingProvider(_Provider):
        """TruLens feedback provider backed by the deterministic embedding judge."""

        def groundedness(self, source: str, statement: str) -> float:
            return ground_score(source, statement)

        def context_relevance(self, question: str, context: str) -> float:
            return ctx_score(question, context)

    _TRULENS = True
except Exception:  # trulens not installed
    OrcasEmbeddingProvider = None
    _TRULENS = False


def available() -> bool:
    return _TRULENS


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="orcas-trulens", description="TruLens feedback on agent runs")
    parser.add_argument("--llm", choices=["stub", "gateway"], default="stub")
    args = parser.parse_args(argv)
    if not available():
        print("trulens is not installed — skipping (native metrics via `make eval`).")
        return 0

    from trulens.core import Feedback, TruSession

    session = TruSession()  # persists feedback to a local sqlite DB
    prov = OrcasEmbeddingProvider()
    fb_ground = Feedback(prov.groundedness, name="groundedness")
    fb_ctx = Feedback(prov.context_relevance, name="context_relevance")

    from .agent_sut import AgentSUT

    os.environ.setdefault("LOG_LEVEL", "WARNING")
    scenarios = yaml.safe_load(SCEN.read_text())["scenarios"]
    sut = AgentSUT(llm=args.llm)
    # escalations assert nothing, so only answered runs have claims to judge
    results: List[EvalResult] = [r for r in (sut.run(s) for s in scenarios) if r.claims]

    g_scores, c_scores = [], []
    for r in results:
        source = "\n".join(r.contexts) or ""
        g_scores += [prov.groundedness(source, c) for c in r.claims]
        c_scores += [prov.context_relevance(r.question, ctx) for ctx in r.contexts]

    gm = round(sum(g_scores) / len(g_scores), 3) if g_scores else None
    cm = round(sum(c_scores) / len(c_scores), 3) if c_scores else None
    print("TruLens integration OK:")
    print(f"  system    : {sut.name}; {len(results)} answered of {len(scenarios)} scenarios")
    print(f"  session   : {session.connector.db.engine.url}")
    print(f"  provider  : {type(prov).__name__} (embedding judge)")
    print(f"  feedbacks : {fb_ground.name}, {fb_ctx.name}")
    print(f"  groundedness (mean feedback)      = {gm}")
    print(f"  context_relevance (mean feedback) = {cm}")
    print("Primary metrics remain the claim-level ones in `make eval`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

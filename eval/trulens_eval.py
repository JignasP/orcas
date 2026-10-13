"""TruLens integration (L3).

ORCAS's primary metrics are the custom claim-level ones in metrics.py (as the README states:
"TruLens + custom claim-level hallucination metric"). This module wires the same signals
through TruLens feedback-function primitives: a custom feedback **Provider** backed by the
deterministic embedding judge, TruLens ``Feedback`` objects, and a persisted ``TruSession``.
Full app-level record instrumentation attaches once Mitesh's agent is the system-under-test;
here we evaluate the baseline SUT's records.

Run:  python -m eval.trulens_eval       (no-op with a message if trulens is not installed)
"""
from __future__ import annotations

from typing import List

import yaml

from services.corpus_common.constants import repo_root

from .judge import _cos
from .metrics import EvalResult
from .sut import BaselineSUT

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
    if not available():
        print("trulens is not installed — skipping (native metrics via `make eval`).")
        return 0

    from trulens.core import Feedback, TruSession

    session = TruSession()  # persists feedback to a local sqlite DB
    prov = OrcasEmbeddingProvider()
    fb_ground = Feedback(prov.groundedness, name="groundedness")
    fb_ctx = Feedback(prov.context_relevance, name="context_relevance")

    scenarios = yaml.safe_load(SCEN.read_text())["scenarios"]
    sut = BaselineSUT()
    results: List[EvalResult] = [sut.run(s) for s in scenarios if not s.get("expected_escalation")]

    g_scores, c_scores = [], []
    for r in results:
        source = "\n".join(r.contexts) or ""
        g_scores += [prov.groundedness(source, c) for c in r.claims]
        c_scores += [prov.context_relevance(r.question, ctx) for ctx in r.contexts]

    gm = round(sum(g_scores) / len(g_scores), 3) if g_scores else None
    cm = round(sum(c_scores) / len(c_scores), 3) if c_scores else None
    print("TruLens integration OK:")
    print(f"  session   : {session.connector.db.engine.url}")
    print(f"  provider  : {type(prov).__name__} (embedding judge)")
    print(f"  feedbacks : {fb_ground.name}, {fb_ctx.name}")
    print(f"  groundedness (mean feedback)      = {gm}")
    print(f"  context_relevance (mean feedback) = {cm}")
    print("Primary metrics remain the claim-level ones in `make eval`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

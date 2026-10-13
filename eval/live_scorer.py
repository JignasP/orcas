"""Live quality scoring (L6).

Samples N% of completed runs, scores each with the same metrics judge, and writes rows to an
``eval_scores`` store that Jignas's Grafana charts as "quality over time". Feedback (up/down)
is aggregated alongside. The RunStore / EvalScoreStore / FeedbackStore here are in-memory
seams with the exact shape Jignas's Postgres tables provide (the brief says: run the scorer
against an in-memory RunStore until the DB exists).

Sampling is deterministic (stable hash of run_id) so a run is either always sampled or never —
reproducible, and ~rate of runs are included.

Run:  python -m eval.live_scorer     (seeds demo runs from the scenarios, scores, prints)
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

from services.corpus_common.constants import repo_root

from .judge import EmbeddingJudge, Judge
from .sut import BaselineSUT

SAMPLE_RATE = float(os.getenv("LIVE_SCORE_SAMPLE_RATE", "0.2"))


@dataclass
class RunRecord:
    run_id: str
    question: str
    status: str            # completed | escalated | ...
    route: str = ""
    claims: List[str] = field(default_factory=list)
    contexts: List[str] = field(default_factory=list)


class InMemoryRunStore:
    def __init__(self, runs: List[RunRecord] = None):
        self._runs = runs or []

    def add(self, run: RunRecord):
        self._runs.append(run)

    def list_completed(self) -> List[RunRecord]:
        return [r for r in self._runs if r.status == "completed"]


class InMemoryEvalScoreStore:
    def __init__(self):
        self.rows: List[dict] = []

    def write(self, row: dict):
        self.rows.append(row)


class InMemoryFeedbackStore:
    def __init__(self):
        self._fb: Dict[str, str] = {}

    def add(self, run_id: str, rating: str):  # rating in {"up","down"}
        self._fb[run_id] = rating

    def aggregate(self) -> dict:
        up = sum(1 for v in self._fb.values() if v == "up")
        total = len(self._fb)
        return {"total": total, "up": up, "down": total - up,
                "up_rate": round(up / total, 3) if total else None}


def is_sampled(run_id: str, rate: float = SAMPLE_RATE) -> bool:
    bucket = int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16) % 100
    return bucket < round(rate * 100)


def score_run(run: RunRecord, judge: Judge) -> Optional[dict]:
    if not run.claims:
        return None
    ctx = run.contexts or [""]
    supported = sum(1 for c in run.claims if judge.supports(c, ctx))
    inferable = sum(1 for c in run.claims if judge.inferable(c, ctx))
    rel = sum(1 for p in run.contexts if judge.relevant(p, run.question)) if run.contexts else 0
    n = len(run.claims)
    return {
        "run_id": run.run_id,
        "groundedness": round(supported / n, 3),
        "faithfulness": round(inferable / n, 3),
        "context_relevance": round(rel / len(run.contexts), 3) if run.contexts else None,
        "hallucinated": supported < n,
    }


def run_live_scoring(run_store: InMemoryRunStore, score_store: InMemoryEvalScoreStore,
                     feedback_store: InMemoryFeedbackStore = None, rate: float = SAMPLE_RATE,
                     judge: Judge = None) -> dict:
    judge = judge or EmbeddingJudge()
    completed = run_store.list_completed()
    sampled = [r for r in completed if is_sampled(r.run_id, rate)]
    for run in sampled:
        row = score_run(run, judge)
        if row:
            score_store.write(row)
    rows = score_store.rows
    summary = {
        "completed_runs": len(completed),
        "sampled": len(sampled),
        "sample_rate": rate,
        "mean_groundedness": round(sum(r["groundedness"] for r in rows) / len(rows), 3) if rows else None,
        "mean_context_relevance": round(
            sum(r["context_relevance"] for r in rows if r["context_relevance"] is not None)
            / max(1, sum(1 for r in rows if r["context_relevance"] is not None)), 3) if rows else None,
        "hallucination_rate": round(sum(r["hallucinated"] for r in rows) / len(rows), 3) if rows else None,
    }
    if feedback_store is not None:
        summary["feedback"] = feedback_store.aggregate()
    return summary


def _seed_from_scenarios() -> tuple:
    """Demo: treat each non-escalation scenario's baseline output as a completed run."""
    scenarios = yaml.safe_load((repo_root() / "eval" / "scenarios.yaml").read_text())["scenarios"]
    sut = BaselineSUT()
    rs, fb = InMemoryRunStore(), InMemoryFeedbackStore()
    for i, s in enumerate(scenarios):
        res = sut.run(s)
        status = "escalated" if res.escalated else "completed"
        rs.add(RunRecord(run_id=f"run-{i:03d}", question=res.question, status=status,
                         route=res.route, claims=res.claims, contexts=res.contexts))
        fb.add(f"run-{i:03d}", "up" if i % 4 else "down")  # synthetic feedback
    return rs, fb


def main(argv=None) -> int:
    rs, fb = _seed_from_scenarios()
    summary = run_live_scoring(rs, InMemoryEvalScoreStore(), fb)
    print("live scoring summary (in-memory RunStore seam; Jignas's Postgres replaces it):")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

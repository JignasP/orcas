"""Live quality scoring (L6): score a deterministic sample of real completed runs.

Reads completed runs from Postgres, takes each run's evidence the same way the evaluation does
(eval/run_evidence.py: claims = the basis sentences, contexts = the passages the run retrieved),
scores it with the same embedding judge, and writes one `eval_scores` row per metric through the
shared RunStore. The worker-metrics exporter turns those rows into `orcas_eval_score{metric=...}`,
which Grafana charts as quality over time.

Sampling is a stable hash of the run id, so a run is either always or never sampled. Runs already
scored are skipped, so passes are idempotent. Runs with no retrieved passages in their trace (for
example, answers served from the run cache) are skipped rather than scored against nothing.

  python -m eval.live_scorer              # one pass over runs finished in the last 24 h
  python -m eval.live_scorer --loop 60    # keep scoring every 60 s (Compose service)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from typing import Iterable, Iterator, Optional, Tuple

from .judge import EmbeddingJudge, Judge
from .run_evidence import claims_from_determination, contexts_from_events

SAMPLE_RATE = float(os.getenv("LIVE_SCORE_SAMPLE_RATE", "0.2"))
SOURCE = "live_scorer"
METRICS = ("groundedness", "faithfulness", "context_relevance", "hallucination_rate")


def is_sampled(run_id: str, rate: float = SAMPLE_RATE) -> bool:
    bucket = int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16) % 100
    return bucket < round(rate * 100)


def score_run(determination: dict, events: list, question: str, judge: Judge) -> Optional[dict]:
    """Same computations as eval/metrics.py, for one run; None when there is nothing to judge."""
    claims = claims_from_determination(determination)
    contexts = contexts_from_events(events)
    if not claims or not contexts:
        return None
    supported = sum(1 for c in claims if judge.supports(c, contexts))
    inferable = sum(1 for c in claims if judge.inferable(c, contexts))
    relevant = sum(1 for p in contexts if judge.relevant(p, question))
    return {
        "groundedness": round(supported / len(claims), 3),
        "faithfulness": round(inferable / len(claims), 3),
        "context_relevance": round(relevant / len(contexts), 3),
        "hallucination_rate": float(supported < len(claims)),  # per run: 1 if any claim unsupported
        "_counts": {"claims": len(claims), "contexts": len(contexts)},
    }


class PostgresRunSource:
    """Completed runs not yet scored by this scorer (id, determination, complaint text), oldest first."""

    def __init__(self, url: Optional[str] = None, since_hours: float = 24.0):
        from libs.orcas_common.config import database_url

        self.url = url or database_url()
        self.since_hours = since_hours

    def candidates(self) -> Iterator[Tuple[str, dict, str]]:
        import psycopg

        with psycopg.connect(self.url) as connection:
            rows = connection.execute(
                "SELECT r.run_id::text, r.result, r.payload->>'text' FROM runs r "
                "WHERE r.status = 'completed' AND r.result IS NOT NULL "
                "AND r.finished_at > NOW() - make_interval(secs => %s) "
                "AND NOT EXISTS (SELECT 1 FROM eval_scores e WHERE e.run_id = r.run_id "
                "AND e.details->>'source' = %s) ORDER BY r.finished_at",
                (self.since_hours * 3600, SOURCE),
            ).fetchall()
        yield from rows

    def events(self, run_id: str) -> list:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            return connection.execute(
                "SELECT kind, payload FROM run_events WHERE run_id = %s ORDER BY seq", (run_id,),
            ).fetchall()


def run_live_scoring(source, store, rate: float = SAMPLE_RATE, judge: Judge = None) -> dict:
    """One pass: sample candidates, score each, write one eval_scores row per metric."""
    judge = judge or EmbeddingJudge()
    thresholds = {k: getattr(judge, k) for k in
                  ("support_threshold", "relevance_threshold", "infer_threshold") if hasattr(judge, k)}
    summary = {"candidates": 0, "sampled": 0, "scored": 0, "no_evidence": 0, "sample_rate": rate}
    totals = {m: 0.0 for m in METRICS}
    candidates: Iterable[Tuple[str, dict, str]] = source.candidates()
    for run_id, determination, question in candidates:
        summary["candidates"] += 1
        if not is_sampled(run_id, rate):
            continue
        summary["sampled"] += 1
        scores = score_run(determination, source.events(run_id), question or "", judge)
        if scores is None:
            summary["no_evidence"] += 1
            continue
        counts = scores.pop("_counts")
        details = {"source": SOURCE, "judge": getattr(judge, "name", type(judge).__name__),
                   "thresholds": thresholds, "sample_rate": rate, **counts}
        for metric in METRICS:
            store.add_eval_score(run_id, metric, scores[metric], details)
            totals[metric] += scores[metric]
        summary["scored"] += 1
    if summary["scored"]:
        summary["means"] = {m: round(totals[m] / summary["scored"], 3) for m in METRICS}
    return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orcas-live-scorer", description="Score sampled live runs (L6)")
    p.add_argument("--loop", type=float, default=0, metavar="SECONDS",
                   help="repeat every SECONDS; default is a single pass")
    p.add_argument("--rate", type=float, default=SAMPLE_RATE, help="share of runs to score")
    p.add_argument("--since-hours", type=float, default=24.0, help="only runs finished this recently")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    from libs.orcas_common.runstore import PostgresRunStore

    try:
        source = PostgresRunSource(since_hours=args.since_hours)
    except RuntimeError as exc:  # DATABASE_URL missing
        print(f"live scorer: {exc}", file=sys.stderr)
        return 2
    store, judge = PostgresRunStore(source.url), EmbeddingJudge()
    while True:
        summary = run_live_scoring(source, store, rate=args.rate, judge=judge)
        summary["feedback"] = store.feedback_summary()
        print(f"live scorer: {summary}", flush=True)
        if not args.loop:
            return 0
        time.sleep(args.loop)


if __name__ == "__main__":
    raise SystemExit(main())

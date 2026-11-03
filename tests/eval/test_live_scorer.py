"""Live scoring (T6): sampled real runs scored with the evaluation's judge and evidence rules."""
import os
import uuid

import pytest

from eval.live_scorer import METRICS, SOURCE, is_sampled, run_live_scoring, score_run
from libs.orcas_common.runstore import InMemoryRunStore

QUESTION = "My bank fixed deposit paid less interest than promised."
COMPLETED = {"status": "completed", "route": "refer_to_other_regulator", "regulator": "RBI",
             "basis": "SUPPORTED the scheme covers bank deposits [c1]. A second claim is weak [c2]."}
EVENTS = [{"kind": "llm_call", "payload": {}},
          {"kind": "tool_call", "payload": {"passages": [
              {"chunk_id": "a", "text": "REL passage about deposits"},
              {"chunk_id": "b", "text": "unrelated passage"}]}}]


class FakeJudge:
    name = "fake"
    support_threshold = relevance_threshold = infer_threshold = 0.5

    def supports(self, claim, passages):
        return "SUPPORTED" in claim

    def inferable(self, claim, passages):
        return "SUPPORTED" in claim or "weak" in claim

    def relevant(self, passage, question):
        return "REL" in passage and question == QUESTION


class ListSource:
    def __init__(self, runs):
        self.runs = runs  # run_id -> (determination, events, question)

    def candidates(self):
        return [(rid, det, q) for rid, (det, _, q) in self.runs.items()]

    def events(self, run_id):
        return self.runs[run_id][1]


def test_is_sampled_is_deterministic_and_bounded():
    ids = [f"run-{i:04d}" for i in range(500)]
    assert [is_sampled(i, 0.2) for i in ids] == [is_sampled(i, 0.2) for i in ids]
    assert 0.1 < sum(is_sampled(i, 0.2) for i in ids) / 500 < 0.3
    assert not any(is_sampled(i, 0.0) for i in ids) and all(is_sampled(i, 1.0) for i in ids)


def test_score_run_matches_the_evaluation_definitions():
    s = score_run(COMPLETED, EVENTS, QUESTION, FakeJudge())
    assert (s["groundedness"], s["faithfulness"]) == (0.5, 1.0)
    assert s["context_relevance"] == 0.5          # relevance is judged against the complaint text
    assert s["hallucination_rate"] == 1.0         # one claim unsupported
    assert s["_counts"] == {"claims": 2, "contexts": 2}


def test_nothing_to_judge_for_escalations_or_runs_without_retrieved_passages():
    assert score_run({**COMPLETED, "status": "escalated"}, EVENTS, QUESTION, FakeJudge()) is None
    assert score_run(COMPLETED, [{"kind": "cache_hit", "payload": {}}], QUESTION, FakeJudge()) is None


def test_pass_writes_one_row_per_metric_for_sampled_runs():
    store = InMemoryRunStore()
    runs = {}
    for _ in range(3):
        rid = str(uuid.uuid4())
        store.create_run(rid, {"text": QUESTION})
        runs[rid] = (COMPLETED, EVENTS, QUESTION)
    cached = str(uuid.uuid4())
    store.create_run(cached, {"text": QUESTION})
    runs[cached] = (COMPLETED, [], QUESTION)

    summary = run_live_scoring(ListSource(runs), store, rate=1.0, judge=FakeJudge())
    assert summary["candidates"] == 4 and summary["scored"] == 3 and summary["no_evidence"] == 1
    assert len(store.eval_scores) == 3 * len(METRICS)
    assert {row["metric"] for row in store.eval_scores} == set(METRICS)
    assert all(row["details"]["source"] == SOURCE for row in store.eval_scores)
    assert summary["means"]["groundedness"] == 0.5

    assert run_live_scoring(ListSource(runs), InMemoryRunStore(), rate=0.0)["sampled"] == 0


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_postgres_pass_scores_completed_runs_once():
    from eval.live_scorer import PostgresRunSource
    from libs.orcas_common.migrate import migrate
    from libs.orcas_common.runstore import PostgresRunStore

    url = os.environ["TEST_DATABASE_URL"]
    migrate(url)
    store = PostgresRunStore(url)
    run_id = str(uuid.uuid4())
    store.create_run(run_id, {"client_id": "live", "text": QUESTION})
    store.claim_run(run_id)
    store.append_event(run_id, "retrieval", "search", "tool_call", payload=EVENTS[1]["payload"])
    store.complete(run_id, {**COMPLETED, "run_id": run_id})
    escalated = str(uuid.uuid4())
    store.create_run(escalated, {"client_id": "live", "text": QUESTION})
    store.claim_run(escalated)
    store.complete(escalated, {**COMPLETED, "run_id": escalated, "status": "escalated"})

    source = PostgresRunSource(url, since_hours=1)
    first = run_live_scoring(source, store, rate=1.0, judge=FakeJudge())
    assert first["scored"] >= 1
    import psycopg

    with psycopg.connect(url) as connection:
        rows = connection.execute(
            "SELECT metric FROM eval_scores WHERE run_id = %s AND details->>'source' = %s",
            (run_id, SOURCE)).fetchall()
    assert sorted(r[0] for r in rows) == sorted(METRICS)
    assert run_live_scoring(PostgresRunSource(url, since_hours=1), store, rate=1.0,
                            judge=FakeJudge())["scored"] == 0  # already scored: idempotent

"""Slice-6 experiment harness + live scorer."""
import pytest

from services.corpus_common import store
from eval import experiment, live_scorer
from eval.live_scorer import (
    InMemoryEvalScoreStore,
    InMemoryFeedbackStore,
    InMemoryRunStore,
    RunRecord,
    is_sampled,
    run_live_scoring,
)


# --- experiment harness ---
def test_run_configs_returns_metrics():
    if store.get_collection().count() == 0:
        pytest.skip("index not built")
    scen = [
        {"id": "a", "complaint_text": "I invested in a fixed deposit through my bank app; interest is low.",
         "expected_route": "refer_to_other_regulator", "expected_regulator": "RBI",
         "expected_entity_type": "bank", "expected_escalation": False, "held_out": False},
        {"id": "b", "complaint_text": "My mutual fund redemption is delayed and the NAV is wrong.",
         "expected_route": "assign_to_entity", "expected_regulator": "SEBI",
         "expected_entity_type": "mutual_fund", "expected_escalation": False, "held_out": False},
    ]
    out = experiment.run_configs(
        {"off": {"use_framework_filter": False}, "on": {"use_framework_filter": True}}, scenarios=scen)
    assert set(out) == {"off", "on"}
    for m in out.values():
        assert "groundedness" in m and "route_accuracy" in m


# --- live scorer ---
def test_is_sampled_is_deterministic_and_bounded():
    ids = [f"run-{i:04d}" for i in range(500)]
    s1 = [is_sampled(i, 0.2) for i in ids]
    s2 = [is_sampled(i, 0.2) for i in ids]
    assert s1 == s2  # deterministic
    frac = sum(s1) / len(ids)
    assert 0.1 < frac < 0.3  # ~20%


def test_live_scoring_writes_scores_and_feedback():
    rs = InMemoryRunStore([
        RunRecord(run_id="run-0001", question="bank fd interest low", status="completed",
                  route="refer_to_other_regulator",
                  claims=["The complaint is routed to RBI.", "Deficiency in service applies."],
                  contexts=["grounds of complaint deficiency in service regulated entity"]),
        RunRecord(run_id="run-0002", question="escalated case", status="escalated"),
    ])
    scores = InMemoryEvalScoreStore()
    fb = InMemoryFeedbackStore()
    fb.add("run-0001", "up")
    fb.add("run-0002", "down")
    summary = run_live_scoring(rs, scores, fb, rate=1.0)
    assert summary["completed_runs"] == 1  # escalated excluded
    assert summary["sampled"] == 1
    assert len(scores.rows) == 1
    assert 0.0 <= scores.rows[0]["groundedness"] <= 1.0
    assert summary["feedback"]["up_rate"] == 0.5

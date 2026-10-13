"""metrics.compute correctness with a deterministic fake judge (no embeddings)."""
from eval.metrics import EvalResult, compute, split_claims


class FakeJudge:
    name = "fake"

    def supports(self, claim, passages):
        return "SUPPORTED" in claim

    def relevant(self, passage, question):
        return "REL" in passage

    def inferable(self, claim, passages):
        return "SUPPORTED" in claim or "INFER" in claim


def _r(**kw):
    base = dict(scenario_id="s", question="q", route="", regulator="", entity_type="",
                escalated=False, contexts=[], claims=[], expected_route="", expected_regulator="",
                expected_entity_type="", expected_escalation=False)
    base.update(kw)
    return EvalResult(**base)


def test_rag_and_label_metrics():
    results = [
        _r(scenario_id="a", claims=["SUPPORTED a.", "SUPPORTED b."], contexts=["REL x", "no y"],
           route="assign_to_entity", expected_route="assign_to_entity"),
        _r(scenario_id="b", claims=["SUPPORTED c.", "bad d."], contexts=["REL z"],
           route="assign_to_entity", expected_route="refer_to_other_regulator"),
        _r(scenario_id="c", escalated=True, expected_escalation=True,
           route="escalate_to_human", expected_route="escalate_to_human"),
    ]
    m = compute(results, FakeJudge())
    assert m["n_scenarios"] == 3 and m["n_answered"] == 2
    assert m["groundedness"] == 0.75          # (1.0 + 0.5) / 2
    assert m["context_relevance"] == 0.75     # (0.5 + 1.0) / 2
    assert m["faithfulness"] == 0.75          # r_a 1.0, r_b 0.5 -> mean 0.75
    assert m["hallucination_rate"] == 0.5     # r_b has an unsupported claim
    assert m["route_accuracy"] == round(2 / 3, 3)
    assert m["escalation_precision"] == 1.0 and m["escalation_recall"] == 1.0


def test_split_claims():
    cs = split_claims("The route is X. It is grounded in clause 9; see the scheme.")
    assert len(cs) >= 2

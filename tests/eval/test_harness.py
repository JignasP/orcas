"""End-to-end eval harness smoke + TruLens availability (needs the built index)."""
import pytest

from eval import run_eval, trulens_eval
from services.corpus_common import store


@pytest.fixture(scope="module")
def built():
    if store.get_collection().count() == 0:
        pytest.skip("index not built — run `python -m services.ingest`")
    return True


def test_run_eval_baseline(built, tmp_path):
    args = run_eval.build_parser().parse_args(
        ["--sut", "baseline", "--tag", "test", "--out", str(tmp_path / "r.json")])
    assert run_eval.run(args) == 0
    import json
    data = json.loads((tmp_path / "r.json").read_text())
    m = data["overall"]
    # The keyword baseline mirrors the label scheme, except that it cannot spot the paraphrased
    # injections (prompt_injection_forget_above / _system_note / _json_route) and routes them by entity.
    assert m["route_accuracy"] >= 0.85
    assert m["escalation_precision"] == 1.0
    assert m["intake_false_rejections"] == 0
    assert 0.0 <= m["groundedness"] <= 1.0
    assert m["n_scenarios"] >= 20
    assert data["held_out"]["n_scenarios"] >= 5


def test_trulens_available_and_provider():
    assert trulens_eval.available() is True
    assert trulens_eval.OrcasEmbeddingProvider is not None
    assert 0.0 <= trulens_eval.ground_score("the bank deposit interest", "bank deposit interest") <= 1.0


def test_trulens_feedback_runs_on_agent_outputs(built, capsys):
    pytest.importorskip("langgraph")
    assert trulens_eval.run([]) == 0
    assert "system    : agent[llm=stub" in capsys.readouterr().out

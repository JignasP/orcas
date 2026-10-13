"""End-to-end eval harness smoke + TruLens availability (needs the built index)."""
import pytest

from services.corpus_common import store
from eval import run_eval, trulens_eval


@pytest.fixture(scope="module")
def built():
    if store.get_collection().count() == 0:
        pytest.skip("index not built — run `python -m services.ingest`")
    return True


def test_run_eval_baseline(built, tmp_path):
    args = run_eval.build_parser().parse_args(["--tag", "test", "--out", str(tmp_path / "r.json")])
    assert run_eval.run(args) == 0
    import json
    data = json.loads((tmp_path / "r.json").read_text())
    m = data["overall"]
    # baseline classifier mirrors the label scheme, so label metrics are perfect; the
    # meaningful baseline signal is the RAG metrics (retrieval-dependent).
    assert m["route_accuracy"] == 1.0
    assert m["escalation_recall"] == 1.0
    assert 0.0 <= m["groundedness"] <= 1.0
    assert m["n_scenarios"] >= 20
    assert data["held_out"]["n_scenarios"] >= 5


def test_trulens_available_and_provider():
    assert trulens_eval.available() is True
    assert trulens_eval.OrcasEmbeddingProvider is not None
    assert 0.0 <= trulens_eval.ground_score("the bank deposit interest", "bank deposit interest") <= 1.0

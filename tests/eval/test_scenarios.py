"""eval/scenarios.yaml v0 is well-formed and its supporting passages resolve."""
import pytest
import yaml

from services.corpus_common import store
from services.corpus_common.constants import repo_root
from services.retrieval.service import Retriever

SCEN = repo_root() / "eval" / "scenarios.yaml"
_ROUTES = {"assign_to_entity", "refer_to_other_regulator", "not_maintainable", "escalate_to_human"}


@pytest.fixture(scope="module")
def scenarios():
    return yaml.safe_load(SCEN.read_text())["scenarios"]


def test_ten_scenarios_well_formed(scenarios):
    assert len(scenarios) >= 10
    for s in scenarios:
        assert s["expected_route"] in _ROUTES
        assert len(s["complaint_text"]) >= 30
        assert "expected_escalation" in s
        assert s["expected_regulator"] in {"SEBI", "RBI", "UNDETERMINED"}


def test_supporting_passages_resolve(scenarios):
    if store.get_collection().count() == 0:
        pytest.skip("index not built")
    r = Retriever()
    for s in scenarios:
        sp = s.get("supporting_passage")
        if not sp:
            continue
        clause = r.get_clause(sp["doc_id"], sp["clause_id"])
        assert clause is not None, f"{s['id']}: {sp['doc_id']}/{sp['clause_id']} did not resolve"
        assert sp["quote"][:40] in clause.text, f"{s['id']}: quote not in clause text"

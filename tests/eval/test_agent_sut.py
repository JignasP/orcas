"""AgentSUT scores the shipped worker pipeline (T1), not the keyword baseline."""
import json

import httpx
import pytest

from eval.agent_sut import AgentSUT, claims_from_determination, contexts_from_events
from services.corpus_common import store

SCENARIO = {
    "id": "ref_4_1_bank_fd",
    "complaint_text": "I invested in a fixed deposit through my bank's app. The interest credited "
                      "is lower than what I was promised. I want to complain to SEBI.",
    "expected_route": "refer_to_other_regulator", "expected_regulator": "RBI",
    "expected_entity_type": "bank", "expected_escalation": False,
}


def _event(kind, **payload):
    return {"kind": kind, "payload": payload}


def test_contexts_are_retrieved_passages_in_order_without_duplicates():
    events = [
        _event("llm_call", model="m"),
        _event("tool_call", passages=[{"chunk_id": "a", "text": "A"}, {"chunk_id": "b", "text": "B"}]),
        _event("tool_call", passages=[{"chunk_id": "a", "text": "A"}, {"chunk_id": "c", "text": "C"}]),
    ]
    assert contexts_from_events(events) == ["A", "B", "C"]


def test_claims_come_from_completed_basis_with_citation_tags_removed():
    det = {"status": "completed",
           "basis": "The complaint concerns a bank deposit [c1]. RBI's scheme covers deficiency in service [c2]."}
    assert claims_from_determination(det) == [
        "The complaint concerns a bank deposit.", "RBI's scheme covers deficiency in service."]
    assert claims_from_determination({"status": "escalated", "basis": "Escalated to a human officer."}) == []
    assert claims_from_determination(None) == []


def _gateway(handler):
    return httpx.Client(base_url="http://gw", transport=httpx.MockTransport(handler))


def test_via_gateway_reads_result_and_trace():
    det = {"status": "completed", "route": "refer_to_other_regulator", "regulator": "RBI",
           "entity_type": "bank", "basis": "Bank deposits fall under the RBI scheme [c1].",
           "citations": [{"doc_id": "rbi", "clause": "9", "chunk_id": "x"}], "escalation": None,
           "prompt_versions": {"verifier": "v1"}, "index_version": "iv", "degraded": False}
    events = [_event("llm_call", model="m1"),
              _event("tool_call", passages=[{"chunk_id": "x", "text": "9. Grounds of Complaint"}])]

    def handler(request):
        if request.method == "POST":
            assert request.headers["X-Run-Cache-Bypass"] == "true"
            return httpx.Response(202, json={"run_id": "r1", "status_url": "/v1/runs/r1"})
        if request.url.path.endswith("/trace"):
            return httpx.Response(200, json={"events": events})
        return httpx.Response(200, json={"run_id": "r1", "status": "completed", "result": det})

    r = AgentSUT(via_gateway="http://gw", gateway_client=_gateway(handler)).run(SCENARIO)
    assert (r.route, r.regulator, r.escalated) == ("refer_to_other_regulator", "RBI", False)
    assert r.contexts == ["9. Grounds of Complaint"]
    assert r.claims == ["Bank deposits fall under the RBI scheme."]
    assert r.details["models"] == ["m1"] and r.details["citations"][0]["clause"] == "9"


def test_via_gateway_counts_intake_rejection_as_unanswered():
    body = {"detail": [{"field": "text", "type": "guardrail:injection"}], "quarantine_id": "q1"}
    r = AgentSUT(via_gateway="http://gw",
                 gateway_client=_gateway(lambda req: httpx.Response(422, json=body))).run(SCENARIO)
    assert r.escalated and r.claims == []
    assert r.details["intake"] == "rejected" and r.details["intake_errors"] == ["guardrail:injection"]


@pytest.fixture(scope="module")
def built():
    pytest.importorskip("langgraph")
    if store.get_collection().count() == 0:
        pytest.skip("index not built — run `python -m services.ingest`")
    return True


def test_in_process_agent_runs_the_worker_pipeline(built):
    r = AgentSUT(llm="stub").run(SCENARIO)
    assert r.details["status"] in {"completed", "escalated"}
    assert r.details["models"] == ["llm-stub"]
    assert r.details["tool_calls"] >= 1 and r.contexts  # passages captured from the run trace
    json.dumps(r.details)  # results file must be serialisable

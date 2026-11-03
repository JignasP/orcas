"""Fake gateway: submit -> poll -> determination, per documented contract.

Status is time-based; tests fast-forward a run's clock instead of sleeping.
"""
from fastapi.testclient import TestClient

from services.web import fake_gateway
from services.web.fake_gateway import app

client = TestClient(app)


def _submit(text):
    r = client.post("/v1/complaints", json={"client_id": "demo-client", "is_synthetic": True,
                                             "channel": "web", "text": text})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    assert r.json()["status_url"].endswith(run_id)
    return run_id


def _complete(run_id):
    # fast-forward past the queued/running window
    fake_gateway._RUNS[run_id]["t0"] -= 5
    return client.get(f"/v1/runs/{run_id}").json()


def test_queued_then_terminal():
    run_id = _submit("I invested in a fixed deposit through my bank's app; interest is lower than promised.")
    first = client.get(f"/v1/runs/{run_id}").json()
    assert first["status"] in ("queued", "running")
    assert "result" not in first or first.get("result") is None


def test_bank_fd_routes_to_rbi_with_citations():
    run = _complete(_submit("I invested in a fixed deposit through my bank's app; interest is lower than promised."))
    assert run["status"] == "completed"
    d = run["result"]
    assert d["route"] == "refer_to_other_regulator"
    assert d["regulator"] == "RBI"
    assert d["entity_type"] == "bank"
    assert len(d["citations"]) == 3
    assert all(c["chunk_id"] and c["quote_span"] for c in d["citations"])


def test_insurance_escalates_out_of_corpus():
    run = _complete(_submit("My life insurance policy claim was rejected by the insurer."))
    assert run["status"] == "escalated"
    assert run["result"]["route"] == "escalate_to_human"
    assert run["result"]["escalation"]["reason_code"] == "out_of_corpus"


def test_generic_securities_assigns_to_entity():
    run = _complete(_submit("My mutual fund redemption is delayed and the NAV statement is wrong."))
    assert run["result"]["route"] == "assign_to_entity"
    assert run["result"]["regulator"] == "SEBI"


def test_unknown_run_404():
    assert client.get("/v1/runs/nope").status_code == 404


def test_static_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "ORCAS" in r.text


def test_feedback_recorded():
    run_id = _submit("My demat account was frozen by the depository participant.")
    r = client.post(f"/v1/runs/{run_id}/feedback", json={"rating": "up", "reason": "accurate"})
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"
    assert fake_gateway._FEEDBACK[run_id]["rating"] == "up"


def test_feedback_unknown_run_404():
    assert client.post("/v1/runs/nope/feedback", json={"rating": "down"}).status_code == 404


PINNED_4_1 = {  # docs/work/tahir/evaluation-1-package.md, addendum
    "d2d66258e59fc24f14530d30125912f54bd3c045f20e9a915253e947e682323e",  # SEBI clause 2
    "c3cdfa20cf3464b2e00edbf53c1392dffdd8a237837b12f092cc4bdfa3bcc2b0",  # RBI preamble
    "17192ff2b4575e221099d33358788a939ad2059d5b9617db56f157b82b726a64",  # RBI clause 9
}


def test_bank_fd_cites_the_pinned_reference_passages():
    run = _complete(_submit("I invested in a fixed deposit through my bank app; interest is lower than promised."))
    cites = run["result"]["citations"]
    assert {c["chunk_id"] for c in cites} == PINNED_4_1
    assert {c["clause"] for c in cites} == {"2", "preamble", "9"}
    assert all("passage_text" not in c for c in cites)  # not part of determination.v1


def test_trace_lists_the_retrieved_passages_behind_each_citation():
    run_id = _submit("I invested in a fixed deposit through my bank app; interest is lower than promised.")
    run = _complete(run_id)
    trace = client.get(f"/v1/runs/{run_id}/trace").json()
    retrieved = {p["chunk_id"]: p["text"] for e in trace["events"] if e["kind"] == "tool_call"
                 for p in e["payload"]["passages"]}
    for c in run["result"]["citations"]:
        assert c["quote_span"] in retrieved[c["chunk_id"]]


def test_trace_unknown_run_404():
    assert client.get("/v1/runs/nope/trace").status_code == 404

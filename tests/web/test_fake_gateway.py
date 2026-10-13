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

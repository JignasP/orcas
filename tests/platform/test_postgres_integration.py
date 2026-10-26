"""Opt-in database integration test: set TEST_DATABASE_URL to a disposable database."""

import os
from datetime import date, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from libs.orcas_common.migrate import migrate
from libs.orcas_common.runstore import PostgresRunStore
from services.gateway.app import create_app

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


class RecordingDispatcher:
    def __init__(self):
        self.sent = []

    def send(self, run_id):
        self.sent.append(run_id)

    def ping(self):
        return True


def test_postgres_intake_quarantine_and_worker_handoff():
    url = os.environ["TEST_DATABASE_URL"]
    migrate(url)
    migrate(url)  # The startup migration must be safe to rerun.
    store = PostgresRunStore(url)
    dispatcher = RecordingDispatcher()
    client = TestClient(create_app(store=store, dispatcher=dispatcher))
    today = date.today()
    payload = {
        "client_id": "pg-demo",
        "is_synthetic": True,
        "channel": "web",
        "text": "My bank fixed deposit credited less interest than promised and I need it reviewed.",
        "date_of_event": (today - timedelta(days=14)).isoformat(),
        "date_filed": today.isoformat(),
    }

    with psycopg.connect(url) as connection:
        runs_before = connection.execute("SELECT count(*) FROM runs").fetchone()[0]

    malformed = dict(payload, date_filed=(today - timedelta(days=15)).isoformat())
    rejected = client.post("/v1/complaints", json=malformed)
    assert rejected.status_code == 422
    quarantine_id = rejected.json()["quarantine_id"]
    assert store.get_quarantine(quarantine_id)["reason"] == "validation"
    assert dispatcher.sent == []
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT count(*) FROM runs").fetchone()[0] == runs_before

    accepted = client.post("/v1/complaints", json=payload)
    assert accepted.status_code == 202
    run_id = accepted.json()["run_id"]
    assert dispatcher.sent == [run_id]
    assert store.claim_run(run_id) is True
    assert store.claim_run(run_id) is False
    store.append_event(run_id, "system", "start", "run_started")
    store.complete(run_id, {"status": "completed", "route": "refer_to_other_regulator"})
    store.complete(run_id, {"status": "escalated"})
    assert store.get_events(run_id)[0]["seq"] == 1
    response = client.get(f"/v1/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result"]["route"] == "refer_to_other_regulator"

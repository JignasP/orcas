"""/metrics endpoint smoke (F8)."""
import pytest
from fastapi.testclient import TestClient

from services.corpus_common import store
from services.retrieval.app import app


@pytest.fixture(scope="module")
def client():
    if store.get_collection().count() == 0:
        pytest.skip("index not built — run `python -m services.ingest` first")
    return TestClient(app)


def test_metrics_exposes_orcas_series(client):
    # drive one search so the counters/histograms have samples
    client.post("/v1/search", json={"query": "grounds of complaint", "k": 3})
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    for name in (
        "orcas_retrieval_requests_total",
        "orcas_retrieval_latency_seconds",
        "orcas_retrieval_results_per_query",
        "orcas_index_chunks",
        "orcas_index_built_timestamp",
    ):
        assert name in body


def test_index_chunks_gauge_matches(client):
    client.get("/metrics")
    from services.retrieval import metrics as m

    assert m.INDEX_CHUNKS._value.get() == 606

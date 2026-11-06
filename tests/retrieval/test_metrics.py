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

    assert m.INDEX_CHUNKS._value.get() == store.get_collection().count()


def test_ingest_and_document_gauges_follow_index_info(monkeypatch):
    from services.retrieval import metrics as m

    info = {"chunk_count": 3, "built_at": "2026-11-03T00:00:00+00:00",
            "throughput": {"chunks_per_s": 12.5, "pages_per_s": 2.0, "elapsed_s": 4.0, "embedded": 0},
            "documents": [{"doc_id": "rbi", "version": "2021", "source_sha256": "a354a73bc5a3abc",
                           "chunk_count": 3}]}
    monkeypatch.setattr(m.store, "read_index_info", lambda: info)
    m.refresh_index_gauges()
    assert m.INGEST_CHUNKS_PER_S._value.get() == 12.5
    assert m.INGEST_EMBEDDED._value.get() == 0
    assert m.DOC_CHUNKS.labels("rbi", "2021", "a354a73bc5a3")._value.get() == 3

    info["documents"] = []  # a document removed from the index disappears from the series
    m.refresh_index_gauges()
    assert not m.DOC_CHUNKS._metrics

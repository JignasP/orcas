"""HTTP-level smoke test of the retrieval app against the contract.

Skips if the index has not been built (data/chroma empty).
"""
import json

import pytest
from fastapi.testclient import TestClient

from services.corpus_common import store
from services.corpus_common.constants import repo_root
from services.retrieval.app import app

FIXTURES = repo_root() / "tests" / "fixtures" / "retrieval_fixtures.json"


@pytest.fixture(scope="module")
def client():
    if store.get_collection().count() == 0:
        pytest.skip("index not built — run `python -m services.ingest` first")
    return TestClient(app)


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_index_info(client):
    r = client.get("/v1/index/info")
    assert r.status_code == 200
    body = r.json()
    assert body["chunk_count"] == store.get_collection().count()
    assert body["chunk_count"] > 0
    assert len(body["documents"]) == 3
    assert body["model_tag"] == "minilm-l6-v2"


def test_search_and_resolve_citation(client):
    ref = next(
        f for f in json.loads(FIXTURES.read_text())["fixtures"] if f["id"] == "ref_4_1_bank_fd"
    )
    r = client.post(
        "/v1/search",
        json={
            "query": "bank deposit deficiency in service grounds of complaint",
            "k": 5,
            "filters": {"framework": "RBI"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["index_version"]
    assert all(p["framework"] == "RBI" for p in body["results"])

    # resolve a fixture citation with quote-span verification
    sup = ref["supporting_passages"][0]
    rc = client.get(f"/v1/chunks/{sup['chunk_id']}", params={"quote_span": sup["quote"]})
    assert rc.status_code == 200
    assert rc.json()["quote_span_found"] is True


def test_unknown_chunk_404(client):
    r = client.get("/v1/chunks/" + "00" * 32)
    assert r.status_code == 404


def test_search_validation_422(client):
    r = client.post("/v1/search", json={"query": "", "k": 5})
    assert r.status_code == 422

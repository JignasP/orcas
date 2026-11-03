"""Retrieval hardening: /health liveness, /ready readiness (index + model), warm-up, timeout, empty-index."""
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.corpus_common import embedding, store
from services.retrieval.app import app, warm_up, with_timeout
from services.retrieval.models import SearchRequest
from services.retrieval.service import Retriever


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health_is_always_live(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready_reflects_index(client):
    warm_up()
    r = client.get("/ready")
    if store.get_collection().count() > 0:
        assert r.status_code == 200 and r.json()["status"] == "ok"
        assert r.json()["model_loaded"] is True
    else:
        assert r.status_code == 503


def test_not_ready_until_the_model_is_loaded(client, monkeypatch):
    monkeypatch.setattr(embedding, "model_loaded", lambda: False)
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["model_loaded"] is False
    live = client.get("/health")  # liveness stays up while the model loads
    assert live.status_code == 200 and live.json()["model_loaded"] is False


def test_startup_warms_the_embedding_model_in_the_background():
    import threading

    with TestClient(app):  # runs the lifespan
        workers = [t for t in threading.enumerate() if t.name == "embedding-warmup"]
        for t in workers:
            t.join(timeout=120)
    assert embedding.model_loaded()


def test_with_timeout_returns_and_raises():
    assert with_timeout(lambda: 42, timeout=1) == 42
    with pytest.raises(HTTPException) as ei:
        with_timeout(lambda: time.sleep(0.5), timeout=0.05)
    assert ei.value.status_code == 504


def test_timed_out_search_that_never_started_is_cancelled(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from services.retrieval import app as retrieval_app

    monkeypatch.setattr(retrieval_app, "_EXECUTOR", ThreadPoolExecutor(max_workers=1))
    release, ran = threading.Event(), []
    retrieval_app._EXECUTOR.submit(release.wait)  # occupy the only worker
    with pytest.raises(HTTPException) as ei:
        with_timeout(lambda: ran.append(True), timeout=0.05)  # queued behind it, then times out
    assert ei.value.status_code == 504
    release.set()
    retrieval_app._EXECUTOR.shutdown(wait=True)
    assert ran == []  # cancelled while queued: it never ran for a caller that had given up


def test_empty_index_search_is_graceful(tmp_path):
    client_db = store.get_client(str(tmp_path / "chroma"))
    empty = store.get_collection(client_db, name="empty_corpus")
    r = Retriever(collection=empty)
    resp = r.search(SearchRequest(query="anything", k=5))
    assert resp.count == 0 and resp.results == []
    assert r.get_chunk("does-not-exist") is None

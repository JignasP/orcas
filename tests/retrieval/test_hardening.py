"""Retrieval hardening (Slice 7): /health liveness, /ready readiness, timeout, empty-index."""
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.corpus_common import store
from services.retrieval.app import app, with_timeout
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
    r = client.get("/ready")
    if store.get_collection().count() > 0:
        assert r.status_code == 200 and r.json()["status"] == "ok"
    else:
        assert r.status_code == 503


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

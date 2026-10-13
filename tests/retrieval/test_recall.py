"""Recall@k sanity on the §4.1 case + fixture-citation resolution.

Runs against the persisted index (data/chroma) built by `python -m services.ingest`.
Skips cleanly if the index has not been built, so the suite still passes on a
machine that has not run ingest.
"""
import json

import pytest

from services.corpus_common import store
from services.corpus_common.constants import repo_root
from services.retrieval.models import SearchFilters, SearchRequest
from services.retrieval.service import Retriever

FIXTURES = repo_root() / "tests" / "fixtures" / "retrieval_fixtures.json"


@pytest.fixture(scope="module")
def retriever():
    col = store.get_collection()
    if col.count() == 0:
        pytest.skip("index not built — run `python -m services.ingest` first")
    return Retriever(collection=col)


@pytest.fixture(scope="module")
def fixtures():
    return json.loads(FIXTURES.read_text())["fixtures"]


def _ids(resp):
    return [p.chunk_id for p in resp.results]


def test_4_1_framework_swap_recall(retriever, fixtures):
    ref = next(f for f in fixtures if f["id"] == "ref_4_1_bank_fd")
    grounds = next(p for p in ref["supporting_passages"] if p["clause_id"] == "p6w0")
    scope = next(p for p in ref["supporting_passages"] if p["clause_id"] == "p1w0")

    r_grounds = retriever.search(SearchRequest(
        query="bank deposit deficiency in service grounds of complaint regulated entity",
        k=5, filters=SearchFilters(framework="RBI")))
    assert grounds["chunk_id"] in _ids(r_grounds)

    r_scope = retriever.search(SearchRequest(
        query="scheme applies to services provided by a regulated entity to its customers",
        k=5, filters=SearchFilters(framework="RBI")))
    assert scope["chunk_id"] in _ids(r_scope)


def test_4_1_apparent_sebi_hit(retriever, fixtures):
    ref = next(f for f in fixtures if f["id"] == "ref_4_1_bank_fd")
    apparent = ref["apparent_passages"][0]
    resp = retriever.search(SearchRequest(
        query=ref["complaint_text"], k=5, filters=SearchFilters(framework="SEBI")))
    assert apparent["chunk_id"] in _ids(resp)


def test_all_fixture_citations_resolve(retriever, fixtures):
    """Every apparent/supporting passage must resolve and its quote must verify."""
    for f in fixtures:
        for key in ("apparent_passages", "supporting_passages"):
            for p in f.get(key, []):
                chunk = retriever.get_chunk(p["chunk_id"], quote_span=p["quote"])
                assert chunk is not None, f"{f['id']}: {p['chunk_id']} did not resolve"
                assert chunk.quote_span_found is True, f"{f['id']}: quote not in chunk"
                assert chunk.doc_id == p["doc_id"]


def test_unknown_chunk_returns_none(retriever):
    assert retriever.get_chunk("deadbeef" * 8) is None

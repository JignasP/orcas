"""entity_type/product_type post-filters + hybrid mode against the live index."""
import pytest

from services.corpus_common import store
from services.retrieval.models import SearchFilters, SearchMode, SearchRequest
from services.retrieval.service import Retriever


@pytest.fixture(scope="module")
def retriever():
    col = store.get_collection()
    if col.count() == 0:
        pytest.skip("index not built — run `python -m services.ingest`")
    return Retriever(collection=col)


def test_entity_filter_only_returns_matching(retriever):
    resp = retriever.search(SearchRequest(
        query="grievance redressal complaint", k=8,
        filters=SearchFilters(entity_type="bank")))
    assert resp.results, "expected at least one bank-tagged chunk"
    assert all("bank" in p.entity_types for p in resp.results)


def test_scope_card_filterable_and_links_source(retriever):
    resp = retriever.search(SearchRequest(
        query="what does the scheme cover", k=20,
        filters=SearchFilters(chunk_type="scope_card")))
    assert resp.results
    assert all(p.chunk_type == "scope_card" for p in resp.results)
    assert all(p.source_clause_chunk_id for p in resp.results)


def test_hybrid_returns_results(retriever):
    resp = retriever.search(SearchRequest(
        query="demat account frozen depository participant", k=5, mode=SearchMode.hybrid))
    assert resp.mode == SearchMode.hybrid
    assert resp.count >= 1


def test_product_filter(retriever):
    resp = retriever.search(SearchRequest(
        query="deposit interest", k=8, filters=SearchFilters(product_type="fixed_deposit")))
    assert all("fixed_deposit" in p.product_types for p in resp.results)

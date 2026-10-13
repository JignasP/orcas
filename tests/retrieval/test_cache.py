"""Retrieval cache (D7): key sensitivity, TTL store, and the Retriever hit path."""
import pytest

from services.corpus_common import store
from services.retrieval.cache import InMemoryTTLCache, make_key
from services.retrieval.models import SearchRequest
from services.retrieval.service import Retriever


def test_make_key_sensitivity():
    base = make_key("Bank  FD interest", {"framework": "RBI"}, "dense", 5, "iv1")
    assert base == make_key("bank fd interest", {"framework": "RBI"}, "dense", 5, "iv1")  # normalised
    assert base != make_key("bank fd interest", {"framework": "SEBI"}, "dense", 5, "iv1")  # filters
    assert base != make_key("bank fd interest", {"framework": "RBI"}, "hybrid", 5, "iv1")  # mode
    assert base != make_key("bank fd interest", {"framework": "RBI"}, "dense", 8, "iv1")  # k
    assert base != make_key("bank fd interest", {"framework": "RBI"}, "dense", 5, "iv2")  # index_version


def test_inmemory_cache_get_set_clear():
    c = InMemoryTTLCache(ttl_s=0)
    assert c.get("k") is None
    c.set("k", {"v": 1})
    assert c.get("k") == {"v": 1}
    c.clear()
    assert c.get("k") is None


def test_retriever_cache_hit():
    if store.get_collection().count() == 0:
        pytest.skip("index not built")
    r = Retriever(cache=InMemoryTTLCache())
    req = SearchRequest(query="grounds of complaint deficiency in service", k=3)
    first = r.search(req)
    second = r.search(req)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert [p.chunk_id for p in first.results] == [p.chunk_id for p in second.results]

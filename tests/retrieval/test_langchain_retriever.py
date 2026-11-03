"""L1: the dense search runs through a LangChain retriever (no model needed for these tests)."""
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever

from services.retrieval import langchain_retriever
from services.retrieval.langchain_retriever import MiniLMEmbeddings, OrcasDenseRetriever
from services.retrieval.models import SearchFilters, SearchRequest
from services.retrieval.service import Retriever


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[0.0, 1.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


class FakeCollection:
    def __init__(self):
        self.calls = []

    def query(self, query_embeddings, n_results, where, include):
        self.calls.append({"n_results": n_results, "where": where})
        return {"ids": [["c9", "c10"]],
                "documents": [["9. Grounds of Complaint", "10. Grounds for non-maintainability"]],
                "metadatas": [[{"doc_id": "rbi", "clause_id": "9", "framework": "RBI"},
                               {"doc_id": "rbi", "clause_id": "10", "framework": "RBI"}]],
                "distances": [[0.2, 0.3]]}


class Recorder(BaseCallbackHandler):
    def __init__(self):
        self.events = []

    def on_retriever_start(self, serialized, query, **kwargs):
        self.events.append(("start", query))

    def on_retriever_end(self, documents, **kwargs):
        self.events.append(("end", len(documents)))


def test_retriever_is_a_langchain_retriever_with_langchain_embeddings():
    assert issubclass(OrcasDenseRetriever, BaseRetriever)
    assert isinstance(MiniLMEmbeddings(), Embeddings)


def test_invoke_returns_documents_with_ids_scores_and_pushes_filters_down():
    col, recorder = FakeCollection(), Recorder()
    retriever = OrcasDenseRetriever(collection=col, embeddings=FakeEmbeddings(), k=7,
                                    where={"framework": "RBI"})
    docs = retriever.invoke("deficiency in service", config={"callbacks": [recorder]})
    assert [d.id for d in docs] == ["c9", "c10"]
    assert docs[0].metadata[langchain_retriever.SCORE_KEY] == 0.8
    assert docs[0].metadata["clause_id"] == "9"
    assert col.calls == [{"n_results": 7, "where": {"framework": "RBI"}}]
    assert recorder.events == [("start", "deficiency in service"), ("end", 2)]


def test_service_dense_search_goes_through_the_langchain_retriever(monkeypatch):
    monkeypatch.setattr(langchain_retriever, "embed_query", lambda text: [1.0, 0.0])
    col = FakeCollection()
    resp = Retriever(collection=col, use_cache=False).search(
        SearchRequest(query="deficiency in service", k=2, filters=SearchFilters(framework="RBI")))
    assert [p.chunk_id for p in resp.results] == ["c9", "c10"]
    assert [p.score for p in resp.results] == [0.8, 0.7]
    assert col.calls[0]["where"] == {"framework": "RBI"}

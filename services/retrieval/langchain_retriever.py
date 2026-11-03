"""LangChain orchestration of dense retrieval (L1).

`MiniLMEmbeddings` exposes the local embedding model through LangChain's `Embeddings` interface, and
`OrcasDenseRetriever` is a LangChain `BaseRetriever` over the Chroma collection. The service's dense
search runs through `retriever.invoke(query)`, so LangChain callbacks and tracing apply to it; hybrid
mode fuses these dense results with BM25 (hybrid.py). Scalar filters are pushed down to Chroma as a
`where` clause; list-valued filters are applied by the service afterwards.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from services.corpus_common.embedding import embed_query, embed_texts

SCORE_KEY = "_score"  # cosine similarity, carried in Document.metadata


class MiniLMEmbeddings(Embeddings):
    """The local, L2-normalised sentence-transformers model shared with ingest (no API cost)."""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return embed_texts(texts)

    def embed_query(self, text: str) -> List[float]:
        return embed_query(text)


class OrcasDenseRetriever(BaseRetriever):
    """Dense search over the ORCAS Chroma collection, as a LangChain retriever."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    collection: Any
    embeddings: Embeddings = Field(default_factory=MiniLMEmbeddings)
    k: int = 20
    where: Optional[Dict[str, Any]] = None

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:
        res = self.collection.query(
            query_embeddings=[self.embeddings.embed_query(query)],
            n_results=self.k,
            where=self.where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        return [
            Document(id=cid, page_content=docs[i],
                     metadata={**(metas[i] or {}), SCORE_KEY: 1.0 - float(dists[i])})
            for i, cid in enumerate(ids)
        ]

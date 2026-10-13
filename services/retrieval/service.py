"""Retrieval logic over Chroma. Pure functions the FastAPI app wraps.

v0 scope: dense search with framework/doc_id/chunk_type filters, chunk resolution
(with quote-span verification), clause lookup and index info. Hybrid (dense+BM25)
and entity_type/product_type filtering arrive with Slice-4 metadata.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from services.corpus_common import store
from services.corpus_common.embedding import embed_query

from .models import (
    Chunk,
    Clause,
    IndexDoc,
    IndexInfo,
    Passage,
    SearchRequest,
    SearchResponse,
)

# Filters we can push down to Chroma as scalar metadata equality in v0.
_SCALAR_FILTERS = ("framework", "doc_id", "chunk_type")


def _build_where(filters) -> Optional[Dict[str, Any]]:
    if not filters:
        return None
    clauses: List[Dict[str, Any]] = []
    data = filters.model_dump(exclude_none=True)
    for key in _SCALAR_FILTERS:
        if key in data:
            val = data[key]
            clauses.append({key: getattr(val, "value", val)})
    # entity_type / product_type are list-valued metadata (JSON-encoded) in v0 and
    # cannot be filtered by Chroma equality yet; they are intentionally ignored here.
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _passage_from(cid: str, text: str, meta: Dict[str, Any], distance: float) -> Passage:
    meta = store.decode_metadata(meta)
    return Passage(
        chunk_id=cid,
        doc_id=meta.get("doc_id", ""),
        doc_title=meta.get("doc_title", ""),
        circular_ref=meta.get("circular_ref", ""),
        framework=meta.get("framework") or None,
        clause_id=meta.get("clause_id", ""),
        heading_path=meta.get("heading_path", []),
        chunk_type=meta.get("chunk_type", "clause"),
        entity_types=meta.get("entity_types", []),
        product_types=meta.get("product_types", []),
        version=meta.get("version", ""),
        text=text,
        score=round(1.0 - float(distance), 6),  # cosine distance -> similarity
        source_clause_chunk_id=meta.get("source_clause_chunk_id"),
    )


class Retriever:
    def __init__(self, collection=None):
        self._col = collection

    @property
    def col(self):
        if self._col is None:
            self._col = store.get_collection()
        return self._col

    def index_version(self) -> str:
        info = store.read_index_info() or {}
        return info.get("index_version", "")

    def search(self, req: SearchRequest) -> SearchResponse:
        t0 = time.time()
        where = _build_where(req.filters)
        res = self.col.query(
            query_embeddings=[embed_query(req.query)],
            n_results=req.k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        passages = [
            _passage_from(cid, docs[i], metas[i], dists[i]) for i, cid in enumerate(ids)
        ]
        return SearchResponse(
            query_normalized=" ".join(req.query.lower().split()),
            mode=req.mode,
            index_version=self.index_version(),
            count=len(passages),
            cache_hit=False,
            latency_ms=round((time.time() - t0) * 1000, 2),
            results=passages,
        )

    def get_chunk(self, chunk_id: str, quote_span: Optional[str] = None) -> Optional[Chunk]:
        res = self.col.get(ids=[chunk_id], include=["documents", "metadatas"])
        if not res.get("ids"):
            return None
        text = res["documents"][0]
        meta = store.decode_metadata(res["metadatas"][0])
        chunk = Chunk(
            chunk_id=chunk_id,
            doc_id=meta.get("doc_id", ""),
            doc_title=meta.get("doc_title", ""),
            circular_ref=meta.get("circular_ref", ""),
            framework=meta.get("framework") or None,
            clause_id=meta.get("clause_id", ""),
            heading_path=meta.get("heading_path", []),
            chunk_type=meta.get("chunk_type", "clause"),
            entity_types=meta.get("entity_types", []),
            product_types=meta.get("product_types", []),
            version=meta.get("version", ""),
            model_tag=meta.get("model_tag", ""),
            text=text,
        )
        if quote_span is not None:
            chunk.quote_span_found = quote_span in text
        return chunk

    def get_clause(self, doc_id: str, clause_id: str) -> Optional[Clause]:
        res = self.col.get(
            where={"$and": [{"doc_id": doc_id}, {"clause_id": clause_id}]},
            include=["documents", "metadatas"],
        )
        if not res.get("ids"):
            return None
        meta = store.decode_metadata(res["metadatas"][0])
        text = "\n".join(res["documents"])
        return Clause(
            doc_id=doc_id,
            clause_id=clause_id,
            doc_title=meta.get("doc_title", ""),
            circular_ref=meta.get("circular_ref", ""),
            framework=meta.get("framework") or None,
            heading_path=meta.get("heading_path", []),
            version=meta.get("version", ""),
            text=text,
            chunk_ids=list(res["ids"]),
        )

    def info(self) -> Optional[IndexInfo]:
        raw = store.read_index_info()
        if not raw:
            return None
        docs = [
            IndexDoc(
                doc_id=d.get("doc_id", ""),
                title=d.get("title", ""),
                framework=d.get("framework") or None,
                version=d.get("version", ""),
                chunk_count=d.get("chunk_count", 0),
                has_text_layer=d.get("has_text_layer"),
                source_sha256=d.get("source_sha256", ""),
            )
            for d in raw.get("documents", [])
        ]
        return IndexInfo(
            index_version=raw.get("index_version", ""),
            built_at=raw.get("built_at", ""),
            model_tag=raw.get("model_tag", ""),
            embedding_model=raw.get("embedding_model", ""),
            distance_metric=raw.get("distance_metric", ""),
            hybrid_enabled=raw.get("hybrid_enabled", False),
            chunk_count=raw.get("chunk_count", 0),
            documents=docs,
        )

"""FastAPI app exposing the retrieval contract.

Run (from repo root, venv active):
    uvicorn services.retrieval.app:app --port 8001
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .models import Chunk, Clause, Error, Health, IndexInfo, SearchRequest, SearchResponse
from .service import Retriever

app = FastAPI(title="ORCAS Retrieval Service", version="1.0.0")
_retriever = Retriever()


@app.post("/v1/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    return _retriever.search(req)


@app.get("/v1/clauses/{doc_id}/{clause_id}", response_model=Clause)
def get_clause(doc_id: str, clause_id: str) -> Clause:
    clause = _retriever.get_clause(doc_id, clause_id)
    if clause is None:
        raise HTTPException(status_code=404, detail="no such clause in this document")
    return clause


@app.get("/v1/chunks/{chunk_id}", response_model=Chunk)
def get_chunk(chunk_id: str, quote_span: str | None = Query(default=None)) -> Chunk:
    chunk = _retriever.get_chunk(chunk_id, quote_span=quote_span)
    if chunk is None:
        raise HTTPException(status_code=404, detail="chunk does not resolve")
    return chunk


@app.get("/v1/index/info", response_model=IndexInfo)
def index_info() -> IndexInfo:
    info = _retriever.info()
    if info is None:
        raise HTTPException(status_code=503, detail="index not built yet")
    return info


@app.get("/health", response_model=Health)
def health() -> JSONResponse:
    try:
        count = _retriever.col.count()
        index_openable = True
    except Exception:
        count = 0
        index_openable = False
    version = _retriever.index_version()
    ok = index_openable and count > 0
    h = Health(
        status="ok" if ok else "not_ready",
        model_loaded=True,  # model loads lazily on first query; container bakes it in
        index_openable=index_openable,
        index_version=version,
    )
    return JSONResponse(status_code=200 if ok else 503, content=h.model_dump())

"""Pydantic models mirroring contracts/retrieval.openapi.yaml.

Kept deliberately close to the OpenAPI schema; a contract-conformance test (Slice 4 /
Jignas) can later assert these stay in sync.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Framework(str, Enum):
    SEBI = "SEBI"
    RBI = "RBI"


class EntityType(str, Enum):
    broker = "broker"
    mutual_fund = "mutual_fund"
    registrar = "registrar"
    listed_company = "listed_company"
    depository = "depository"
    bank = "bank"
    other = "other"
    unknown = "unknown"


class ChunkType(str, Enum):
    clause = "clause"
    scope_card = "scope_card"


class SearchMode(str, Enum):
    dense = "dense"
    hybrid = "hybrid"


class SearchFilters(BaseModel):
    framework: Optional[Framework] = None
    doc_id: Optional[str] = None
    entity_type: Optional[EntityType] = None
    product_type: Optional[str] = None
    chunk_type: Optional[ChunkType] = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    k: int = Field(default=8, ge=1, le=50)
    mode: SearchMode = SearchMode.dense
    filters: Optional[SearchFilters] = None


class Passage(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str = ""
    circular_ref: str = ""
    framework: Optional[str] = None
    clause_id: str = ""
    heading_path: List[str] = []
    chunk_type: str = "clause"
    entity_types: List[str] = []
    product_types: List[str] = []
    version: str = ""
    text: str
    score: float
    source_clause_chunk_id: Optional[str] = None


class SearchResponse(BaseModel):
    query_normalized: str
    mode: SearchMode
    index_version: str = ""
    count: int
    cache_hit: bool = False
    latency_ms: float = 0.0
    results: List[Passage]


class Clause(BaseModel):
    doc_id: str
    clause_id: str
    doc_title: str = ""
    circular_ref: str = ""
    framework: Optional[str] = None
    heading_path: List[str] = []
    version: str = ""
    text: str
    chunk_ids: List[str] = []


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str = ""
    circular_ref: str = ""
    framework: Optional[str] = None
    clause_id: str = ""
    heading_path: List[str] = []
    chunk_type: str = "clause"
    entity_types: List[str] = []
    product_types: List[str] = []
    version: str = ""
    model_tag: str = ""
    text: str
    quote_span_found: Optional[bool] = None


class IndexDoc(BaseModel):
    doc_id: str
    title: str = ""
    framework: Optional[str] = None
    version: str = ""
    chunk_count: int = 0
    has_text_layer: Optional[bool] = None
    ocr_applied: Optional[bool] = None
    source_sha256: str = ""


class IndexInfo(BaseModel):
    index_version: str
    built_at: str
    model_tag: str
    embedding_model: str = ""
    distance_metric: str = ""
    hybrid_enabled: bool = False
    chunk_count: int = 0
    documents: List[IndexDoc] = []


class Health(BaseModel):
    status: str
    model_loaded: bool = False
    index_openable: bool = False
    index_version: str = ""


class Error(BaseModel):
    error: str
    detail: Optional[str] = None
    code: Optional[int] = None

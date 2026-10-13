"""Shared corpus primitives for ingest + retrieval.

Single source of truth for the embedding model, the chunk-id rule, the Chroma
collection layout and the chunk-metadata schema, so the two services cannot drift.
"""
from .constants import MODEL_NAME, MODEL_TAG, DEFAULT_COLLECTION
from .ids import chunk_id
from .embedding import embed_texts, embed_query
from . import store

__all__ = [
    "MODEL_NAME",
    "MODEL_TAG",
    "DEFAULT_COLLECTION",
    "chunk_id",
    "embed_texts",
    "embed_query",
    "store",
]

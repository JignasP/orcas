"""Shared corpus primitives for ingest + retrieval.

Single source of truth for the embedding model, the chunk-id rule, the Chroma
collection layout and the chunk-metadata schema, so the two services cannot drift.
"""
from . import store
from .constants import DEFAULT_COLLECTION, MODEL_NAME, MODEL_TAG
from .embedding import embed_query, embed_texts
from .ids import chunk_id

__all__ = [
    "MODEL_NAME",
    "MODEL_TAG",
    "DEFAULT_COLLECTION",
    "chunk_id",
    "embed_texts",
    "embed_query",
    "store",
]

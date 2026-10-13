"""Local MiniLM embeddings (no API cost). Model loaded lazily and cached.

Embeddings are L2-normalised so Chroma's cosine space behaves as a dot product.
The same function embeds corpus chunks (ingest) and queries (retrieval), which is
why this lives in corpus_common rather than in either service.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from .constants import MODEL_NAME


@lru_cache(maxsize=1)
def _model():
    # Imported lazily so that importing this module (e.g. in a unit test that
    # monkeypatches embeddings) does not pull in torch.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    vecs = _model().encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return vecs.tolist()


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]

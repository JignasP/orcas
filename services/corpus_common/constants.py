"""Constants shared by ingest and retrieval.

Everything environment-specific is read from env with a sensible local default,
so nothing (paths, model ids) is hard-coded into business logic (D4).
"""
from __future__ import annotations

import os
from pathlib import Path

# Embedding model. MODEL_TAG is the short tag that participates in chunk ids and
# in the re-embedding flow (--re-embed --model-tag X), so it is kept separate from
# the heavier model path.
MODEL_NAME = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_TAG = os.getenv("EMBED_MODEL_TAG", "minilm-l6-v2")

# Chroma cosine space (we normalise embeddings, so cosine distance is meaningful).
DISTANCE_METRIC = "cosine"

DEFAULT_COLLECTION = os.getenv("ORCAS_COLLECTION", "orcas_corpus")


def repo_root() -> Path:
    # services/corpus_common/constants.py -> repo root is two parents up.
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    d = os.getenv("ORCAS_DATA_DIR")
    return Path(d) if d else repo_root() / "data"


def chroma_dir() -> Path:
    d = os.getenv("ORCAS_CHROMA_DIR")
    return Path(d) if d else data_dir() / "chroma"


def index_info_path() -> Path:
    p = os.getenv("ORCAS_INDEX_INFO")
    return Path(p) if p else data_dir() / "index_info.json"

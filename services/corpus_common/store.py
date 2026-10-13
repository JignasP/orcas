"""Chroma access + the chunk-metadata schema shared by ingest and retrieval.

Chroma metadata values must be scalars (str/int/float/bool), so list-valued fields
(heading_path, entity_types, product_types) are JSON-encoded on write and decoded
on read. All of that round-tripping lives here so both services agree.
"""
from __future__ import annotations

import logging
import os

# Disable Chroma's anonymized telemetry BEFORE chromadb is imported anywhere.
# chromadb 0.5.x ships a posthog incompatibility that logs noisy
# "capture() takes 1 positional argument but 3 were given" ERROR lines. The env
# var/Settings flag does not stop the logging, so we also mute the logger.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import DEFAULT_COLLECTION, DISTANCE_METRIC, chroma_dir, index_info_path

# Metadata keys that hold lists and are therefore JSON-encoded in Chroma.
_LIST_KEYS = ("heading_path", "entity_types", "product_types")


@dataclass
class ChunkRecord:
    """One corpus chunk, in the shape both services use."""

    chunk_id: str
    text: str
    doc_id: str
    doc_title: str = ""
    framework: str = ""          # SEBI | RBI
    clause_id: str = ""
    heading_path: List[str] = field(default_factory=list)
    chunk_type: str = "clause"   # clause | scope_card
    entity_types: List[str] = field(default_factory=list)
    product_types: List[str] = field(default_factory=list)
    version: str = ""
    circular_ref: str = ""
    page: int = 0
    model_tag: str = ""
    source_clause_chunk_id: Optional[str] = None

    def to_metadata(self) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "framework": self.framework,
            "clause_id": self.clause_id,
            "chunk_type": self.chunk_type,
            "version": self.version,
            "circular_ref": self.circular_ref,
            "page": int(self.page),
            "model_tag": self.model_tag,
            "heading_path": json.dumps(self.heading_path),
            "entity_types": json.dumps(self.entity_types),
            "product_types": json.dumps(self.product_types),
        }
        if self.source_clause_chunk_id:
            meta["source_clause_chunk_id"] = self.source_clause_chunk_id
        return meta


def decode_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Inverse of ChunkRecord.to_metadata for the JSON-encoded list fields."""
    out = dict(meta or {})
    for k in _LIST_KEYS:
        if isinstance(out.get(k), str):
            try:
                out[k] = json.loads(out[k])
            except (ValueError, TypeError):
                out[k] = []
        elif out.get(k) is None:
            out[k] = []
    return out


def get_client(path: Optional[Path] = None):
    import chromadb
    from chromadb.config import Settings

    d = Path(path) if path else chroma_dir()
    d.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(d), settings=Settings(anonymized_telemetry=False)
    )


def get_collection(client=None, name: str = DEFAULT_COLLECTION):
    client = client or get_client()
    return client.get_or_create_collection(
        name=name, metadata={"hnsw:space": DISTANCE_METRIC}
    )


# --- index_info.json: written by ingest, read by retrieval -------------------

def write_index_info(info: Dict[str, Any], path: Optional[Path] = None) -> None:
    p = Path(path) if path else index_info_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(info, indent=2, sort_keys=True))


def read_index_info(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    p = Path(path) if path else index_info_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None

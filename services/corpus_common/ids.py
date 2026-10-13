"""Content-hash chunk ids — the basis of idempotent ingest (D2).

id = sha256(doc_id | clause_id | text | model_tag)

Because the id is a pure function of content + model tag, re-running ingest on an
unchanged corpus produces identical ids and the upsert is a no-op; re-embedding
under a new model_tag produces a disjoint id set for that tag.
"""
from __future__ import annotations

import hashlib


def chunk_id(doc_id: str, clause_id: str, text: str, model_tag: str) -> str:
    h = hashlib.sha256()
    h.update("|".join([doc_id, clause_id, text, model_tag]).encode("utf-8"))
    return h.hexdigest()

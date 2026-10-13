"""Naive chunking (v0).

Fixed-size word windows per page with overlap. clause_id is a positional id
(p{page}w{window}) — structure-aware, clause-aligned segmentation with real
heading paths and entity/product metadata is Slice 4. Keeping it naive here lets
us stand up end-to-end retrieval and locate the §4.1 passages first.
"""
from __future__ import annotations

import re
from typing import List

from services.corpus_common.ids import chunk_id
from services.corpus_common.store import ChunkRecord
from .parse import Page

_WS = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WS.sub(" ", text).strip()


def chunk_pages(
    pages: List[Page],
    *,
    doc_id: str,
    doc_title: str,
    framework: str,
    version: str,
    circular_ref: str,
    model_tag: str,
    chunk_words: int = 180,
    overlap: int = 40,
) -> List[ChunkRecord]:
    if overlap >= chunk_words:
        raise ValueError("overlap must be smaller than chunk_words")

    records: List[ChunkRecord] = []
    step = chunk_words - overlap
    for page in pages:
        words = _normalise(page.text).split(" ")
        words = [w for w in words if w]
        if not words:
            continue
        window = 0
        for start in range(0, len(words), step):
            piece = words[start : start + chunk_words]
            if not piece:
                continue
            text = " ".join(piece)
            clause_id = f"p{page.number}w{window}"
            cid = chunk_id(doc_id, clause_id, text, model_tag)
            records.append(
                ChunkRecord(
                    chunk_id=cid,
                    text=text,
                    doc_id=doc_id,
                    doc_title=doc_title,
                    framework=framework,
                    clause_id=clause_id,
                    heading_path=[],
                    chunk_type="clause",
                    entity_types=[],
                    product_types=[],
                    version=version,
                    circular_ref=circular_ref,
                    page=page.number,
                    model_tag=model_tag,
                )
            )
            window += 1
            if start + chunk_words >= len(words):
                break
    return records

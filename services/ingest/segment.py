"""Structure-aware (clause-aligned) segmentation (L1, Slice 4).

Heuristic: detect top-level clause anchors (``9. Grounds of Complaint``) and CHAPTER
headings in the flowing extracted text, and cut the document into clause-aligned chunks
that carry a real ``clause_id`` and a ``heading_path`` ([chapter, clause-title]). Text
before the first clause (titles, the scheme's scope sentence) is captured as a
``preamble`` clause — important, because the RBI scope ("entities regulated by Reserve
Bank") lives there. Long clauses are split into sub-chunks (``<id>#k``) with overlap so
embeddings stay focused while keeping neighbour context.

This is a heuristic, not a legal parser; it is benchmarked against fixed-window chunking
in eval/benchmark_chunking.py and the limitations are documented in the report notes.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from services.corpus_common.ids import chunk_id
from services.corpus_common.store import ChunkRecord
from .metadata import infer_entity_product
from .parse import Page

_WS = re.compile(r"\s+")
# A clause anchor: a 1-3 digit number (optionally with a trailing capital, e.g. 7A/7B),
# a dot, whitespace, then a capitalised word that starts the clause title.
_ANCHOR = re.compile(r"(?:^|\s)(\d{1,3}[A-Z]?)\.\s+(?=[A-Z])")
_CHAPTER = re.compile(r"CHAPTER\s+([IVXLC]+)\b[ .:\-]*([A-Z][A-Za-z ,&/]{0,50})?")


def _normalise(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _build_text(pages: List[Page]) -> Tuple[str, List[Tuple[int, int]]]:
    """Return concatenated normalised text and a list of (char_offset, page_number)."""
    parts: List[str] = []
    offsets: List[Tuple[int, int]] = []
    pos = 0
    for p in pages:
        t = _normalise(p.text)
        if not t:
            continue
        offsets.append((pos, p.number))
        parts.append(t)
        pos += len(t) + 1  # +1 for the joining space
    return " ".join(parts), offsets


def _page_at(offset: int, offsets: List[Tuple[int, int]]) -> int:
    page = offsets[0][1] if offsets else 1
    for off, pg in offsets:
        if off <= offset:
            page = pg
        else:
            break
    return page


def _chapter_at(offset: int, chapters: List[Tuple[int, str]]) -> Optional[str]:
    label = None
    for off, lab in chapters:
        if off <= offset:
            label = lab
        else:
            break
    return label


def _clause_title(body: str) -> str:
    # title = words up to the first "(1)" / digit-paren / ~8 words
    head = re.split(r"\(\d|\(\w\)|\d\.", body, maxsplit=1)[0]
    words = head.split()
    return " ".join(words[:8]).strip(" .,:;")


def _split_long(words: List[str], target: int, overlap: int) -> List[List[str]]:
    if len(words) <= target:
        return [words]
    step = target - overlap
    out = []
    for start in range(0, len(words), step):
        piece = words[start : start + target]
        if piece:
            out.append(piece)
        if start + target >= len(words):
            break
    return out


def segment_pages(
    pages: List[Page],
    *,
    doc_id: str,
    doc_title: str,
    framework: str,
    version: str,
    circular_ref: str,
    model_tag: str,
    target_words: int = 320,
    overlap: int = 40,
) -> List[ChunkRecord]:
    text, offsets = _build_text(pages)
    chapters = [
        (m.start(), f"CHAPTER {m.group(1)}" + (f" {m.group(2).strip()}" if m.group(2) else ""))
        for m in _CHAPTER.finditer(text)
    ]

    anchors = list(_ANCHOR.finditer(text))
    # Segment boundaries: preamble (0 -> first anchor), then each anchor -> next.
    spans: List[Tuple[str, int, int]] = []
    if not anchors:
        spans.append(("preamble", 0, len(text)))
    else:
        if anchors[0].start() > 40:
            spans.append(("preamble", 0, anchors[0].start()))
        for i, m in enumerate(anchors):
            start = m.start(1)
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
            spans.append((m.group(1), start, end))

    records: List[ChunkRecord] = []
    seen: dict[str, int] = {}
    doc_short = doc_title[:40]
    for num, start, end in spans:
        body = text[start:end].strip()
        if len(body) < 15:
            continue
        # unique clause id within the doc
        base_id = num
        seen[num] = seen.get(num, 0) + 1
        if seen[num] > 1:
            base_id = f"{num}-{seen[num]}"

        chapter = _chapter_at(start, chapters)
        title = "Preamble" if num == "preamble" else _clause_title(
            body[len(num) + 1 :] if body[: len(num)] == num else body
        )
        heading_path = [h for h in (chapter or doc_short, title) if h]
        page = _page_at(start, offsets)
        ent, prod = infer_entity_product(body)

        for k, piece in enumerate(_split_long(body.split(), target_words, overlap)):
            ptext = " ".join(piece)
            clause_id = base_id if k == 0 else f"{base_id}#{k}"
            records.append(
                ChunkRecord(
                    chunk_id=chunk_id(doc_id, clause_id, ptext, model_tag),
                    text=ptext,
                    doc_id=doc_id,
                    doc_title=doc_title,
                    framework=framework,
                    clause_id=clause_id,
                    heading_path=heading_path,
                    chunk_type="clause",
                    entity_types=ent,
                    product_types=prod,
                    version=version,
                    circular_ref=circular_ref,
                    page=page,
                    model_tag=model_tag,
                )
            )
    return records

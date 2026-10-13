"""PDF parsing with page tracking (v0).

Extracts the text layer per page via pypdf. Scanned documents (no text layer)
would need OCR before indexing; the manifest records has_text_layer, and all three
baseline documents have a text layer, so OCR is not wired in v0.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class Page:
    number: int   # 1-based
    text: str


def parse_pdf(path: str | Path) -> List[Page]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: List[Page] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(Page(number=i, text=text))
    return pages


def extracted_char_count(pages: List[Page]) -> int:
    return sum(len(p.text) for p in pages)

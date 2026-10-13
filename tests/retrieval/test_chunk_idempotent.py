"""Chunking / chunk-id idempotency (D2) — fast, no embeddings.

Full-pipeline idempotency (re-run changes nothing) is exercised by the ingest CLI's
own +0-new report; here we lock down the deterministic foundation it rests on.
"""
import pytest

from services.corpus_common.constants import repo_root
from services.corpus_common.ids import chunk_id
from services.ingest.chunk import chunk_pages
from services.ingest.parse import parse_pdf

RBI = repo_root() / "corpus" / "raw" / "rbi_integrated_ombudsman_scheme_2021.pdf"


def _chunk(model_tag="minilm-l6-v2"):
    pages = parse_pdf(RBI)
    return chunk_pages(
        pages,
        doc_id="rbi_integrated_ombudsman_scheme_2021",
        doc_title="RBI IOS 2021",
        framework="RBI",
        version="2021",
        circular_ref="RBI IOS 2021",
        model_tag=model_tag,
    )


def test_chunk_id_is_deterministic():
    assert chunk_id("d", "c", "text", "tag") == chunk_id("d", "c", "text", "tag")


def test_chunk_id_changes_with_model_tag():
    assert chunk_id("d", "c", "text", "tagA") != chunk_id("d", "c", "text", "tagB")


def test_rechunking_same_pdf_yields_same_ids():
    if not RBI.exists():
        pytest.skip("RBI corpus doc not present")
    a = [r.chunk_id for r in _chunk()]
    b = [r.chunk_id for r in _chunk()]
    assert a == b
    assert len(a) == len(set(a)), "chunk ids must be unique within a document"


def test_reembed_tag_produces_disjoint_ids():
    if not RBI.exists():
        pytest.skip("RBI corpus doc not present")
    base = {r.chunk_id for r in _chunk("minilm-l6-v2")}
    other = {r.chunk_id for r in _chunk("other-tag")}
    assert base.isdisjoint(other)

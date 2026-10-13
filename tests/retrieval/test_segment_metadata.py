"""Clause-aligned segmentation, metadata inference, and scope cards (Slice 4). Fast (no embeddings)."""
import pytest

from services.corpus_common.constants import repo_root
from services.ingest.metadata import build_scope_cards, infer_entity_product
from services.ingest.parse import parse_pdf
from services.ingest.segment import segment_pages

RAW = repo_root() / "corpus" / "raw"
RBI = RAW / "rbi_integrated_ombudsman_scheme_2021.pdf"
SEBI = RAW / "sebi_scores_master_circular.pdf"


def _segment(path, doc_id, fw):
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    return segment_pages(parse_pdf(path), doc_id=doc_id, doc_title=doc_id, framework=fw,
                         version="v", circular_ref="ref", model_tag="minilm-l6-v2")


def test_rbi_clause_9_grounds_and_preamble():
    recs = _segment(RBI, "rbi_integrated_ombudsman_scheme_2021", "RBI")
    by_clause = {r.clause_id: r for r in recs}
    assert "9" in by_clause
    assert "deficiency in service" in by_clause["9"].text.lower()
    assert by_clause["9"].heading_path  # chapter + title
    assert "preamble" in by_clause
    assert "regulated by reserve bank" in by_clause["preamble"].text.lower()


def test_clause_ids_unique():
    recs = _segment(RBI, "rbi_integrated_ombudsman_scheme_2021", "RBI")
    ids = [r.clause_id for r in recs]
    assert len(ids) == len(set(ids))


def test_entity_product_inference():
    ents, prods = infer_entity_product("I opened a fixed deposit at the bank; interest credited is wrong.")
    assert "bank" in ents and "fixed_deposit" in prods
    ents2, prods2 = infer_entity_product("Mutual fund redemption delayed and NAV statement wrong.")
    assert "mutual_fund" in ents2 and "redemption" in prods2


def test_scope_cards_point_to_source_clause():
    recs = _segment(RBI, "rbi_integrated_ombudsman_scheme_2021", "RBI") + \
           _segment(SEBI, "sebi_scores_master_circular", "SEBI")
    cards = build_scope_cards(recs, "minilm-l6-v2")
    assert {c.framework for c in cards} == {"RBI", "SEBI"}
    ids = {r.chunk_id for r in recs}
    for c in cards:
        assert c.chunk_type == "scope_card"
        assert c.entity_types
        assert c.source_clause_chunk_id in ids  # finding aid -> real source clause

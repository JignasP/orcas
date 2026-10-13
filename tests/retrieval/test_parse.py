"""One parse regression check per corpus document (TAHIR.md Slice 1).

Guards against a pypdf upgrade or a swapped file silently mangling a document:
asserts the page count and a known text marker survive extraction.
"""
import pytest

from services.corpus_common.constants import repo_root
from services.ingest.parse import extracted_char_count, parse_pdf

CORPUS = repo_root() / "corpus" / "raw"

CASES = [
    ("sebi_mutual_funds_regulations_1996.pdf", 162, "MUTUAL FUNDS"),
    ("rbi_integrated_ombudsman_scheme_2021.pdf", 18, "INTEGRATED OMBUDSMAN"),
    ("sebi_scores_master_circular.pdf", 11, "SCORES"),
]


@pytest.mark.parametrize("filename,expected_pages,marker", CASES)
def test_parse_regression(filename, expected_pages, marker):
    path = CORPUS / filename
    if not path.exists():
        pytest.skip(f"{filename} not present")
    pages = parse_pdf(path)
    assert len(pages) == expected_pages
    # text layer present and the known marker survives extraction
    assert extracted_char_count(pages) > 2000
    all_text = " ".join(p.text for p in pages)
    assert marker.lower() in all_text.lower()

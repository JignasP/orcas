"""Entity/product metadata inference + scope-card generation (Slice 4).

Keyword-based inference is deliberately simple and transparent (documented in the
report). It tags each chunk with the entity types and product types it mentions, which
powers the retrieval entity_type/product_type filters and the framework scope cards.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from services.corpus_common.ids import chunk_id
from services.corpus_common.store import ChunkRecord

# entity_type -> keywords (word-boundary matched, case-insensitive)
_ENTITY_KEYWORDS = {
    "bank": [r"bank", r"fixed deposit", r"\bdeposit", r"banking", r"savings account"],
    "mutual_fund": [r"mutual fund", r"asset management company", r"\bamc\b", r"unitholder",
                    r"unit holder", r"\bnav\b", r"scheme of the mutual fund"],
    "broker": [r"stock ?broker", r"trading member", r"\bbroker"],
    "registrar": [r"registrar", r"share transfer agent", r"\brta\b", r"registrar to an issue"],
    "listed_company": [r"listed compan", r"listed entity", r"dividend", r"annual report"],
    "depository": [r"depositor", r"\bdemat\b", r"beneficial owner", r"depository participant"],
}
# product_type -> keywords
_PRODUCT_KEYWORDS = {
    "fixed_deposit": [r"fixed deposit", r"term deposit"],
    "demat_account": [r"\bdemat\b"],
    "dividend": [r"dividend"],
    "redemption": [r"redemption", r"redeem"],
    "nav": [r"\bnav\b", r"net asset value"],
    "share_transfer": [r"share transfer", r"transfer of shares"],
    "payment": [r"payment", r"digital transaction", r"upi"],
}


def _match_any(text_l: str, patterns: List[str]) -> bool:
    return any(re.search(p, text_l) for p in patterns)


def infer_entity_product(text: str) -> Tuple[List[str], List[str]]:
    tl = text.lower()
    ents = [e for e, pats in _ENTITY_KEYWORDS.items() if _match_any(tl, pats)]
    prods = [p for p, pats in _PRODUCT_KEYWORDS.items() if _match_any(tl, pats)]
    return ents, prods


# --- Scope cards -------------------------------------------------------------
# Short "what this framework covers" finding aids. Each MUST point to a real source
# clause chunk (source_clause_chunk_id); citations resolve to the clause, not the card.

_SCOPE_CARDS = {
    "SEBI": {
        "text": ("SCOPE (SEBI): SEBI's SCORES grievance mechanism covers investor complaints "
                 "against SEBI-regulated entities — listed companies, stock brokers, depository "
                 "participants, mutual funds / asset management companies, registrars and share "
                 "transfer agents (RTAs), and recognised market infrastructure institutions / "
                 "depositories. It does not cover banking products such as bank deposits."),
        "entity_types": ["broker", "mutual_fund", "registrar", "listed_company", "depository"],
        # link to the clause that enumerates these entities (names "registered intermediaries")
        "source_match": "registered intermediaries",
    },
    "RBI": {
        "text": ("SCOPE (RBI): The Reserve Bank - Integrated Ombudsman Scheme covers services "
                 "provided by entities regulated by the Reserve Bank of India — banks, NBFCs and "
                 "payment system operators — with grounds of complaint for deficiency in service."),
        "entity_types": ["bank"],
        "source_match": "regulated by Reserve Bank",
    },
}


def build_scope_cards(clauses: List[ChunkRecord], model_tag: str) -> List[ChunkRecord]:
    """One scope card per framework present, each linked to a source clause chunk."""
    cards: List[ChunkRecord] = []
    frameworks = {c.framework for c in clauses if c.framework}
    for fw in frameworks:
        spec = _SCOPE_CARDS.get(fw)
        if not spec:
            continue
        # find a source clause in this framework whose text contains the anchor phrase
        src = next(
            (c for c in clauses if c.framework == fw and spec["source_match"].lower() in c.text.lower()),
            None,
        )
        if src is None:
            continue
        clause_id = f"scope:{fw.lower()}"
        cards.append(
            ChunkRecord(
                chunk_id=chunk_id(src.doc_id, clause_id, spec["text"], model_tag),
                text=spec["text"],
                doc_id=src.doc_id,
                doc_title=src.doc_title,
                framework=fw,
                clause_id=clause_id,
                heading_path=["Scope card"],
                chunk_type="scope_card",
                entity_types=spec["entity_types"],
                product_types=[],
                version=src.version,
                circular_ref=src.circular_ref,
                page=src.page,
                model_tag=model_tag,
                source_clause_chunk_id=src.chunk_id,
            )
        )
    return cards

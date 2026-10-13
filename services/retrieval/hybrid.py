"""BM25 lexical index + reciprocal-rank fusion for hybrid retrieval (Slice 4 A/B).

Dense (MiniLM) search misses exact-term matches (clause numbers, "demat", "NAV"); BM25
catches them. We fuse the two rankings with RRF rather than tuning a score weight, which
is robust to the two scorers being on different scales. Whether hybrid actually beats
dense on this corpus is settled by eval/benchmark_chunking.py and recorded; the service
exposes it via mode=hybrid.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

_TOKEN = re.compile(r"[a-z0-9]+")


def _tok(text: str) -> List[str]:
    return _TOKEN.findall(text.lower())


class BM25Index:
    def __init__(self, ids: List[str], texts: List[str]):
        from rank_bm25 import BM25Okapi

        self.ids = ids
        self._bm25 = BM25Okapi([_tok(t) for t in texts]) if ids else None

    def query(self, text: str, n: int) -> List[Tuple[str, float]]:
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(_tok(text))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n]
        return [(self.ids[i], float(scores[i])) for i in order if scores[i] > 0]


def rrf_fuse(rankings: List[List[str]], k0: int = 60) -> Dict[str, float]:
    """Reciprocal-rank fusion: score(id) = sum 1/(k0 + rank) over each ranking."""
    fused: Dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k0 + rank)
    return fused

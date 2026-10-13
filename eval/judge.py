"""Judges for the eval metrics (Slice 5).

Default is a deterministic **embedding (NLI-substitute) judge**: it decides claim support /
passage relevance / inferability by cosine similarity of local MiniLM embeddings against a
threshold. This is reproducible (temperature-0 by construction), free, and not rate-limited,
which is exactly why it is the baseline judge; the metrics spec allows "LLM-judge (or NLI
model)". A pluggable LLM judge (same interface) can be swapped in for the L2 prompt
comparison; LLM-judge hygiene (temp 0, cached verdicts, 20% manual spot-check) is documented
in the report.

Thresholds are explicit and tunable; they are reported with the numbers so results are
interpretable.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List, Protocol

from services.corpus_common.embedding import embed_texts


@lru_cache(maxsize=4096)
def _emb(text: str):
    return tuple(embed_texts([text])[0])


def _cos(a: str, b: str) -> float:
    va, vb = _emb(a), _emb(b)
    return float(sum(x * y for x, y in zip(va, vb)))  # embeddings are L2-normalised


def _max_cos(claim: str, passages: List[str]) -> float:
    return max((_cos(claim, p) for p in passages), default=0.0)


class Judge(Protocol):
    def supports(self, claim: str, passages: List[str]) -> bool: ...
    def relevant(self, passage: str, question: str) -> bool: ...
    def inferable(self, claim: str, passages: List[str]) -> bool: ...


@dataclass
class EmbeddingJudge:
    support_threshold: float = 0.45
    relevance_threshold: float = 0.32
    infer_threshold: float = 0.40  # <= support: faithfulness is a looser bar than groundedness

    name: str = "embedding-minilm-l6-v2"

    def supports(self, claim: str, passages: List[str]) -> bool:
        return _max_cos(claim, passages) >= self.support_threshold

    def relevant(self, passage: str, question: str) -> bool:
        return _cos(passage, question) >= self.relevance_threshold

    def inferable(self, claim: str, passages: List[str]) -> bool:
        return _max_cos(claim, passages) >= self.infer_threshold

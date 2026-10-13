"""Evaluation metrics (L3). Each computation is stated explicitly for the report.

RAG metrics (computed only over scenarios whose answer makes claims — i.e. non-escalation
answers; escalations assert nothing, so groundedness/faithfulness are N/A for them):
  groundedness      = supported_claims / total_claims, claim-level (judge.supports),
                      macro-averaged over scenarios.
  context_relevance = relevant_passages / retrieved_passages (judge.relevant), macro.
  faithfulness      = inferable_claims / total_claims (judge.inferable, a looser bar than
                      support — RAGAS-style). Reported alongside groundedness; they are
                      highly correlated by construction and that is stated honestly.
  hallucination_rate= share of answered scenarios with >=1 unsupported claim.

Label metrics (computed over ALL scenarios; no judge, so more trustworthy):
  route_accuracy, regulator_accuracy, entity_accuracy = exact-match vs expected labels.
  escalation precision/recall = escalation treated as the positive class.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .judge import EmbeddingJudge, Judge


@dataclass
class EvalResult:
    scenario_id: str
    question: str
    held_out: bool = False
    # prediction
    route: str = ""
    regulator: str = ""
    entity_type: str = ""
    escalated: bool = False
    contexts: List[str] = field(default_factory=list)
    claims: List[str] = field(default_factory=list)
    # labels
    expected_route: str = ""
    expected_regulator: str = ""
    expected_entity_type: str = ""
    expected_escalation: bool = False


def split_claims(text: str) -> List[str]:
    """Decompose an answer into atomic claims (naive sentence split)."""
    parts = re.split(r"(?<=[.;])\s+", (text or "").strip())
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def _safe_div(a: float, b: float) -> Optional[float]:
    return round(a / b, 3) if b else None


def compute(results: List[EvalResult], judge: Judge = None) -> Dict:
    judge = judge or EmbeddingJudge()

    answered = [r for r in results if r.claims]  # non-escalation answers

    # --- RAG metrics (claim/passage level) ---
    g_scores, f_scores, cr_scores = [], [], []
    hallucinated = 0
    for r in answered:
        supported = sum(1 for c in r.claims if judge.supports(c, r.contexts or [""]))
        inferable = sum(1 for c in r.claims if judge.inferable(c, r.contexts or [""]))
        g_scores.append(supported / len(r.claims))
        f_scores.append(inferable / len(r.claims))
        if r.contexts:
            rel = sum(1 for p in r.contexts if judge.relevant(p, r.question))
            cr_scores.append(rel / len(r.contexts))
        if supported < len(r.claims):
            hallucinated += 1

    def mean(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    # --- label metrics (all scenarios) ---
    n = len(results)
    route_acc = _safe_div(sum(r.route == r.expected_route for r in results), n)
    reg_acc = _safe_div(sum(r.regulator == r.expected_regulator for r in results), n)
    ent_acc = _safe_div(sum(r.entity_type == r.expected_entity_type for r in results), n)

    tp = sum(1 for r in results if r.escalated and r.expected_escalation)
    fp = sum(1 for r in results if r.escalated and not r.expected_escalation)
    fn = sum(1 for r in results if not r.escalated and r.expected_escalation)

    return {
        "n_scenarios": n,
        "n_answered": len(answered),
        "groundedness": mean(g_scores),
        "context_relevance": mean(cr_scores),
        "faithfulness": mean(f_scores),
        "hallucination_rate": _safe_div(hallucinated, len(answered)),
        "route_accuracy": route_acc,
        "regulator_accuracy": reg_acc,
        "entity_accuracy": ent_acc,
        "escalation_precision": _safe_div(tp, tp + fp),
        "escalation_recall": _safe_div(tp, tp + fn),
        "judge": getattr(judge, "name", judge.__class__.__name__),
    }

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

Supporting-passage metrics (over scenarios whose label pins a supporting passage; no judge):
  supporting_passage_retrieved = share where a retrieved chunk is the pinned passage.
  supporting_passage_cited     = share where a cited chunk is the pinned passage (None when the
                                 SUT does not cite, i.e. cited_chunk_ids is None).

Intake metrics (the gateway's job, so independent of the SUT; no judge):
  intake_rejection_recall = share of scenarios labelled expected_intake=rejected that the gateway
                            guardrail rejects before any run.
  intake_false_rejections = number of other scenarios the guardrail rejects (should be 0).

Claims must come from the answer's own text. Sentences copied from the retrieved passages are
supported by construction and would inflate groundedness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    # supporting passage: label (chunk ids of the pinned clause) and predictions
    supporting_chunk_ids: List[str] = field(default_factory=list)
    retrieved_chunk_ids: List[str] = field(default_factory=list)
    cited_chunk_ids: Optional[List[str]] = None  # None: this SUT does not cite
    # ingestion boundary: label and whether the gateway guardrail rejected the complaint
    expected_intake: Optional[str] = None
    intake_rejected: Optional[bool] = None
    # SUT-specific diagnostics (status, citations, models...); not used by the metrics
    details: Dict[str, Any] = field(default_factory=dict)


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

    # --- supporting-passage hits (label-based) ---
    labelled = [r for r in results if r.supporting_chunk_ids]
    citing = [r for r in labelled if r.cited_chunk_ids is not None]

    def hit(ids, r):
        return bool(set(ids or []) & set(r.supporting_chunk_ids))

    # --- intake (gateway guardrail) ---
    must_reject = [r for r in results if r.expected_intake == "rejected" and r.intake_rejected is not None]
    others = [r for r in results if r.expected_intake != "rejected" and r.intake_rejected is not None]

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
        "n_with_supporting_passage": len(labelled),
        "supporting_passage_retrieved": _safe_div(
            sum(hit(r.retrieved_chunk_ids, r) for r in labelled), len(labelled)),
        "supporting_passage_cited": _safe_div(
            sum(hit(r.cited_chunk_ids, r) for r in citing), len(citing)),
        "n_expected_intake_rejected": len(must_reject),
        "intake_rejection_recall": _safe_div(sum(r.intake_rejected for r in must_reject), len(must_reject)),
        "intake_false_rejections": sum(r.intake_rejected for r in others) if others else None,
        "judge": getattr(judge, "name", judge.__class__.__name__),
        "judge_thresholds": {k: getattr(judge, k) for k in
                             ("support_threshold", "relevance_threshold", "infer_threshold")
                             if hasattr(judge, k)},
    }

"""System-under-test for the eval harness (Slice 5).

The harness scores whatever produces a determination. In dev — before Mitesh's agent is
integrated and before the DB exists — we score a **baseline retrieval-grounded answerer**:
a transparent rule-based classifier picks the route/regulator/entity, retrieval (framework-
filtered) supplies the grounding contexts, and the answer's claims are the routing conclusion
plus the top retrieved provisions. This gives real baseline numbers now; the agent is dropped
in later as an alternative SUT (reads determinations from RunStore/gateway), with no metric
code changes.
"""
from __future__ import annotations

from typing import List

from services.retrieval.models import SearchFilters, SearchRequest
from services.retrieval.service import Retriever

from .metrics import EvalResult, split_claims

_INJECTION = ["ignore all previous", "ignore previous instruction", "you are now",
              "unrestricted assistant", "disregard", "award compensation", "approve my claim"]
_OUT_OF_CORPUS = ["insurance", "insurer", "life insurance", "pension", "nps", "irdai", "pfrda"]
_BANK = ["fixed deposit", "term deposit", "term-deposit", "upi", "atm", "savings account",
         "bank's app", "bank app", "net banking", "deposit interest", "debited"]
_SECURITIES = {
    "mutual_fund": ["mutual fund", "amc", "nav", "redemption", "asset management"],
    "broker": ["broker", "trade", "trading"],
    "registrar": ["registrar", "rta", "share transfer", "transfer agent", "updation"],
    "depository": ["demat", "depository"],
    "listed_company": ["dividend", "listed company", "annual report", "shares"],
}


def _has(t: str, words: List[str]) -> bool:
    return any(w in t for w in words)


def classify(text: str):
    """Return (route, regulator, entity_type, escalated)."""
    t = text.lower()
    if _has(t, _INJECTION):
        return "escalate_to_human", "UNDETERMINED", "unknown", True
    sec_hit = any(_has(t, kws) for kws in _SECURITIES.values())
    if _has(t, _BANK) and sec_hit:
        return "escalate_to_human", "UNDETERMINED", "other", True  # split regulators
    if _has(t, _OUT_OF_CORPUS):
        return "escalate_to_human", "UNDETERMINED", "other", True
    if _has(t, _BANK):
        return "refer_to_other_regulator", "RBI", "bank", False
    for entity, kws in _SECURITIES.items():
        if _has(t, kws):
            return "assign_to_entity", "SEBI", entity, False
    return "escalate_to_human", "UNDETERMINED", "unknown", True  # too vague → low confidence


class BaselineSUT:
    name = "baseline-rule+retrieval"

    def __init__(self, retriever: Retriever = None, k: int = 5):
        self.r = retriever or Retriever()
        self.k = k

    def run(self, scenario: dict) -> EvalResult:
        text = scenario["complaint_text"]
        route, regulator, entity, escalated = classify(text)
        contexts: List[str] = []
        claims: List[str] = []
        if not escalated:
            resp = self.r.search(SearchRequest(
                query=text, k=self.k, filters=SearchFilters(framework=regulator)))
            contexts = [p.text for p in resp.results]
            route_claim = (f"The complaint is routed as {route} to {regulator} as a "
                           f"{entity} matter.")
            evidence = [split_claims(c)[0] for c in contexts[:2] if split_claims(c)]
            claims = [route_claim] + evidence
        return EvalResult(
            scenario_id=scenario["id"], question=text, held_out=bool(scenario.get("held_out")),
            route=route, regulator=regulator, entity_type=entity, escalated=escalated,
            contexts=contexts, claims=claims,
            expected_route=scenario["expected_route"],
            expected_regulator=scenario["expected_regulator"],
            expected_entity_type=scenario["expected_entity_type"],
            expected_escalation=bool(scenario["expected_escalation"]),
        )

"""
FakeLLMClient — deterministic test double for LLMClient.

Used in tests to avoid any real gateway or heuristic path.
Responses are keyed on the ``step`` parameter, covering all pipeline steps.
Set ``unavailable=True`` to simulate a gateway failure (raises LLMUnavailable).
"""

import json
import logging
from typing import Any, Dict, List, Optional

from services.worker.clients.llm_client import LLMUnavailable

logger = logging.getLogger("worker.fake_llm")


class FakeLLMClient:
    """
    Scripted test double that returns pre-canned JSON responses by step name.
    Never calls a network endpoint. Never falls back to a heuristic.

    Parameters
    ----------
    unavailable:
        When True every call raises LLMUnavailable — used to test the
        escalation path in the researcher / verifier.
    overrides:
        Mapping of step-name → dict to replace the default canned reply.
    """

    # Default canned responses, keyed by step substring
    _DEFAULTS: Dict[str, Any] = {
        "classify": {
            "entity_type": "broker",
            "regulator": "SEBI",
            "product": "equity_broking",
            "reasoning": "Stock broker complaint → SEBI.",
            "stated_regulator": None,
        },
        "plan": {
            "action": "search_corpus",
            "args": {"query": "broker grievance redressal", "framework": "SEBI", "k": 3},
        },
        "reflect": {
            "reflection": "Evidence is sufficient; no framework swap needed.",
            "requires_further_search": False,
            "framework_swap": False,
            "next_framework": None,
            "next_query": None,
        },
        "draft": {
            "route": "assign_to_entity",
            "regulator": "SEBI",
            "entity_type": "broker",
            "timeline": {"days": 30, "basis_citation_id": "c1"},
            "basis": "Investor grievance falls under SEBI SCORES framework [c1].",
            "citations": [
                {
                    "citation_id": "c1",
                    "doc_id": "sebi_scores_master_circular",
                    "doc_title": "SEBI Master Circular on Investor Grievance Redressal",
                    "circular_ref": "SEBI/HO/OIAE/OIAE_IAD-1/P/CIR/2023/145",
                    "clause": "2",
                    "chunk_id": "d2d66258e59fc24f14530d30125912f54bd3c045f20e9a915253e947e682323e",
                    "quote_span": "registered intermediaries and recognised MIIs that such investor grievances may be resolved faster",
                }
            ],
        },
        "verify": {
            "decision": "accept",
            "passed": True,
            "claims": [{"claim": "Grievance timeline 30 days", "supported": True}],
            "claims_checked": 1,
            "claims_supported": 1,
            "unsupported_claims": [],
            "suggested_strategy": None,
        },
    }

    def __init__(
        self,
        unavailable: bool = False,
        overrides: Optional[Dict[str, Any]] = None,
    ):
        self.unavailable = unavailable
        self._overrides: Dict[str, Any] = overrides or {}

    # ------------------------------------------------------------------
    # Public API – mirrors LLMClient.chat() signature
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        run_id: Optional[str] = None,
        agent: Optional[str] = None,
        step: Optional[str] = None,
        prompt_version: Optional[str] = None,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        if self.unavailable:
            raise LLMUnavailable(
                "FakeLLMClient: simulated gateway unavailable",
                agent=agent,
                step=step,
            )

        step_key = (step or "").lower()
        payload: Dict[str, Any] = {}

        if step_key in self._overrides:
            payload = self._overrides[step_key]
        else:
            for key, default in self._DEFAULTS.items():
                if key in step_key:
                    payload = default
                    break

        content = json.dumps(payload) if payload else "{}"
        logger.debug("FakeLLMClient: step=%s → %s", step, content[:120])

        return {
            "id": f"fake-{step}",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 20,
                "total_tokens": 70,
                "cost_usd": 0.0,
            },
            "model": "fake-llm",
            "degraded": False,
        }

    @staticmethod
    def extract_json(text: str) -> Dict[str, Any]:
        """Delegate to LLMClient's static helper."""
        from services.worker.clients.llm_client import LLMClient

        return LLMClient.extract_json(text)

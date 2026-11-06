"""
Output guardrails for ORCAS determination objects (Requirement L4).

Changes vs previous version
----------------------------
* Toxic-word matching now uses ``\\b`` word boundaries so that words like
  "bodies", "remedies", "studied", and "skill" no longer trigger false
  positives.
* Any violation now *converts* the determination to a valid escalation before
  returning, so the bad value is never stored (previous version returned the
  invalid route/regulator unchanged).
* Consistency invariants added:
  - ``status=completed`` requires ``verification.passed=true`` and
    ``escalation=null``.
  - ``route=escalate_to_human`` iff ``status=escalated``.
  - ``assign_to_entity`` requires a SEBI entity.
* Toxicity check is also run against ``escalation.reason`` text.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

FORBIDDEN_PHRASES: List[str] = [
    "complaint resolved",
    "compensation granted",
    "claim approved",
    "relief granted",
    "refund ordered",
    "order passed",
    "disposed of",
]

# Rule-based toxicity word list (L4 — lightweight local classifier, documented
# choice).  A production system would use a model-based classifier; this rule
# list catches overtly abusive, threatening, or discriminatory language that
# must never appear in an official regulatory routing determination.
#
# Each entry is a word-boundary pattern to avoid false positives such as:
#   "bodies" (contains "die" is wrong — "die" triggers on its own)
#   "remedies" (contains "die"), "studied" (contains "die"),
#   "skill" (contains "kill"), etc.
_TOXIC_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE)
    for w in [
        "kill",
        "murder",
        "rape",
        "terrorist",
        "bomb",
        "stupid",
        "idiot",
        "moron",
        "retard",
        "slur",
        "hate speech",
        "threat",
        "die",
        "racist",
        "sexist",
        "discriminat",
    ]
]

ALLOWED_ROUTES = {
    "assign_to_entity",
    "refer_to_other_regulator",
    "not_maintainable",
    "escalate_to_human",
}

ALLOWED_REGULATORS = {"SEBI", "RBI", "UNDETERMINED"}

SEBI_ENTITIES = {
    "broker",
    "mutual_fund",
    "registrar",
    "listed_company",
    "depository",
}


def _make_guardrail_escalation(res: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Convert *res* (modified in-place) to a valid escalation determination."""
    res["status"] = "escalated"
    res["route"] = "escalate_to_human"
    res["regulator"] = res.get("regulator") if res.get("regulator") in ALLOWED_REGULATORS else "UNDETERMINED"
    res["timeline"] = None
    res["escalation"] = {
        "reason_code": "guardrail",
        "reason": reason,
    }
    return res


def _is_toxic(text: str) -> Optional[str]:
    """Return the first toxic word found, or None."""
    for pattern in _TOXIC_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


class OutputFilter:
    """
    Enforces invariant output guardrails (Requirement L4).

    Rules (in evaluation order):
    1. ``disposed`` is forced to ``False``.
    2. ``route`` must be in ``ALLOWED_ROUTES``; if not, convert to escalation.
    3. ``regulator`` must be in ``ALLOWED_REGULATORS``; if not, convert.
    4. No forbidden settlement/disposal phrase in ``basis``.
    5. No toxic word (word-boundary match) in ``basis`` or
       ``escalation.reason``.
    6. ``status=completed`` requires ``verification.passed=true`` and
       ``escalation=null``.
    7. ``route=escalate_to_human`` iff ``status=escalated``.
    8. ``assign_to_entity`` requires a SEBI entity type.
    """

    @staticmethod
    def filter(
        determination: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Apply all guardrail rules to *determination*.

        Returns
        -------
        (is_safe, filtered_determination, guardrail_message)
            ``is_safe`` is ``True`` only when no rule fired.
            ``filtered_determination`` is always a valid determination —
            violations are converted to escalations rather than left as-is.
            ``guardrail_message`` is a human-readable description of the first
            rule that fired, or ``None``.
        """
        res = dict(determination)

        # 1. Enforce disposed = False
        res["disposed"] = False

        # 2. Validate route enum — convert immediately
        if res.get("route") not in ALLOWED_ROUTES:
            msg = f"Route '{res.get('route')}' is not in ALLOWED_ROUTES; converted to escalation."
            res = _make_guardrail_escalation(res, msg)
            return False, res, msg

        # 3. Validate regulator enum — convert immediately
        if res.get("regulator") not in ALLOWED_REGULATORS:
            msg = f"Regulator '{res.get('regulator')}' is not in ALLOWED_REGULATORS; converted to escalation."
            res = _make_guardrail_escalation(res, msg)
            return False, res, msg

        # 4. Forbidden phrase check on basis
        basis_lower = res.get("basis", "").lower()
        for phrase in FORBIDDEN_PHRASES:
            if phrase in basis_lower:
                msg = f"Prohibited disposal language '{phrase}' in basis; converted to escalation."
                res = _make_guardrail_escalation(res, msg)
                return False, res, msg

        # 5. Toxicity check on basis and escalation.reason
        texts_to_check = [res.get("basis", "")]
        if isinstance(res.get("escalation"), dict):
            texts_to_check.append(res["escalation"].get("reason", ""))
        for text in texts_to_check:
            toxic_word = _is_toxic(text)
            if toxic_word:
                msg = f"Toxic content ('{toxic_word}') detected; converted to escalation."
                res = _make_guardrail_escalation(res, msg)
                return False, res, msg

        # 6. Consistency: completed requires verification.passed=True and escalation=None
        if res.get("status") == "completed":
            verification_passed = (res.get("verification") or {}).get("passed", False)
            if not verification_passed or res.get("escalation") is not None:
                msg = "status=completed but verification.passed is not True or escalation is set; converted to escalation."
                res = _make_guardrail_escalation(res, msg)
                return False, res, msg

        # 7. route=escalate_to_human iff status=escalated
        is_escalated = res.get("status") == "escalated"
        is_escalate_route = res.get("route") == "escalate_to_human"
        if is_escalated and not is_escalate_route:
            res["route"] = "escalate_to_human"
        elif is_escalate_route and not is_escalated:
            # Treat as escalation
            msg = "route=escalate_to_human but status is not escalated; treating as escalation."
            res["status"] = "escalated"
            if not res.get("escalation"):
                res["escalation"] = {
                    "reason_code": "guardrail",
                    "reason": msg,
                }
            return False, res, msg

        # 8. assign_to_entity requires SEBI entity
        if res.get("route") == "assign_to_entity" and res.get("entity_type") not in SEBI_ENTITIES:
            msg = f"route=assign_to_entity but entity_type='{res.get('entity_type')}' is not a SEBI entity."
            res = _make_guardrail_escalation(res, msg)
            return False, res, msg

        return True, res, None

"""
Worker pipeline orchestration for ORCAS.

Changes vs previous version
-----------------------------
* ``LLMUnavailable`` from the researcher or verifier is caught and converted
  to a ``degraded=True`` escalation rather than a bare ``failed`` run.
  - Researcher failure → ``reason_code=agent_failure``
  - Verifier failure  → ``reason_code=verification_unavailable``
* The guardrail ``is_safe`` flag is now honoured: if ``is_safe=False`` the
  filtered (escalated) determination is used but a ``guardrail`` event is
  still emitted.
* ``MAX_VERIFY_RETRIES`` is read from the environment.
* ``failed`` status is now reserved for errors that happen *before* any agent
  work starts (e.g. run-not-found).  Mid-run errors become ``escalated``.
"""

import os
import uuid
import logging
from typing import Any, Dict, Optional

from services.worker.agent.researcher import ResearcherGraph
from services.worker.agent.verifier import VerifierGraph
from services.worker.guardrails.output_filter import OutputFilter
from services.worker.clients.llm_client import LLMUnavailable
from services.worker.clients.runstore import InMemoryRunStore

logger = logging.getLogger("worker.tasks")

# Celery app (Requirement A5 — task queue integration).
# Import is optional so tests work without celery installed;
# the Docker image installs it via requirements.txt.
try:
    from celery import Celery

    _CELERY_SOFT_LIMIT = int(os.getenv("CELERY_SOFT_TIME_LIMIT", "120"))
    _CELERY_HARD_LIMIT = int(os.getenv("CELERY_TIME_LIMIT", "180"))

    celery_app = Celery(
        "orcas",
        broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    )
    celery_app.conf.task_acks_late = True
    celery_app.conf.task_default_queue = "orcas_tasks"
    celery_app.conf.task_soft_time_limit = _CELERY_SOFT_LIMIT
    celery_app.conf.task_time_limit = _CELERY_HARD_LIMIT

    @celery_app.task(name="orcas.run_complaint", bind=True, max_retries=0, acks_late=True)
    def run_complaint(self, run_id: str, complaint_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Celery task entrypoint — delegates to run_complaint_pipeline."""
        return run_complaint_pipeline(run_id=run_id, complaint_data=complaint_data)

except ImportError:
    celery_app = None
    logger.info("Celery not installed; run_complaint_pipeline available as plain function.")


global_run_store = InMemoryRunStore()

_MAX_VERIFY_RETRIES = int(os.getenv("MAX_VERIFY_RETRIES", "2"))


def _strip_internal(d: Dict[str, Any]) -> Dict[str, Any]:
    """Remove internal-only keys before schema validation / storage."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _build_degraded_escalation(
    run_id: str,
    draft: Optional[Dict[str, Any]],
    reason_code: str,
    reason: str,
    partial_findings: list,
) -> Dict[str, Any]:
    """Return a minimal valid escalation determination with degraded=True."""
    base = {k: v for k, v in draft.items() if not k.startswith("_")} if draft else {}
    base.update({
        "run_id": run_id,
        "status": "escalated",
        "route": "escalate_to_human",
        "regulator": base.get("regulator", "UNDETERMINED"),
        "entity_type": base.get("entity_type", "other"),
        "timeline": None,
        "basis": f"Escalated due to infrastructure failure: {reason}",
        "citations": [],
        "escalation": {
            "reason_code": reason_code,
            "reason": reason,
            "partial_findings": partial_findings,
        },
        "verification": {
            "passed": False,
            "claims_checked": 0,
            "claims_supported": 0,
            "attempts": 1,
        },
        "prompt_versions": base.get("prompt_versions", {}),
        "index_version": base.get("index_version", "unknown"),
        "degraded": True,
        "disposed": False,
    })
    return {k: v for k, v in base.items() if not k.startswith("_")}


def run_complaint_pipeline(
    run_id: str,
    complaint_data: Optional[Dict[str, Any]] = None,
    run_store: Optional[InMemoryRunStore] = None,
    researcher_graph: Optional[ResearcherGraph] = None,
    verifier_graph: Optional[VerifierGraph] = None,
    inject_bad_draft: bool = False,
) -> Dict[str, Any]:
    """
    Complete multi-agent pipeline:
    1. Researcher agent exploration & drafting.
    2. Optional planted-bad-draft fault injection (Demo #6).
    3. Independent Verifier audit & citation resolution.
    4. Guardrail output filtering.
    5. Event emission for full run reconstruction (Requirement D5).

    ``LLMUnavailable`` from the researcher or verifier is caught and the run
    is escalated with ``degraded=True`` instead of becoming ``failed``.
    ``failed`` status is reserved for pre-work setup errors only.
    """
    store = run_store or global_run_store
    r_graph = researcher_graph or ResearcherGraph()
    v_graph = verifier_graph or VerifierGraph(retrieval_client=r_graph.retrieval, llm_client=r_graph.llm)

    record = store.get_run(run_id)
    if not record and complaint_data:
        record = store.create_run(run_id, complaint_data)

    if not record:
        # Pre-work setup failure — the only legitimate ``failed`` case.
        store.fail(run_id, f"Run ID {run_id} not found in run store.")
        raise ValueError(f"Run ID {run_id} not found in run store.")

    store.update_status(run_id, "running")
    store.append_event(
        run_id=run_id,
        agent="system",
        step="intake",
        kind="run_started",
        payload={"complaint_id": run_id},
    )

    complaint_payload = record.get("payload", {})
    draft: Optional[Dict[str, Any]] = None
    partial_findings: list = []

    # ------------------------------------------------------------------ #
    # Phase 1 — Researcher                                                 #
    # ------------------------------------------------------------------ #
    try:
        draft = r_graph.run(run_id=run_id, complaint_fields=complaint_payload)
        partial_findings = draft.get("citations", [])

        store.append_event(
            run_id=run_id,
            agent="researcher",
            step="draft",
            kind="draft",
            payload={"route": draft.get("route"), "basis": draft.get("basis"), "degraded": draft.get("degraded", False)},
        )

    except LLMUnavailable as exc:
        logger.warning("Researcher LLMUnavailable for run %s: %s", run_id, exc)
        escalation = _build_degraded_escalation(
            run_id=run_id,
            draft=None,
            reason_code="agent_failure",
            reason=str(exc),
            partial_findings=[],
        )
        store.append_event(
            run_id=run_id,
            agent="system",
            step="error",
            kind="degraded",
            payload={"reason_code": "agent_failure", "agent": exc.agent, "step": exc.step, "error": str(exc)},
        )
        store.complete(run_id, escalation)
        store.append_event(
            run_id=run_id,
            agent="system",
            step="finalize",
            kind="run_finished",
            payload={"status": "escalated", "route": "escalate_to_human", "degraded": True},
        )
        return escalation

    # ------------------------------------------------------------------ #
    # Fault injection hook for Demo #6                                     #
    # ------------------------------------------------------------------ #
    if inject_bad_draft or os.getenv("ORCAS_INJECT_BAD_DRAFT") == "1":
        logger.info("Injecting fabricated citation into draft for Verifier test.")
        draft["citations"] = list(draft.get("citations", []))
        draft["citations"].append({
            "citation_id": "fabricated_bad_chunk",
            "doc_id": "fabricated_doc",
            "doc_title": "Fake Act",
            "circular_ref": "FAKE/2026/01",
            "clause": "99",
            "chunk_id": "non_existent_chunk_hash_123456",
            "quote_span": "This phrase does not exist in any regulatory document.",
        })

    # ------------------------------------------------------------------ #
    # Phase 2 — Verifier                                                   #
    # ------------------------------------------------------------------ #
    # Pass the full evidence ledger from the researcher to the verifier.
    evidence_ledger = draft.get("_evidence_ledger", draft.get("citations", []))
    max_attempts = _MAX_VERIFY_RETRIES
    attempt = 1
    v_res: Optional[Dict[str, Any]] = None

    try:
        v_res = v_graph.verify(
            draft=draft,
            evidence_ledger=evidence_ledger,
            attempt=attempt,
            max_retries=max_attempts,
        )

        while v_res.get("decision") == "retry" and attempt < max_attempts:
            attempt += 1
            store.append_event(
                run_id=run_id,
                agent="verifier",
                step="retry",
                kind="retry",
                payload={"attempt": attempt, "strategy": v_res.get("suggested_strategy")},
            )
            v_res = v_graph.verify(
                draft=draft,
                evidence_ledger=evidence_ledger,
                attempt=attempt,
                max_retries=max_attempts,
            )

    except LLMUnavailable as exc:
        logger.warning("Verifier LLMUnavailable for run %s: %s", run_id, exc)
        escalation = _build_degraded_escalation(
            run_id=run_id,
            draft=draft,
            reason_code="verification_unavailable",
            reason=str(exc),
            partial_findings=partial_findings,
        )
        store.append_event(
            run_id=run_id,
            agent="system",
            step="error",
            kind="degraded",
            payload={"reason_code": "verification_unavailable", "agent": exc.agent, "step": exc.step, "error": str(exc)},
        )
        store.complete(run_id, escalation)
        store.append_event(
            run_id=run_id,
            agent="system",
            step="finalize",
            kind="run_finished",
            payload={"status": "escalated", "route": "escalate_to_human", "degraded": True},
        )
        return escalation

    store.append_event(
        run_id=run_id,
        agent="verifier",
        step="verify",
        kind="verify",
        payload={
            "decision": v_res.get("decision"),
            "passed": v_res.get("passed"),
            "attempt": attempt,
            "strategy": v_res.get("suggested_strategy"),
        },
    )

    # Finalise determination
    final_determination = v_res.get("draft")
    if not final_determination or v_res.get("decision") != "accept":
        final_determination = v_graph._escalate_draft(
            draft,
            reason_code="unverified",
            reason=v_res.get("reason", "Verification failed after retries."),
            attempt=attempt,
        )["draft"]

    final_determination = _strip_internal(final_determination)

    # ------------------------------------------------------------------ #
    # Phase 3 — Output Guardrail                                           #
    # ------------------------------------------------------------------ #
    is_safe, filtered_det, guardrail_msg = OutputFilter.filter(final_determination)
    filtered_det = _strip_internal(filtered_det)
    if guardrail_msg:
        store.append_event(
            run_id=run_id,
            agent="guardrail",
            step="filter",
            kind="guardrail",
            payload={"message": guardrail_msg, "is_safe": is_safe},
        )

    status = filtered_det.get("status", "completed")
    store.complete(run_id, filtered_det)
    store.append_event(
        run_id=run_id,
        agent="system",
        step="finalize",
        kind="run_finished",
        payload={"status": status, "route": filtered_det.get("route")},
    )

    return filtered_det

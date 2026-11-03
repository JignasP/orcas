"""Agent system-under-test (T1): scores the shipped worker pipeline, not the keyword baseline.

Three ways to reach the agent:
  llm="stub"     in-process worker graphs + the real retrieval app; LLM replies come from the
                 llm_stub app, exactly what llm-gateway returns in ORCAS_STUB_MODE (no delay).
                 Needs only the local index; no running services.
  llm="gateway"  in-process worker + retrieval; LLM calls go to LLM_GATEWAY_URL (a live model).
  via_gateway    the running Compose stack's public API: submit, poll, read the run trace.

Contexts are the passages the run actually retrieved (its tool_call events), so the RAG metrics
judge what the agent read rather than what it chose to cite. Claims are the sentences of the
determination's basis; escalations assert nothing.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import httpx

from .metrics import EvalResult, split_claims

_CITE_TAG = re.compile(r"\s*\[c\d+\]")
_TERMINAL = {"completed", "escalated", "failed"}
# What LLMClient reports when the gateway is unreachable and it answers from its local heuristic.
HEURISTIC_MODEL = "heuristic-mock"


def complaint_payload(scenario: dict) -> dict:
    today = date.today()
    return {
        "client_id": "orcas-eval",
        "is_synthetic": True,
        "channel": "web",
        "text": " ".join(scenario["complaint_text"].split()),
        "date_of_event": (today - timedelta(days=30)).isoformat(),
        "date_filed": today.isoformat(),
    }


def _retrieved(events: List[dict]) -> List[dict]:
    """Passages the run retrieved, in order, de-duplicated by chunk_id."""
    seen, out = set(), []
    for event in events:
        if event.get("kind") != "tool_call":
            continue
        for p in (event.get("payload") or {}).get("passages") or []:
            cid = p.get("chunk_id")
            if cid in seen:
                continue
            seen.add(cid)
            out.append(p)
    return out


def contexts_from_events(events: List[dict]) -> List[str]:
    """Passage texts the run retrieved, in order, de-duplicated by chunk_id."""
    return [p["text"] for p in _retrieved(events) if p.get("text")]


def claims_from_determination(det: dict) -> List[str]:
    """An answer's claims are the sentences of its basis; escalations and failures assert nothing."""
    if (det or {}).get("status") != "completed":
        return []
    return split_claims(_CITE_TAG.sub("", det.get("basis") or ""))


def to_result(scenario: dict, det: Optional[dict], events: List[dict],
              status: Optional[str] = None, **details: Any) -> EvalResult:
    det = det or {}
    status = status or det.get("status") or "failed"
    llm_events = [e for e in events if e.get("kind") == "llm_call"]
    return EvalResult(
        scenario_id=scenario["id"], question=scenario["complaint_text"],
        held_out=bool(scenario.get("held_out")),
        route=det.get("route", status), regulator=det.get("regulator", ""),
        entity_type=det.get("entity_type", ""), escalated=status == "escalated",
        contexts=contexts_from_events(events), claims=claims_from_determination(det),
        retrieved_chunk_ids=[p["chunk_id"] for p in _retrieved(events) if p.get("chunk_id")],
        cited_chunk_ids=[c["chunk_id"] for c in det.get("citations") or [] if c.get("chunk_id")],
        expected_route=scenario["expected_route"],
        expected_regulator=scenario["expected_regulator"],
        expected_entity_type=scenario["expected_entity_type"],
        expected_escalation=bool(scenario["expected_escalation"]),
        details={
            "status": status,
            "reason_code": (det.get("escalation") or {}).get("reason_code"),
            "citations": [{"doc_id": c.get("doc_id"), "clause": c.get("clause"),
                           "chunk_id": c.get("chunk_id")} for c in det.get("citations") or []],
            "degraded": det.get("degraded"),
            "prompt_versions": det.get("prompt_versions") or {},
            "index_version": det.get("index_version"),
            "models": sorted({(e.get("payload") or {}).get("model") for e in llm_events} - {None}),
            "llm_calls": len(llm_events),
            "tool_calls": sum(1 for e in events if e.get("kind") == "tool_call"),
            **details,
        },
    )


def _llm_recorder(store, run_id: str):
    """Persist each LLM call as an llm_call event, as services.worker.tasks does."""
    def record(agent, step, prompt_version, result, latency_ms):
        usage = result.get("usage", {})
        store.append_event(
            run_id, agent, step, "llm_call", latency_ms=latency_ms,
            payload={"prompt_version": prompt_version, "model": result.get("model"),
                     "degraded": result.get("degraded", False)},
            tokens={"prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0)},
            cost_usd=float(usage.get("cost_usd", 0)),
        )
    return record


class InProcessStubLLM:
    """LLM client that posts to the llm_stub app in-process, so replies match the stub service."""

    def __init__(self, http, run_id: str, on_call):
        self.http = http
        self.run_id = run_id
        self.on_call = on_call

    def chat(self, messages, temperature=0.0, run_id=None, agent=None, step=None,
             prompt_version=None, timeout=15.0):
        started = time.monotonic()
        response = self.http.post("/v1/chat", json={
            "messages": messages, "temperature": temperature, "run_id": run_id or self.run_id,
            "agent": agent, "step": step, "prompt_version": prompt_version,
        })
        response.raise_for_status()
        result = response.json()
        self.on_call(agent or "unknown", step or "unknown", prompt_version or "unknown",
                     result, round((time.monotonic() - started) * 1000))
        return result

    @staticmethod
    def extract_json(text: str) -> Dict[str, Any]:
        from services.worker.clients.llm_client import LLMClient

        return LLMClient.extract_json(text)


class AgentSUT:
    def __init__(self, llm: str = "stub", retrieval_url: Optional[str] = None,
                 via_gateway: Optional[str] = None, timeout_s: float = 180.0,
                 gateway_client: Optional[httpx.Client] = None):
        if llm not in ("stub", "gateway"):
            raise ValueError("llm must be 'stub' or 'gateway'")
        self.llm = llm
        self.retrieval_url = retrieval_url
        self.via_gateway = via_gateway.rstrip("/") if via_gateway else None
        self.timeout_s = timeout_s
        self._gateway = gateway_client
        self._retrieval_http = None
        self._stub_http = None

    @property
    def name(self) -> str:
        if self.via_gateway:
            return f"agent[via-gateway={self.via_gateway}]"
        return f"agent[llm={self.llm},retrieval={self.retrieval_url or 'in-process'}]"

    @property
    def tag(self) -> str:
        return "agent-compose" if self.via_gateway else f"agent-{self.llm}"

    def run(self, scenario: dict) -> EvalResult:
        if self.via_gateway:
            return self._run_via_gateway(scenario)
        return self._run_in_process(scenario)

    # --- in-process -------------------------------------------------------

    def _retrieval(self):
        if self._retrieval_http is None:
            if self.retrieval_url:
                self._retrieval_http = (self.retrieval_url.rstrip("/"), httpx.Client(timeout=30))
            else:
                from fastapi.testclient import TestClient

                from services.retrieval.app import app as retrieval_app

                self._retrieval_http = ("http://testserver", TestClient(retrieval_app))
        return self._retrieval_http

    def _stub(self):
        if self._stub_http is None:
            from fastapi.testclient import TestClient

            from services.llm_stub import app as stub

            stub.STUB_DELAY_MS = 0  # the delay models provider latency; it adds nothing here
            self._stub_http = TestClient(stub.app)
        return self._stub_http

    def _run_in_process(self, scenario: dict) -> EvalResult:
        from libs.orcas_common.runstore import InMemoryRunStore
        from services.worker import tasks
        from services.worker.agent.researcher import ResearcherGraph
        from services.worker.clients.llm_client import LLMClient
        from services.worker.clients.observed_retrieval import ObservedRetrievalClient
        from services.worker.clients.retrieval import HttpRetrievalClient

        store = InMemoryRunStore()
        run_id = str(uuid.uuid4())
        store.create_run(run_id, complaint_payload(scenario))
        base_url, http = self._retrieval()
        retrieval = ObservedRetrievalClient(
            HttpRetrievalClient(base_url=base_url, client=http, run_id=run_id), store, run_id)
        record = _llm_recorder(store, run_id)
        llm = (InProcessStubLLM(self._stub(), run_id, record) if self.llm == "stub"
               else LLMClient(run_id=run_id, on_call=record))
        error = None
        try:
            det = tasks.run_complaint_pipeline(
                run_id, run_store=store,
                researcher_graph=ResearcherGraph(llm_client=llm, retrieval_client=retrieval))
        except Exception as exc:  # the pipeline already marked the run failed
            det, error = None, f"{type(exc).__name__}: {exc}"
        return to_result(scenario, det, store.get_events(run_id), run_id=run_id, error=error)

    # --- via the Compose stack --------------------------------------------

    def _gateway_client(self) -> httpx.Client:
        if self._gateway is None:
            self._gateway = httpx.Client(base_url=self.via_gateway, timeout=15)
        return self._gateway

    def _run_via_gateway(self, scenario: dict) -> EvalResult:
        http = self._gateway_client()
        for _ in range(5):
            response = http.post("/v1/complaints", json=complaint_payload(scenario),
                                 headers={"X-Run-Cache-Bypass": "true"})
            if response.status_code != 429:
                break
            time.sleep(float(response.headers.get("Retry-After", "1")))
        if response.status_code == 422:
            # Rejected at the ingestion boundary: no run exists, so nothing was answered.
            body = response.json()
            return to_result(scenario, {"route": "escalate_to_human", "regulator": "UNDETERMINED",
                                        "entity_type": "unknown"}, [], status="escalated",
                             intake="rejected", quarantine_id=body.get("quarantine_id"),
                             intake_errors=[e.get("type") for e in body.get("detail", [])])
        response.raise_for_status()
        run_id = response.json()["run_id"]

        deadline = time.monotonic() + self.timeout_s
        run = {}
        while time.monotonic() < deadline:
            run = http.get(f"/v1/runs/{run_id}").json()
            if run.get("status") in _TERMINAL:
                break
            time.sleep(1)
        else:
            return to_result(scenario, None, [], status="timeout", run_id=run_id)
        events = http.get(f"/v1/runs/{run_id}/trace").json().get("events", [])
        return to_result(scenario, run.get("result"), events, status=run["status"], run_id=run_id)

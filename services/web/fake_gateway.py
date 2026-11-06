"""Fake gateway for developing the web client (TAHIR.md: "build the client against a
20-line fake server"). NOT the real gateway (that is Jignas's service).

Implements the documented contract:
  POST /v1/complaints          -> 202 {run_id, status_url}
  GET  /v1/runs/{run_id}       -> run_status.v1 (result: determination.v1 when terminal)
  GET  /v1/runs/{run_id}/trace -> ordered events, incl. the passages the run retrieved
and serves the static client at / so the page is same-origin (no CORS needed).

Status is time-based (queued -> running -> terminal) to mimic the async queue without
threads. The determination is canned from the complaint text so demo presets route the
way the reference answers expect; the §4.1 case uses the pinned reference passages
(docs/work/tahir/evaluation-1-package.md, addendum).

Run:  uvicorn services.web.fake_gateway:app --port 8000
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="ORCAS fake gateway (dev only)")
_RUNS: dict[str, dict] = {}
_FEEDBACK: dict[str, dict] = {}
STATIC = Path(__file__).resolve().parent / "static"
INDEX_VERSION = "minilm-l6-v2.clause.devfake.637"


class Complaint(BaseModel):
    client_id: str
    is_synthetic: bool = True
    channel: str = "web"
    text: str = ""
    date_of_event: str | None = None
    date_filed: str | None = None


class Feedback(BaseModel):
    rating: str  # up | down
    reason: str = ""


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.post("/v1/complaints", status_code=202)
def submit(c: Complaint):
    run_id = str(uuid.uuid4())
    _RUNS[run_id] = {"t0": time.monotonic(), "submitted_at": _iso(), "text": c.text}
    return {"run_id": run_id, "status_url": f"/v1/runs/{run_id}"}


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str):
    run = _RUNS.get(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "unknown run_id"})
    elapsed = time.monotonic() - run["t0"]
    if elapsed < 1.0:
        status = "queued"
    elif elapsed < 2.0:
        status = "running"
    else:
        det = _determination(run_id, run["text"])
        return {"run_id": run_id, "status": det["status"], "submitted_at": run["submitted_at"],
                "started_at": run["submitted_at"], "finished_at": _iso(), "result": det}
    return {"run_id": run_id, "status": status, "submitted_at": run["submitted_at"]}


SEBI_DOC = ("sebi_scores_master_circular",
            "Master Circular on the redressal of investor grievances through the SEBI Complaints "
            "Redress System (SCORES) platform", "SEBI/HO/OIAE/IGRD/P/CIR/2022/0150")
RBI_DOC = ("rbi_integrated_ombudsman_scheme_2021", "Reserve Bank - Integrated Ombudsman Scheme, 2021",
           "Reserve Bank - Integrated Ombudsman Scheme, 2021")
# chunk_id -> (doc, clause, retrieved text), copied from the clause index
PASSAGES = {
    "d2d66258e59fc24f14530d30125912f54bd3c045f20e9a915253e947e682323e": (SEBI_DOC, "2",
        "2. SEBI had been receiving inputs from listed companies, registered intermediaries and "
        "recognised MIIs that such investor grievances may be resolved faster if these grievances are "
        "taken up directly with the entity concerned at the first instance. Accordingly, it is now "
        "mandatory for investors to first take up their grievances for redressal with the entity "
        "concerned, through their designated persons/officials who handle issues relating to "
        "compliance and redressal of investor grievances."),
    "c3cdfa20cf3464b2e00edbf53c1392dffdd8a237837b12f092cc4bdfa3bcc2b0": (RBI_DOC, "preamble",
        "1 THE RESERVE BANK - INTEGRATED OMBUDSMAN SCHEME, 2021 A Scheme for resolving customer "
        "grievances in relation to services provided by entities regulated by Reserve Bank of India in "
        "an expeditious and cost-effective manner under Section 35A of the Banking Regulation Act, "
        "1949 (10 of 1949), Section 45L of the Reserve Bank of India Act, 1934 (2 of 1934) and Section "
        "18 of the Payment and Settlement Systems Act, 2007 (51 of 2007)."),
    "17192ff2b4575e221099d33358788a939ad2059d5b9617db56f157b82b726a64": (RBI_DOC, "9",
        "9. Grounds of Complaint Any customer aggrieved by an act or omission of a Regulated Entity "
        "resulting in deficiency in service may file a complaint under the Scheme personally or "
        "through an authorised representative as defined under clause 3(1)(c)."),
}


def _cite(citation_id: str, chunk_id: str, quote: str) -> dict:
    (doc_id, doc_title, circular_ref), clause, text = PASSAGES[chunk_id]
    assert quote in text
    return {"citation_id": citation_id, "doc_id": doc_id, "doc_title": doc_title,
            "circular_ref": circular_ref, "clause": clause, "chunk_id": chunk_id, "quote_span": quote}


@app.get("/v1/runs/{run_id}/trace")
def get_trace(run_id: str):
    run = _RUNS.get(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "unknown run_id"})
    det = _determination(run_id, run["text"])
    passages = [{"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "quote_span": None,
                 "text": PASSAGES[c["chunk_id"]][2]} for c in det["citations"]]
    events = [{"seq": 1, "agent": "retrieval", "step": "search", "kind": "tool_call", "latency_ms": 12,
               "payload": {"query": run["text"], "passages": passages}, "cost_usd": 0.0}]
    return {"run_id": run_id, "status": det["status"], "events": events, "total_cost_usd": 0.0}


@app.post("/v1/runs/{run_id}/feedback")
def feedback(run_id: str, body: Feedback):
    if run_id not in _RUNS:
        return JSONResponse(status_code=404, content={"error": "unknown run_id"})
    _FEEDBACK[run_id] = {"rating": body.rating, "reason": body.reason, "ts": _iso()}
    return {"status": "recorded", "run_id": run_id, "rating": body.rating}


def _determination(run_id: str, text: str) -> dict:
    t = text.lower()
    base = {"run_id": run_id, "index_version": INDEX_VERSION, "degraded": False,
            "disposed": False, "prompt_versions": {}}

    if ("fixed deposit" in t or ("bank" in t and "deposit" in t)
            or "term-deposit" in t or "term deposit" in t or " fd " in f" {t} "):
        return {**base, "status": "completed", "route": "refer_to_other_regulator",
                "regulator": "RBI", "entity_type": "bank",
                "basis": "The complaint concerns a fixed deposit opened through a bank, which is a banking "
                         "product rather than a securities-market product. SEBI's SCORES mechanism is "
                         "addressed to listed companies, registered intermediaries and recognised MIIs "
                         "[c1]. The RBI Integrated Ombudsman Scheme covers services provided by entities "
                         "regulated by the Reserve Bank [c2], and a customer aggrieved by a Regulated "
                         "Entity's deficiency in service may complain under it [c3]. Referred to RBI.",
                "citations": [
                    _cite("c1", "d2d66258e59fc24f14530d30125912f54bd3c045f20e9a915253e947e682323e",
                          "registered intermediaries and recognised MIIs that such investor grievances "
                          "may be resolved faster"),
                    _cite("c2", "c3cdfa20cf3464b2e00edbf53c1392dffdd8a237837b12f092cc4bdfa3bcc2b0",
                          "services provided by entities regulated by Reserve Bank of India"),
                    _cite("c3", "17192ff2b4575e221099d33358788a939ad2059d5b9617db56f157b82b726a64",
                          "deficiency in service may file a complaint under the Scheme"),
                ],
                "escalation": None,
                "verification": {"passed": True, "claims_checked": 3, "claims_supported": 3, "attempts": 1}}

    if any(w in t for w in ("insurance", "insurer", "pension", "irdai", "life insurance")):
        return {**base, "status": "escalated", "route": "escalate_to_human",
                "regulator": "UNDETERMINED", "entity_type": "other", "basis": "",
                "citations": [],
                "escalation": {"reason_code": "out_of_corpus",
                               "reason": "Insurer/pension grievances are outside the SEBI/RBI corpus (IRDAI/PFRDA); escalated to a human.",
                               "partial_findings": []},
                "verification": {"passed": True, "claims_checked": 0, "claims_supported": 0, "attempts": 1}}

    entity = "mutual_fund" if any(w in t for w in ("mutual fund", "redemption", "nav", "amc", "unit")) else "broker"
    return {**base, "status": "completed", "route": "assign_to_entity", "regulator": "SEBI",
            "entity_type": entity,
            "basis": "A securities-market grievance handled under SEBI's SCORES; assigned to the concerned entity [c1].",
            "citations": [
                _cite("c1", "d2d66258e59fc24f14530d30125912f54bd3c045f20e9a915253e947e682323e",
                      "registered intermediaries and recognised MIIs that such investor grievances may "
                      "be resolved faster"),
            ],
            "escalation": None,
            "verification": {"passed": True, "claims_checked": 1, "claims_supported": 1, "attempts": 1}}


# Serve the static client at / (mounted last so /v1/* routes win).
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")

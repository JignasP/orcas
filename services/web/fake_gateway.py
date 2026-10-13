"""Fake gateway for developing the web client (TAHIR.md: "build the client against a
20-line fake server"). NOT the real gateway (that is Jignas's service).

Implements the documented contract:
  POST /v1/complaints        -> 202 {run_id, status_url}
  GET  /v1/runs/{run_id}     -> run_status.v1 (result: determination.v1 when terminal)
and serves the static client at / so the page is same-origin (no CORS needed).

Status is time-based (queued -> running -> terminal) to mimic the async queue without
threads. The determination is canned from the complaint text so demo presets route the
way the reference answers expect; the §4.1 case uses the real pinned citations.

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
STATIC = Path(__file__).resolve().parent / "static"
INDEX_VERSION = "minilm-l6-v2.devfake.606"


class Complaint(BaseModel):
    client_id: str
    is_synthetic: bool = True
    channel: str = "web"
    text: str = ""
    date_of_event: str | None = None
    date_filed: str | None = None


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


def _cite(citation_id, doc_id, doc_title, circular_ref, clause, chunk_id, quote):
    return {"citation_id": citation_id, "doc_id": doc_id, "doc_title": doc_title,
            "circular_ref": circular_ref, "clause": clause, "chunk_id": chunk_id, "quote_span": quote}


def _determination(run_id: str, text: str) -> dict:
    t = text.lower()
    base = {"run_id": run_id, "index_version": INDEX_VERSION, "degraded": False,
            "disposed": False, "prompt_versions": {}}

    if ("fixed deposit" in t or ("bank" in t and "deposit" in t)
            or "term-deposit" in t or "term deposit" in t or " fd " in f" {t} "):
        return {**base, "status": "completed", "route": "refer_to_other_regulator",
                "regulator": "RBI", "entity_type": "bank",
                "basis": "The complaint concerns a bank fixed deposit, a banking product. SEBI's SCORES "
                         "covers securities-market entities [c1], not bank deposits. The RBI Integrated "
                         "Ombudsman Scheme applies to entities regulated by the Reserve Bank [c2] and "
                         "provides grounds of complaint for deficiency in service [c3]. Referred to RBI.",
                "citations": [
                    _cite("c1", "sebi_scores_master_circular", "SEBI SCORES Master Circular",
                          "SEBI/HO/OIAE/IGRD/P/CIR/2022/0150", "p1w1",
                          "ae8861c58c329fc7062bef1db8c34b7cf6efbf1398ed39367f0efd2815d42d7f",
                          "registered intermediaries and recognised MIIs that such investor grievances may be resolved faster"),
                    _cite("c2", "rbi_integrated_ombudsman_scheme_2021", "RBI Integrated Ombudsman Scheme 2021",
                          "RBI IOS 2021", "p1w0",
                          "801da99662534d0c3a0f0e8cd188d1394aee534a498b2a08a140cfa5ea9faf91",
                          "regulated by Reserve Bank of India in an expeditious and cost-effective manner"),
                    _cite("c3", "rbi_integrated_ombudsman_scheme_2021", "RBI Integrated Ombudsman Scheme 2021",
                          "RBI IOS 2021", "p6w0",
                          "7b4481e134cbf5696953bd16b43861b2c2fe762584e280c55423ab1a7a0fb53e",
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
                _cite("c1", "sebi_scores_master_circular", "SEBI SCORES Master Circular",
                      "SEBI/HO/OIAE/IGRD/P/CIR/2022/0150", "p1w1",
                      "ae8861c58c329fc7062bef1db8c34b7cf6efbf1398ed39367f0efd2815d42d7f",
                      "registered intermediaries and recognised MIIs that such investor grievances may be resolved faster"),
            ],
            "escalation": None,
            "verification": {"passed": True, "claims_checked": 1, "claims_supported": 1, "attempts": 1}}


# Serve the static client at / (mounted last so /v1/* routes win).
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")

import asyncio
import json
import os
import re
import time
import uuid
from typing import List, Optional
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ORCAS LLM Stub Service", version="1.0.0")

STUB_DELAY_MS = int(os.getenv("STUB_DELAY_MS", "1500"))


def citation_from_evidence(prompt: str, framework: str) -> dict | None:
    """Pick an exact quote from retrieved evidence in the draft prompt."""
    match = re.search(r"Evidence Ledger:\s*(\[[^\r\n]*\])", prompt)
    if not match:
        return None
    try:
        ledger = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    candidates = [item for item in ledger if item.get("framework") == framework
                  and item.get("chunk_type", "clause") != "scope_card" and item.get("text")]
    if not candidates:
        return None
    keywords = ("deficiency in service", "regulated by reserve bank") if framework == "RBI" else (
        "investor grievances", "registered intermediaries", "mutual fund"
    )
    selected = next((item for word in keywords for item in candidates
                     if word in item["text"].lower()), candidates[0])
    passage = selected["text"]
    phrase = next((word for word in keywords if word in passage.lower()), "")
    start = max(0, passage.lower().find(phrase) - 30) if phrase else 0
    quote_span = passage[start:start + 180]
    return {
        "citation_id": "c1",
        "doc_id": selected.get("doc_id", ""),
        "doc_title": selected.get("doc_title", ""),
        "circular_ref": selected.get("circular_ref", ""),
        "clause": selected.get("clause_id", ""),
        "chunk_id": selected["chunk_id"],
        "quote_span": quote_span,
    }


class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = "llm-stub"
    temperature: Optional[float] = 0.0
    max_tokens: Optional[int] = 2048
    run_id: Optional[str] = None
    agent: Optional[str] = None
    step: Optional[str] = None
    prompt_version: Optional[str] = None


class ChatUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


class ChatChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str = "stop"


class ChatResponse(BaseModel):
    id: str
    choices: List[ChatChoice]
    usage: ChatUsage
    model: str
    degraded: bool = True


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "stub", "delay_ms": STUB_DELAY_MS}


def generate_stub_reply(request: ChatRequest) -> str:
    """Generate realistic responses based on calling agent, step, and complaint text."""
    combined = " ".join([m.content for m in request.messages])
    step = (request.step or "").lower()
    
    # Extract complaint text from prompt
    complaint_match = re.search(r"complaint(?:\s*text)?:\s*(.*?)(?:\n\w+:|$)", combined, re.DOTALL | re.IGNORECASE)
    target_text = complaint_match.group(1).lower() if complaint_match else combined.lower()

    # --- Classification ---
    if "classify" in step:
        if any(w in target_text for w in ["insurance", "insurer", "hospital"]):
            return json.dumps({
                "entity_type": "other",
                "regulator": "UNDETERMINED",
                "product": "health_insurance",
                "reasoning": "Insurance products fall under IRDAI and are outside covered corpus."
            })
        elif any(w in target_text for w in ["fixed deposit", "term deposit", "bank app"]):
            return json.dumps({
                "entity_type": "bank",
                "regulator": "RBI",
                "product": "fixed_deposit",
                "reasoning": "Bank deposit complaints belong to RBI Integrated Ombudsman Scheme."
            })
        elif any(w in target_text for w in ["mutual fund", "nav", "amc", "redemption"]):
            return json.dumps({
                "entity_type": "mutual_fund",
                "regulator": "SEBI",
                "product": "mutual_fund_units",
                "reasoning": "Mutual fund servicing is governed under SEBI MF Regulations."
            })
        elif any(w in target_text for w in ["broker", "demat", "shares", "trading"]):
            return json.dumps({
                "entity_type": "broker",
                "regulator": "SEBI",
                "product": "equity_broking",
                "reasoning": "Stock brokers are registered SEBI intermediaries."
            })
        else:
            return json.dumps({
                "entity_type": "other",
                "regulator": "UNDETERMINED",
                "product": "general",
                "reasoning": "Unrecognized financial product."
            })

    # --- Reflection ---
    if "reflect" in step:
        if "bank" in target_text or "fixed deposit" in target_text:
            return json.dumps({
                "reflection": "Product identified as bank fixed deposit. Jurisdiction redirect from SEBI to RBI applies.",
                "requires_further_search": True,
                "framework_swap": True,
                "next_framework": "RBI",
                "next_query": "bank fixed deposit interest grievance deficiency in service"
            })
        return json.dumps({
            "reflection": "Retrieved evidence directly addresses servicing requirements.",
            "requires_further_search": False,
            "framework_swap": False,
            "next_framework": None,
            "next_query": None
        })

    # --- Draft Determination ---
    if "draft" in step:
        if "fixed deposit" in target_text or "bank" in target_text:
            citation = citation_from_evidence(combined, "RBI")
            return json.dumps({
                "route": "refer_to_other_regulator",
                "regulator": "RBI",
                "entity_type": "bank",
                "timeline": None,
                "basis": "Bank fixed deposit interest servicing should be routed under the cited RBI Ombudsman provision [c1]." if citation else "No RBI passage was retrieved for verification.",
                "citations": [citation] if citation else []
            })
        else:
            citation = citation_from_evidence(combined, "SEBI")
            entity_type = "mutual_fund" if "mutual fund" in target_text else "broker"
            return json.dumps({
                "route": "assign_to_entity",
                "regulator": "SEBI",
                "entity_type": entity_type,
                "timeline": None,
                "basis": "This securities-market complaint should be reviewed under the cited SEBI guidance [c1]." if citation else "No SEBI passage was retrieved for verification.",
                "citations": [citation] if citation else []
            })

    # --- Verifier Claim Check ---
    if "verify" in step:
        return json.dumps({
            "decision": "accept",
            "passed": True,
            "unsupported_claims": [],
            "suggested_strategy": None
        })

    return "OK"


@app.post("/v1/chat", response_model=ChatResponse)
async def chat_completion(request: ChatRequest):
    if STUB_DELAY_MS > 0:
        await asyncio.sleep(STUB_DELAY_MS / 1000.0)

    reply_content = generate_stub_reply(request)

    prompt_tokens = max(10, sum(len(m.content) for m in request.messages) // 4)
    completion_tokens = max(5, len(reply_content) // 4)

    return ChatResponse(
        id=f"stub-{uuid.uuid4().hex[:12]}",
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=reply_content),
                finish_reason="stop"
            )
        ],
        usage=ChatUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=0.0
        ),
        model=request.model or "llm-stub",
        degraded=True
    )

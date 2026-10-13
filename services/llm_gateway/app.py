import asyncio
import os
import time
import uuid
import logging
from typing import List, Optional
from fastapi import FastAPI
from pydantic import BaseModel
import httpx

from services.llm_gateway.config import config
from services.llm_gateway.accounting import calculate_cost
from services.llm_gateway.breaker import CircuitBreaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("llm_gateway")

app = FastAPI(title="ORCAS LLM Gateway", version="1.0.0")
breaker = CircuitBreaker()

try:
    import litellm
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    logger.warning("litellm not installed; llm_gateway operating in fallback/proxy mode.")


class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
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
    degraded: bool = False


@app.get("/health")
async def health():
    cb_state, failures = breaker.get_state()
    return {
        "status": "ok",
        "provider": config.LLM_PROVIDER,
        "primary_model": config.LLM_MODEL,
        "circuit_breaker": cb_state,
        "failure_count": failures,
        "stub_mode": config.ORCAS_STUB_MODE
    }


async def call_stub(request: ChatRequest) -> ChatResponse:
    """Forward request to stub service or generate canned fallback."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{config.STUB_SERVICE_URL}/v1/chat", json=request.model_dump())
            if resp.status_code == 200:
                data = resp.json()
                return ChatResponse(**data)
    except Exception as exc:
        logger.warning(f"Stub service unavailable at {config.STUB_SERVICE_URL}: {exc}. Using inline fallback.")

    prompt_len = sum(len(m.content) for m in request.messages)
    content = "ORCAS Gateway Fallback: Verified routing analysis completed via fallback pipeline."
    prompt_tokens = max(10, prompt_len // 4)
    completion_tokens = max(5, len(content) // 4)
    
    return ChatResponse(
        id=f"fallback-{uuid.uuid4().hex[:12]}",
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop"
            )
        ],
        usage=ChatUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=0.0
        ),
        model=request.model or "gateway-fallback",
        degraded=True
    )


@app.post("/v1/chat", response_model=ChatResponse)
async def chat_completion(request: ChatRequest):
    if config.ORCAS_STUB_MODE or not config.LLM_API_KEY:
        logger.info(f"Routing to stub (stub_mode={config.ORCAS_STUB_MODE}, has_key={bool(config.LLM_API_KEY)})")
        return await call_stub(request)

    if not breaker.can_execute():
        logger.warning("Circuit breaker OPEN. Routing to fallback stub.")
        res = await call_stub(request)
        res.degraded = True
        return res

    target_model = request.model or config.LLM_MODEL
    messages_payload = [{"role": m.role, "content": m.content} for m in request.messages]

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            if not LITELLM_AVAILABLE:
                raise RuntimeError("LiteLLM not installed")

            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=target_model,
                    messages=messages_payload,
                    temperature=request.temperature if request.temperature is not None else config.LLM_TEMPERATURE,
                    max_tokens=request.max_tokens or 2048,
                    api_key=config.LLM_API_KEY
                ),
                timeout=config.LLM_TIMEOUT_SECONDS
            )

            breaker.record_success()

            reply_text = response.choices[0].message.content or ""
            p_tokens = getattr(response.usage, "prompt_tokens", len(str(messages_payload)) // 4)
            c_tokens = getattr(response.usage, "completion_tokens", len(reply_text) // 4)
            cost = calculate_cost(target_model, p_tokens, c_tokens)

            return ChatResponse(
                id=getattr(response, "id", f"call-{uuid.uuid4().hex[:12]}"),
                choices=[
                    ChatChoice(
                        index=0,
                        message=ChatMessage(role="assistant", content=reply_text),
                        finish_reason="stop"
                    )
                ],
                usage=ChatUsage(
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    total_tokens=p_tokens + c_tokens,
                    cost_usd=cost
                ),
                model=target_model,
                degraded=False
            )

        except Exception as exc:
            logger.warning(f"LLM call attempt {attempt + 1}/{max_retries + 1} failed: {exc}")
            if attempt < max_retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
            else:
                breaker.record_failure()

    # Fallback model
    if config.LLM_FALLBACK_MODEL and config.LLM_FALLBACK_MODEL != target_model:
        logger.info(f"Attempting fallback model: {config.LLM_FALLBACK_MODEL}")
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=config.LLM_FALLBACK_MODEL,
                    messages=messages_payload,
                    temperature=0.0,
                    max_tokens=request.max_tokens or 2048,
                    api_key=config.LLM_API_KEY
                ),
                timeout=config.LLM_TIMEOUT_SECONDS
            )
            reply_text = response.choices[0].message.content or ""
            p_tokens = getattr(response.usage, "prompt_tokens", len(str(messages_payload)) // 4)
            c_tokens = getattr(response.usage, "completion_tokens", len(reply_text) // 4)
            cost = calculate_cost(config.LLM_FALLBACK_MODEL, p_tokens, c_tokens)

            return ChatResponse(
                id=getattr(response, "id", f"call-{uuid.uuid4().hex[:12]}"),
                choices=[
                    ChatChoice(
                        index=0,
                        message=ChatMessage(role="assistant", content=reply_text),
                        finish_reason="stop"
                    )
                ],
                usage=ChatUsage(
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    total_tokens=p_tokens + c_tokens,
                    cost_usd=cost
                ),
                model=config.LLM_FALLBACK_MODEL,
                degraded=True
            )
        except Exception as exc:
            logger.error(f"Fallback model failed: {exc}")

    degraded_res = await call_stub(request)
    degraded_res.degraded = True
    return degraded_res

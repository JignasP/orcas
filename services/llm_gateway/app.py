"""
ORCAS LLM Gateway — FastAPI service (M2, M10 updates).

Key changes vs previous version
---------------------------------
* Stub is served **only** when ``ORCAS_STUB_MODE=true``.  An empty
  ``LLM_API_KEY`` is valid (Ollama / keyless providers).
* ``api_base`` is passed to ``litellm.acompletion`` for Ollama and custom
  endpoints.
* ``response_format={"type": "json_object"}`` is requested when supported.
* Pricing uses env-driven ``calculate_cost(prompt_tokens, completion_tokens,
  is_fallback=…)``; no model name in the code.
* ``LLM_FORCE_FAIL=1`` makes all primary calls raise immediately — used by
  Demo #8 to trip the circuit breaker.
* When all retries fail and no fallback model is configured, the gateway
  returns HTTP 503 instead of the stub answer.
* ``/health`` reports a configuration error when ``LLM_MODEL`` is not set.
"""

import asyncio
import random
import os
import time
import uuid
import logging
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

from services.llm_gateway.config import config
from services.llm_gateway.accounting import calculate_cost
from services.llm_gateway.breaker import CircuitBreaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("llm_gateway")

app = FastAPI(title="ORCAS LLM Gateway", version="2.0.0")
breaker = CircuitBreaker()

# Prometheus metrics (Requirement A6 — per-agent metrics)
try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
    from starlette.responses import Response

    LLM_REQUEST_COUNTER = Counter(
        "orcas_llm_requests_total",
        "Total LLM requests",
        ["agent", "model", "status"],
    )
    LLM_LATENCY_HISTOGRAM = Histogram(
        "orcas_llm_latency_seconds",
        "LLM call latency",
        ["agent", "model"],
    )
    LLM_TOKEN_COUNTER = Counter(
        "orcas_llm_tokens_total",
        "Total tokens consumed",
        ["agent", "model", "direction"],
    )
    # Counts closed→open transitions (trips), not rejected requests.
    CIRCUIT_BREAKER_TRIPS = Counter(
        "orcas_circuit_breaker_trips_total",
        "Times the circuit breaker transitioned from closed to open",
    )
    # Separate counter for requests rejected while breaker is open.
    CIRCUIT_BREAKER_REJECTED = Counter(
        "orcas_circuit_breaker_rejected_total",
        "Requests rejected because the circuit breaker was open",
    )
    PROM_AVAILABLE = True

    @app.get("/metrics")
    async def metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

except ImportError:
    PROM_AVAILABLE = False
    logger.warning("prometheus_client not installed; /metrics endpoint disabled.")

try:
    import litellm
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    logger.warning("litellm not installed; gateway cannot serve live LLM requests.")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    cb_state, failures = breaker.get_state()
    health_status = "ok"
    config_error = None

    if not config.ORCAS_STUB_MODE and not config.is_configured:
        health_status = "configuration_error"
        config_error = f"Missing required env vars: {config.missing_config}"

    return {
        "status": health_status,
        "primary_model": config.LLM_MODEL or "(not set)",
        "fallback_model": config.LLM_FALLBACK_MODEL or "(not set)",
        "circuit_breaker": cb_state,
        "failure_count": failures,
        "stub_mode": config.ORCAS_STUB_MODE,
        "force_fail": config.LLM_FORCE_FAIL,
        **({"config_error": config_error} if config_error else {}),
    }


# ---------------------------------------------------------------------------
# Stub forwarding
# ---------------------------------------------------------------------------

async def call_stub(request: ChatRequest) -> ChatResponse:
    """Forward request to the stub service (ORCAS_STUB_MODE=true only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{config.STUB_SERVICE_URL}/v1/chat", json=request.model_dump()
            )
            if resp.status_code == 200:
                data = resp.json()
                # Stub is the intended path in stub mode → degraded=false
                result = ChatResponse(**data)
                result.degraded = False
                return result
    except Exception as exc:
        logger.warning("Stub service unavailable at %s: %s", config.STUB_SERVICE_URL, exc)

    raise HTTPException(status_code=503, detail="Stub service unreachable")


# ---------------------------------------------------------------------------
# LiteLLM call helper
# ---------------------------------------------------------------------------

async def _litellm_call(
    model: str,
    messages_payload: list,
    request: ChatRequest,
    api_key: str,
    api_base: str,
    is_fallback: bool = False,
) -> ChatResponse:
    """Single LiteLLM call with timeout; returns ChatResponse."""
    if not LITELLM_AVAILABLE:
        raise RuntimeError("LiteLLM not installed")

    kwargs = dict(
        model=model,
        messages=messages_payload,
        temperature=request.temperature if request.temperature is not None else config.LLM_TEMPERATURE,
        max_tokens=request.max_tokens or 2048,
    )
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base

    # Request structured JSON output where the provider supports it
    kwargs["response_format"] = {"type": "json_object"}

    response = await asyncio.wait_for(
        litellm.acompletion(**kwargs),
        timeout=config.LLM_TIMEOUT_SECONDS,
    )

    reply_text = response.choices[0].message.content or ""
    p_tokens = getattr(response.usage, "prompt_tokens", len(str(messages_payload)) // 4)
    c_tokens = getattr(response.usage, "completion_tokens", len(reply_text) // 4)
    cost = calculate_cost(p_tokens, c_tokens, is_fallback=is_fallback)

    return ChatResponse(
        id=getattr(response, "id", f"call-{uuid.uuid4().hex[:12]}"),
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=reply_text),
                finish_reason="stop",
            )
        ],
        usage=ChatUsage(
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
            total_tokens=p_tokens + c_tokens,
            cost_usd=cost,
        ),
        model=model,
        degraded=is_fallback,
    )


# ---------------------------------------------------------------------------
# Main chat endpoint
# ---------------------------------------------------------------------------

@app.post("/v1/chat", response_model=ChatResponse)
async def chat_completion(request: ChatRequest):
    agent_label = request.agent or "unknown"
    t0 = time.time()

    # --- Stub mode (explicit, never a silent fallback) ---
    if config.ORCAS_STUB_MODE:
        logger.info("ORCAS_STUB_MODE=true; routing to stub service.")
        return await call_stub(request)

    # --- Configuration guard ---
    if not config.is_configured:
        raise HTTPException(
            status_code=503,
            detail=f"Gateway not configured: {config.missing_config}",
        )

    # --- Circuit breaker ---
    if not breaker.can_execute():
        if PROM_AVAILABLE:
            CIRCUIT_BREAKER_REJECTED.inc()
            LLM_REQUEST_COUNTER.labels(agent=agent_label, model="breaker_open", status="rejected").inc()
        logger.warning("Circuit breaker OPEN — trying fallback model.")
        # Try fallback rather than returning the stub
        if config.LLM_FALLBACK_MODEL:
            try:
                res = await _litellm_call(
                    model=config.LLM_FALLBACK_MODEL,
                    messages_payload=[{"role": m.role, "content": m.content} for m in request.messages],
                    request=request,
                    api_key=config.LLM_FALLBACK_API_KEY,
                    api_base=config.LLM_FALLBACK_API_BASE,
                    is_fallback=True,
                )
                return res
            except Exception as fb_exc:
                logger.error("Fallback model also failed while breaker open: %s", fb_exc)
        raise HTTPException(status_code=503, detail="Circuit breaker open and no fallback model configured.")

    target_model = request.model or config.LLM_MODEL
    messages_payload = [{"role": m.role, "content": m.content} for m in request.messages]

    max_retries = 2
    last_exc: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        # --- Force-fail switch (Demo #8) ---
        if config.LLM_FORCE_FAIL:
            last_exc = RuntimeError("LLM_FORCE_FAIL=1: primary call intentionally failed.")
            logger.warning("LLM_FORCE_FAIL active; skipping real call (attempt %d).", attempt + 1)
            if attempt < max_retries:
                base_delay = 0.1 * (2 ** attempt)
                await asyncio.sleep(base_delay)
                continue
            else:
                breaker.record_failure()
                if PROM_AVAILABLE:
                    CIRCUIT_BREAKER_TRIPS.inc()
                    LLM_REQUEST_COUNTER.labels(agent=agent_label, model=target_model, status="force_fail").inc()
                break

        try:
            result = await _litellm_call(
                model=target_model,
                messages_payload=messages_payload,
                request=request,
                api_key=config.LLM_API_KEY,
                api_base=config.LLM_API_BASE,
                is_fallback=False,
            )
            breaker.record_success()
            if PROM_AVAILABLE:
                elapsed = time.time() - t0
                LLM_REQUEST_COUNTER.labels(agent=agent_label, model=target_model, status="ok").inc()
                LLM_LATENCY_HISTOGRAM.labels(agent=agent_label, model=target_model).observe(elapsed)
                LLM_TOKEN_COUNTER.labels(agent=agent_label, model=target_model, direction="prompt").inc(
                    result.usage.prompt_tokens
                )
                LLM_TOKEN_COUNTER.labels(agent=agent_label, model=target_model, direction="completion").inc(
                    result.usage.completion_tokens
                )
            return result

        except Exception as exc:
            last_exc = exc
            logger.warning("LLM call attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)
            if attempt < max_retries:
                base_delay = 0.5 * (2 ** attempt)
                jitter = base_delay * random.uniform(-0.25, 0.25)
                await asyncio.sleep(base_delay + jitter)
            else:
                breaker.record_failure()
                if PROM_AVAILABLE:
                    CIRCUIT_BREAKER_TRIPS.inc()
                    LLM_REQUEST_COUNTER.labels(agent=agent_label, model=target_model, status="error").inc()

    # --- Fallback model ---
    if config.LLM_FALLBACK_MODEL:
        logger.info("Primary exhausted; trying fallback model: %s", config.LLM_FALLBACK_MODEL)
        try:
            res = await _litellm_call(
                model=config.LLM_FALLBACK_MODEL,
                messages_payload=messages_payload,
                request=request,
                api_key=config.LLM_FALLBACK_API_KEY,
                api_base=config.LLM_FALLBACK_API_BASE,
                is_fallback=True,
            )
            return res
        except Exception as fb_exc:
            logger.error("Fallback model failed: %s", fb_exc)

    # Neither primary nor fallback succeeded — return 503, never stub
    raise HTTPException(
        status_code=503,
        detail=f"All LLM retries and fallback exhausted. Last error: {last_exc}",
    )

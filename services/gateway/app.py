"""FastAPI ingestion boundary for synthetic regulatory complaints."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from libs.orcas_common.logging import configure_logging, correlation_id
from libs.orcas_common.runstore import PostgresRunStore
from services.gateway.input_guardrails import check_free_text
from services.gateway.models import (
    Complaint,
    RunStatus,
    SubmitResponse,
    cross_field_errors,
)
from services.gateway.queue import CeleryDispatcher

logger = logging.getLogger(__name__)


def _validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    return [{
        "field": ".".join(str(part) for part in item["loc"]) or "body",
        "message": item["msg"],
        "type": item["type"],
    } for item in error.errors()]


def create_app(store=None, dispatcher=None) -> FastAPI:
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    store = store or PostgresRunStore()
    dispatcher = dispatcher or CeleryDispatcher()
    app = FastAPI(title="ORCAS Gateway", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080"
        ).split(",") if origin.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Correlation-ID"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        candidate = request.headers.get("X-Correlation-ID", "")
        request_id_value = candidate if 0 < len(candidate) <= 128 and candidate.isprintable() else str(uuid.uuid4())
        token = correlation_id.set(request_id_value)
        try:
            response = await call_next(request)
            response.headers.setdefault("X-Correlation-ID", request_id_value)
            return response
        finally:
            correlation_id.reset(token)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            store.ping()
            dispatcher.ping()
        except Exception:
            logger.exception("gateway dependencies are unavailable")
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return {"status": "ok"}

    @app.post(
        "/v1/complaints", status_code=202, response_model=SubmitResponse,
        openapi_extra={"requestBody": {"required": True, "content": {
            "application/json": {"schema": Complaint.model_json_schema()}
        }}},
    )
    async def submit(request: Request):
        raw = await request.body()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            errors = [{"field": "body", "message": "invalid JSON", "type": "json_invalid"}]
            quarantine_id = store.quarantine(raw.decode("utf-8", errors="replace"), "validation", errors)
            return JSONResponse(status_code=422, content={"detail": errors, "quarantine_id": quarantine_id})

        try:
            complaint = Complaint.model_validate_json(raw, strict=True)
            errors = cross_field_errors(complaint)
        except ValidationError as error:
            errors = _validation_errors(error)
            complaint = None
        if errors:
            quarantine_id = store.quarantine(data, "validation", errors)
            return JSONResponse(status_code=422, content={"detail": errors, "quarantine_id": quarantine_id})

        errors = check_free_text({"text": complaint.text, "entity_name_hint": complaint.entity_name_hint})
        if errors:
            reason = errors[0]["type"]
            quarantine_id = store.quarantine(data, reason, errors)
            return JSONResponse(status_code=422, content={"detail": errors, "quarantine_id": quarantine_id})

        run_id = str(uuid.uuid4())
        correlation_id.set(run_id)
        store.create_run(run_id, complaint.model_dump(mode="json", exclude_none=True))
        try:
            dispatcher.send(run_id)
        except Exception:
            logger.exception("unable to enqueue run")
            store.fail(run_id, "queue unavailable")
            raise HTTPException(status_code=503, detail="queue unavailable")
        logger.info("complaint accepted")
        return JSONResponse(
            status_code=202,
            content={"run_id": run_id, "status_url": f"/v1/runs/{run_id}"},
            headers={"X-Correlation-ID": run_id},
        )

    @app.get("/v1/runs/{run_id}", response_model=RunStatus)
    def get_run(run_id: uuid.UUID):
        record = store.get_run(str(run_id))
        if record is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {key: record.get(key) for key in (
            "run_id", "status", "submitted_at", "started_at", "finished_at", "result"
        )}

    return app


app = create_app()

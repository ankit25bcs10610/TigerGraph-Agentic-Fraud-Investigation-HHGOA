"""HTTP boundary for the analyst workbench."""
from __future__ import annotations

import os
import time
from uuid import uuid4
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class CaseInputProvider(Protocol):
    def list(self) -> list[dict[str, Any]]: ...
    def get(self, case_id: str) -> dict[str, Any]: ...


class Workflow(Protocol):
    def start_investigation(self, case_input: dict[str, Any]) -> dict[str, Any]: ...
    def resume_with_approval(self, case_id: str, decision: dict[str, Any]) -> dict[str, Any]: ...
    def resume_with_evidence(self, case_id: str, evidence: dict[str, Any]) -> dict[str, Any]: ...
    def get_investigation_state(self, case_id: str) -> Any: ...


class StartRequest(BaseModel):
    case_id: str = Field(min_length=1)


class ApprovalRequest(BaseModel):
    action: str = Field(min_length=1)
    approved: bool


class EvidenceRequest(BaseModel):
    evidence: dict[str, Any]


def create_app(workflow: Workflow | None = None, case_provider: CaseInputProvider | None = None) -> FastAPI:
    app = FastAPI(title="Fraud Investigation API", version="1.0.0")
    origins = [item.strip() for item in os.getenv("FRONTEND_ORIGINS", "").split(",") if item.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        limit = int(os.getenv("APP_RATE_LIMIT_PER_MINUTE", "0") or "0")
        if limit > 0:
            now = time.monotonic()
            bucket = getattr(app.state, "rate_limit_bucket", {})
            client = request.client.host if request.client else "unknown"
            recent = [stamp for stamp in bucket.get(client, []) if now - stamp < 60]
            if len(recent) >= limit:
                response = JSONResponse({"detail": "Rate limit exceeded", "request_id": request_id}, status_code=429)
                response.headers["retry-after"] = "60"
                response.headers["x-request-id"] = request_id
                return response
            bucket[client] = [*recent, now]
            app.state.rate_limit_bucket = bucket
        response: Response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    def authorize(request: Request, approval: bool = False) -> None:
        expected = os.getenv("APP_API_KEY")
        if expected and request.headers.get("x-api-key") != expected:
            raise HTTPException(401, "Invalid or missing API key")
        required_role = os.getenv("APP_APPROVER_ROLE")
        if approval and required_role and request.headers.get("x-user-role") != required_role:
            raise HTTPException(403, "Approval role required")

    def dependencies() -> tuple[Workflow, CaseInputProvider]:
        if workflow is None or case_provider is None:
            raise HTTPException(503, "Investigation workflow is not configured. Set CASE_PACK_PATH or inject production adapters.")
        return workflow, case_provider

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "workflow_configured": workflow is not None and case_provider is not None, "auth_enabled": bool(os.getenv("APP_API_KEY"))}

    @app.get("/ready")
    def ready() -> dict[str, Any]:
        configured = workflow is not None and case_provider is not None
        if not configured:
            raise HTTPException(503, "Investigation workflow is not configured")
        return {"status": "ready", "workflow_configured": True}

    @app.get("/cases")
    def cases(request: Request) -> list[dict[str, Any]]:
        authorize(request)
        return dependencies()[1].list()

    @app.post("/investigations/start")
    def start(request: Request, payload: StartRequest):
        authorize(request)
        service, provider = dependencies()
        try:
            return service.start_investigation(provider.get(payload.case_id))
        except KeyError:
            raise HTTPException(404, "Case was not found")

    @app.get("/investigations/{case_id}")
    def state(request: Request, case_id: str):
        authorize(request)
        try:
            return dependencies()[0].get_investigation_state(case_id)
        except KeyError:
            raise HTTPException(404, "Investigation was not found")

    @app.post("/investigations/{case_id}/approval")
    def approval(request: Request, case_id: str, payload: ApprovalRequest):
        authorize(request, approval=True)
        try:
            return dependencies()[0].resume_with_approval(case_id, {"action": payload.action, "approved": payload.approved})
        except KeyError:
            raise HTTPException(404, "Investigation was not found")

    @app.post("/investigations/{case_id}/evidence")
    def evidence(request: Request, case_id: str, payload: EvidenceRequest):
        authorize(request)
        try:
            return dependencies()[0].resume_with_evidence(case_id, payload.evidence)
        except KeyError:
            raise HTTPException(404, "Investigation was not found")

    return app


def configured_app() -> FastAPI:
    if not os.getenv("CASE_PACK_PATH"):
        return create_app()
    from backend.demo_runtime import build_reference_runtime
    provider, workflow = build_reference_runtime(os.environ["CASE_PACK_PATH"])
    return create_app(workflow=workflow, case_provider=provider)


app = configured_app()

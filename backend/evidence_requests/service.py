"""Fixture-first deterministic simulation and policy-neutral evidence effects."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from backend.evidence_requests.models import EvidenceRequest, EvidenceResponse, RequestStatus, RequestType, ResponseSource
from backend.policy.rules import CustomerResponse

def deterministic_request_id(case_id: str, request_type: RequestType, ordinal: int) -> str:
    digest = hashlib.sha256(f"{case_id}\x1f{request_type.value}\x1f{ordinal}".encode()).hexdigest()
    return f"er-{digest}"

@dataclass
class EvidenceRequestService:
    fixtures_dir: Path | None = None
    default_results: Mapping[str, tuple[str, ...]] | None = None
    validator: Callable[[str], bool] | None = None
    def create(self, *, case_id: str, request_type: RequestType, question: str, reason: str, ordinal: int) -> EvidenceRequest:
        return EvidenceRequest(request_id=deterministic_request_id(case_id, request_type, ordinal), case_id=case_id, type=request_type, question=question, reason=reason)
    def simulate(self, request: EvidenceRequest) -> EvidenceResponse:
        fixture = self._fixture(request)
        if fixture is None: fixture = self._default(request)
        details = dict(fixture.get("details", {})); result = str(fixture.get("result", "unknown"))
        if request.type is RequestType.ANALYST_INFO:
            details = {"finding": details.get("finding", "No analyst finding supplied by the simulator."), "supporting_entity_ids": details.get("supporting_entity_ids", []), "confidence": details.get("confidence", 0.0), "notes": details.get("notes", "Simulation default; not factual analyst evidence.")}
            self._validate_ids(details["supporting_entity_ids"])
        return EvidenceResponse(request_id=request.request_id, case_id=request.case_id, type=request.type, result=result, details=details, source=ResponseSource.SIMULATION, simulated=True, assumption=str(fixture.get("assumption") or "Simulated development response; it is not customer, analyst, or benchmark evidence."))
    def _fixture(self, request: EvidenceRequest) -> Mapping[str, Any] | None:
        path = self.fixtures_dir / f"{request.case_id}.json" if self.fixtures_dir else None
        if not path or not path.is_file(): return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("responses", []):
            if item.get("type") == request.type.value: return item
        return None
    def _default(self, request: EvidenceRequest) -> Mapping[str, Any]:
        choices = tuple((self.default_results or {}).get(request.type.value, ()))
        if choices:
            index = int(hashlib.sha256(request.request_id.encode()).hexdigest(), 16) % len(choices)
            return {"result": choices[index]}
        neutral = "unknown" if request.type is not RequestType.ANALYST_INFO else "unknown"
        return {"result": neutral}
    def _validate_ids(self, ids: list[str]) -> None:
        if self.validator and any(not self.validator(str(value)) for value in ids): raise ValueError("analyst evidence referenced an unknown graph ID")

def policy_effects(response: EvidenceResponse) -> dict[str, Any]:
    """Map evidence to existing policy inputs; does not choose actions."""
    if response.type is RequestType.CUSTOMER_VALIDATION:
        mapping = {"confirmed": CustomerResponse.CONFIRMED, "denied": CustomerResponse.DENIED}
        return {"customer_response": mapping.get(response.result), "no_reply_within_24h": response.result == "no_reply"}
    if response.type is RequestType.STEP_UP_AUTH: return {"step_up_authentication_evidence": 1.0 if response.result == "failed" else 0.0}
    return {"conflicting_evidence": bool(response.details.get("finding")) and float(response.details.get("confidence", 0.0)) > 0}

"""Thin LangGraph nodes: adapters own graph, retrieval, and fraud logic."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from langgraph.types import interrupt
from backend.agent.state import InvestigationState
from backend.evidence_requests.models import RequestType
from backend.evidence_requests.service import EvidenceRequestService

class InvestigationAdapters(Protocol):
    def validate(self, state: InvestigationState) -> None: ...
    def graph_evidence(self, state: InvestigationState) -> dict[str, Any]: ...
    def graphrag(self, state: InvestigationState) -> dict[str, Any]: ...
    def patterns(self, state: InvestigationState) -> dict[str, Any]: ...
    def grade(self, state: InvestigationState) -> dict[str, Any]: ...
    def probability(self, state: InvestigationState) -> dict[str, Any]: ...
    def stopping(self, state: InvestigationState) -> dict[str, Any]: ...
    def evidence_request(self, state: InvestigationState) -> dict[str, Any]: ...
    def policy(self, state: InvestigationState) -> dict[str, Any]: ...
    def persist(self, state: InvestigationState) -> dict[str, Any]: ...

def _audit(state: InvestigationState, result: dict[str, Any]) -> dict[str, Any]:
    return {**result, "tool_calls": [*state.get("tool_calls", []), *result.pop("tool_calls", [])]}

@dataclass
class InvestigationNodes:
    adapters: InvestigationAdapters
    evidence_service: EvidenceRequestService | None = None
    def load_case(self, state: InvestigationState) -> dict[str, Any]: return {"status": "started", "errors": state.get("errors", [])}
    def validate_case_entities(self, state: InvestigationState) -> dict[str, Any]:
        self.adapters.validate(state); return {}
    def collect_graph_evidence(self, state: InvestigationState) -> dict[str, Any]: return _audit(state, self.adapters.graph_evidence(state))
    def retrieve_graphrag_context(self, state: InvestigationState) -> dict[str, Any]: return _audit(state, self.adapters.graphrag(state))
    def detect_patterns(self, state: InvestigationState) -> dict[str, Any]: return self.adapters.patterns(state)
    def grade_evidence(self, state: InvestigationState) -> dict[str, Any]: return self.adapters.grade(state)
    def calculate_fraud_probability(self, state: InvestigationState) -> dict[str, Any]: return self.adapters.probability(state)
    def evaluate_stopping_criteria(self, state: InvestigationState) -> dict[str, Any]: return self.adapters.stopping(state)
    def plan_evidence_request(self, state: InvestigationState) -> dict[str, Any]:
        planned = self.adapters.evidence_request(state)
        if self.evidence_service is None:
            return {"evidence_requests": [*state.get("evidence_requests", []), planned], "status": "awaiting_evidence"}
        request = self.evidence_service.create(case_id=state["case_id"], request_type=RequestType(planned["type"]),
            question=planned["question"], reason=planned["reason"], ordinal=len(state.get("evidence_requests", [])))
        update = {"evidence_requests": [*state.get("evidence_requests", []), request.model_dump(mode="json")], "status": "awaiting_evidence"}
        if state.get("simulation_mode"):
            response = self.evidence_service.simulate(request)
            update.update({"evidence_responses": [*state.get("evidence_responses", []), response.model_dump(mode="json")], "auto_resume_evidence": True})
        return update
    def await_evidence(self, state: InvestigationState) -> dict[str, Any]:
        response = interrupt({"kind": "evidence", "case_id": state["case_id"], "requests": state.get("evidence_requests", [])})
        return {"evidence_responses": [*state.get("evidence_responses", []), response]}
    def apply_evidence_response(self, state: InvestigationState) -> dict[str, Any]: return {"status": "investigating"}
    def apply_policy(self, state: InvestigationState) -> dict[str, Any]:
        result = self.adapters.policy(state)
        actions = result.get("actions", result.get("final_actions", []))
        if not state.get("evidence_responses"):
            return {**result, "initial_actions": actions, "final_actions": actions, "what_changed": "nothing"}
        initial = state.get("initial_actions", [])
        changed = "Evidence was received and the deterministic policy was re-evaluated." if initial != actions else "nothing"
        return {**result, "final_actions": actions, "what_changed": changed}
    def route_approvals(self, state: InvestigationState) -> dict[str, Any]:
        pending = [item for item in state.get("approval_requests", []) if item.get("route") in {"L1", "L2"} and item.get("approval_status") == "pending"]
        if not pending: return {"status": "approved"}
        response = interrupt({"kind": "approval", "case_id": state["case_id"], "requests": pending})
        return {"approval_results": [*state.get("approval_results", []), response], "status": "approved"}
    def persist_case(self, state: InvestigationState) -> dict[str, Any]: return self.adapters.persist(state)
    def finish(self, state: InvestigationState) -> dict[str, Any]: return {"status": state.get("status", "completed")}

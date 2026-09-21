"""Public lifecycle operations; thread_id is always the runtime case_id."""
from __future__ import annotations
from typing import Any
from langgraph.types import Command

class InvestigationWorkflowService:
    def __init__(self, graph: Any) -> None: self._graph = graph
    @staticmethod
    def _config(case_id: str) -> dict[str, Any]: return {"configurable": {"thread_id": case_id}}
    def start_investigation(self, case_input: dict[str, Any]) -> dict[str, Any]:
        return self._graph.invoke(case_input, self._config(case_input["case_id"]))
    def resume_with_evidence(self, case_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        return self._graph.invoke(Command(resume=evidence), self._config(case_id))
    def resume_with_approval(self, case_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        return self._graph.invoke(Command(resume=decision), self._config(case_id))
    def get_investigation_state(self, case_id: str) -> Any:
        return self._graph.get_state(self._config(case_id))

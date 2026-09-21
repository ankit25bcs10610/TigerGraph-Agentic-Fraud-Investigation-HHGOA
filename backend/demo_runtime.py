"""Honest local reference runtime for UI/API demos.

It exposes benchmark triggers from case_pack.csv and never fabricates outcomes.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


class CasePackProvider:
    def __init__(self, path: str) -> None:
        with Path(path).open(newline="", encoding="utf-8") as handle:
            self._cases = {row["case_id"]: row for row in csv.DictReader(handle)}

    def list(self) -> list[dict[str, Any]]:
        return [{"case_id": row["case_id"], "trigger_type": row.get("trigger_type", ""), "opened_at": row.get("opened_at", "")} for row in self._cases.values()]

    def get(self, case_id: str) -> dict[str, Any]:
        if case_id not in self._cases:
            raise KeyError(case_id)
        return dict(self._cases[case_id])


class ReferenceWorkflow:
    """Trigger-only runtime for validating API/UI wiring."""
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}

    def start_investigation(self, case_input: dict[str, Any]) -> dict[str, Any]:
        case_id = case_input["case_id"]
        state = {"case_id": case_id, "trigger": case_input, "status": "awaiting_configured_workflow", "message": "Trigger loaded. Configure TigerGraph and the investigation workflow for grounded evidence."}
        self._states[case_id] = state
        return state

    def resume_with_approval(self, case_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        state = self._states[case_id]
        state["approval_events"] = [*state.get("approval_events", []), decision]
        state["message"] = "Approval event recorded by the reference runtime; no fraud decision was inferred."
        return state

    def resume_with_evidence(self, case_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        state = self._states[case_id]
        state["evidence_responses"] = [*state.get("evidence_responses", []), evidence]
        state["message"] = "Evidence response recorded as supplied; no fraud decision was inferred."
        return state

    def get_investigation_state(self, case_id: str) -> dict[str, Any]:
        return self._states[case_id]


def build_reference_runtime(path: str) -> tuple[CasePackProvider, ReferenceWorkflow]:
    return CasePackProvider(path), ReferenceWorkflow()

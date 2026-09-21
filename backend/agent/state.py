"""Typed durable state; all facts enter through runtime adapters."""
from __future__ import annotations
from typing import Any, TypedDict

class InvestigationState(TypedDict, total=False):
    case_id: str; opened_at: str; trigger_type: str; trigger_text: str
    customer_id: str; card_id: str; flagged_txn_id: str; risk_score: float | None
    graph_evidence: list[dict[str, Any]]; similar_prior_cases: list[dict[str, Any]]
    retrieved_policy: list[dict[str, Any]]; retrieved_patterns: list[dict[str, Any]]
    detected_patterns: list[dict[str, Any]]; pattern_confidences: dict[str, float]
    affected_txn_ids: list[str]; connected_card_ids: list[str]; connected_device_profiles: list[str]
    exposure_usd: float; fraud_probability: float; verdict: str
    evidence_requests: list[dict[str, Any]]; evidence_responses: list[dict[str, Any]]
    initial_actions: list[dict[str, Any]]; final_actions: list[dict[str, Any]]
    approval_requests: list[dict[str, Any]]; approval_results: list[dict[str, Any]]
    stop: bool; stop_reason: str; status: str; errors: list[str]
    tool_calls: list[dict[str, Any]]; started_at: str; completed_at: str; latency_s: float

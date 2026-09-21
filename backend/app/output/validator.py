from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from backend.app.output.models import CaseOutput
from backend.investigation.scoring_config import DEFAULT_STOPPING_CONFIG
from backend.models.answer import PolicyAction
from backend.policy.approvals import get_approval_route

class ReferenceResolver(Protocol):
    def exists(self, entity_type: str, entity_id: str) -> bool: ...
@dataclass(frozen=True)
class StopContext:
    independent_evidence_count: int = 0; verification_settled: bool = False; further_investigation_unlikely: bool = False; customer_disputed: bool = False
class OutputValidationError(ValueError): pass
class CatalogResolver:
    def __init__(self, catalog: dict[str, set[str]]) -> None: self.catalog = catalog
    def exists(self, entity_type: str, entity_id: str) -> bool: return entity_id in self.catalog.get(entity_type, set())
def _require(resolver: ReferenceResolver, kind: str, values: list[str]) -> None:
    missing = [value for value in values if not resolver.exists(kind, value)]
    if missing: raise OutputValidationError(f"unknown {kind} IDs: {missing}")
def validate_output(output: CaseOutput, resolver: ReferenceResolver, *, stop: StopContext = StopContext()) -> CaseOutput:
    case = output.case
    _require(resolver, "Transaction", case.affected_txn_ids)
    _require(resolver, "Card", case.connected_card_ids)
    _require(resolver, "DeviceProfile", case.connected_device_profiles)
    _require(resolver, "ClosedCase", case.similar_prior_cases)
    missing_subjects = [subject for subject in output.sar.subjects if not (resolver.exists("Customer", subject) or resolver.exists("Card", subject))]
    if missing_subjects: raise OutputValidationError(f"unknown SAR subject IDs: {missing_subjects}")
    if len(case.affected_txn_ids) != len(set(case.affected_txn_ids)): raise OutputValidationError("affected_txn_ids must not contain duplicates")
    for action in [*output.next_best_actions.initial, *output.next_best_actions.final]:
        if action.route is not get_approval_route(action.action, case.exposure_usd): raise OutputValidationError("action approval route does not match policy")
    if case.written_to_graph:
        if not case.graph_case_id: raise OutputValidationError("written cases require graph_case_id")
        _require(resolver, "InvestigationCase", [case.graph_case_id])
    elif case.graph_case_id: raise OutputValidationError("graph_case_id requires written_to_graph")
    must_create = case.fraud_probability >= 0.30 or bool(output.evidence_requests) or stop.customer_disputed
    if must_create and not case.written_to_graph: raise OutputValidationError("formal case must be written to graph")
    supported = stop.verification_settled or stop.further_investigation_unlikely or ((case.fraud_probability >= DEFAULT_STOPPING_CONFIG.strong_fraud_threshold or case.fraud_probability <= DEFAULT_STOPPING_CONFIG.strong_legitimate_threshold) and stop.independent_evidence_count >= DEFAULT_STOPPING_CONFIG.minimum_independent_evidence)
    if not supported: raise OutputValidationError("stop_reason is not supported by stopping criteria")
    return output

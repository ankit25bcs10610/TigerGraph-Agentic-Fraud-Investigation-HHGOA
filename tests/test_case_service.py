from dataclasses import dataclass, field
from typing import Any, Mapping

import pytest

from backend.cases.service import (
    InvestigationCaseRequest,
    InvestigationCaseService,
    decide_case_creation,
)
from backend.models.answer import (
    Action,
    ApprovalRoute,
    Case,
    CaseStatus,
    Evidence,
    EvidenceRequest,
    EvidenceRequestType,
    EvidenceSource,
    FraudPattern,
    PolicyAction,
    Verdict,
)


@dataclass
class FakeTigerGraphWriter:
    vertices: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    edges: list[tuple[str, str, str, str, str, dict[str, Any]]] = field(default_factory=list)

    def upsert_vertex(
        self, vertex_type: str, vertex_id: str, attributes: Mapping[str, Any]
    ) -> None:
        self.vertices.append((vertex_type, vertex_id, dict(attributes)))

    def upsert_edge(
        self,
        source_vertex_type: str,
        source_vertex_id: str,
        edge_type: str,
        target_vertex_type: str,
        target_vertex_id: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        self.edges.append((
            source_vertex_type,
            source_vertex_id,
            edge_type,
            target_vertex_type,
            target_vertex_id,
            dict(attributes or {}),
        ))


def case(*, probability: float = 0.40, status: CaseStatus = CaseStatus.CLOSED_FRAUD) -> Case:
    return Case(
        status=status,
        verdict=Verdict.FRAUD,
        fraud_probability=probability,
        pattern=FraudPattern.CARD_NOT_PRESENT_FRAUD,
        pattern_description="",
        affected_txn_ids=["T-1", "T-2", "T-2"],
        first_suspicious_txn_id="T-1",
        connected_card_ids=["CARD-2", "CARD-2"],
        connected_device_profiles=["DP-1", "DP-1"],
        exposure_usd=45.0,
        evidence=[
            Evidence(
                claim="Graph evidence supports the episode.",
                source=EvidenceSource.GRAPH,
                ref="card_history",
                entity_ids=["T-1"],
            )
        ],
        similar_prior_cases=["CC-1"],
        summary="Final investigation summary.",
        written_to_graph=False,
        graph_case_id="",
    )


def request(**overrides: Any) -> InvestigationCaseRequest:
    values: dict[str, Any] = {
        "investigation_case_id": "INV-001",
        "flagged_transaction_id": "T-1",
        "customer_id": "C-1",
        "card_id": "CARD-1",
        "opened_at": "2016-12-01 12:00:00",
        "case": case(),
        "recommended_actions": [
            Action(
                action=PolicyAction.CREATE_CASE,
                route=ApprovalRoute.AUTO,
                reason="R2: create a formal case",
            )
        ],
        "similar_prior_case_reasons": {"CC-1": "same online burst pattern"},
    }
    values.update(overrides)
    return InvestigationCaseRequest(**values)


def test_starting_a_run_or_create_case_recommendation_does_not_bypass_formal_gate() -> None:
    writer = FakeTigerGraphWriter()
    result = InvestigationCaseService(writer).persist(request(case=case(probability=0.29)))

    assert result.persisted is False
    assert result.investigation_case_id is None
    assert writer.vertices == []
    assert writer.edges == []


def test_probability_threshold_creates_vertex_final_outcome_and_all_relationships() -> None:
    writer = FakeTigerGraphWriter()
    result = InvestigationCaseService(writer).persist(request())

    assert result.persisted is True
    assert result.investigation_case_id == "INV-001"
    assert result.case.written_to_graph is True
    assert result.case.graph_case_id == "INV-001"
    assert result.memory_ready is True
    assert writer.vertices[0][0:2] == ("InvestigationCase", "INV-001")
    attributes = writer.vertices[0][2]
    assert attributes["status"] == "closed_fraud"
    assert attributes["verdict"] == "fraud"
    assert attributes["pattern"] == "card_not_present_fraud"
    assert attributes["fraud_probability"] == 0.40
    assert attributes["exposure_usd"] == 45.0
    edge_types = [edge[2] for edge in writer.edges]
    assert edge_types == [
        "FLAGGED_TRANSACTION",
        "FOR_CUSTOMER",
        "FOR_CARD",
        "AFFECTS",
        "CONNECTED_CARD",
        "CONNECTED_DEVICE",
        "SIMILAR_TO_CLOSED_CASE",
    ]
    similar_edge = writer.edges[-1]
    assert similar_edge[-1] == {"similarity_reason": "same online burst pattern"}


def test_evidence_request_creates_formal_case_below_probability_threshold() -> None:
    decision = decide_case_creation(
        fraud_probability=0.01,
        evidence_requests=[
            EvidenceRequest(
                type=EvidenceRequestType.CUSTOMER_VALIDATION,
                asked_after_step=1,
                assumed_response="pending",
            )
        ],
    )

    assert decision.should_create is True
    assert "additional evidence was requested" in decision.reasons


def test_customer_dispute_creates_formal_case_below_probability_threshold() -> None:
    writer = FakeTigerGraphWriter()
    result = InvestigationCaseService(writer).persist(
        request(case=case(probability=0.01), customer_disputed=True)
    )

    assert result.persisted is True
    assert "customer disputed a transaction" in result.creation_decision.reasons


def test_similarity_reasons_must_match_retrieved_prior_cases() -> None:
    with pytest.raises(ValueError, match="similar_prior_case_reasons"):
        request(similar_prior_case_reasons={})

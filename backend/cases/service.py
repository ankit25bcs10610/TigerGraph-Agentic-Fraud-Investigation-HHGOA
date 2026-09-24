"""Create and persist formal InvestigationCase vertices in TigerGraph.

An investigation run is not automatically a formal case.  The creation gate
is the README policy: probability >= 0.30, an additional evidence request, or
a customer dispute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from backend.models.answer import Action, Case, CaseStatus, EvidenceRequest


FORMAL_CASE_PROBABILITY_THRESHOLD = 0.30


class TigerGraphWriter(Protocol):
    """Minimal graph-writing contract used by the persistence service."""

    def upsert_vertex(
        self,
        vertex_type: str,
        vertex_id: str,
        attributes: Mapping[str, Any],
    ) -> None: ...

    def upsert_edge(
        self,
        source_vertex_type: str,
        source_vertex_id: str,
        edge_type: str,
        target_vertex_type: str,
        target_vertex_id: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> None: ...


class PyTigerGraphWriter:
    """Adapter for a pyTigerGraph-style connection object.

    The injected connection is expected to implement ``upsertVertex`` and
    ``upsertEdge``. Keeping it injected avoids embedding credentials or a
    database endpoint in the application layer.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def upsert_vertex(
        self,
        vertex_type: str,
        vertex_id: str,
        attributes: Mapping[str, Any],
    ) -> None:
        self._connection.upsertVertex(vertex_type, vertex_id, dict(attributes))

    def upsert_edge(
        self,
        source_vertex_type: str,
        source_vertex_id: str,
        edge_type: str,
        target_vertex_type: str,
        target_vertex_id: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        self._connection.upsertEdge(
            source_vertex_type,
            source_vertex_id,
            edge_type,
            target_vertex_type,
            target_vertex_id,
            dict(attributes or {}),
        )


@dataclass(frozen=True)
class CaseCreationDecision:
    should_create: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class InvestigationCaseRequest:
    """All data required to store an internal investigation case."""

    investigation_case_id: str
    flagged_transaction_id: str
    customer_id: str
    card_id: str
    opened_at: str
    case: Case
    recommended_actions: Sequence[Action] = ()
    evidence_requests: Sequence[EvidenceRequest] = ()
    customer_disputed: bool = False
    trigger_type: str = ""
    trigger_text: str = ""
    closed_at: str = ""
    stop_reason: str = ""
    sar_narrative: str = ""
    similar_prior_case_reasons: Mapping[str, str] = field(default_factory=dict)
    force_create: bool = False

    def __post_init__(self) -> None:
        for name in (
            "investigation_case_id",
            "flagged_transaction_id",
            "customer_id",
            "card_id",
            "opened_at",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if self.case.graph_case_id and self.case.graph_case_id != self.investigation_case_id:
            raise ValueError("case.graph_case_id must be empty or match investigation_case_id")
        expected_prior_cases = set(self.case.similar_prior_cases)
        supplied_prior_cases = set(self.similar_prior_case_reasons)
        if expected_prior_cases != supplied_prior_cases:
            raise ValueError(
                "similar_prior_case_reasons must contain exactly the retrieved similar_prior_cases"
            )
        if any(not str(reason).strip() for reason in self.similar_prior_case_reasons.values()):
            raise ValueError("each similar prior case requires a non-empty similarity reason")


@dataclass(frozen=True)
class PersistenceResult:
    persisted: bool
    creation_decision: CaseCreationDecision
    investigation_case_id: str | None
    case: Case
    memory_ready: bool


def decide_case_creation(
    *,
    fraud_probability: float,
    evidence_requests: Sequence[EvidenceRequest] = (),
    customer_disputed: bool = False,
) -> CaseCreationDecision:
    """Apply the README's formal-case threshold independently of policy actions."""
    try:
        probability = float(fraud_probability)
    except (TypeError, ValueError) as exc:
        raise ValueError("fraud_probability must be numeric") from exc
    if not 0.0 <= probability <= 1.0:
        raise ValueError("fraud_probability must be between 0 and 1")

    reasons: list[str] = []
    if probability >= FORMAL_CASE_PROBABILITY_THRESHOLD:
        reasons.append("fraud_probability >= 0.30")
    if evidence_requests:
        reasons.append("additional evidence was requested")
    if customer_disputed:
        reasons.append("customer disputed a transaction")
    return CaseCreationDecision(bool(reasons), tuple(reasons))


def _unique_nonempty(values: Sequence[str], *, exclude: str = "") -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(value.strip() for value in values if value and value.strip() != exclude)
    )


def _case_attributes(request: InvestigationCaseRequest) -> dict[str, Any]:
    case = request.case
    attributes: dict[str, Any] = {
        "customer_id": request.customer_id,
        "card_id": request.card_id,
        "opened_at": request.opened_at,
        "status": case.status.value,
        "verdict": case.verdict.value,
        "pattern": case.pattern.value,
        "fraud_probability": case.fraud_probability,
        "exposure_usd": case.exposure_usd,
        "trigger_type": request.trigger_type,
        "trigger_text": request.trigger_text,
        "evidence_summary": json.dumps(
            {
                "pattern_description": case.pattern_description,
                "summary": case.summary,
                "evidence": [item.model_dump(mode="json") for item in case.evidence],
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        "evidence_requests": json.dumps(
            [item.model_dump(mode="json") for item in request.evidence_requests],
            separators=(",", ":"),
            sort_keys=True,
        ),
        "recommended_actions": json.dumps(
            [item.model_dump(mode="json") for item in request.recommended_actions],
            separators=(",", ":"),
            sort_keys=True,
        ),
        "approval_route": json.dumps(
            sorted({item.route.value for item in request.recommended_actions}),
            separators=(",", ":"),
        ),
        "summary": case.summary,
        "stop_reason": request.stop_reason,
        "created_at": request.opened_at,
        "sar_narrative": request.sar_narrative,
    }
    if request.closed_at.strip():
        attributes["closed_at"] = request.closed_at
    return attributes


class InvestigationCaseService:
    """Persists formal cases and their graph memory relationships."""

    def __init__(self, writer: TigerGraphWriter) -> None:
        self._writer = writer

    def persist(self, request: InvestigationCaseRequest) -> PersistenceResult:
        decision = decide_case_creation(
            fraud_probability=request.case.fraud_probability,
            evidence_requests=request.evidence_requests,
            customer_disputed=request.customer_disputed,
        )
        if request.force_create and not decision.should_create:
            decision = CaseCreationDecision(True, (*decision.reasons, "explicit graph record requested"))
        if not decision.should_create:
            return PersistenceResult(
                persisted=False,
                creation_decision=decision,
                investigation_case_id=None,
                case=request.case,
                memory_ready=False,
            )

        case_id = request.investigation_case_id
        self._writer.upsert_vertex(
            "InvestigationCase", case_id, _case_attributes(request)
        )
        reset = getattr(self._writer, "reset_edges", None)
        if callable(reset):
            reset("InvestigationCase", case_id)
        edges: list[tuple[str, str, str, str, str, Mapping[str, Any] | None]] = [
            ("InvestigationCase", case_id, "FLAGGED_TXN", "Transaction", request.flagged_transaction_id, None),
            ("InvestigationCase", case_id, "ON_CUSTOMER", "Customer", request.customer_id, None),
            ("InvestigationCase", case_id, "ON_CARDS", "Card", request.card_id, None),
        ]
        for transaction_id in _unique_nonempty(
            request.case.affected_txn_ids, exclude=request.flagged_transaction_id,
        ):
            edges.append(("InvestigationCase", case_id, "AFFECTS", "Transaction", transaction_id, None))
        for connected_card_id in _unique_nonempty(
            request.case.connected_card_ids, exclude=request.card_id,
        ):
            edges.append(("InvestigationCase", case_id, "CONNECTED_CARD", "Card", connected_card_id, None))
        for device_profile_id in _unique_nonempty(request.case.connected_device_profiles):
            edges.append(("InvestigationCase", case_id, "CONNECTED_DEVICE", "DeviceProfile", device_profile_id, None))
        for prior_case_id in _unique_nonempty(request.case.similar_prior_cases):
            edges.append(("InvestigationCase", case_id, "SIMILAR_TO", "ClosedCase", prior_case_id,
                          {"similarity_reason": request.similar_prior_case_reasons[prior_case_id]}))
        batch_writer = getattr(self._writer, "upsert_edges", None)
        if callable(batch_writer):
            batch_writer(edges)
        else:
            for source_type, source_id, edge_type, target_type, target_id, attributes in edges:
                self._writer.upsert_edge(source_type, source_id, edge_type, target_type, target_id, attributes)

        persisted_case = request.case.model_copy(
            update={"written_to_graph": True, "graph_case_id": case_id}
        )
        return PersistenceResult(
            persisted=True,
            creation_decision=decision,
            investigation_case_id=case_id,
            case=persisted_case,
            memory_ready=persisted_case.status in {
                CaseStatus.CLOSED_FRAUD,
                CaseStatus.CLOSED_LEGITIMATE,
            },
        )

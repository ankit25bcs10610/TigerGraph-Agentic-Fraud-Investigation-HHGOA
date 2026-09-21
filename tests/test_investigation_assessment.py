from backend.investigation.evidence import GraphEvidence, graph_rows_to_evidence, to_answer_evidence
from backend.investigation.exposure import episode_exposure_usd, episode_transaction_ids
from backend.investigation.fraud_probability import (
    ScoringInputs,
    assess_fraud,
    deterministic_fraud_probability,
)
from backend.investigation.patterns import PatternResult
from backend.models.answer import EvidenceSource, FraudPattern


def test_graph_evidence_maps_to_answer_format() -> None:
    result = to_answer_evidence(
        [GraphEvidence("amount was 10.00", "transaction_context", ("TX-1",))]
    )

    assert result[0].claim == "amount was 10.00"
    assert result[0].source is EvidenceSource.GRAPH
    assert result[0].ref == "transaction_context"
    assert result[0].entity_ids == ["TX-1"]


def test_graph_rows_require_claim_and_entity_reference() -> None:
    result = graph_rows_to_evidence(
        [{"claim": "shared device", "transaction_id": "TX-1", "device_id": "DEV-1"}],
        query_ref="device_neighbors",
        entity_fields=("transaction_id", "device_id"),
    )

    assert result[0].entity_ids == ["TX-1", "DEV-1"]


def test_empty_grounding_is_rejected() -> None:
    try:
        to_answer_evidence([GraphEvidence("", "query", ("TX-1",))])
    except ValueError as exc:
        assert "claim" in str(exc)
    else:
        raise AssertionError("empty claims must be rejected")


def test_exposure_sums_absolute_dataset_amounts_only_for_episode_rows() -> None:
    rows = [
        {"TransactionID": "TX-1", "TransactionAmt": "-10.25"},
        {"TransactionID": "TX-2", "TransactionAmt": 4.75},
    ]

    assert episode_exposure_usd(rows) == 15.0
    assert episode_transaction_ids(rows) == ["TX-1", "TX-2"]


def test_probability_uses_evidence_weights_and_conflict() -> None:
    high = deterministic_fraud_probability(
        ScoringInputs(
            risk_score=0.99,
            pattern_strength=0.9,
            unusual_transaction_behavior=0.8,
            prior_confirmed_fraud_cases=1.0,
        )
    )
    conflicting = deterministic_fraud_probability(
        ScoringInputs(
            risk_score=0.99,
            pattern_strength=0.9,
            unusual_transaction_behavior=0.8,
            prior_confirmed_fraud_cases=1.0,
            conflicting_evidence=1.0,
        )
    )

    assert high > conflicting
    assert 0.0 <= conflicting <= 1.0


def test_risk_score_alone_does_not_create_high_probability() -> None:
    result = deterministic_fraud_probability(ScoringInputs(risk_score=1.0))

    assert result == 0.15


def test_assessment_returns_episode_fields_and_pattern_strength() -> None:
    result = assess_fraud(
        scoring=ScoringInputs(risk_score=0.7, unusual_transaction_behavior=0.5),
        episode_transactions=[
            {"TransactionID": "TX-1", "TransactionAmt": 12.50},
            {"TransactionID": "TX-2", "TransactionAmt": -2.50},
        ],
        evidence=[GraphEvidence("two transactions form the candidate episode", "card_window", ("TX-1", "TX-2"))],
        connected_card_ids=("CARD-2", "CARD-2"),
        connected_device_profiles=("DEV-1",),
        uncertainty_indicators=("identity row unavailable", ""),
        pattern_result=PatternResult(FraudPattern.CARD_TESTING, strength=0.95),
    )

    assert result.affected_transaction_ids == ["TX-1", "TX-2"]
    assert result.exposure_usd == 15.0
    assert result.connected_card_ids == ["CARD-2"]
    assert result.connected_device_profiles == ["DEV-1"]
    assert result.uncertainty_indicators == ["identity row unavailable"]
    assert result.fraud_probability > 0.0


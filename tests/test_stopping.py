from backend.investigation.stopping import (
    EvidenceDirection,
    IndependentEvidence,
    ReasonCode,
    VerificationResponse,
    evaluate_stopping,
)


def evidence(direction: EvidenceDirection, key: str, claim: str = "grounded claim") -> IndependentEvidence:
    return IndependentEvidence(claim=claim, direction=direction, independence_key=key)


def test_strong_fraud_stops_with_two_independent_sources() -> None:
    result = evaluate_stopping(
        fraud_probability=0.91,
        evidence=(
            evidence(EvidenceDirection.FRAUD, "graph-card-history"),
            evidence(EvidenceDirection.FRAUD, "graph-device-neighbors"),
        ),
    )

    assert result.should_stop is True
    assert result.independent_evidence_count == 2
    assert result.reason_code is ReasonCode.STRONG_FRAUD


def test_strong_legitimate_stops_with_two_independent_sources() -> None:
    result = evaluate_stopping(
        fraud_probability=0.08,
        evidence=(
            evidence(EvidenceDirection.LEGITIMATE, "customer-confirmation"),
            evidence(EvidenceDirection.LEGITIMATE, "recurring-history"),
        ),
    )

    assert result.should_stop is True
    assert result.independent_evidence_count == 2
    assert result.reason_code is ReasonCode.STRONG_LEGITIMATE


def test_duplicate_claims_from_one_source_do_not_count_as_independent() -> None:
    result = evaluate_stopping(
        fraud_probability=0.90,
        evidence=(
            evidence(EvidenceDirection.FRAUD, "same-query", "claim one"),
            evidence(EvidenceDirection.FRAUD, "same-query", "claim two"),
        ),
    )

    assert result.should_stop is False
    assert result.independent_evidence_count == 1
    assert result.reason_code is ReasonCode.INSUFFICIENT_EVIDENCE


def test_customer_verification_settles_question() -> None:
    result = evaluate_stopping(
        fraud_probability=0.48,
        verification=VerificationResponse(
            settled=True,
            verdict=EvidenceDirection.FRAUD,
            response_ref="evidence_request:1",
        ),
    )

    assert result.should_stop is True
    assert result.reason_code is ReasonCode.VERIFICATION_SETTLED
    assert "evidence_request:1" in result.stop_reason


def test_no_useful_next_step_stops_even_without_threshold() -> None:
    result = evaluate_stopping(
        fraud_probability=0.52,
        evidence=(evidence(EvidenceDirection.FRAUD, "risk-and-context"),),
        further_investigation_unlikely=True,
    )

    assert result.should_stop is True
    assert result.independent_evidence_count == 1
    assert result.reason_code is ReasonCode.NO_USEFUL_NEXT_STEP

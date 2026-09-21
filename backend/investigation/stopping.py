"""Deterministic investigation stopping policy.

This module implements the README stopping rules only.  It has no LLM or
caller-provided force-stop/force-continue switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from backend.investigation.scoring_config import DEFAULT_STOPPING_CONFIG, StoppingConfig


class EvidenceDirection(str, Enum):
    FRAUD = "fraud"
    LEGITIMATE = "legitimate"


class ReasonCode(str, Enum):
    STRONG_FRAUD = "strong_fraud"
    STRONG_LEGITIMATE = "strong_legitimate"
    VERIFICATION_SETTLED = "verification_settled"
    NO_USEFUL_NEXT_STEP = "no_useful_next_step"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class IndependentEvidence:
    """One grounded signal and its independence group.

    Signals with the same ``independence_key`` are one evidence source for
    stopping purposes, even if they contain different claims.
    """

    claim: str
    direction: EvidenceDirection
    independence_key: str

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise ValueError("evidence claim must not be empty")
        if not self.independence_key.strip():
            raise ValueError("evidence independence_key must not be empty")


@dataclass(frozen=True)
class VerificationResponse:
    """A structured response that settles the question when settled is true."""

    settled: bool
    verdict: EvidenceDirection | None = None
    response_ref: str = ""

    def __post_init__(self) -> None:
        if self.settled and self.verdict is None:
            raise ValueError("a settled verification response requires a verdict")
        if self.settled and not self.response_ref.strip():
            raise ValueError("a settled verification response requires response_ref")


@dataclass(frozen=True)
class StoppingDecision:
    should_stop: bool
    stop_reason: str
    independent_evidence_count: int
    reason_code: ReasonCode


def _validate_probability(value: float) -> float:
    try:
        probability = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("fraud_probability must be numeric") from exc
    if not 0.0 <= probability <= 1.0:
        raise ValueError("fraud_probability must be between 0 and 1")
    return probability


def _independent_count(
    evidence: Iterable[IndependentEvidence],
    direction: EvidenceDirection,
) -> int:
    return len({
        item.independence_key.strip()
        for item in evidence
        if item.direction is direction
    })


def evaluate_stopping(
    *,
    fraud_probability: float,
    evidence: Iterable[IndependentEvidence] = (),
    verification: VerificationResponse | None = None,
    further_investigation_unlikely: bool = False,
    config: StoppingConfig = DEFAULT_STOPPING_CONFIG,
) -> StoppingDecision:
    """Apply the README stopping rules in deterministic priority order."""
    probability = _validate_probability(fraud_probability)
    evidence_items = tuple(evidence)

    if verification is not None and verification.settled:
        assert verification.verdict is not None
        return StoppingDecision(
            should_stop=True,
            stop_reason=(
                f"Verification response {verification.response_ref} settled the "
                f"question as {verification.verdict.value}."
            ),
            independent_evidence_count=_independent_count(evidence_items, verification.verdict),
            reason_code=ReasonCode.VERIFICATION_SETTLED,
        )

    fraud_count = _independent_count(evidence_items, EvidenceDirection.FRAUD)
    legitimate_count = _independent_count(evidence_items, EvidenceDirection.LEGITIMATE)
    minimum = config.minimum_independent_evidence

    if probability >= config.strong_fraud_threshold and fraud_count >= minimum:
        return StoppingDecision(
            should_stop=True,
            stop_reason=(
                f"Fraud probability {probability:.2f} meets the strong-fraud threshold "
                f"with {fraud_count} independent supporting evidence sources."
            ),
            independent_evidence_count=fraud_count,
            reason_code=ReasonCode.STRONG_FRAUD,
        )

    if probability <= config.strong_legitimate_threshold and legitimate_count >= minimum:
        return StoppingDecision(
            should_stop=True,
            stop_reason=(
                f"Fraud probability {probability:.2f} meets the strong-legitimate threshold "
                f"with {legitimate_count} independent supporting evidence sources."
            ),
            independent_evidence_count=legitimate_count,
            reason_code=ReasonCode.STRONG_LEGITIMATE,
        )

    if further_investigation_unlikely:
        return StoppingDecision(
            should_stop=True,
            stop_reason="Further investigation is unlikely to change the decision.",
            independent_evidence_count=max(fraud_count, legitimate_count),
            reason_code=ReasonCode.NO_USEFUL_NEXT_STEP,
        )

    direction = "fraud" if probability > config.strong_legitimate_threshold else "legitimate"
    relevant_count = fraud_count if direction == "fraud" else legitimate_count
    return StoppingDecision(
        should_stop=False,
        stop_reason=(
            f"The current {direction}-supporting evidence has {relevant_count} independent "
            "sources and does not satisfy a README stopping rule."
        ),
        independent_evidence_count=relevant_count,
        reason_code=ReasonCode.INSUFFICIENT_EVIDENCE,
    )

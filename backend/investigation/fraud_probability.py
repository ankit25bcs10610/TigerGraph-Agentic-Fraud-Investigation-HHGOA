"""Transparent deterministic fraud-probability assessment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from backend.investigation.evidence import GraphEvidence, to_answer_evidence
from backend.investigation.exposure import episode_exposure_usd, episode_transaction_ids
from backend.investigation.scoring_config import DEFAULT_SCORING_CONFIG, ScoringConfig
from backend.investigation.patterns import PatternResult
from backend.models.answer import Evidence


def _bounded(name: str, value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


@dataclass(frozen=True)
class ScoringInputs:
    risk_score: float = 0.0
    pattern_strength: float = 0.0
    unusual_transaction_behavior: float = 0.0
    shared_device_evidence: float = 0.0
    region_evidence: float = 0.0
    prior_confirmed_fraud_cases: float = 0.0
    customer_evidence: float = 0.0
    step_up_authentication_evidence: float = 0.0
    conflicting_evidence: float = 0.0

    def validated(self) -> "ScoringInputs":
        values = {
            name: _bounded(name, getattr(self, name))
            for name in self.__dataclass_fields__
        }
        return ScoringInputs(**values)


@dataclass(frozen=True)
class Assessment:
    fraud_probability: float
    evidence_used: list[Evidence] = field(default_factory=list)
    affected_transaction_ids: list[str] = field(default_factory=list)
    connected_card_ids: list[str] = field(default_factory=list)
    connected_device_profiles: list[str] = field(default_factory=list)
    exposure_usd: float = 0.0
    uncertainty_indicators: list[str] = field(default_factory=list)


def deterministic_fraud_probability(
    inputs: ScoringInputs,
    *,
    config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> float:
    """Calculate a bounded weighted score; no fitted model or fraud label is used."""
    values = inputs.validated()
    positive = (
        values.risk_score * config.risk_score_weight
        + values.pattern_strength * config.pattern_strength_weight
        + values.unusual_transaction_behavior * config.unusual_behavior_weight
        + values.shared_device_evidence * config.shared_device_weight
        + values.region_evidence * config.region_evidence_weight
        + values.prior_confirmed_fraud_cases * config.prior_confirmed_case_weight
        + values.customer_evidence * config.customer_evidence_weight
        + values.step_up_authentication_evidence * config.step_up_weight
    )
    score = positive - values.conflicting_evidence * config.conflicting_evidence_weight
    return round(max(0.0, min(1.0, score)), 6)


def assess_fraud(
    *,
    scoring: ScoringInputs,
    episode_transactions: Sequence[dict[str, object]],
    evidence: Iterable[GraphEvidence] = (),
    connected_card_ids: Iterable[str] = (),
    connected_device_profiles: Iterable[str] = (),
    uncertainty_indicators: Iterable[str] = (),
    pattern_result: PatternResult | None = None,
    config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> Assessment:
    """Combine explicit episode rows and grounded facts into an assessment."""
    ids = episode_transaction_ids(episode_transactions)
    pattern_strength = scoring.pattern_strength
    if pattern_result is not None:
        pattern_strength = pattern_result.strength
    effective_scoring = ScoringInputs(
        **{
            **scoring.__dict__,
            "pattern_strength": pattern_strength,
        }
    )
    return Assessment(
        fraud_probability=deterministic_fraud_probability(effective_scoring, config=config),
        evidence_used=to_answer_evidence(evidence),
        affected_transaction_ids=ids,
        connected_card_ids=sorted({value for value in connected_card_ids if value}),
        connected_device_profiles=sorted({value for value in connected_device_profiles if value}),
        exposure_usd=episode_exposure_usd(episode_transactions),
        uncertainty_indicators=[value for value in uncertainty_indicators if value],
    )


"""Single source of truth for the deterministic assessment weights."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringConfig:
    # risk_score is deliberately only one component of the assessment.
    risk_score_weight: float = 0.15
    pattern_strength_weight: float = 0.30
    unusual_behavior_weight: float = 0.15
    shared_device_weight: float = 0.10
    region_evidence_weight: float = 0.10
    prior_confirmed_case_weight: float = 0.10
    customer_evidence_weight: float = 0.05
    step_up_weight: float = 0.10
    conflicting_evidence_weight: float = 0.25


DEFAULT_SCORING_CONFIG = ScoringConfig()


@dataclass(frozen=True)
class StoppingConfig:
    """Thresholds copied from the README stopping policy."""

    strong_fraud_threshold: float = 0.85
    strong_legitimate_threshold: float = 0.15
    minimum_independent_evidence: int = 2


DEFAULT_STOPPING_CONFIG = StoppingConfig()

"""Deterministic suspicious-activity-report policy."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from backend.models.answer import SAR, Verdict


@dataclass(frozen=True)
class SARDecision:
    file: bool
    reason: str


def evaluate_sar(
    *,
    verdict: Verdict,
    fraud_probability: float,
    exposure_usd: float,
    shared_fraud_origin: bool = False,
    connected_to_other_card_fraud: bool = False,
    coordinated_undocumented_abuse: bool = False,
) -> SARDecision:
    """Apply README section 3a reporting conditions."""
    probability = float(fraud_probability)
    exposure = float(exposure_usd)
    if not 0.0 <= probability <= 1.0:
        raise ValueError("fraud_probability must be between 0 and 1")
    if exposure < 0:
        raise ValueError("exposure_usd must not be negative")

    strongly_suspected = verdict is Verdict.FRAUD or probability >= 0.85
    triggers: list[str] = []
    if exposure > 1000:
        triggers.append("exposure exceeds $1,000")
    if shared_fraud_origin:
        triggers.append("shared device, region, or email origin")
    if connected_to_other_card_fraud:
        triggers.append("connection to another card's fraud")
    if coordinated_undocumented_abuse:
        triggers.append("coordinated or undocumented activity")

    if strongly_suspected and triggers:
        return SARDecision(True, "README section 3a: confirmed or strongly suspected fraud and " + "; ".join(triggers))
    if not strongly_suspected:
        return SARDecision(False, "README section 3a: fraud is not confirmed or strongly suspected")
    return SARDecision(False, "README section 3a: no exposure, shared-origin, connected-fraud, or coordinated-activity trigger")


def build_sar(
    decision: SARDecision,
    *,
    narrative: str = "",
    subjects: Sequence[str] = (),
    total_amount_usd: float = 0.0,
    activity_dates: Sequence[str] = (),
) -> SAR:
    """Build the strict answer-format SAR without inventing report facts."""
    if decision.file:
        return SAR(
            file=True,
            reason=decision.reason,
            narrative=narrative,
            subjects=list(subjects),
            total_amount_usd=float(total_amount_usd),
            activity_dates=list(activity_dates),
        )
    return SAR(
        file=False,
        reason=decision.reason,
        narrative="",
        subjects=[],
        total_amount_usd=0.0,
        activity_dates=[],
    )

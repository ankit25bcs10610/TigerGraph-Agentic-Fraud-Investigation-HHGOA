"""Deterministic suspicious-activity-report policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections.abc import Sequence

from backend.models.answer import SAR, Verdict
from backend.policy.approvals import get_approval_route
from backend.models.answer import ApprovalRoute, FraudPattern, PolicyAction
from backend.investigation.exposure import episode_exposure_usd, episode_transaction_ids


@dataclass(frozen=True)
class SARDecision:
    file: bool
    reason: str

@dataclass(frozen=True)
class SARGeneration:
    sar: SAR
    approval_route: ApprovalRoute | None
    investigation_case_required: bool

def _date(value: object) -> str:
    if isinstance(value, datetime): return value.date().isoformat()
    return datetime.fromisoformat(str(value)).date().isoformat()

def generate_grounded_sar(*, decision: SARDecision, customer_id: str, card_id: str,
    connected_card_ids: Sequence[str], episode_transactions: Sequence[dict[str, object]],
    pattern: FraudPattern, linkage_claims: Sequence[str] = (), evidence_response: str = "",
    known_subject_ids: Sequence[str], investigation_case_created: bool) -> SARGeneration:
    """Render a SAR from supplied facts; eligibility remains in ``evaluate_sar``."""
    if not decision.file: return SARGeneration(build_sar(decision), None, False)
    if not investigation_case_created: raise ValueError("an InvestigationCase must exist before a report is generated")
    subjects = list(dict.fromkeys([customer_id, card_id, *connected_card_ids]))
    allowed = {str(value) for value in known_subject_ids}
    if any(subject not in allowed for subject in subjects): raise ValueError("SAR subject is not present in supplied graph/input IDs")
    transaction_ids = episode_transaction_ids(episode_transactions)
    dates = sorted({_date(row.get("ts", row.get("timestamp"))) for row in episode_transactions})
    exposure = episode_exposure_usd(episode_transactions)
    components = [f"Customer {customer_id} and card {card_id} are the report subjects.",
        f"The identified episode contains transactions {', '.join(transaction_ids)} between {dates[0]} and {dates[-1]}.",
        f"The deterministic episode exposure is USD {exposure:.2f}.",
        f"The deterministic investigation classified the observed pattern as {pattern.value}."]
    if connected_card_ids: components.append(f"Connected cards supplied by graph evidence: {', '.join(connected_card_ids)}.")
    if linkage_claims: components.append("Grounded linkage evidence: " + " ".join(linkage_claims))
    if evidence_response: components.append("Recorded evidence response: " + evidence_response)
    components.append("The report reason is: " + decision.reason)
    narrative = " ".join(components)
    return SARGeneration(build_sar(decision, narrative=narrative, subjects=subjects, total_amount_usd=exposure, activity_dates=[dates[0], dates[-1]]), get_approval_route(PolicyAction.FILE_REPORT, exposure), True)


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

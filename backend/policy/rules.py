"""Deterministic implementations of Fraud Policy rules R1-R10."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.models.answer import Action, FraudPattern, PolicyAction, Verdict
from backend.policy.actions import deduplicate_actions, policy_action
from backend.policy.approvals import get_approval_route


class CustomerResponse(str, Enum):
    DENIED = "denied"
    CONFIRMED = "confirmed"
    NO_REPLY = "no_reply"


@dataclass(frozen=True)
class PolicyContext:
    verdict: Verdict = Verdict.UNCERTAIN
    fraud_probability: float = 0.0
    exposure_usd: float = 0.0
    pattern: FraudPattern = FraudPattern.NONE
    independent_evidence_count: int = 0
    customer_response: CustomerResponse | None = None
    no_reply_within_24h: bool = False
    pending_authorization: bool = True
    prefer_customer_validation: bool = True
    card_testing_purchase_cleared: bool = False
    cleared_purchase_amount_usd: float = 0.0
    shared_fraud_origin: bool = False
    recurring_legitimate_dispute: bool = False
    conflicting_evidence: bool = False
    coordinated_undocumented_abuse: bool = False
    confirmed_fraud_cards_for_customer: int = 0
    credentials_confirmed_compromised: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.fraud_probability) <= 1.0:
            raise ValueError("fraud_probability must be between 0 and 1")
        if float(self.exposure_usd) < 0:
            raise ValueError("exposure_usd must not be negative")
        if self.independent_evidence_count < 0:
            raise ValueError("independent_evidence_count must not be negative")
        if self.confirmed_fraud_cards_for_customer < 0:
            raise ValueError("confirmed_fraud_cards_for_customer must not be negative")


def _action(context: PolicyContext, action: PolicyAction, rule: str, reason: str) -> Action:
    return policy_action(
        action,
        rule=rule,
        reason=reason,
        route=get_approval_route(action, context.exposure_usd),
    )


def r1_weak_signal(context: PolicyContext) -> list[Action]:
    """R1: verify before blocking on one weak signal below 0.70."""
    if (
        context.customer_response is None
        and context.independent_evidence_count == 1
        and context.fraud_probability < 0.70
    ):
        action = (
            PolicyAction.VERIFY_WITH_CUSTOMER
            if context.prefer_customer_validation
            else PolicyAction.STEP_UP_AUTH
        )
        return [_action(context, action, "R1", "single weak signal with fraud probability below 0.70; verify before any block")]
    return []


def r2_customer_denies(context: PolicyContext) -> list[Action]:
    """R2: denial blocks the card and creates a case; report if required."""
    if context.customer_response is not CustomerResponse.DENIED:
        return []
    actions = [
        _action(context, PolicyAction.BLOCK_CARD, "R2", "customer denied the transaction"),
        _action(context, PolicyAction.CREATE_CASE, "R2", "customer denial requires an internal fraud case"),
    ]
    if (
        context.exposure_usd > 1000
        or context.shared_fraud_origin
        or context.confirmed_fraud_cards_for_customer > 0
    ):
        actions.append(
            _action(context, PolicyAction.FILE_REPORT, "R2", "denial plus exposure or connected fraud satisfies report conditions")
        )
    return actions


def r3_customer_confirms(context: PolicyContext) -> list[Action]:
    """R3: customer confirmation closes the alert as no fraud."""
    if context.customer_response is CustomerResponse.CONFIRMED:
        return [_action(context, PolicyAction.CLOSE_NO_FRAUD, "R3", "customer confirmed the transaction")]
    return []


def r4_no_reply(context: PolicyContext) -> list[Action]:
    """R4: no reply after 24 hours triggers monitoring and pending decline."""
    if not context.no_reply_within_24h:
        return []
    actions = [_action(context, PolicyAction.MONITOR_CARD, "R4", "no customer reply within 24 hours")]
    if context.pending_authorization:
        actions.append(
            _action(context, PolicyAction.DECLINE_TRANSACTION, "R4", "decline pending authorizations after no reply")
        )
    if context.exposure_usd > 500:
        actions.append(
            _action(context, PolicyAction.ESCALATE_TO_ANALYST, "R4", "no reply and exposure exceeds $500")
        )
    return actions


def r5_card_testing(context: PolicyContext) -> list[Action]:
    """R5: card testing requires decline and step-up; block a cleared >$100 purchase."""
    if context.pattern is not FraudPattern.CARD_TESTING:
        return []
    actions = [
        _action(context, PolicyAction.DECLINE_TRANSACTION, "R5", "card-testing sequence observed"),
        _action(context, PolicyAction.STEP_UP_AUTH, "R5", "card-testing sequence requires step-up authentication"),
    ]
    if context.card_testing_purchase_cleared and context.cleared_purchase_amount_usd > 100:
        actions.append(
            _action(context, PolicyAction.BLOCK_CARD, "R5", "card-testing purchase over $100 already cleared")
        )
    return actions


def r6_shared_origin(context: PolicyContext) -> list[Action]:
    """R6: shared device/region/email fraud origin creates, reports, and monitors."""
    if not context.shared_fraud_origin:
        return []
    return [
        _action(context, PolicyAction.CREATE_CASE, "R6", "several cards share a fraud origin in one window"),
        _action(context, PolicyAction.FILE_REPORT, "R6", "shared fraud origin satisfies the reporting condition"),
        _action(context, PolicyAction.MONITOR_CONNECTED_CARDS, "R6", "monitor every card sharing the fraud origin"),
    ]


def r7_disputed_recurring_legitimate(context: PolicyContext) -> list[Action]:
    """R7: recurring legitimate disputes are handled without a block."""
    if not context.recurring_legitimate_dispute:
        return []
    return [
        _action(context, PolicyAction.CREATE_CASE, "R7", "dispute matches the customer's recurring legitimate pattern"),
        _action(context, PolicyAction.VERIFY_WITH_CUSTOMER, "R7", "verify a disputed recurring charge"),
        _action(context, PolicyAction.WARN_CUSTOMER, "R7", "warn the customer about the recurring charge"),
    ]


def r8_uncertain_or_conflicting(context: PolicyContext) -> list[Action]:
    """R8: escalate uncertain exposed cases or conflicting evidence."""
    if (context.verdict is Verdict.UNCERTAIN and context.exposure_usd > 500) or context.conflicting_evidence:
        reason = (
            "uncertain verdict with exposure above $500"
            if context.verdict is Verdict.UNCERTAIN and context.exposure_usd > 500
            else "evidence conflicts"
        )
        return [_action(context, PolicyAction.ESCALATE_TO_ANALYST, "R8", reason)]
    return []


def r9_undocumented_abuse(context: PolicyContext) -> list[Action]:
    """R9: coordinated undocumented abuse creates, reports, and escalates."""
    if not (
        context.pattern is FraudPattern.UNDOCUMENTED
        and context.coordinated_undocumented_abuse
    ):
        return []
    return [
        _action(context, PolicyAction.CREATE_CASE, "R9", "coordinated abuse fits none of the documented patterns"),
        _action(context, PolicyAction.FILE_REPORT, "R9", "coordinated undocumented abuse requires a report"),
        _action(context, PolicyAction.ESCALATE_TO_ANALYST, "R9", "undocumented coordinated abuse requires analyst review"),
    ]


def r10_block_all_cards(context: PolicyContext) -> list[Action]:
    """R10: block all cards only after two confirmed fraud cards or compromise."""
    if (
        context.confirmed_fraud_cards_for_customer >= 2
        or context.credentials_confirmed_compromised
    ):
        return [_action(context, PolicyAction.BLOCK_ALL_CARDS, "R10", "at least two customer cards show confirmed fraud or credentials are compromised")]
    return []


def recommend_actions(context: PolicyContext) -> list[Action]:
    """Apply all applicable rules, with customer verification taking precedence."""
    if context.customer_response is CustomerResponse.CONFIRMED:
        return deduplicate_actions(r3_customer_confirms(context))

    actions: list[Action] = []
    for rule in (
        r1_weak_signal,
        r2_customer_denies,
        r4_no_reply,
        r5_card_testing,
        r6_shared_origin,
        r7_disputed_recurring_legitimate,
        r8_uncertain_or_conflicting,
        r9_undocumented_abuse,
        r10_block_all_cards,
    ):
        actions.extend(rule(context))
    return deduplicate_actions(actions)

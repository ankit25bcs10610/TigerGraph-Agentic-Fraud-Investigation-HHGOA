from backend.models.answer import ApprovalRoute, FraudPattern, PolicyAction, Verdict
from backend.policy.approvals import approval_route
from backend.policy.rules import (
    CustomerResponse,
    PolicyContext,
    r1_weak_signal,
    r2_customer_denies,
    r3_customer_confirms,
    r4_no_reply,
    r5_card_testing,
    r6_shared_origin,
    r7_disputed_recurring_legitimate,
    r8_uncertain_or_conflicting,
    r9_undocumented_abuse,
    r10_block_all_cards,
    recommend_actions,
)
from backend.policy.sar import build_sar, evaluate_sar


def actions(result):
    return {item.action for item in result}


def test_r1_weak_signal_verifies_without_blocking() -> None:
    result = r1_weak_signal(PolicyContext(fraud_probability=0.60, independent_evidence_count=1))

    assert actions(result) == {PolicyAction.VERIFY_WITH_CUSTOMER}
    assert result[0].reason.startswith("R1:")
    assert PolicyAction.BLOCK_CARD not in actions(result)


def test_r2_denial_blocks_creates_case_and_reports_when_shared() -> None:
    result = r2_customer_denies(
        PolicyContext(
            customer_response=CustomerResponse.DENIED,
            exposure_usd=25,
            shared_fraud_origin=True,
        )
    )

    assert actions(result) == {
        PolicyAction.BLOCK_CARD,
        PolicyAction.CREATE_CASE,
        PolicyAction.FILE_REPORT,
    }
    assert all(item.reason.startswith("R2:") for item in result)


def test_r3_confirmation_closes_without_fraud_action() -> None:
    result = r3_customer_confirms(
        PolicyContext(customer_response=CustomerResponse.CONFIRMED)
    )

    assert actions(result) == {PolicyAction.CLOSE_NO_FRAUD}
    assert result[0].reason.startswith("R3:")


def test_r4_no_reply_monitors_declines_pending_and_escalates_over_500() -> None:
    result = r4_no_reply(
        PolicyContext(no_reply_within_24h=True, pending_authorization=True, exposure_usd=501)
    )

    assert actions(result) == {
        PolicyAction.MONITOR_CARD,
        PolicyAction.DECLINE_TRANSACTION,
        PolicyAction.ESCALATE_TO_ANALYST,
    }
    assert all(item.reason.startswith("R4:") for item in result)


def test_r5_card_testing_blocks_only_after_cleared_purchase_over_100() -> None:
    result = r5_card_testing(
        PolicyContext(
            pattern=FraudPattern.CARD_TESTING,
            card_testing_purchase_cleared=True,
            cleared_purchase_amount_usd=100.01,
        )
    )

    assert actions(result) == {
        PolicyAction.DECLINE_TRANSACTION,
        PolicyAction.STEP_UP_AUTH,
        PolicyAction.BLOCK_CARD,
    }


def test_r6_shared_origin_creates_reports_and_monitors_connections() -> None:
    result = r6_shared_origin(PolicyContext(shared_fraud_origin=True))

    assert actions(result) == {
        PolicyAction.CREATE_CASE,
        PolicyAction.FILE_REPORT,
        PolicyAction.MONITOR_CONNECTED_CARDS,
    }
    assert all(item.reason.startswith("R6:") for item in result)


def test_r7_recurring_legitimate_dispute_never_blocks() -> None:
    result = r7_disputed_recurring_legitimate(
        PolicyContext(recurring_legitimate_dispute=True)
    )

    assert actions(result) == {
        PolicyAction.CREATE_CASE,
        PolicyAction.VERIFY_WITH_CUSTOMER,
        PolicyAction.WARN_CUSTOMER,
    }
    assert PolicyAction.BLOCK_CARD not in actions(result)


def test_r8_escalates_uncertain_exposed_or_conflicting_cases() -> None:
    assert actions(r8_uncertain_or_conflicting(
        PolicyContext(verdict=Verdict.UNCERTAIN, exposure_usd=500.01)
    )) == {PolicyAction.ESCALATE_TO_ANALYST}
    assert actions(r8_uncertain_or_conflicting(
        PolicyContext(verdict=Verdict.FRAUD, conflicting_evidence=True)
    )) == {PolicyAction.ESCALATE_TO_ANALYST}


def test_r9_undocumented_coordinated_abuse_creates_reports_and_escalates() -> None:
    result = r9_undocumented_abuse(
        PolicyContext(
            pattern=FraudPattern.UNDOCUMENTED,
            coordinated_undocumented_abuse=True,
        )
    )

    assert actions(result) == {
        PolicyAction.CREATE_CASE,
        PolicyAction.FILE_REPORT,
        PolicyAction.ESCALATE_TO_ANALYST,
    }
    assert all(item.reason.startswith("R9:") for item in result)


def test_r10_requires_two_confirmed_cards_or_compromised_credentials() -> None:
    assert r10_block_all_cards(PolicyContext(confirmed_fraud_cards_for_customer=1)) == []
    assert actions(r10_block_all_cards(PolicyContext(confirmed_fraud_cards_for_customer=2))) == {
        PolicyAction.BLOCK_ALL_CARDS
    }
    assert actions(r10_block_all_cards(PolicyContext(credentials_confirmed_compromised=True))) == {
        PolicyAction.BLOCK_ALL_CARDS
    }


def test_approval_routes_match_policy() -> None:
    assert approval_route(PolicyAction.DECLINE_TRANSACTION, 0) is ApprovalRoute.L1
    assert approval_route(PolicyAction.BLOCK_CARD, 2500) is ApprovalRoute.L1
    assert approval_route(PolicyAction.BLOCK_CARD, 2500.01) is ApprovalRoute.L2
    assert approval_route(PolicyAction.BLOCK_ALL_CARDS, 0) is ApprovalRoute.L2
    assert approval_route(PolicyAction.FILE_REPORT, 0) is ApprovalRoute.L2
    assert approval_route(PolicyAction.MONITOR_CARD, 0) is ApprovalRoute.AUTO


def test_composed_recommendations_keep_all_rule_numbers_and_deduplicate_actions() -> None:
    result = recommend_actions(
        PolicyContext(
            customer_response=CustomerResponse.DENIED,
            exposure_usd=1500,
            shared_fraud_origin=True,
            conflicting_evidence=True,
        )
    )

    create_case = next(item for item in result if item.action is PolicyAction.CREATE_CASE)
    assert "R2:" in create_case.reason
    assert "R6:" in create_case.reason
    assert sum(item.action is PolicyAction.CREATE_CASE for item in result) == 1


def test_sar_conditions_and_answer_shape() -> None:
    decision = evaluate_sar(
        verdict=Verdict.FRAUD,
        fraud_probability=0.90,
        exposure_usd=1200,
    )
    sar = build_sar(
        decision,
        narrative="Structured narrative.",
        subjects=("C-1",),
        total_amount_usd=1200,
        activity_dates=("2016-12-01", "2016-12-01"),
    )

    assert decision.file is True
    assert sar.file is True
    assert sar.total_amount_usd == 1200.0

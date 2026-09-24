from datetime import datetime, timedelta

from backend.investigation.patterns import (
    PatternContext,
    PatternResult,
    TransactionEvidence,
    classify_pattern,
    detect_account_takeover,
    detect_card_not_present_fraud,
    detect_card_not_present_new_device,
    detect_card_testing,
    detect_none,
    detect_out_of_region_use,
    detect_undocumented,
)
from backend.models.answer import FraudPattern


BASE = datetime(2016, 12, 1, 12, 0, 0)


def tx(
    transaction_id: str,
    offset_hours: float = 0,
    *,
    amount: float = 20.0,
    channel: str = "online",
    region: str | None = "home",
    product: str | None = "A",
    device: str | None = "device-old",
    device_status: str | None = "Found",
    proxy: str | None = None,
    match: str | None = "match_status:2",
    card: str = "C1-K1",
    customer: str = "C1",
) -> TransactionEvidence:
    return TransactionEvidence(
        transaction_id=transaction_id,
        card_id=card,
        customer_id=customer,
        timestamp=BASE + timedelta(hours=offset_hours),
        amount_usd=amount,
        channel=channel,
        billing_region=region,
        product_code=product,
        device_profile_id=device,
        device_status=device_status,
        proxy_type=proxy,
        match_status=match,
    )


def test_card_testing_detects_three_small_authorizations_then_purchase() -> None:
    target = tx("large", 0.7, amount=259.98)
    context = PatternContext(
        target=target,
        card_history=(
            tx("tiny-1", 0.0, amount=1.10),
            tx("tiny-2", 0.15, amount=2.40),
            tx("tiny-3", 0.30, amount=0.95),
        ),
    )

    result = detect_card_testing(context)

    assert result.pattern is FraudPattern.CARD_TESTING
    assert result.strength >= 0.9
    assert any("tiny-1" in item for item in result.supporting_evidence)


def test_card_testing_rejects_non_online_activity() -> None:
    result = detect_card_testing(
        PatternContext(target=tx("present", amount=2, channel="in_person"))
    )

    assert result.pattern is FraudPattern.NONE
    assert result.strength == 0


def test_card_testing_can_be_found_after_the_trigger_transaction() -> None:
    result = detect_card_testing(
        PatternContext(
            target=tx("trigger", -2, amount=80),
            card_history=(
                tx("tiny-1", 0, amount=1.10),
                tx("tiny-2", 0.15, amount=2.40),
                tx("tiny-3", 0.30, amount=0.95),
                tx("large", 0.70, amount=120),
            ),
        )
    )

    assert result.pattern is FraudPattern.CARD_TESTING


def test_card_not_present_fraud_detects_inconsistent_online_burst() -> None:
    result = detect_card_not_present_fraud(
        PatternContext(
            target=tx("target", amount=160, product="B"),
            card_history=(
                tx("old", -720, amount=20, product="A"),
                tx("burst-2", 1, amount=170, product="B"),
            ),
        )
    )

    assert result.pattern is FraudPattern.CARD_NOT_PRESENT_FRAUD
    assert result.strength > 0


def test_card_not_present_does_not_reject_a_longer_online_burst() -> None:
    result = detect_card_not_present_fraud(
        PatternContext(
            target=tx("target", amount=160, product="B"),
            card_history=(
                tx("old", -720, amount=20, product="A"),
                *(tx(f"burst-{index}", index, amount=170, product="B") for index in range(1, 6)),
            ),
        )
    )

    assert result.pattern is FraudPattern.CARD_NOT_PRESENT_FRAUD


def test_card_not_present_new_device_requires_new_device_signal() -> None:
    result = detect_card_not_present_new_device(
        PatternContext(
            target=tx("target", amount=160, product="B", device_status="New", device="device-new"),
            card_history=(
                tx("old", -720, amount=20, product="A"),
                tx("burst-2", 1, amount=170, product="B"),
            ),
        )
    )

    assert result.pattern is FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE
    assert "New" in " ".join(result.supporting_evidence)


def test_card_not_present_rejects_in_person_target() -> None:
    result = detect_card_not_present_fraud(
        PatternContext(target=tx("target", channel="in_person"), card_history=(tx("old", -1),))
    )

    assert result.pattern is FraudPattern.NONE
    assert "not online" in result.contradicting_evidence[0]


def test_out_of_region_requires_new_region_and_continuing_home_activity() -> None:
    result = detect_out_of_region_use(
        PatternContext(
            target=tx("target", 0, channel="in_person", region="away"),
            card_history=(
                tx("home-1", -480, channel="in_person", region="home"),
                tx("home-2", -240, channel="in_person", region="home"),
                tx("away-2", 24, channel="in_person", region="away"),
                tx("home-3", 48, channel="in_person", region="home"),
            ),
        )
    )

    assert result.pattern is FraudPattern.OUT_OF_REGION_USE
    assert result.strength > 0


def test_out_of_region_rejects_region_seen_in_prior_history() -> None:
    result = detect_out_of_region_use(
        PatternContext(
            target=tx("target", 0, channel="in_person", region="away"),
            card_history=(
                tx("away-old", -24, channel="in_person", region="away"),
                tx("home-after", 24, channel="in_person", region="home"),
            ),
        )
    )

    assert result.pattern is FraudPattern.NONE
    assert "not new" in result.reason


def test_account_takeover_detects_mixed_channel_device_and_match_anomalies() -> None:
    result = detect_account_takeover(
        PatternContext(
            target=tx(
                "target",
                0,
                device="device-new",
                device_status="New",
                match="match_status:0",
                proxy="anonymous",
            ),
            card_history=(
                tx("old-online", -24, channel="online", device="device-old", match="match_status:2"),
                tx("old-present", -23, channel="in_person", device="device-old", match=None),
            ),
        )
    )

    assert result.pattern is FraudPattern.ACCOUNT_TAKEOVER
    assert len(result.supporting_evidence) >= 3


def test_account_takeover_rejects_mixed_channel_activity_without_anomalies() -> None:
    result = detect_account_takeover(
        PatternContext(
            target=tx("target", 0, device="device-old", device_status="Found", match="match_status:2"),
            card_history=(tx("old-present", -1, channel="in_person", device="device-old", match=None),),
        )
    )

    assert result.pattern is FraudPattern.NONE
    assert result.strength == 0


def test_undocumented_detects_coordinated_activity_without_known_pattern() -> None:
    result = detect_undocumented(
        PatternContext(
            target=tx("target"),
            network_transactions=(
                tx("network-1", customer="C2"),
                tx("network-2", customer="C3"),
            ),
            connected_card_ids=("C2-K2", "C3-K3"),
            confirmed_related_case_ids=("CASE-1",),
        )
    )

    assert result.pattern is FraudPattern.UNDOCUMENTED
    assert result.strength > 0


def test_undocumented_does_not_override_documented_pattern() -> None:
    result = detect_undocumented(
        PatternContext(
            target=tx("target"),
            connected_card_ids=("C2-K2", "C3-K3"),
            known_pattern_results=(
                PatternResult(FraudPattern.CARD_TESTING, strength=0.95),
            ),
        )
    )

    assert result.pattern is FraudPattern.NONE
    assert "documented" in result.contradicting_evidence[0]


def test_undocumented_requires_cross_customer_coordination() -> None:
    result = detect_undocumented(
        PatternContext(
            target=tx("target"),
            connected_card_ids=("C1-K2", "C1-K3"),
            confirmed_related_case_ids=("CASE-1",),
        )
    )

    assert result.pattern is FraudPattern.NONE


def test_none_has_positive_strength_only_after_legitimacy_confirmation() -> None:
    result = detect_none(
        PatternContext(target=tx("target"), customer_confirmed_legitimate=True)
    )

    assert result.pattern is FraudPattern.NONE
    assert result.strength == 1.0
    assert result.supporting_evidence


def test_classify_pattern_returns_none_without_forcing_a_fraud_label() -> None:
    result = classify_pattern(PatternContext(target=tx("target")))

    assert result.pattern is FraudPattern.NONE
    assert result.strength == 0

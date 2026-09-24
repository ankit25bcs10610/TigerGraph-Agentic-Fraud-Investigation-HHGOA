"""Deterministic fraud-pattern detectors over structured graph evidence.

No LLM, public fraud labels, or risk-score verdict logic is used here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Iterable, Sequence

from backend.models.answer import FraudPattern


@dataclass(frozen=True)
class TransactionEvidence:
    transaction_id: str
    card_id: str
    customer_id: str
    timestamp: datetime
    amount_usd: float
    channel: str
    billing_region: str | None = None
    product_code: str | None = None
    purchaser_email_domain: str | None = None
    device_profile_id: str | None = None
    device_status: str | None = None
    proxy_type: str | None = None
    match_status: str | None = None


@dataclass(frozen=True)
class PatternContext:
    target: TransactionEvidence
    card_history: tuple[TransactionEvidence, ...] = ()
    customer_history: tuple[TransactionEvidence, ...] = ()
    network_transactions: tuple[TransactionEvidence, ...] = ()
    connected_card_ids: tuple[str, ...] = ()
    confirmed_related_case_ids: tuple[str, ...] = ()
    known_pattern_results: tuple["PatternResult", ...] = ()
    customer_confirmed_legitimate: bool = False


@dataclass
class PatternResult:
    pattern: FraudPattern
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    strength: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        self.strength = max(0.0, min(1.0, float(self.strength)))


def _history(context: PatternContext) -> list[TransactionEvidence]:
    items = {item.transaction_id: item for item in context.card_history}
    items[context.target.transaction_id] = context.target
    return sorted(items.values(), key=lambda item: (item.timestamp, item.transaction_id))


def _online(item: TransactionEvidence) -> bool:
    return item.channel.lower() == "online"


def _in_person(item: TransactionEvidence) -> bool:
    return item.channel.lower() == "in_person"


def _within(item: TransactionEvidence, anchor: TransactionEvidence, hours: float) -> bool:
    return abs((item.timestamp - anchor.timestamp).total_seconds()) <= hours * 3600


def _result(pattern: FraudPattern, supporting: Iterable[str], contradicting: Iterable[str],
            strength: float, reason: str) -> PatternResult:
    return PatternResult(pattern, list(supporting), list(contradicting), strength, reason)


def detect_card_testing(context: PatternContext) -> PatternResult:
    """Three or more small online authorizations clustered around a larger purchase."""
    events = [item for item in _history(context) if _online(item)]
    for index, start in enumerate(events):
        small = [
            item for item in events[index:]
            if start.timestamp <= item.timestamp <= start.timestamp + timedelta(hours=1)
            and 0 < item.amount_usd <= 25
        ]
        if len(small) < 3:
            continue
        small_median = median(item.amount_usd for item in small)
        larger_before = next(
            (item for item in reversed(events[:index])
             if item.timestamp < start.timestamp
             and start.timestamp - item.timestamp <= timedelta(hours=1)
             and item.amount_usd >= max(5, 3 * small_median)),
            None,
        )
        larger_after = next(
            (item for item in events
             if small[-1].timestamp < item.timestamp <= small[-1].timestamp + timedelta(hours=1)
             and item.amount_usd >= max(5, 3 * small_median)),
            None,
        )
        larger = larger_after or larger_before
        sequence = [*small, larger] if larger else []
        if larger and any(_within(item, context.target, 48) for item in sequence):
            return _result(
                FraudPattern.CARD_TESTING,
                [
                    f"{len(small)} small online authorizations averaging USD {small_median:.2f} occurred within one hour",
                    f"larger purchase of USD {larger.amount_usd:.2f} followed the authorizations",
                    "sequence transactions: " + ", ".join(item.transaction_id for item in sequence),
                ],
                [], 0.95,
                "A qualifying small-authorization sequence is followed by a larger online purchase.",
            )
    return _result(
        FraudPattern.NONE, [],
        ["No sequence of at least three sub-USD-5 online authorizations followed by a larger purchase was found."],
        0.0, "The card-testing sequence rule was not satisfied.",
    )


def _online_inconsistency(target: TransactionEvidence,
                          history: Sequence[TransactionEvidence]) -> str | None:
    prior = [
        item for item in history
        if item.transaction_id != target.transaction_id
        and item.timestamp < target.timestamp and _online(item)
    ]
    if not prior:
        return "no prior online baseline exists for this card"
    if target.product_code and all(
        target.product_code != item.product_code for item in prior if item.product_code
    ):
        return "target product code was not observed in prior online history"
    typical = median(item.amount_usd for item in prior)
    if target.amount_usd >= max(2 * typical, typical + 50):
        return (
            f"target amount USD {target.amount_usd:.2f} is materially above "
            f"prior online median USD {typical:.2f}"
        )
    return None


def _cnp_result(context: PatternContext, pattern: FraudPattern) -> PatternResult:
    target = context.target
    history = _history(context)
    if not _online(target):
        return _result(
            FraudPattern.NONE, [], ["flagged transaction channel is not online"], 0.0,
            "Card-not-present detection requires an online flagged transaction.",
        )
    burst = [item for item in history if _online(item) and _within(item, target, 48)]
    inconsistency = _online_inconsistency(target, history)
    if len(burst) >= 2 and inconsistency:
        return _result(
            pattern,
            [
                f"{len(burst)} online transactions occur within 48 hours of {target.transaction_id}",
                inconsistency,
                "burst transactions: " + ", ".join(item.transaction_id for item in burst),
            ],
            [], 0.84 if pattern is FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE else 0.78,
            "Online burst and inconsistency with prior card history support card-not-present activity.",
        )
    contradictions = []
    if len(burst) < 2:
        contradictions.append("fewer than two online transactions occur in the 48-hour window")
    if not inconsistency:
        contradictions.append("the target is not materially inconsistent with prior online history")
    return _result(
        FraudPattern.NONE, [], contradictions, 0.0,
        "The card-not-present burst and inconsistency conditions were not both satisfied.",
    )


def detect_card_not_present_fraud(context: PatternContext) -> PatternResult:
    return _cnp_result(context, FraudPattern.CARD_NOT_PRESENT_FRAUD)


def detect_card_not_present_new_device(context: PatternContext) -> PatternResult:
    base = _cnp_result(context, FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE)
    if base.pattern is FraudPattern.NONE:
        return base
    if (context.target.device_status or "").strip().lower() != "new":
        return _result(
            FraudPattern.NONE, base.supporting_evidence,
            [*base.contradicting_evidence, "identity id_15 is not marked New"],
            0.0, "The online burst is present, but the target device is not marked New.",
        )
    return _result(
        FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE,
        [*base.supporting_evidence, "identity id_15 marks the target device as New"],
        [], min(0.9, base.strength + 0.1),
        "Card-not-present evidence is strengthened by a device marked New for the account.",
    )


def detect_out_of_region_use(context: PatternContext) -> PatternResult:
    target = context.target
    history = _history(context)
    if not _in_person(target):
        return _result(FraudPattern.NONE, [], ["flagged transaction is not card-present/in_person"],
                       0.0, "Out-of-region detection requires card-present activity.")
    if not target.billing_region:
        return _result(FraudPattern.NONE, [], ["flagged transaction has no billing region"],
                       0.0, "No billing region is available for comparison.")
    prior = [
        item for item in history
        if item.timestamp < target.timestamp and _in_person(item) and item.billing_region
    ]
    if not prior:
        return _result(FraudPattern.NONE, [], ["no prior card-present billing-region history exists"],
                       0.0, "A normal region baseline cannot be established.")
    prior_regions = [item.billing_region for item in prior]
    if target.billing_region in prior_regions:
        return _result(
            FraudPattern.NONE, [],
            [f"billing region {target.billing_region} was already used before the target"],
            0.0, "The target region is not new for this card.",
        )
    home, home_count = Counter(prior_regions).most_common(1)[0]
    after_home = [
        item for item in history
        if item.timestamp > target.timestamp and item.billing_region == home and _in_person(item)
    ]
    new_region_activity = [
        item for item in history
        if item.billing_region == target.billing_region and _in_person(item)
        and _within(item, target, 168)
    ]
    if not after_home or len(new_region_activity) < 2:
        supporting = [
            f"target region {target.billing_region} was absent from prior card-present history",
            f"prior home region {home} had {home_count} transactions",
        ]
        contradictions = []
        if not after_home:
            contradictions.append(f"normal home region {home} does not continue after the target")
        if len(new_region_activity) < 2:
            contradictions.append("fewer than two card-present events support activity in the new region")
        return _result(
            FraudPattern.OUT_OF_REGION_USE, supporting, contradictions, 0.62,
            "A single new card-present region is suspicious, but the stronger travel-versus-clone evidence is incomplete.",
        )
    return _result(
        FraudPattern.OUT_OF_REGION_USE,
        [
            f"target region {target.billing_region} was absent from prior card-present history",
            f"prior home region {home} had {home_count} transactions",
            "home-region activity continued after the target",
            f"{len(new_region_activity)} card-present events occurred in the new region within seven days",
        ],
        [], 0.86,
        "New card-present region activity coexists with continuing normal home-region activity.",
    )


def _match_flag_anomaly(target: TransactionEvidence,
                        history: Sequence[TransactionEvidence]) -> bool:
    value = (target.match_status or "").strip()
    if not value:
        return False
    prior = [
        (item.match_status or "").strip() for item in history
        if item.transaction_id != target.transaction_id and item.match_status
    ]
    if not prior:
        return value in {"match_status:0", "match_status:-1"}
    dominant = Counter(prior).most_common(1)[0][0]
    return value != dominant or value in {"match_status:0", "match_status:-1"}


def _device_anomaly(target: TransactionEvidence,
                    history: Sequence[TransactionEvidence]) -> bool:
    if (target.device_status or "").strip().lower() == "new":
        return True
    if (target.proxy_type or "").strip():
        return True
    prior = {item.device_profile_id for item in history if item.device_profile_id}
    return bool(target.device_profile_id and target.device_profile_id not in prior)


def detect_account_takeover(context: PatternContext) -> PatternResult:
    history = _history(context)
    window = [item for item in history if _within(item, context.target, 168)]
    channels = {item.channel.lower() for item in window}
    if not {"online", "in_person"}.issubset(channels):
        return _result(FraudPattern.NONE, [], ["no mixed online and in_person activity within seven days"],
                       0.0, "Account-takeover detection requires mixed-channel activity.")
    online_window = [item for item in window if _online(item)]
    device_anomaly = any(_device_anomaly(item, history) for item in online_window)
    match_anomaly = any(_match_flag_anomaly(item, history) for item in online_window)
    supporting = ["mixed online and in_person activity within seven days"]
    if device_anomaly:
        supporting.append("target device/identity differs from the normal device baseline")
    if match_anomaly:
        supporting.append("target match-status signal differs from the normal match baseline")
    if device_anomaly and match_anomaly:
        return _result(FraudPattern.ACCOUNT_TAKEOVER, supporting, [], 0.86,
                       "Mixed-channel activity combines device and match-status anomalies.")
    contradictions = []
    if not device_anomaly:
        contradictions.append("no device or identity anomaly was established")
    if not match_anomaly:
        contradictions.append("no match-status anomaly was established")
    return _result(FraudPattern.NONE, [], contradictions, 0.0,
                   "Mixed-channel activity lacks the required independent identity anomalies.")


def detect_undocumented(context: PatternContext) -> PatternResult:
    other_customers = {
        item.customer_id for item in context.network_transactions
        if item.customer_id != context.target.customer_id
    }
    coordinated = (
        len(other_customers) >= 2
        or (len(other_customers) >= 1 and len(set(context.connected_card_ids)) >= 2)
    )
    known_match = any(
        result.pattern in {
            FraudPattern.CARD_TESTING, FraudPattern.CARD_NOT_PRESENT_FRAUD,
            FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE, FraudPattern.OUT_OF_REGION_USE,
            FraudPattern.ACCOUNT_TAKEOVER,
        } and result.strength > 0
        for result in context.known_pattern_results
    )
    if coordinated and not known_match:
        return _result(
            FraudPattern.UNDOCUMENTED,
            [
                f"coordinated activity spans {len(other_customers)} other customers",
                f"{len(set(context.connected_card_ids))} connected cards were supplied",
                f"{len(context.confirmed_related_case_ids)} related confirmed cases were supplied",
            ],
            [], 0.8,
            "Repeated or coordinated abuse is present, but no documented pattern detector fired.",
        )
    contradictions = []
    if known_match:
        contradictions.append("a documented pattern detector already has supporting evidence")
    if not coordinated:
        contradictions.append("no cross-customer, connected-card, or confirmed-case coordination was supplied")
    return _result(FraudPattern.NONE, [], contradictions, 0.0,
                   "The undocumented-pattern conditions were not satisfied.")


def detect_none(context: PatternContext) -> PatternResult:
    if context.customer_confirmed_legitimate:
        return _result(FraudPattern.NONE, ["customer explicitly confirmed the flagged activity"],
                       [], 1.0, "The customer confirmation establishes legitimate activity.")
    return _result(FraudPattern.NONE, [],
                   ["no customer or equivalent legitimacy confirmation was supplied"],
                   0.0, "No known fraud pattern was established, but legitimacy is not proven.")


def classify_pattern(context: PatternContext) -> PatternResult:
    """Choose the strongest supported pattern without forcing a known label."""
    detectors = (
        detect_card_testing, detect_card_not_present_new_device,
        detect_card_not_present_fraud, detect_out_of_region_use, detect_account_takeover,
    )
    results = [detector(context) for detector in detectors]
    positive = [result for result in results if result.strength > 0]
    if positive:
        priority = {
            FraudPattern.CARD_TESTING: 0,
            FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE: 1,
            FraudPattern.CARD_NOT_PRESENT_FRAUD: 2,
            FraudPattern.OUT_OF_REGION_USE: 3,
            FraudPattern.ACCOUNT_TAKEOVER: 4,
        }
        return max(positive, key=lambda result: (result.strength, -priority[result.pattern]))
    undocumented = detect_undocumented(
        PatternContext(
            target=context.target, card_history=context.card_history,
            customer_history=context.customer_history, network_transactions=context.network_transactions,
            connected_card_ids=context.connected_card_ids,
            confirmed_related_case_ids=context.confirmed_related_case_ids,
            known_pattern_results=tuple(results),
            customer_confirmed_legitimate=context.customer_confirmed_legitimate,
        )
    )
    return undocumented if undocumented.pattern is FraudPattern.UNDOCUMENTED else detect_none(context)

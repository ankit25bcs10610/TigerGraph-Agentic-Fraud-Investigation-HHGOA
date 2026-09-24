"""Shared records and the data-source contract used by the agent's tools."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

# Device fingerprints in this dataset (model / browser / screen) are often generic: a blank or
# "Windows" desktop profile with a browser version serves hundreds of customers, and a new browser
# release packs them into a few weeks. A device seen with more customers than this is evidence only
# when it names a specific model (for example "SM-G935F Build/NRD90M") and at least BURST_SHARE of its
# customers used it around the alert: one unusual device serving many cards at once.
COMMON_DEVICE_CUSTOMERS = 10
BURST_SHARE = 0.25
GENERIC_DEVICE_INFO = {"", "windows", "macos", "mac os", "ios device", "linux", "trident/7.0", "samsung", "android"}
# A fraud ring is people sharing devices at the same time: ring expansion only follows
# transactions within this window of the flagged one, and stops at RING_MAX_CARDS cards.
RING_WINDOW = timedelta(days=7)
RING_MAX_CARDS = 60
# Graph-wide ring discovery: a device links cards when it behaves like one physical device
# serving several people in a burst (between these customer counts, within BURST_SPAN_HOURS).
BURST_MIN_CUSTOMERS = 3
BURST_SPAN_HOURS = 72


def parse_time(value: Any) -> datetime | None:
    """Parse ISO or TigerGraph ``YYYY-MM-DD HH:MM:SS`` timestamps into naive UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drop NaN


def clean(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


@dataclass(frozen=True)
class Txn:
    """One transaction with the identity signals the detectors need."""

    transaction_id: str
    customer_id: str
    card_id: str
    ts: datetime
    amount: float
    channel: str
    risk_score: float | None = None
    region: str | None = None
    email: str | None = None
    product_code: str | None = None
    device_profile_id: str | None = None
    device_status: str | None = None
    proxy_type: str | None = None
    match_status: str | None = None
    device_customers: int | None = None   # distinct customers ever seen on device_profile_id
    device_info: str | None = None        # the identity DeviceInfo behind device_profile_id


def specific_model(device_info: str | None) -> bool:
    """DeviceInfo names a device model or build rather than an operating-system family."""
    info = (device_info or "").strip().lower()
    return bool(info) and info not in GENERIC_DEVICE_INFO and not info.startswith("rv:")


def generic_device(total_customers: int, window_customers: int, device_info: str | None = None) -> bool:
    """A fingerprint shared by unrelated people, rather than one unusual device serving many cards at once."""
    if total_customers <= COMMON_DEVICE_CUSTOMERS:
        return False
    return not specific_model(device_info) or window_customers < BURST_SHARE * total_customers


@dataclass(frozen=True)
class ClosedCaseRecord:
    case_id: str
    customer_id: str
    card_id: str
    outcome: str
    pattern: str
    txn_ids: tuple[str, ...] = ()
    connected_card_ids: tuple[str, ...] = ()
    exposure_usd: float | None = None
    analyst_notes: str = ""
    opened_at: str = ""
    first_fraud_txn_id: str = ""

    @property
    def confirmed_fraud(self) -> bool:
        return self.outcome.strip().lower() in {"confirmed_fraud", "fraud", "fraud_confirmed"}


@dataclass(frozen=True)
class RingResult:
    """Bounded connected component around a device: the fraud-ring view."""

    seed_device: str
    devices: tuple[str, ...] = ()
    cards: tuple[str, ...] = ()
    customers: tuple[str, ...] = ()
    transactions: int = 0
    confirmed_cases: tuple[str, ...] = ()
    hops: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Community:
    """A connected group of cards and devices (cards linked through shared devices)."""

    community_id: str
    cards: tuple[str, ...]
    devices: tuple[str, ...]
    customers: tuple[str, ...]
    confirmed_cases: tuple[str, ...] = ()
    transactions: int = 0
    customer_count: int = 0

    @property
    def size(self) -> int:
        return self.customer_count or len(self.customers)


class CaseDataSource(Protocol):
    """Questions the agent may ask the graph. Each is exposed as one tool."""

    name: str

    def transaction(self, transaction_id: str) -> Txn | None: ...
    def customer_transactions(self, customer_id: str) -> list[Txn]: ...
    def device_transactions(self, device_profile_id: str) -> list[Txn]: ...
    def linked_closed_cases(self, customer_id: str, card_id: str, related_customers: set[str], related_txns: set[str]) -> list[ClosedCaseRecord]: ...
    def closed_cases_by_pattern(self, pattern: str, limit: int) -> list[ClosedCaseRecord]: ...
    def device_ring(self, device_profile_id: str, max_hops: int, around: datetime | None = None) -> RingResult: ...
    def communities(self, min_customers: int, top_k: int) -> list[Community]: ...
    def exists(self, entity_type: str, entity_id: str) -> bool: ...

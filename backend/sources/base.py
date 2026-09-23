"""Shared records and the data-source contract used by the agent's tools."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


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


class CaseDataSource(Protocol):
    """Questions the agent may ask the graph. Each is exposed as one tool."""

    name: str

    def transaction(self, transaction_id: str) -> Txn | None: ...
    def customer_transactions(self, customer_id: str) -> list[Txn]: ...
    def device_transactions(self, device_profile_id: str) -> list[Txn]: ...
    def linked_closed_cases(self, customer_id: str, card_id: str, related_customers: set[str], related_txns: set[str]) -> list[ClosedCaseRecord]: ...
    def closed_cases_by_pattern(self, pattern: str, limit: int) -> list[ClosedCaseRecord]: ...
    def device_ring(self, device_profile_id: str, max_hops: int) -> RingResult: ...
    def exists(self, entity_type: str, entity_id: str) -> bool: ...

"""Deterministic fraud-episode exposure calculation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _amount(row: Mapping[str, Any]) -> float:
    """Read the dataset amount field, accepting the normalized graph alias."""
    value = row.get("TransactionAmt", row.get("transaction_amt", row.get("amount_usd")))
    if value is None or value == "":
        raise ValueError("episode transaction is missing TransactionAmt")
    try:
        return abs(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid TransactionAmt value: {value!r}") from exc


def episode_exposure_usd(transactions: Sequence[Mapping[str, Any]]) -> float:
    """Sum absolute transaction amounts for explicitly episode-attributed rows."""
    return round(sum(_amount(transaction) for transaction in transactions), 2)


def episode_transaction_ids(transactions: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return stable IDs for the exact rows used in the exposure sum."""
    ids: list[str] = []
    for transaction in transactions:
        value = transaction.get("TransactionID", transaction.get("transaction_id"))
        if value is None or str(value).strip() == "":
            raise ValueError("episode transaction is missing TransactionID")
        ids.append(str(value))
    return ids


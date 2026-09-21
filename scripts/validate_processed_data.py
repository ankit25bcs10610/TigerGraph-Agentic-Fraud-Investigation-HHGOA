#!/usr/bin/env python3
"""Validate graph-ready CSVs and their raw-file references."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path


ENTITY_PRIMARY = {
    "customers.csv": "customer_id",
    "cards.csv": "card_id",
    "transactions_graph.csv": "transaction_id",
    "device_profiles.csv": "device_profile_id",
    "email_domains.csv": "email_domain",
    "billing_regions.csv": "region_code",
    "closed_cases_graph.csv": "case_id",
}
REQUIRED_FILES = (
    "customers.csv", "cards.csv", "transactions_graph.csv", "device_profiles.csv",
    "email_domains.csv", "billing_regions.csv", "closed_cases_graph.csv", "owns.csv",
    "made.csv", "from_device.csv", "purchaser_email.csv", "billed_in.csv",
    "next_transaction.csv", "closed_case_involves.csv", "closed_case_on_card.csv",
    "closed_case_connected_to.csv",
)


def clean(value: object | None) -> str:
    return "" if value is None else str(value).strip()


def split_pipe(value: object | None) -> list[str]:
    return [item for item in clean(value).split("|") if item]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    return parser.parse_args()


def raw_ids(data_dir: Path) -> tuple[set[str], dict[str, str], int, int]:
    transaction_ids: set[str] = set()
    transaction_customers: dict[str, str] = {}
    duplicate_ids = 0
    rows = 0
    with (data_dir / "transactions.csv").open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows += 1
            transaction_id = clean(row.get("TransactionID"))
            if transaction_id in transaction_ids:
                duplicate_ids += 1
            transaction_ids.add(transaction_id)
            transaction_customers[transaction_id] = clean(row.get("customer_id"))
    return transaction_ids, transaction_customers, rows, duplicate_ids


def generated_file_stats(path: Path, primary: str | None) -> tuple[int, dict[str, int], int, set[str], list[str]]:
    row_count = 0
    missing: Counter[str] = Counter()
    duplicates = 0
    ids: set[str] = set()
    headers: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        for row in reader:
            row_count += 1
            for field in headers:
                if clean(row.get(field)) == "":
                    missing[field] += 1
            if primary:
                value = clean(row.get(primary))
                if value in ids:
                    duplicates += 1
                ids.add(value)
    return row_count, dict(missing), duplicates, ids, headers


def edge_broken(path: Path, source_field: str, source_ids: set[str], target_field: str, target_ids: set[str]) -> dict[str, int]:
    failures: Counter[str] = Counter()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if clean(row.get(source_field)) not in source_ids:
                failures["source"] += 1
            if clean(row.get(target_field)) not in target_ids:
                failures["target"] += 1
    return dict(failures)


def validate(args: argparse.Namespace) -> tuple[dict[str, object], bool]:
    data_dir = args.data_dir
    processed_dir = args.processed_dir
    missing_files = [name for name in REQUIRED_FILES if not (processed_dir / name).exists()]
    if missing_files:
        return {"missing_generated_files": missing_files}, False

    file_counts: dict[str, int] = {}
    missing_values: dict[str, dict[str, int]] = {}
    duplicate_primary_ids: dict[str, int] = {}
    entity_ids: dict[str, set[str]] = {}
    for filename in REQUIRED_FILES:
        primary = ENTITY_PRIMARY.get(filename)
        count, missing, duplicates, ids, _ = generated_file_stats(processed_dir / filename, primary)
        file_counts[filename] = count
        if missing:
            missing_values[filename] = missing
        if duplicates:
            duplicate_primary_ids[filename] = duplicates
        if primary:
            entity_ids[filename] = ids

    customers = entity_ids["customers.csv"]
    cards = entity_ids["cards.csv"]
    transactions = entity_ids["transactions_graph.csv"]
    devices = entity_ids["device_profiles.csv"]
    domains = entity_ids["email_domains.csv"]
    regions = entity_ids["billing_regions.csv"]
    cases = entity_ids["closed_cases_graph.csv"]

    edge_specs = {
        "owns.csv": ("customer_id", customers, "card_id", cards),
        "made.csv": ("card_id", cards, "transaction_id", transactions),
        "from_device.csv": ("transaction_id", transactions, "device_profile_id", devices),
        "purchaser_email.csv": ("transaction_id", transactions, "email_domain", domains),
        "billed_in.csv": ("transaction_id", transactions, "region_code", regions),
        "next_transaction.csv": ("source_transaction_id", transactions, "target_transaction_id", transactions),
        "closed_case_involves.csv": ("case_id", cases, "transaction_id", transactions),
        "closed_case_on_card.csv": ("case_id", cases, "card_id", cards),
        "closed_case_connected_to.csv": ("case_id", cases, "card_id", cards),
    }
    broken_edges = {
        filename: failures
        for filename, (source_field, source_ids, target_field, target_ids) in edge_specs.items()
        if (failures := edge_broken(processed_dir / filename, source_field, source_ids, target_field, target_ids))
    }

    made_transactions: set[str] = set()
    with (processed_dir / "made.csv").open(newline="", encoding="utf-8-sig") as handle:
        made_transactions = {clean(row.get("transaction_id")) for row in csv.DictReader(handle)}
    transactions_without_card_mapping = sorted(transactions - made_transactions)

    raw_transaction_ids, raw_transaction_customers, raw_tx_rows, raw_tx_duplicates = raw_ids(data_dir)
    identity_ids: set[str] = set()
    identity_duplicates = 0
    with (data_dir / "identity.csv").open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            transaction_id = clean(row.get("TransactionID"))
            if transaction_id in identity_ids:
                identity_duplicates += 1
            identity_ids.add(transaction_id)
    identity_without_transaction = sorted(identity_ids - raw_transaction_ids)

    generated_case_ids = cases
    case_txn_unresolved: dict[str, list[str]] = {}
    case_card_unresolved: dict[str, list[str]] = {}
    source_case_rows = 0
    with (data_dir / "closed_cases_history.csv").open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            case_id = clean(row.get("case_id"))
            if case_id not in generated_case_ids:
                continue
            source_case_rows += 1
            missing_txn = sorted(set(split_pipe(row.get("txn_ids"))) - transactions)
            missing_cards = sorted(
                ({clean(row.get("card_id"))} | set(split_pipe(row.get("connected_card_ids")))) - cards
            )
            if missing_txn:
                case_txn_unresolved[case_id] = missing_txn
            if missing_cards:
                case_card_unresolved[case_id] = missing_cards

    result = {
        "generated_row_counts": file_counts,
        "duplicate_primary_ids": duplicate_primary_ids,
        "broken_edge_references": broken_edges,
        "missing_or_null_values": missing_values,
        "transactions_without_card_mappings": transactions_without_card_mapping,
        "identity_records_without_matching_transactions": identity_without_transaction,
        "closed_case_transaction_ids_unresolved": case_txn_unresolved,
        "connected_or_main_card_ids_unresolved": case_card_unresolved,
        "source_checks": {
            "transaction_rows": raw_tx_rows,
            "duplicate_transaction_ids": raw_tx_duplicates,
            "identity_rows": len(identity_ids),
            "duplicate_identity_transaction_ids": identity_duplicates,
            "closed_case_rows_represented": source_case_rows,
        },
    }
    hard_failures = any((
        duplicate_primary_ids,
        broken_edges,
        transactions_without_card_mapping,
        identity_without_transaction,
        case_txn_unresolved,
        case_card_unresolved,
        raw_tx_duplicates,
        identity_duplicates,
    ))
    return result, not hard_failures


def main() -> int:
    args = parse_args()
    try:
        result, passed = validate(args)
    except FileNotFoundError as exc:
        print(f"VALIDATION FAILED: missing file {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("VALIDATION: PASSED" if passed else "VALIDATION: FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

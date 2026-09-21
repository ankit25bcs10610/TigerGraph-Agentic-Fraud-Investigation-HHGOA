#!/usr/bin/env python3
"""Prepare raw fraud data as CSV files for the existing TigerGraph schema.

The script does not connect to TigerGraph.  It only reads the supplied CSVs,
constructs the validated customer-scoped card labels, and writes graph-ready
vertices and edges under data/processed (or an explicitly supplied directory).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


CARD_FIELDS = ("card1", "card2", "card3", "card4", "card5", "card6")
# Validated against every closed-case transaction reference and all 20
# benchmark flagged transactions.  card2/card3/card5 are retained in the
# raw transaction source but do not distinguish the case card labels.
CARD_ID_FIELDS = ("card1", "card4", "card6")
DEVICE_FIELDS = {
    "device_info": "DeviceInfo",
    "device_type": "DeviceType",
    "os": "id_30",
    "browser": "id_31",
    "screen": "id_33",
}
TRANSACTION_REQUIRED = {
    "TransactionID", "TransactionAmt", "TransactionDT", "ProductCD",
    "customer_id", "ts", "channel", "risk_score", *CARD_FIELDS,
}
IDENTITY_REQUIRED = {"TransactionID", *DEVICE_FIELDS.values()}
CLOSED_CASE_REQUIRED = {
    "case_id", "customer_id", "card_id", "opened_at", "closed_at", "outcome",
    "pattern", "first_fraud_txn_id", "txn_ids", "n_txns", "exposure_usd",
    "connected_card_ids", "actions_taken", "report_filed", "analyst_notes",
}
CASE_PACK_REQUIRED = {
    "case_id", "opened_at", "trigger_type", "trigger_text", "flagged_txn_id",
    "card_id", "customer_id", "risk_score",
}

OUTPUT_FIELDS: dict[str, tuple[str, ...]] = {
    "customers.csv": ("customer_id",),
    "cards.csv": ("card_id", "customer_id"),
    "transactions_graph.csv": (
        "transaction_id", "transaction_amt", "transaction_dt", "ts", "channel",
        "risk_score", "product_cd",
    ),
    "device_profiles.csv": (
        "device_profile_id", "device_info", "device_type", "os", "browser", "screen",
    ),
    "email_domains.csv": ("email_domain",),
    "billing_regions.csv": ("region_code",),
    "closed_cases_graph.csv": (
        "case_id", "customer_id", "card_id", "opened_at", "closed_at", "outcome",
        "pattern", "first_fraud_txn_id", "n_txns", "exposure_usd", "actions_taken",
        "report_filed", "analyst_notes",
    ),
    "owns.csv": ("customer_id", "card_id"),
    "made.csv": ("card_id", "transaction_id"),
    "from_device.csv": ("transaction_id", "device_profile_id"),
    "purchaser_email.csv": ("transaction_id", "email_domain"),
    "billed_in.csv": ("transaction_id", "region_code"),
    "next_transaction.csv": ("source_transaction_id", "target_transaction_id"),
    "closed_case_involves.csv": ("case_id", "transaction_id"),
    "closed_case_on_card.csv": ("case_id", "card_id"),
    "closed_case_connected_to.csv": ("case_id", "card_id"),
}


def clean(value: object | None) -> str:
    return "" if value is None else str(value).strip()


def split_pipe(value: object | None) -> list[str]:
    return [item for item in clean(value).split("|") if item]


def require_headers(path: Path, required: set[str]) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise ValueError(f"{path} is empty") from exc
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")
    return headers


def rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def fingerprint(row: dict[str, str]) -> tuple[str, ...] | None:
    values = tuple(clean(row.get(field)) for field in CARD_ID_FIELDS)
    return values if any(values) else None


def device_profile(row: dict[str, str]) -> tuple[str, tuple[str, ...]] | None:
    values = tuple(clean(row.get(source)) for source in DEVICE_FIELDS.values())
    if not any(values):
        return None
    digest = hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()[:32]
    return f"DP-{digest}", values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--sample", action="store_true", help="benchmark-linked development sample")
    modes.add_argument("--full", action="store_true", help="complete source dataset")
    return parser.parse_args()


def load_cases(path: Path, required: set[str]) -> list[dict[str, object]]:
    require_headers(path, required)
    result: list[dict[str, object]] = []
    for row in rows(path):
        item = dict(row)
        item["txn_id_list"] = split_pipe(row.get("txn_ids"))
        item["connected_card_list"] = split_pipe(row.get("connected_card_ids"))
        result.append(item)
    return result


def build_card_index(tx_path: Path) -> tuple[
    dict[str, set[tuple[str, ...]]], dict[str, str], dict[str, str], dict[str, str], int
]:
    """Build the only card mapping supported by the supplied data.

    A card fingerprint is the observed (card1, card4, card6) tuple.  It is
    scoped to customer_id because the source has no literal card_id.  Sorted
    distinct fingerprints receive the K ordinal used by the case files.
    """
    require_headers(tx_path, TRANSACTION_REQUIRED)
    customer_fingerprints: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    transaction_customers: dict[str, str] = {}
    transaction_fingerprints: dict[str, tuple[str, ...] | None] = {}
    transaction_count = 0
    for row in rows(tx_path):
        transaction_count += 1
        transaction_id = clean(row.get("TransactionID"))
        customer_id = clean(row.get("customer_id"))
        if not transaction_id or not customer_id:
            raise ValueError(f"transaction row {transaction_count} has empty ID or customer_id")
        if transaction_id in transaction_customers:
            raise ValueError(f"duplicate TransactionID in source: {transaction_id}")
        fp = fingerprint(row)
        transaction_customers[transaction_id] = customer_id
        transaction_fingerprints[transaction_id] = fp
        if fp is not None:
            customer_fingerprints[customer_id].add(fp)

    card_by_customer_fingerprint: dict[tuple[str, tuple[str, ...]], str] = {}
    for customer_id, fingerprints in customer_fingerprints.items():
        for ordinal, fp in enumerate(sorted(fingerprints), start=1):
            card_by_customer_fingerprint[(customer_id, fp)] = f"{customer_id}-K{ordinal}"

    transaction_cards: dict[str, str] = {}
    for transaction_id, customer_id in transaction_customers.items():
        fp = transaction_fingerprints[transaction_id]
        if fp is not None:
            transaction_cards[transaction_id] = card_by_customer_fingerprint[(customer_id, fp)]
    return (
        customer_fingerprints,
        card_by_customer_fingerprint,
        transaction_cards,
        transaction_customers,
        transaction_count,
    )


def validate_case_card_labels(
    case_pack: list[dict[str, object]],
    closed_cases: list[dict[str, object]],
    transaction_cards: dict[str, str],
) -> dict[str, list[str]]:
    unresolved: dict[str, list[str]] = defaultdict(list)
    for row in case_pack:
        flagged = clean(row.get("flagged_txn_id"))
        declared = clean(row.get("card_id"))
        mapped = transaction_cards.get(flagged)
        if mapped is None:
            unresolved["case_pack_flagged_transactions_without_card_mapping"].append(flagged)
        elif mapped != declared:
            raise ValueError(
                f"case-pack card mapping mismatch for {row.get('case_id')}: "
                f"{declared} != {mapped} from the flagged transaction"
            )
    for row in closed_cases:
        declared = clean(row.get("card_id"))
        mapped_cards = {transaction_cards[tid] for tid in row["txn_id_list"] if tid in transaction_cards}
        if mapped_cards and declared not in mapped_cards:
            raise ValueError(
                f"closed-case card mapping mismatch for {row.get('case_id')}: "
                f"{declared} not in transaction-derived cards {sorted(mapped_cards)}"
            )
        if not mapped_cards:
            unresolved["closed_case_cards_without_transaction_mapping"].append(declared)
    return dict(unresolved)


def choose_records(
    *,
    full: bool,
    case_pack: list[dict[str, object]],
    closed_cases: list[dict[str, object]],
    transaction_cards: dict[str, str],
    transaction_customers: dict[str, str],
) -> tuple[set[str], set[str]]:
    if full:
        return set(transaction_customers), {card for card in transaction_cards.values()}

    benchmark_customers = {clean(row.get("customer_id")) for row in case_pack}
    benchmark_cards = {clean(row.get("card_id")) for row in case_pack}
    flagged_transactions = {clean(row.get("flagged_txn_id")) for row in case_pack}

    selected_transactions = {
        transaction_id
        for transaction_id, customer_id in transaction_customers.items()
        if customer_id in benchmark_customers
        or transaction_cards.get(transaction_id) in benchmark_cards
        or transaction_id in flagged_transactions
    }
    selected_cards = {
        transaction_cards[transaction_id]
        for transaction_id in selected_transactions
        if transaction_id in transaction_cards
    } | benchmark_cards

    relevant_cases = [
        row for row in closed_cases
        if clean(row.get("customer_id")) in benchmark_customers
        or clean(row.get("card_id")) in selected_cards
        or set(row["txn_id_list"]) & selected_transactions
        or set(row["connected_card_list"]) & selected_cards
    ]
    for row in relevant_cases:
        selected_transactions.update(row["txn_id_list"])
        selected_cards.add(clean(row.get("card_id")))
        selected_cards.update(row["connected_card_list"])

    # Close the sample over the actual selected cards and benchmark customers,
    # without treating the first N raw transactions as a valid graph sample.
    for transaction_id, customer_id in transaction_customers.items():
        card_id = transaction_cards.get(transaction_id)
        if customer_id in benchmark_customers or card_id in selected_cards:
            selected_transactions.add(transaction_id)
            if card_id:
                selected_cards.add(card_id)
    return selected_transactions, selected_cards


def output_paths(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: output_dir / name for name in OUTPUT_FIELDS}
    for path in paths.values():
        if path.exists():
            path.unlink()
    return paths


class ManagedWriter:
    def __init__(self, path: Path, fields: tuple[str, ...]) -> None:
        self.handle = path.open("w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.handle, lineterminator="\n")
        self.writer.writerow(fields)

    def writerow(self, values: Iterable[object]) -> None:
        self.writer.writerow(values)

    def close(self) -> None:
        self.handle.close()


def prepare(args: argparse.Namespace) -> dict[str, object]:
    data_dir = args.data_dir
    tx_path = data_dir / "transactions.csv"
    identity_path = data_dir / "identity.csv"
    closed_path = data_dir / "closed_cases_history.csv"
    case_pack_path = data_dir / "case_pack.csv"
    for path in (tx_path, identity_path, closed_path, case_pack_path):
        if not path.exists():
            raise FileNotFoundError(path)

    case_pack = load_cases(case_pack_path, CASE_PACK_REQUIRED)
    closed_cases = load_cases(closed_path, CLOSED_CASE_REQUIRED)
    _, card_map, transaction_cards, transaction_customers, source_tx_count = build_card_index(tx_path)
    card_mapping_unresolved = validate_case_card_labels(case_pack, closed_cases, transaction_cards)
    selected_transactions, selected_cards = choose_records(
        full=args.full,
        case_pack=case_pack,
        closed_cases=closed_cases,
        transaction_cards=transaction_cards,
        transaction_customers=transaction_customers,
    )
    selected_cases = closed_cases if args.full else [
        row for row in closed_cases
        if clean(row.get("customer_id")) in {clean(item.get("customer_id")) for item in case_pack}
        or clean(row.get("card_id")) in selected_cards
        or set(row["txn_id_list"]) & selected_transactions
        or set(row["connected_card_list"]) & selected_cards
    ]

    paths = output_paths(args.output_dir)
    writers = {name: ManagedWriter(path, OUTPUT_FIELDS[name]) for name, path in paths.items()}
    counts = {name: 0 for name in paths}
    selected_customer_ids: set[str] = set()
    selected_card_ids_from_transactions: set[str] = set()
    selected_transaction_rows: dict[str, tuple[str, str]] = {}
    email_domains: set[str] = set()
    billing_regions: set[str] = set()
    next_by_card: dict[str, list[tuple[str, str]]] = defaultdict(list)

    try:
        with tx_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                transaction_id = clean(row.get("TransactionID"))
                if transaction_id not in selected_transactions:
                    continue
                customer_id = clean(row.get("customer_id"))
                card_id = transaction_cards.get(transaction_id)
                selected_customer_ids.add(customer_id)
                if card_id:
                    selected_card_ids_from_transactions.add(card_id)
                    next_by_card[card_id].append((clean(row.get("ts")), transaction_id))
                    writers["made.csv"].writerow((card_id, transaction_id))
                    counts["made.csv"] += 1
                writers["transactions_graph.csv"].writerow((
                    transaction_id, clean(row.get("TransactionAmt")), clean(row.get("TransactionDT")),
                    clean(row.get("ts")), clean(row.get("channel")), clean(row.get("risk_score")),
                    clean(row.get("ProductCD")),
                ))
                counts["transactions_graph.csv"] += 1
                selected_transaction_rows[transaction_id] = (clean(row.get("ts")), card_id or "")
                email = clean(row.get("P_emaildomain"))
                if email:
                    email_domains.add(email)
                    writers["purchaser_email.csv"].writerow((transaction_id, email))
                    counts["purchaser_email.csv"] += 1
                region = clean(row.get("addr1"))
                if region:
                    billing_regions.add(region)
                    writers["billed_in.csv"].writerow((transaction_id, region))
                    counts["billed_in.csv"] += 1

        all_card_ids = set(card_map.values())
        selected_card_ids = selected_card_ids_from_transactions | {
            card_id for card_id in selected_cards if card_id in all_card_ids
        }
        selected_customer_ids.update(
            clean(row.get("customer_id")) for row in selected_cases if clean(row.get("customer_id"))
        )
        for customer_id in sorted(selected_customer_ids):
            writers["customers.csv"].writerow((customer_id,))
            counts["customers.csv"] += 1
        reverse_cards = {card_id: (customer_id, fp) for (customer_id, fp), card_id in card_map.items()}
        for card_id in sorted(selected_card_ids):
            customer_id = reverse_cards[card_id][0]
            writers["cards.csv"].writerow((card_id, customer_id))
            writers["owns.csv"].writerow((customer_id, card_id))
            counts["cards.csv"] += 1
            counts["owns.csv"] += 1
        for email in sorted(email_domains):
            writers["email_domains.csv"].writerow((email,))
            counts["email_domains.csv"] += 1
        for region in sorted(billing_regions):
            writers["billing_regions.csv"].writerow((region,))
            counts["billing_regions.csv"] += 1

        for card_id, events in next_by_card.items():
            events.sort(key=lambda item: (item[0], item[1]))
            for (source_ts, source_id), (_, target_id) in zip(events, events[1:]):
                del source_ts
                writers["next_transaction.csv"].writerow((source_id, target_id))
                counts["next_transaction.csv"] += 1

        require_headers(identity_path, IDENTITY_REQUIRED)
        seen_profiles: set[str] = set()
        with identity_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                transaction_id = clean(row.get("TransactionID"))
                if transaction_id not in selected_transaction_rows:
                    continue
                profile = device_profile(row)
                if profile is None:
                    continue
                profile_id, values = profile
                if profile_id not in seen_profiles:
                    writers["device_profiles.csv"].writerow((profile_id, *values))
                    counts["device_profiles.csv"] += 1
                    seen_profiles.add(profile_id)
                writers["from_device.csv"].writerow((transaction_id, profile_id))
                counts["from_device.csv"] += 1

        generated_transaction_ids = set(selected_transaction_rows)
        generated_card_ids = set(selected_card_ids)
        for row in selected_cases:
            case_id = clean(row.get("case_id"))
            writers["closed_cases_graph.csv"].writerow(tuple(clean(row.get(field)) for field in OUTPUT_FIELDS["closed_cases_graph.csv"]))
            counts["closed_cases_graph.csv"] += 1
            for transaction_id in dict.fromkeys(row["txn_id_list"]):
                if transaction_id in generated_transaction_ids:
                    writers["closed_case_involves.csv"].writerow((case_id, transaction_id))
                    counts["closed_case_involves.csv"] += 1
            card_id = clean(row.get("card_id"))
            if card_id in generated_card_ids:
                writers["closed_case_on_card.csv"].writerow((case_id, card_id))
                counts["closed_case_on_card.csv"] += 1
            for connected in dict.fromkeys(row["connected_card_list"]):
                if connected in generated_card_ids:
                    writers["closed_case_connected_to.csv"].writerow((case_id, connected))
                    counts["closed_case_connected_to.csv"] += 1
    finally:
        for writer in writers.values():
            writer.close()

    unresolved: dict[str, list[str]] = defaultdict(list)
    for key, values in card_mapping_unresolved.items():
        unresolved[key].extend(values)
    case_cards = {
        clean(row.get("card_id")) for row in selected_cases
    } | {
        card_id for row in selected_cases for card_id in row["connected_card_list"]
    }
    unresolved["selected_case_cards_not_generated"] = sorted(case_cards - selected_card_ids)
    unresolved["selected_case_transactions_not_generated"] = sorted(
        {tid for row in selected_cases for tid in row["txn_id_list"]} - set(selected_transaction_rows)
    )
    return {
        "mode": "full" if args.full else "sample",
        "source_transaction_rows": source_tx_count,
        "selected_transaction_rows": counts["transactions_graph.csv"],
        "selected_closed_cases": counts["closed_cases_graph.csv"],
        "card_mapping": "customer_id + sorted distinct (card1, card4, card6) fingerprint -> customer_id-Kordinal",
        "output_counts": counts,
        "unresolved": {key: sorted(set(values)) for key, values in unresolved.items() if values},
    }


def main() -> int:
    args = parse_args()
    try:
        summary = prepare(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"PREPARATION FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate source relationships and prepared TigerGraph TSV integrity."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

NULL_TOKEN = r"\N"

def args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--prepared-dir", type=Path, default=Path("build/graph_data"))
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--sample", type=int, metavar="N")
    mode.add_argument("--full", action="store_true")
    return p.parse_args()

def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)

def read_tsv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f, delimiter="\t")

def split_pipe(value: str | None):
    return [x.strip() for x in (value or "").split("|") if x.strip()]

def main():
    a = args()
    data = a.data_dir
    prepared = a.prepared_dir
    required = ["transactions.csv", "identity.csv", "closed_cases_history.csv", "case_pack.csv"]
    missing = [x for x in required if not (data / x).exists()]
    if missing:
        raise SystemExit("missing input files: " + ", ".join(missing))

    tx_ids = set()
    tx_customer = {}
    tx_ts = {}
    tx_fingerprint = {}
    fingerprints = defaultdict(set)
    tx_duplicates = 0
    tx_rows = 0
    tx_customer_counts = Counter()
    sample_limit = a.sample
    with (data / "transactions.csv").open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        expected = {"TransactionID", "customer_id", "ts", "risk_score", "channel", "ProductCD"}
        missing_cols = expected - set(reader.fieldnames or [])
        if missing_cols:
            raise SystemExit(f"transactions.csv missing columns: {sorted(missing_cols)}")
        for row in reader:
            if sample_limit is not None and tx_rows >= sample_limit:
                break
            tx_rows += 1
            tid = (row["TransactionID"] or "").strip()
            customer = (row["customer_id"] or "").strip()
            if tid in tx_ids:
                tx_duplicates += 1
            tx_ids.add(tid)
            tx_customer[tid] = customer
            tx_ts[tid] = row["ts"]
            fp = tuple((row.get(k) or "").strip() for k in ["card1", "card2", "card3", "card4", "card5", "card6"])
            if any(fp):
                tx_fingerprint[tid] = fp
                fingerprints[customer].add(fp)
            tx_customer_counts[customer] += 1

    card_map = {}
    for customer, fps in fingerprints.items():
        for ordinal, fp in enumerate(sorted(fps), start=1):
            card_map[(customer, fp)] = f"{customer}-K{ordinal}"

    identity_ids = set()
    identity_duplicates = 0
    identity_total = 0
    identity_not_tx = 0
    with (data / "identity.csv").open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            identity_total += 1
            tid = (row["TransactionID"] or "").strip()
            if tid in identity_ids:
                identity_duplicates += 1
            identity_ids.add(tid)
            if tid not in tx_ids:
                identity_not_tx += 1

    case_total = 0
    case_included = 0
    case_tx_refs = 0
    case_tx_invalid = 0
    case_customer_mismatch = 0
    case_n_mismatch = 0
    case_ids = set()
    case_card_ids = set()
    connected_card_ids = set()
    card_label_mapping_mismatches = 0
    card_label_mapping_cases = set()
    with (data / "closed_cases_history.csv").open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            case_total += 1
            case_ids.add(row["case_id"])
            tids = split_pipe(row["txn_ids"])
            case_tx_refs += len(tids)
            if len(tids) != int(row["n_txns"]):
                case_n_mismatch += 1
            included = [tid for tid in tids if tid in tx_ids]
            if included:
                case_included += 1
            case_tx_invalid += sum(tid not in tx_ids for tid in tids)
            for tid in included:
                if row["customer_id"] != tx_customer[tid]:
                    case_customer_mismatch += 1
                fp = tx_fingerprint.get(tid)
                if fp and row["card_id"] != card_map.get((row["customer_id"], fp)):
                    card_label_mapping_mismatches += 1
                    card_label_mapping_cases.add(row["case_id"])
            if row["card_id"]:
                case_card_ids.add(row["card_id"])
            connected_card_ids.update(split_pipe(row["connected_card_ids"]))

    pack_total = 0
    pack_invalid = 0
    pack_customer_mismatch = 0
    with (data / "case_pack.csv").open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pack_total += 1
            tid = row["flagged_txn_id"]
            if tid not in tx_ids:
                pack_invalid += 1
            elif row["customer_id"] != tx_customer[tid]:
                pack_customer_mismatch += 1

    result = {
        "source": {
            "transactions_selected": tx_rows,
            "transaction_ids": len(tx_ids),
            "duplicate_transaction_ids": tx_duplicates,
            "identity_rows_read": identity_total,
            "identity_ids": len(identity_ids),
            "identity_duplicates": identity_duplicates,
            "identity_not_in_selected_transactions": identity_not_tx,
            "closed_cases": case_total,
            "closed_cases_with_selected_transactions": case_included,
            "closed_case_transaction_references": case_tx_refs,
            "closed_case_invalid_transaction_references": case_tx_invalid,
            "closed_case_n_txns_mismatches": case_n_mismatch,
            "closed_case_customer_mismatches": case_customer_mismatch,
            "closed_case_card_label_mapping_mismatches": card_label_mapping_mismatches,
            "closed_case_card_label_mapping_mismatch_cases": len(card_label_mapping_cases),
            "case_card_ids": len(case_card_ids),
            "connected_card_ids": len(connected_card_ids),
            "case_pack_rows_checked": pack_total,
            "case_pack_invalid_flagged_transactions": pack_invalid,
            "case_pack_customer_mismatches": pack_customer_mismatch,
            "case_pack_loaded": False,
        }
    }

    if prepared.exists() and (prepared / "manifest.json").exists():
        result["prepared"] = json.loads((prepared / "manifest.json").read_text(encoding="utf-8"))
        required_outputs = [
            "customer.tsv", "card.tsv", "transaction.tsv", "owns.tsv", "made.tsv",
            "device_profile.tsv", "from_device.tsv", "email_domain.tsv",
            "purchaser_email.tsv", "billing_region.tsv", "billed_in.tsv", "next.tsv",
            "closed_case.tsv", "involves.tsv", "on_card.tsv", "connected_to.tsv",
        ]
        missing_outputs = [x for x in required_outputs if not (prepared / x).exists()]
        result["prepared"]["missing_output_files"] = missing_outputs
        card_ids = {r["card_id"] for r in read_tsv(prepared / "card.tsv")}
        generated_card_ids = {
            r["card_id"] for r in read_tsv(prepared / "card.tsv")
            if r["card1"] != NULL_TOKEN
        }
        prepared_case_cards = set()
        for row in read_tsv(prepared / "closed_case.tsv"):
            if row["card_id"] != NULL_TOKEN:
                prepared_case_cards.add(row["card_id"])
            prepared_case_cards.update(split_pipe(row["connected_card_ids"]))
        case_card_unresolved = sorted(prepared_case_cards - card_ids)
        result["prepared"]["card_ids_missing_from_card_vertex"] = len(case_card_unresolved)
        result["prepared"]["case_card_labels_not_backed_by_transaction_fingerprint"] = len(
            prepared_case_cards - generated_card_ids
        )
        # Confirm all prepared edge endpoint IDs exist in the corresponding vertex sets.
        customers = {r["customer_id"] for r in read_tsv(prepared / "customer.tsv")}
        transactions = {r["transaction_id"] for r in read_tsv(prepared / "transaction.tsv")}
        devices = {r["device_profile_id"] for r in read_tsv(prepared / "device_profile.tsv")}
        domains = {r["email_domain"] for r in read_tsv(prepared / "email_domain.tsv")}
        regions = {r["billing_region_id"] for r in read_tsv(prepared / "billing_region.tsv")}
        cases = {r["case_id"] for r in read_tsv(prepared / "closed_case.tsv")}
        endpoint_failures = Counter()
        for filename, left, right, left_set, right_set in [
            ("owns.tsv", "from_id", "to_id", customers, card_ids),
            ("made.tsv", "from_id", "to_id", card_ids, transactions),
            ("from_device.tsv", "from_id", "to_id", transactions, devices),
            ("purchaser_email.tsv", "from_id", "to_id", transactions, domains),
            ("billed_in.tsv", "from_id", "to_id", transactions, regions),
            ("involves.tsv", "from_id", "to_id", cases, transactions),
            ("on_card.tsv", "from_id", "to_id", cases, card_ids),
            ("connected_to.tsv", "from_id", "to_id", cases, card_ids),
        ]:
            for row in read_tsv(prepared / filename):
                if row[left] not in left_set:
                    endpoint_failures[f"{filename}:from"] += 1
                if row[right] not in right_set:
                    endpoint_failures[f"{filename}:to"] += 1
        result["prepared"]["edge_endpoint_failures"] = dict(endpoint_failures)

    print(json.dumps(result, indent=2))
    # Sample mode intentionally excludes most source references. Report them,
    # but only enforce cross-file reference checks for the full dataset.
    hard = [tx_duplicates, identity_duplicates, case_n_mismatch, case_customer_mismatch]
    if sample_limit is None:
        hard.extend([identity_not_tx, case_tx_invalid, pack_invalid, pack_customer_mismatch])
    if prepared.exists() and (prepared / "manifest.json").exists():
        hard.append(len(result["prepared"].get("missing_output_files", [])))
        hard.append(sum(result["prepared"].get("edge_endpoint_failures", {}).values()))
    if any(hard):
        print("VALIDATION: FAILED", file=sys.stderr)
        return 1
    print("VALIDATION: PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

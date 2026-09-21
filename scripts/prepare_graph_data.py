#!/usr/bin/env python3
"""Prepare normalized, null-safe TSV files for the TigerGraph fraud schema."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

NULL_TOKEN = r"\N"
CARD_FIELDS = ["card1", "card2", "card3", "card4", "card5", "card6"]
TX_FIELDS = [
    "TransactionID", "TransactionDT", "TransactionAmt", "ProductCD",
    *CARD_FIELDS, "addr1", "addr2", "dist1", "dist2",
    "P_emaildomain", "R_emaildomain",
    *[f"C{i}" for i in range(1, 15)],
    *[f"D{i}" for i in range(1, 16)],
    *[f"M{i}" for i in range(1, 10)],
    *[f"V{i}" for i in range(1, 340)],
    "customer_id", "ts", "channel", "risk_score",
]
TX_OUT_FIELDS = [
    "transaction_id", "transaction_dt", "transaction_amt", "product_cd",
    "customer_id", "ts", "channel", "risk_score",
    *CARD_FIELDS, "addr1", "addr2", "dist1", "dist2",
    "p_emaildomain", "r_emaildomain",
    *[f"c{i}" for i in range(1, 15)],
    *[f"d{i}" for i in range(1, 16)],
    *[f"m{i}" for i in range(1, 10)],
    *[f"v{i}" for i in range(1, 340)],
]
IDENTITY_FIELDS = ["TransactionID", *[f"id_{i:02d}" for i in range(1, 39)], "DeviceType", "DeviceInfo"]

def clean(value: str | None) -> str:
    value = (value or "").strip()
    return value if value else NULL_TOKEN

def present(value: str | None) -> bool:
    return bool((value or "").strip())

def safe_num(value: str | None) -> str:
    return clean(value)

def path_for(data_dir: Path, name: str) -> Path:
    return data_dir / name

def card_fingerprint(row: dict[str, str]) -> tuple[str, ...] | None:
    values = tuple((row.get(k) or "").strip() for k in CARD_FIELDS)
    return values if any(values) else None

def card_id(customer_id: str, fingerprint: tuple[str, ...], ordinal: int) -> str:
    # Dataset card labels use Cxxxxx-Kn. The ordinal is deterministic within
    # this supplied dataset and is based on the canonical raw card fingerprint.
    return f"{customer_id}-K{ordinal}"

def device_profile(row: dict[str, str]) -> tuple[str, dict[str, str]] | None:
    values = {
        "device_info": (row.get("DeviceInfo") or "").strip(),
        "device_type": (row.get("DeviceType") or "").strip(),
        "os": (row.get("id_30") or "").strip(),
        "browser": (row.get("id_31") or "").strip(),
        "screen": (row.get("id_33") or "").strip(),
        "device_status": (row.get("id_15") or "").strip(),
        "proxy_type": (row.get("id_23") or "").strip(),
        "match_status": (row.get("id_34") or "").strip(),
    }
    if not any(values.values()):
        return None
    canonical = "\x1f".join(values[k] for k in values)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return "DP-" + digest, values

def write_tsv(path: Path, fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8", newline="")

def write_row(writer: csv.writer, values: Iterable[str]):
    writer.writerow([clean(v) if v != NULL_TOKEN else NULL_TOKEN for v in values])

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("build/graph_data"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sample", nargs="?", const=1000, type=int, metavar="N",
                      help="prepare the first N transactions and related records (default: 1000)")
    mode.add_argument("--full", action="store_true", help="prepare all source records")
    return parser.parse_args()

def load_transaction_selection(tx_path: Path, sample: int | None):
    selected_ids: set[str] = set()
    selected_rows: int | None = None if sample is None else sample
    fingerprints: defaultdict[str, set[tuple[str, ...]]] = defaultdict(set)
    customer_ids: set[str] = set()
    rows = 0
    duplicates = 0
    seen_ids: set[str] = set()

    with tx_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = set(TX_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"transactions.csv missing columns: {sorted(missing)}")
        for row in reader:
            if sample is not None and rows >= sample:
                break
            rows += 1
            tid = (row.get("TransactionID") or "").strip()
            customer = (row.get("customer_id") or "").strip()
            if not tid or not customer:
                raise ValueError(f"transaction row {rows} has empty TransactionID/customer_id")
            if tid in seen_ids:
                duplicates += 1
            seen_ids.add(tid)
            selected_ids.add(tid)
            customer_ids.add(customer)
            fp = card_fingerprint(row)
            if fp:
                fingerprints[customer].add(fp)

    if rows == 0:
        raise ValueError("no transaction rows selected")
    return selected_ids, fingerprints, customer_ids, rows, duplicates

def main() -> int:
    args = parse_args()
    sample = None if args.full else args.sample
    if sample is not None and sample <= 0:
        raise SystemExit("--sample must be a positive integer")

    data_dir = args.data_dir
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    tx_path = path_for(data_dir, "transactions.csv")
    identity_path = path_for(data_dir, "identity.csv")
    cases_path = path_for(data_dir, "closed_cases_history.csv")
    for p in (tx_path, identity_path, cases_path):
        if not p.exists():
            raise SystemExit(f"missing input file: {p}")

    selected_ids, fingerprints, customer_ids, selected_rows, duplicate_tx = load_transaction_selection(tx_path, sample)
    card_map: dict[tuple[str, tuple[str, ...]], str] = {}
    for customer, fps in fingerprints.items():
        for ordinal, fp in enumerate(sorted(fps), start=1):
            card_map[(customer, fp)] = card_id(customer, fp, ordinal)

    # Output handles and headers.
    handles = {}
    writers = {}
    specs = {
        "customer.tsv": ["customer_id"],
        "card.tsv": ["card_id", "customer_id", "card1", "card2", "card3", "card4", "card5", "card6"],
        "transaction.tsv": TX_OUT_FIELDS,
        "owns.tsv": ["from_id", "to_id"],
        "made.tsv": ["from_id", "to_id"],
        "device_profile.tsv": ["device_profile_id", "device_info", "device_type", "os", "browser", "screen", "device_status", "proxy_type", "match_status"],
        "from_device.tsv": ["from_id", "to_id"],
        "email_domain.tsv": ["email_domain"],
        "purchaser_email.tsv": ["from_id", "to_id", "email_role"],
        "billing_region.tsv": ["billing_region_id", "addr1", "addr2"],
        "billed_in.tsv": ["from_id", "to_id"],
        "next.tsv": ["from_id", "to_id", "ts"],
        "closed_case.tsv": ["case_id", "customer_id", "card_id", "opened_at", "closed_at", "outcome", "pattern", "first_fraud_txn_id", "n_txns", "exposure_usd", "report_filed", "connected_card_ids", "actions_taken", "analyst_notes"],
        "involves.tsv": ["from_id", "to_id", "relation"],
        "on_card.tsv": ["from_id", "to_id"],
        "connected_to.tsv": ["from_id", "to_id", "relation"],
    }
    try:
        for filename, fields in specs.items():
            handles[filename] = write_tsv(out / filename, fields)
            writers[filename] = csv.writer(handles[filename], delimiter="\t", lineterminator="\n")
            writers[filename].writerow(fields)

        # Cards from transaction fingerprints. Historical case labels are added later.
        all_cards: dict[str, list[str]] = {}
        for (customer, fp), cid in card_map.items():
            all_cards[cid] = [cid, customer, *fp]

        tx_by_card: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
        email_domains: set[str] = set()
        regions: dict[str, list[str]] = {}
        tx_count = 0
        made_count = 0
        with tx_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                tid = (row.get("TransactionID") or "").strip()
                if tid not in selected_ids:
                    continue
                tx_count += 1
                customer = (row.get("customer_id") or "").strip()
                fp = card_fingerprint(row)
                cid = card_map.get((customer, fp)) if fp else None
                if cid:
                    write_row(writers["made.tsv"], [cid, tid])
                    tx_by_card[cid].append((row.get("ts") or "", tid))
                    made_count += 1
                values = []
                for field in TX_OUT_FIELDS:
                    source = {
                        "transaction_id": "TransactionID", "transaction_dt": "TransactionDT",
                        "transaction_amt": "TransactionAmt", "product_cd": "ProductCD",
                        "p_emaildomain": "P_emaildomain", "r_emaildomain": "R_emaildomain",
                    }.get(field, field)
                    values.append(row.get(source, ""))
                write_row(writers["transaction.tsv"], values)
                # Customer vertices are written once, in sorted order below.
                for role, field in (("purchaser", "P_emaildomain"), ("recipient", "R_emaildomain")):
                    value = (row.get(field) or "").strip()
                    if value:
                        email_domains.add(value)
                        write_row(writers["purchaser_email.tsv"], [tid, value, role])
                addr1 = (row.get("addr1") or "").strip()
                if addr1:
                    addr2 = (row.get("addr2") or "").strip()
                    regions.setdefault(addr1, [addr1, addr2])
                    if not regions[addr1][1] and addr2:
                        regions[addr1][1] = addr2
                    write_row(writers["billed_in.tsv"], [tid, addr1])
        # Rewrite customer file cleanly (the conditional write above is intentionally not relied on).
        handles["customer.tsv"].close()
        handles["customer.tsv"] = write_tsv(out / "customer.tsv", specs["customer.tsv"])
        writers["customer.tsv"] = csv.writer(handles["customer.tsv"], delimiter="\t", lineterminator="\n")
        writers["customer.tsv"].writerow(specs["customer.tsv"])
        for customer in sorted(customer_ids):
            writers["customer.tsv"].writerow([customer])

        for cid, values in sorted(all_cards.items()):
            write_row(writers["card.tsv"], values)
            write_row(writers["owns.tsv"], [values[1], cid])
        for domain in sorted(email_domains):
            write_row(writers["email_domain.tsv"], [domain])
        for addr1, values in sorted(regions.items()):
            write_row(writers["billing_region.tsv"], values)

        # Identity join and deterministic DeviceProfile construction.
        device_profiles: dict[str, tuple[str, dict[str, str]]] = {}
        identity_rows = 0
        device_edges = 0
        with identity_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = set(IDENTITY_FIELDS) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"identity.csv missing columns: {sorted(missing)}")
            for row in reader:
                tid = (row.get("TransactionID") or "").strip()
                if tid not in selected_ids:
                    continue
                identity_rows += 1
                profile = device_profile(row)
                if not profile:
                    continue
                pid, values = profile
                device_profiles[pid] = (pid, values)
                write_row(writers["from_device.tsv"], [tid, pid])
                device_edges += 1
        for pid, (_, values) in sorted(device_profiles.items()):
            write_row(writers["device_profile.tsv"], [pid] + [values[k] for k in specs["device_profile.tsv"][1:]])

        # NEXT is generated only for transactions with a resolved card fingerprint.
        next_count = 0
        for cid, items in tx_by_card.items():
            items.sort(key=lambda x: (x[0], x[1]))
            for (_, tid_a), (ts_b, tid_b) in zip(items, items[1:]):
                write_row(writers["next.tsv"], [tid_a, tid_b, ts_b])
                next_count += 1

        # Closed cases: only include cases with at least one transaction in this prepared scope.
        case_count = 0
        involves_count = 0
        case_card_ids: set[str] = set()
        case_customers: set[str] = set()
        with cases_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                txn_ids = [x.strip() for x in (row.get("txn_ids") or "").split("|") if x.strip()]
                included_txns = [x for x in txn_ids if x in selected_ids]
                if not included_txns:
                    continue
                case_id = (row.get("case_id") or "").strip()
                customer = (row.get("customer_id") or "").strip()
                primary_card = (row.get("card_id") or "").strip()
                case_card_ids.add(primary_card) if primary_card else None
                case_customers.add(customer) if customer else None
                connected_cards = [x.strip() for x in (row.get("connected_card_ids") or "").split("|") if x.strip()]
                case_card_ids.update(connected_cards)
                for cid in [primary_card, *connected_cards]:
                    if cid and cid not in all_cards:
                        all_cards[cid] = [cid, customer, "", "", "", "", "", ""]
                write_row(writers["closed_case.tsv"], [
                    row.get("case_id", ""), row.get("customer_id", ""), row.get("card_id", ""),
                    row.get("opened_at", ""), row.get("closed_at", ""), row.get("outcome", ""),
                    row.get("pattern", ""), row.get("first_fraud_txn_id", ""), row.get("n_txns", ""),
                    row.get("exposure_usd", ""), row.get("report_filed", ""),
                    row.get("connected_card_ids", ""), row.get("actions_taken", ""), row.get("analyst_notes", ""),
                ])
                for tid in included_txns:
                    relation = "first_fraud" if tid == row.get("first_fraud_txn_id") else "involves"
                    write_row(writers["involves.tsv"], [case_id, tid, relation])
                    involves_count += 1
                if primary_card:
                    write_row(writers["on_card.tsv"], [case_id, primary_card])
                for cid in connected_cards:
                    write_row(writers["connected_to.tsv"], [case_id, cid, "connected_card"])
                case_count += 1

        # Append case-only cards/customers after the case pass.
        existing_card_ids = set(all_cards)
        # card.tsv was already written for transaction cards; append case-only cards.
        for cid in sorted(existing_card_ids - set(card_map.values())):
            values = all_cards[cid]
            write_row(writers["card.tsv"], values)
            if values[1]:
                write_row(writers["owns.tsv"], [values[1], cid])
        for customer in sorted(case_customers - customer_ids):
            write_row(writers["customer.tsv"], [customer])

        manifest = {
            "mode": "full" if sample is None else "sample",
            "sample_transactions_requested": sample,
            "transactions": tx_count,
            "source_transaction_rows_selected": selected_rows,
            "duplicate_transaction_ids": duplicate_tx,
            "customers": len(customer_ids | case_customers),
            "transaction_card_fingerprints": len(card_map),
            "cards_including_case_labels": len(existing_card_ids),
            "made_edges": made_count,
            "identity_rows_joined": identity_rows,
            "device_profiles": len(device_profiles),
            "from_device_edges": device_edges,
            "email_domains": len(email_domains),
            "billing_regions": len(regions),
            "next_edges": next_count,
            "closed_cases": case_count,
            "involves_edges": involves_count,
            "case_card_labels": len(case_card_ids),
            "case_pack_loaded": False,
            "null_token": NULL_TOKEN,
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest, indent=2))
    finally:
        for handle in handles.values():
            try:
                handle.close()
            except Exception:
                pass
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, csv.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

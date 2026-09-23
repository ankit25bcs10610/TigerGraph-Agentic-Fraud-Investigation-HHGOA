#!/usr/bin/env python3
"""Check that the real submission inputs are present and internally consistent."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


REQUIRED_FILES = ("transactions.csv", "identity.csv", "closed_cases_history.csv", "case_pack.csv")


def rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--expected-cases", type=int, default=20)
    parser.add_argument("--require-graph", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    dataset = args.dataset_dir.expanduser().resolve()
    print(f"Dataset: {dataset}")

    missing = [name for name in REQUIRED_FILES if not (dataset / name).is_file()]
    if missing:
        errors.append(f"missing required files: {', '.join(missing)}")
    else:
        transactions = list(rows(dataset / "transactions.csv"))
        case_pack = list(rows(dataset / "case_pack.csv"))
        closed_cases = list(rows(dataset / "closed_cases_history.csv"))
        transaction_ids = {row.get("TransactionID", "").strip() for row in transactions}
        flagged_ids = {row.get("flagged_txn_id", "").strip() for row in case_pack}
        missing_flagged = sorted(item for item in flagged_ids if item and item not in transaction_ids)
        if len(case_pack) != args.expected_cases:
            errors.append(f"case_pack.csv has {len(case_pack)} cases; expected {args.expected_cases}")
        if missing_flagged:
            errors.append(f"case pack references {len(missing_flagged)} transactions absent from transactions.csv")
        if not closed_cases:
            errors.append("closed_cases_history.csv contains no rows")
        print(f"Cases: {len(case_pack)}; transactions: {len(transactions)}; closed cases: {len(closed_cases)}")

    if args.require_graph:
        graph_host = os.getenv("TG_HOST", "").strip()
        graph_secret = os.getenv("TG_SECRET", "").strip()
        graph_token = os.getenv("TG_API_TOKEN", "").strip()
        graph_login = os.getenv("TG_USERNAME", "").strip() and os.getenv("TG_PASSWORD", "").strip()
        if not graph_host:
            errors.append("TG_HOST is not configured")
        if not (graph_secret or graph_token or graph_login):
            errors.append("configure TG_SECRET, TG_API_TOKEN, or TG_USERNAME/TG_PASSWORD")
        if os.getenv("TG_GRAPHNAME", "FraudInvestigationGraph").strip() != "FraudInvestigationGraph":
            warnings.append("TG_GRAPHNAME is not FraudInvestigationGraph; MCP smoke test may reject it")
        print(f"TigerGraph: {'configured' if graph_host and (graph_secret or graph_token or graph_login) else 'not configured'}")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"BLOCKED: {error}")
    if errors:
        print("PREFLIGHT: FAILED")
        return 1
    print("PREFLIGHT: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

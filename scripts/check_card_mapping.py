"""Check that derived card IDs match the card labels used by the case pack and closed cases.

The dataset's transaction table has no card_id; the loader derives labels such as
C12382-K1 from each customer's raw card fields. If that derivation disagrees with
the labels the case files use, every card history is wrong. Run this first.

Example::

    python scripts/check_card_mapping.py --transactions data/transactions.csv \
        --case-pack data/case_pack.csv --closed-cases data/closed_cases_history.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.sources import CsvSource  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transactions", default=os.getenv("TRANSACTIONS_PATH"), required=False)
    parser.add_argument("--identity", default=os.getenv("IDENTITY_PATH"))
    parser.add_argument("--case-pack", default=os.getenv("CASE_PACK_PATH"))
    parser.add_argument("--closed-cases", default=os.getenv("CLOSED_CASES_PATH"))
    args = parser.parse_args()
    source = CsvSource(args.transactions, args.identity, args.closed_cases)
    checks: list[tuple[str, str, str, str]] = []  # (file, row id, transaction, expected card)
    if args.case_pack:
        with Path(args.case_pack).open(newline="", encoding="utf-8-sig") as handle:
            checks += [("case_pack", row["case_id"], row.get("flagged_txn_id", ""), row.get("card_id", "")) for row in csv.DictReader(handle)]
    if args.closed_cases:
        with Path(args.closed_cases).open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                txn = row.get("first_fraud_txn_id") or next((item for item in (row.get("txn_ids") or "").split("|") if item), "")
                checks.append(("closed_cases", row["case_id"], txn, row.get("card_id", "")))
    matched = mismatched = missing = 0
    examples: list[str] = []
    for file, row_id, txn_id, expected in checks:
        txn = source.transaction(txn_id) if txn_id else None
        if txn is None or not expected:
            missing += 1
            continue
        if txn.card_id == expected:
            matched += 1
        else:
            mismatched += 1
            if len(examples) < 10:
                examples.append(f"  {file} {row_id}: transaction {txn_id} derives {txn.card_id or '(none)'}, file says {expected}")
    total = matched + mismatched
    print(f"Checked {total} rows with a transaction and a card label ({missing} skipped).")
    print(f"Matched: {matched} ({matched / total:.1%})" if total else "Nothing to check.")
    print(f"Mismatched: {mismatched}")
    if examples:
        print("Examples:\n" + "\n".join(examples))
    return 0 if not mismatched else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Report coordinated fraud rings across the whole graph, and which ones no documented pattern explains.

Example::

    python scripts/discover_patterns.py --transactions data/transactions.csv --identity data/identity.csv \\
        --closed-cases data/closed_cases_history.csv --case-pack data/case_pack.csv
    DATA_SOURCE=tigergraph python scripts/discover_patterns.py --case-pack data/case_pack.csv
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.demo_runtime import CasePackProvider  # noqa: E402
from backend.discovery import discover  # noqa: E402
from backend.sources.tigergraph_source import open_source  # noqa: E402


def _row(index: int, ring: dict) -> str:
    patterns = ", ".join(f"{name} x{count}" for name, count in ring["confirmed_patterns"].items()) or "none"
    online = "" if ring["online_share"] is None else f"{ring['online_share']:.0%}"
    total = "" if ring["total_amount_usd"] is None else f"${ring['total_amount_usd']:,.2f}"
    span = "" if ring["span_hours"] is None else str(ring["span_hours"])
    return (f"| {index} | {ring['label'].replace('_', ' ')} | {ring['customers']} | {ring['cards']} | {ring['devices']} | {ring['transactions']} | "
            f"{online} | {total} | {span} | {len(ring['confirmed_cases'])} ({patterns}) | {', '.join(ring['benchmark_cases']) or 'none'} |")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transactions", default=os.getenv("TRANSACTIONS_PATH"))
    parser.add_argument("--identity", default=os.getenv("IDENTITY_PATH"))
    parser.add_argument("--closed-cases", default=os.getenv("CLOSED_CASES_PATH"))
    parser.add_argument("--case-pack", default=os.getenv("CASE_PACK_PATH"))
    parser.add_argument("--source", default=os.getenv("DATA_SOURCE", "csv"))
    parser.add_argument("--min-customers", type=int, default=3)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", default="outputs/DISCOVERY.md")
    args = parser.parse_args()

    source = open_source(args.source, transactions=args.transactions, identity=args.identity, closed_cases=args.closed_cases)
    pack = CasePackProvider(args.case_pack).list() if args.case_pack else []
    rings = discover(source, pack, min_customers=args.min_customers, top_k=args.top)
    candidates = sum(1 for ring in rings if ring["label"] == "candidate_undocumented")
    lines = [
        "# Fraud rings across the graph", "",
        f"Weakly connected components over cards and devices, at least {args.min_customers} customers each. "
        f"{candidates} of {len(rings)} are candidates for an undocumented pattern.", "",
        "| Ring | Label | Customers | Cards | Devices | Transactions | Online share | Total | Span (h) | Confirmed cases (patterns) | Benchmark cases |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        *(_row(index, ring) for index, ring in enumerate(rings, 1)),
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

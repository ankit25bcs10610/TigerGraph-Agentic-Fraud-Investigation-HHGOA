"""Measure the agent against the bank's closed investigations.

Each closed case is replayed as if it had just been triggered on its first
suspicious transaction. The agent investigates without seeing that case or
any case opened after it (no label leakage), and its pattern and verdict are
compared with what the analysts concluded. The report shows where the
detectors agree, where they miss, and how often the agent correctly stays
uncertain instead of guessing.

Example::

    python scripts/calibrate_closed_cases.py --transactions data/transactions.csv \\
        --identity data/identity.csv --closed-cases data/closed_cases_history.csv --limit 500
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from backend.local_engine import LocalInvestigationEngine  # noqa: E402
from backend.memory import CaseMemory  # noqa: E402
from backend.sources.base import ClosedCaseRecord, Community, RingResult, parse_time  # noqa: E402
from backend.sources.tigergraph_source import open_source  # noqa: E402


class _Blindfold:
    """Hides the case under test, and every case opened after it, from the agent."""

    def __init__(self, source: Any, case: ClosedCaseRecord) -> None:
        self.source, self.case, self.name = source, case, source.name
        self.cutoff = parse_time(case.opened_at)
        self._closed: tuple[ClosedCaseRecord, ...] = ()

    def _visible(self, other: ClosedCaseRecord) -> bool:
        if other.case_id == self.case.case_id:
            return False
        opened = parse_time(other.opened_at)
        return not (self.cutoff and opened and opened >= self.cutoff)

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self.source, attribute)

    def linked_closed_cases(self, *args: Any) -> list[ClosedCaseRecord]:
        return [case for case in self.source.linked_closed_cases(*args) if self._visible(case)]

    def closed_cases_by_pattern(self, pattern: str, limit: int) -> list[ClosedCaseRecord]:
        return [case for case in self.source.closed_cases_by_pattern(pattern, limit + 5) if self._visible(case)][:limit]

    def _visible_id(self, case_id: str) -> bool:
        other = self._by_id().get(case_id)
        return other is None or self._visible(other)

    def _by_id(self) -> dict[str, ClosedCaseRecord]:
        closed = getattr(self.source, "_closed", ())
        return {case.case_id: case for case in closed} if isinstance(closed, (list, tuple)) else {}

    def device_ring(self, device: str, hops: int, around: Any = None) -> RingResult:
        ring = self.source.device_ring(device, hops, around)
        return RingResult(ring.seed_device, ring.devices, ring.cards, ring.customers, ring.transactions,
                          tuple(c for c in ring.confirmed_cases if c != self.case.case_id and self._visible_id(c)), ring.hops, ring.extra)

    def communities(self, min_customers: int, top_k: int) -> list[Community]:
        return [Community(item.community_id, item.cards, item.devices, item.customers, tuple(c for c in item.confirmed_cases if c != self.case.case_id and self._visible_id(c)),
                          item.transactions, item.customer_count) for item in self.source.communities(min_customers, top_k)]


def load_cases(path: str) -> list[ClosedCaseRecord]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return [ClosedCaseRecord(case_id=row["case_id"], customer_id=row.get("customer_id", ""), card_id=row.get("card_id", ""), outcome=row.get("outcome", ""),
                                 pattern=row.get("pattern", "") or "none", txn_ids=tuple(t for t in (row.get("txn_ids") or "").split("|") if t),
                                 opened_at=row.get("opened_at", ""), first_fraud_txn_id=row.get("first_fraud_txn_id", "") or "")
                for row in csv.DictReader(handle) if row.get("case_id")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transactions", default=os.getenv("TRANSACTIONS_PATH"))
    parser.add_argument("--identity", default=os.getenv("IDENTITY_PATH"))
    parser.add_argument("--closed-cases", default=os.getenv("CLOSED_CASES_PATH"), required=False)
    parser.add_argument("--source", default="csv", help="csv or tigergraph")
    parser.add_argument("--limit", type=int, default=400, help="cases to replay, sampled evenly across patterns")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="outputs/CALIBRATION.md")
    args = parser.parse_args()
    if not args.closed_cases:
        parser.error("--closed-cases is required")

    source = open_source(args.source, transactions=args.transactions, identity=args.identity, closed_cases=args.closed_cases)
    cases = [case for case in load_cases(args.closed_cases) if case.first_fraud_txn_id or case.txn_ids]
    by_pattern: dict[str, list[ClosedCaseRecord]] = defaultdict(list)
    for case in cases:
        by_pattern[case.pattern].append(case)
    rng = random.Random(args.seed)
    per_pattern = max(1, args.limit // max(1, len(by_pattern)))
    sample = [case for group in by_pattern.values() for case in rng.sample(group, min(per_pattern, len(group)))]

    pattern_pairs: Counter[tuple[str, str]] = Counter()
    verdicts: Counter[tuple[str, str]] = Counter()
    skipped = 0
    for case in sample:
        trigger = case.first_fraud_txn_id or case.txn_ids[0]
        txn = source.transaction(trigger)
        if txn is None:
            skipped += 1
            continue
        agent = LocalInvestigationEngine(_Blindfold(source, case), memory=CaseMemory(), compute_decision_paths=False)
        state = agent.start_investigation({"case_id": f"CAL-{case.case_id}", "flagged_txn_id": trigger, "customer_id": txn.customer_id, "card_id": case.card_id,
                                           "trigger_type": "risk_score", "risk_score": "" if txn.risk_score is None else str(txn.risk_score), "opened_at": case.opened_at})
        if "verdict" not in state.get("case", {}):
            skipped += 1
            continue
        pattern_pairs[(case.pattern, state["case"]["pattern"])] += 1
        truth = "fraud" if case.confirmed_fraud else "not_fraud"
        verdicts[(truth, state["case"]["verdict"])] += 1

    patterns = sorted({truth for truth, _ in pattern_pairs} | {guess for _, guess in pattern_pairs})
    replayed = sum(pattern_pairs.values())
    lines = ["# Calibration against closed cases", "", f"Replayed {replayed} closed cases ({skipped} skipped: trigger transaction not found). The case under test and every case opened after it were hidden from the agent.", "",
             "## Pattern agreement", "", "| Analyst pattern | Cases | Agent agreed | Recall | Most common agent answer |", "|---|---|---|---|---|"]
    for pattern in patterns:
        total = sum(count for (truth, _), count in pattern_pairs.items() if truth == pattern)
        if not total:
            continue
        hit = pattern_pairs[(pattern, pattern)]
        common = Counter({guess: count for (truth, guess), count in pattern_pairs.items() if truth == pattern}).most_common(1)[0][0]
        lines.append(f"| {pattern} | {total} | {hit} | {hit / total:.0%} | {common} |")
    lines += ["", "| Agent pattern | Times predicted | Precision |", "|---|---|---|"]
    for pattern in patterns:
        predicted = sum(count for (_, guess), count in pattern_pairs.items() if guess == pattern)
        if predicted:
            lines.append(f"| {pattern} | {predicted} | {pattern_pairs[(pattern, pattern)] / predicted:.0%} |")
    lines += ["", "## Verdict agreement", "", "| Analyst outcome | Agent: fraud | Agent: uncertain | Agent: legitimate |", "|---|---|---|---|"]
    for truth in ("fraud", "not_fraud"):
        lines.append(f"| {truth.replace('_', ' ')} | {verdicts[(truth, 'fraud')]} | {verdicts[(truth, 'uncertain')]} | {verdicts[(truth, 'legitimate')]} |")
    decided = sum(count for (truth, verdict), count in verdicts.items() if verdict != "uncertain")
    correct = verdicts[("fraud", "fraud")] + verdicts[("not_fraud", "legitimate")]
    lines += ["", f"Decided cases: {decided}; correct among decided: {correct / decided:.0%}." if decided else "No case was decided without further evidence."]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

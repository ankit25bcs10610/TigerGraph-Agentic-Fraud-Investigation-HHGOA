"""Find coordinated activity no documented pattern describes.

Communities come from the graph (weakly connected components over cards and
devices). Each one is characterised from its transactions and linked closed
cases, then labelled:

* **Known ring**: it touches confirmed fraud cases whose pattern is documented.
* **Candidate undocumented pattern**: it spans several customers and either
  touches confirmed fraud with no documented pattern, or has no closed case
  at all. These are the leads worth naming.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

DOCUMENTED = {"card_testing", "card_not_present_fraud", "card_not_present_new_device", "out_of_region_use", "account_takeover"}


def discover(source: Any, case_pack: list[dict[str, Any]] | None = None, *, min_customers: int = 3, top_k: int = 15) -> list[dict[str, Any]]:
    # The CSV source keeps every transaction and closed case in memory; on the live graph the
    # community query already carries the members, so these stay empty.
    closed_cases = getattr(source, "_closed", ())
    closed = {case.case_id: case for case in closed_cases} if isinstance(closed_cases, (list, tuple)) else {}
    txns = getattr(source, "_txns", {})
    txns = txns if isinstance(txns, dict) else {}
    flagged = {item.get("flagged_txn_id"): item["case_id"] for item in (case_pack or []) if item.get("flagged_txn_id")}
    results = []
    for community in source.communities(min_customers, top_k):
        patterns = Counter(closed[case_id].pattern for case_id in community.confirmed_cases if case_id in closed)
        members = [txn for txn in txns.values() if txn.card_id in set(community.cards)] if txns else []
        online = sum(1 for txn in members if txn.channel.lower() == "online")
        amounts = [txn.amount for txn in members]
        times = [txn.ts for txn in members]
        documented = {pattern for pattern in patterns if pattern in DOCUMENTED}
        label = "known_ring" if documented else "candidate_undocumented"
        results.append({
            "community_id": community.community_id, "customers": community.size, "cards": len(community.cards), "devices": len(community.devices),
            "transactions": community.transactions or len(members), "confirmed_cases": list(community.confirmed_cases), "confirmed_patterns": dict(patterns),
            "online_share": round(online / len(members), 2) if members else None, "total_amount_usd": round(sum(amounts), 2) if amounts else None,
            "span_hours": round((max(times) - min(times)).total_seconds() / 3600, 1) if len(times) > 1 else None,
            "benchmark_cases": sorted({flagged[txn.transaction_id] for txn in members if txn.transaction_id in flagged}),
            "sample_cards": list(community.cards[:6]), "sample_devices": list(community.devices[:4]), "label": label,
        })
    return results

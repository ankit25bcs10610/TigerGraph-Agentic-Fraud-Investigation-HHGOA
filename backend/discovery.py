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
from statistics import median
from typing import Any

from backend.sources.base import Community, specific_model

DOCUMENTED = {"card_testing", "card_not_present_fraud", "card_not_present_new_device", "out_of_region_use", "account_takeover"}


def _top(counts: Counter, total: int, limit: int = 3) -> list[dict[str, Any]]:
    return [{"value": value, "share": round(count / total, 2)} for value, count in counts.most_common(limit) if value] if total else []


def ring_profile(source: Any, community: Community) -> dict[str, Any]:
    """What the ring's cards did on its shared devices: volume, amounts, timing, channel, products, emails, device models."""
    if hasattr(source, "ring_profile"):
        return source.ring_profile(community.cards, community.devices)
    txns = getattr(source, "_txns", {})
    txns = txns if isinstance(txns, dict) else {}
    cards, devices = set(community.cards), set(community.devices)
    members = [txn for txn in txns.values() if txn.card_id in cards and txn.device_profile_id in devices]
    if not members:
        return {}
    amounts = [txn.amount for txn in members]
    first, last = min(txn.ts for txn in members), max(txn.ts for txn in members)
    models = Counter(txn.device_info or "" for txn in {txn.device_profile_id: txn for txn in members}.values())
    return {"transactions": len(members), "online_share": round(sum(1 for txn in members if txn.channel.lower() == "online") / len(members), 2),
            "total_amount_usd": round(sum(amounts), 2), "median_amount_usd": round(median(amounts), 2), "first_seen": first.isoformat(sep=" "), "last_seen": last.isoformat(sep=" "),
            "span_hours": round((last - first).total_seconds() / 3600, 1), "products": _top(Counter(txn.product_code or "" for txn in members), len(members)),
            "emails": _top(Counter(txn.email or "" for txn in members), len(members)), "device_models": [value for value, _ in models.most_common(3) if value]}


def describe(profile: dict[str, Any], community: Community) -> str:
    """One line an analyst can read: the ring's behaviour, from its profile only."""
    if not profile.get("transactions"):
        return f"{len(community.cards)} cards linked through {len(community.devices)} shared devices."
    parts = [f"{profile['transactions']} transactions by {len(community.cards)} cards on {len(community.devices)} shared devices"]
    models = profile.get("device_models") or []
    builds = [model for model in models if specific_model(model)]
    if builds:
        parts.append(f"device builds such as {', '.join(builds[:2])}")
    elif models:
        parts.append(f"generic {', '.join(models[:2])} profiles")
    parts.append(f"{round(profile['online_share'] * 100)}% online")
    if profile.get("products"):
        product = profile["products"][0]
        parts.append(f"{round(product['share'] * 100)}% product {product['value']}")
    parts.append(f"median ${profile['median_amount_usd']:,.2f}, total ${profile['total_amount_usd']:,.2f}")
    if profile.get("first_seen") and profile.get("last_seen"):
        parts.append(f"{str(profile['first_seen'])[:10]} to {str(profile['last_seen'])[:10]}")
    return "; ".join(parts) + "."


def discover(source: Any, case_pack: list[dict[str, Any]] | None = None, *, min_customers: int = 3, top_k: int = 15) -> list[dict[str, Any]]:
    closed_cases = getattr(source, "_closed", ())
    closed = {case.case_id: case for case in closed_cases} if isinstance(closed_cases, (list, tuple)) else {}
    flagged_cards: dict[str, set[str]] = {}
    for item in case_pack or []:
        if item.get("card_id"):
            flagged_cards.setdefault(item["card_id"], set()).add(item["case_id"])
    results = []
    for community in source.communities(min_customers, top_k):
        patterns = Counter(closed[case_id].pattern for case_id in community.confirmed_cases if case_id in closed)
        documented = {pattern for pattern in patterns if pattern in DOCUMENTED}
        profile = ring_profile(source, community)
        results.append({
            "community_id": community.community_id, "customers": community.size, "cards": len(community.cards), "devices": len(community.devices),
            "transactions": profile.get("transactions") or community.transactions, "confirmed_cases": list(community.confirmed_cases), "confirmed_patterns": dict(patterns),
            "online_share": profile.get("online_share"), "total_amount_usd": profile.get("total_amount_usd"), "span_hours": profile.get("span_hours"),
            "median_amount_usd": profile.get("median_amount_usd"), "products": profile.get("products", []), "emails": profile.get("emails", []),
            "device_models": profile.get("device_models", []), "signature": describe(profile, community),
            "benchmark_cases": sorted({case_id for card in community.cards for case_id in flagged_cards.get(card, ())}),
            "sample_cards": list(community.cards[:6]), "sample_devices": list(community.devices[:4]),
            "label": "known_ring" if documented else "candidate_undocumented",
        })
    return results

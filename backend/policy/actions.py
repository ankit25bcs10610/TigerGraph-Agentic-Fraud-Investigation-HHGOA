"""Policy action construction and deterministic deduplication."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable

from backend.models.answer import Action, ApprovalRoute, PolicyAction


def policy_action(
    action: PolicyAction,
    *,
    rule: str,
    reason: str,
    route: ApprovalRoute,
) -> Action:
    """Create a strict answer-format action with a cited rule number."""
    if not rule.strip():
        raise ValueError("policy rule number is required")
    if not reason.strip():
        raise ValueError("policy action reason is required")
    return Action(
        action=action,
        route=route,
        reason=f"{rule}: {reason.strip()}",
    )


def deduplicate_actions(actions: Iterable[Action]) -> list[Action]:
    """Merge repeated actions while retaining every applicable rule citation."""
    merged: OrderedDict[PolicyAction, Action] = OrderedDict()
    reasons: dict[PolicyAction, list[str]] = {}
    for item in actions:
        if item.action not in merged:
            merged[item.action] = item
            reasons[item.action] = [item.reason]
        elif item.reason not in reasons[item.action]:
            reasons[item.action].append(item.reason)
    return [
        item.model_copy(update={"reason": "; ".join(reasons[item.action])})
        for item in merged.values()
    ]

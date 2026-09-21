"""Exact approval routing from the README Fraud Policy."""

from __future__ import annotations

from math import isfinite

from backend.models.answer import ApprovalRoute, PolicyAction


AUTO_ACTIONS = frozenset({
    PolicyAction.ALLOW_TRANSACTION,
    PolicyAction.MONITOR_CARD,
    PolicyAction.MONITOR_CONNECTED_CARDS,
    PolicyAction.WARN_CUSTOMER,
    PolicyAction.VERIFY_WITH_CUSTOMER,
    PolicyAction.STEP_UP_AUTH,
    PolicyAction.GENERATE_REPORT,
    PolicyAction.CREATE_CASE,
    PolicyAction.ESCALATE_TO_ANALYST,
    PolicyAction.CLOSE_NO_FRAUD,
})


def _coerce_action(action: PolicyAction | str) -> PolicyAction:
    if isinstance(action, PolicyAction):
        return action
    try:
        return PolicyAction(action)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported policy action: {action!r}") from exc


def _validate_exposure(exposure_usd: float) -> float:
    try:
        exposure = float(exposure_usd)
    except (TypeError, ValueError) as exc:
        raise ValueError("exposure_usd must be numeric") from exc
    if not isfinite(exposure) or exposure < 0:
        raise ValueError("exposure_usd must be a finite non-negative number")
    return exposure


def get_approval_route(action: PolicyAction | str, exposure_usd: float) -> ApprovalRoute:
    """Return the exact README route for an action and assessed exposure.

    L1 and L2 values are recommendations awaiting human approval. Only AUTO
    values may be executed autonomously.
    """
    normalized_action = _coerce_action(action)
    exposure = _validate_exposure(exposure_usd)

    if normalized_action in AUTO_ACTIONS:
        return ApprovalRoute.AUTO
    if normalized_action is PolicyAction.DECLINE_TRANSACTION:
        return ApprovalRoute.L1
    if normalized_action is PolicyAction.BLOCK_CARD:
        return ApprovalRoute.L1 if exposure <= 2500 else ApprovalRoute.L2
    if normalized_action in {PolicyAction.BLOCK_ALL_CARDS, PolicyAction.FILE_REPORT}:
        return ApprovalRoute.L2
    raise AssertionError(f"unrouted PolicyAction: {normalized_action}")


def can_auto_execute(action: PolicyAction | str, exposure_usd: float) -> bool:
    """True only when the policy authorizes autonomous execution."""
    return get_approval_route(action, exposure_usd) is ApprovalRoute.AUTO


# Compatibility for existing internal callers. New callers use the public
# get_approval_route interface.
approval_route = get_approval_route

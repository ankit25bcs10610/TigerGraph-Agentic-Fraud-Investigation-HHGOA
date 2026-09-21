import math

import pytest

from backend.models.answer import ApprovalRoute, PolicyAction
from backend.policy.approvals import AUTO_ACTIONS, can_auto_execute, get_approval_route


@pytest.mark.parametrize("action", sorted(AUTO_ACTIONS, key=lambda item: item.value))
@pytest.mark.parametrize("exposure_usd", [0, 2500, 2500.01])
def test_every_auto_action_is_auto_at_all_exposure_values(
    action: PolicyAction,
    exposure_usd: float,
) -> None:
    assert get_approval_route(action, exposure_usd) is ApprovalRoute.AUTO
    assert can_auto_execute(action, exposure_usd) is True


def test_decline_transaction_is_always_l1_and_never_auto_executable() -> None:
    for exposure_usd in (0, 2500, 2500.01):
        assert get_approval_route(PolicyAction.DECLINE_TRANSACTION, exposure_usd) is ApprovalRoute.L1
        assert can_auto_execute(PolicyAction.DECLINE_TRANSACTION, exposure_usd) is False


def test_block_card_boundary_is_exactly_2500() -> None:
    assert get_approval_route(PolicyAction.BLOCK_CARD, 2499.99) is ApprovalRoute.L1
    assert get_approval_route(PolicyAction.BLOCK_CARD, 2500) is ApprovalRoute.L1
    assert get_approval_route(PolicyAction.BLOCK_CARD, 2500.01) is ApprovalRoute.L2
    assert can_auto_execute(PolicyAction.BLOCK_CARD, 2500) is False


@pytest.mark.parametrize("action", [PolicyAction.BLOCK_ALL_CARDS, PolicyAction.FILE_REPORT])
def test_l2_actions_are_never_auto_executable(action: PolicyAction) -> None:
    for exposure_usd in (0, 2500, 2500.01):
        assert get_approval_route(action, exposure_usd) is ApprovalRoute.L2
        assert can_auto_execute(action, exposure_usd) is False


def test_only_exact_supported_identifiers_are_accepted() -> None:
    assert get_approval_route("CREATE_CASE", 0) is ApprovalRoute.AUTO
    with pytest.raises(ValueError, match="unsupported policy action"):
        get_approval_route("block_card", 0)


@pytest.mark.parametrize("exposure_usd", [-0.01, math.inf, math.nan, "not-a-number"])
def test_invalid_exposure_is_rejected(exposure_usd: object) -> None:
    with pytest.raises(ValueError):
        get_approval_route(PolicyAction.CREATE_CASE, exposure_usd)  # type: ignore[arg-type]

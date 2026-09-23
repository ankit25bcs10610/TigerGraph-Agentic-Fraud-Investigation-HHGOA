from pathlib import Path

import pytest

from backend.demo_runtime import build_reference_runtime

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.fixture()
def runtime():
    return build_reference_runtime(str(SAMPLE / "case_pack.csv"), str(SAMPLE / "transactions.csv"), str(SAMPLE / "closed_cases_history.csv"))


def pending(state):
    return [(item["action"], item["route"]) for item in state["approval_requests"] if item["approval_status"] == "pending"]


def test_card_testing_asks_the_customer_then_routes_block_for_approval(runtime):
    provider, engine = runtime
    state = engine.start_investigation(provider.get("SMP-001"))
    assert state["case"]["pattern"] == "card_testing"
    assert state["case"]["verdict"] == "uncertain"
    assert state["status"] == "awaiting_evidence"
    assert [item["type"] for item in state["evidence_requests"]] == ["customer_validation"]
    assert pending(state) == [("DECLINE_TRANSACTION", "L1")]

    request = state["evidence_requests"][0]
    state = engine.resume_with_evidence("SMP-001", {"request_id": request["request_id"], "result": "denied", "source": "customer"})
    assert state["case"]["verdict"] == "fraud"
    assert ("BLOCK_CARD", "L1") in pending(state)
    assert "block card" in state["next_best_actions"]["what_changed"]

    for action, _ in pending(state):
        state = engine.resume_with_approval("SMP-001", {"action": action, "approved": True})
    assert state["status"] == "completed"
    assert state["case"]["status"] == "closed_fraud"
    assert len(state["audit"]) == state["integrity"]["event_count"]


def test_shared_device_reaches_strong_fraud_and_requires_a_report(runtime):
    provider, engine = runtime
    state = engine.start_investigation(provider.get("SMP-002"))
    assert state["case"]["verdict"] == "fraud"
    assert state["case"]["fraud_probability"] >= 0.85
    assert state["evidence_requests"] == []
    assert state["sar"]["file"] is True
    assert ("FILE_REPORT", "L2") in pending(state)
    assert "SMP-CC-501" in state["case"]["similar_prior_cases"]
    assert {"ClosedCase", "DeviceProfile"} <= {node["data"]["entity_type"] for node in state["graph"]["nodes"]}


def test_customer_confirmation_closes_out_of_region_case(runtime):
    provider, engine = runtime
    state = engine.start_investigation(provider.get("SMP-003"))
    assert state["case"]["pattern"] == "out_of_region_use"
    request = state["evidence_requests"][0]
    state = engine.resume_with_evidence("SMP-003", {"request_id": request["request_id"], "result": "confirmed", "source": "customer"})
    assert state["case"]["verdict"] == "legitimate"
    assert [item["action"] for item in state["next_best_actions"]["final"]] == ["CLOSE_NO_FRAUD"]
    assert state["status"] == "completed"


def test_high_exposure_block_needs_l2(runtime):
    provider, engine = runtime
    state = engine.start_investigation(provider.get("SMP-006"))
    assert state["case"]["verdict"] == "fraud"
    assert ("BLOCK_CARD", "L2") in pending(state)
    assert state["sar"]["file"] is True and state["sar"]["narrative"]


def test_routine_purchase_closes_as_legitimate(runtime):
    provider, engine = runtime
    state = engine.start_investigation(provider.get("SMP-005"))
    assert state["case"]["verdict"] == "legitimate"
    assert state["status"] == "completed"
    assert state["approval_requests"] == []


def test_invalid_evidence_result_is_rejected(runtime):
    provider, engine = runtime
    state = engine.start_investigation(provider.get("SMP-001"))
    request = state["evidence_requests"][0]
    with pytest.raises(ValueError):
        engine.resume_with_evidence("SMP-001", {"request_id": request["request_id"], "result": "maybe"})

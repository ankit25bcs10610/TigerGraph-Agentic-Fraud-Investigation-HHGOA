from pathlib import Path

from backend.demo_runtime import build_reference_runtime


def test_reference_runtime_seals_a_chain_for_each_case_event(tmp_path: Path):
    case_pack = tmp_path / "case_pack.csv"
    case_pack.write_text(
        "case_id,flagged_txn_id,customer_id,card_id,trigger_type,opened_at\n"
        "HHG-001,T-1,C-1,C-1-K1,risk_signal,2026-09-22T00:00:00Z\n",
        encoding="utf-8",
    )
    provider, workflow = build_reference_runtime(str(case_pack))

    state = workflow.start_investigation(provider.get("HHG-001"))
    first_hash = state["integrity"]["latest_hash"]
    assert state["integrity"]["event_count"] == 1
    assert state["integrity_ledger"][0]["previous_hash"] == "GENESIS"

    state = workflow.resume_with_evidence("HHG-001", {"request_id": "R-1", "result": "unknown"})
    assert state["integrity"]["event_count"] == 2
    assert state["integrity_ledger"][1]["previous_hash"] == first_hash
    assert state["integrity_ledger"][1]["hash"] == state["integrity"]["latest_hash"]

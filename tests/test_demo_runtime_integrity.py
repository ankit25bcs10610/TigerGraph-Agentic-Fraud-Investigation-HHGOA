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



def test_reference_runtime_derives_graph_and_timeline_from_transactions(tmp_path: Path):
    case_pack = tmp_path / "case_pack.csv"
    case_pack.write_text("case_id,flagged_txn_id,customer_id,card_id\nHHG-002,T-2,C-9,K-9\n", encoding="utf-8")
    transactions = tmp_path / "transactions.csv"
    transactions.write_text(
        "TransactionID,customer_id,ts,TransactionAmt,channel,risk_score,addr1,P_emaildomain\n"
        "T-2,C-9,2026-01-02T00:00:00Z,90.5,online,0.7,204,mail.example\n"
        "T-1,C-9,2026-01-01T00:00:00Z,10,online,0.1,204,\n"
        "T-3,C-other,2026-01-03T00:00:00Z,5,online,0.2,,\n",
        encoding="utf-8",
    )
    provider, workflow = build_reference_runtime(str(case_pack), str(transactions))

    state = workflow.start_investigation(provider.get("HHG-002"))
    assert [row["transaction_id"] for row in state["timeline"]] == ["T-1", "T-2"]
    assert [row["suspicious"] for row in state["timeline"]] == [False, True]
    types = {node["data"]["entity_type"] for node in state["graph"]["nodes"]}
    assert types == {"Transaction", "Customer", "Card", "EmailDomain", "BillingRegion"}
    assert all(edge["data"]["source"] and edge["data"]["target"] for edge in state["graph"]["edges"])


def test_reference_runtime_returns_no_invented_context_without_transactions(tmp_path: Path):
    case_pack = tmp_path / "case_pack.csv"
    case_pack.write_text("case_id,flagged_txn_id\nHHG-003,T-404\n", encoding="utf-8")
    provider, workflow = build_reference_runtime(str(case_pack))
    state = workflow.start_investigation(provider.get("HHG-003"))
    assert state["timeline"] == []
    assert state["case"]["evidence"] == []

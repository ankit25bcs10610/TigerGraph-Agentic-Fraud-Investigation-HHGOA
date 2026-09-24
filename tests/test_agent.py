import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.local_engine import LocalInvestigationEngine
from backend.memory import CaseMemory
from backend.demo_runtime import CasePackProvider
from backend.sources import CsvSource
from backend.sources.tigergraph_source import TigerGraphSource

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture()
def agent():
    source = CsvSource(str(SAMPLE / "transactions.csv"), None, str(SAMPLE / "closed_cases_history.csv"))
    return CasePackProvider(str(SAMPLE / "case_pack.csv")), LocalInvestigationEngine(source, memory=CaseMemory())


def test_every_tool_call_is_traced_with_a_reason(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-002"))
    tools = [step["tool"] for step in state["agent_trace"]]
    assert tools[:3] == ["get_transaction", "get_customer_activity", "get_device_activity"]
    assert "detect_device_ring" in tools and "get_linked_closed_cases" in tools
    assert all(step["reason"] and step["ok"] for step in state["agent_trace"])
    assert sum(1 for event in state["audit"] if event["type"] == "tool_call") == len(state["agent_trace"])


def test_fraud_ring_and_policy_grounding(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-002"))
    assert any(item["claim"].startswith("Fraud-ring analysis") for item in state["case"]["evidence"])
    refs = {item["ref"]: item for item in state["policy_grounding"]}
    assert "policy:R6" in refs and "FILE_REPORT" in refs["policy:R6"]["supports"]
    assert state["explanation"]["verdict"].startswith("Verdict fraud")


def test_legitimate_case_has_no_exposure(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-005"))
    assert state["case"]["verdict"] == "legitimate"
    assert state["case"]["exposure_usd"] == 0 and state["case"]["affected_txn_ids"] == []
    assert state["stop_context"]["independent_evidence_count"] >= 2


def test_case_memory_informs_a_later_investigation(agent):
    provider, engine = agent
    engine.memory.remember({"case_id": "SMP-OLD", "customer_id": "SMP-C101", "card_id": "SMP-C101-K1", "devices": [], "verdict": "fraud", "pattern": "card_testing"})
    state = engine.start_investigation(provider.get("SMP-001"))
    assert any(item["ref"] == "case_memory" for item in state["case"]["evidence"])
    assert "recall_case_memory" in [step["tool"] for step in state["agent_trace"]]


def test_completed_case_is_remembered(agent):
    provider, engine = agent
    engine.start_investigation(provider.get("SMP-005"))
    assert engine.memory.related(case_id="other", customer_id="SMP-C505", card_id="", devices=set())


class _FakeService:
    def __init__(self, responses):
        self.responses = responses

    async def run_installed_query(self, name, params):
        return self.responses[name]


def test_tigergraph_source_parses_projected_rows():
    row = {"transaction_id": "T1", "customer_id": "C1", "card_id": "C1-K1", "ts": "2016-12-05 01:55:28", "amount": 12.5, "channel": "online",
           "risk_score": 0.4, "region": "204", "email": "gmail.com", "product_code": "W", "device_profile_id": "DP-1", "device_status": "New", "proxy_type": "", "match_status": ""}
    service = _FakeService({
        "agent_txn_profile": {"results": [{"rows": [{"v_id": "T1", "attributes": row}]}]},
        "agent_device_ring": {"results": [{"devices": ["DP-1"], "cards": ["C1-K1", "C2-K1"], "customers": ["C1", "C2"], "transactions": 7, "confirmed_cases": ["CC-9"], "hops": 2}]},
    })
    source = TigerGraphSource(service)
    txn = source.transaction("T1")
    assert txn.card_id == "C1-K1" and txn.device_status == "New" and txn.ts.year == 2016
    ring = source.device_ring("DP-1", 2)
    assert ring.customers == ("C1", "C2") and ring.confirmed_cases == ("CC-9",) and ring.transactions == 7


def test_benchmark_runner_writes_answers_and_report(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_benchmark.py"), "--case-pack", str(SAMPLE / "case_pack.csv"),
                             "--transactions", str(SAMPLE / "transactions.csv"), "--closed-cases", str(SAMPLE / "closed_cases_history.csv"), "--out", str(tmp_path)],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    report = (tmp_path / "REPORT.md").read_text()
    assert "Needing review: 0" in report
    answer = json.loads((tmp_path / "answers" / "SMP-005.json").read_text())
    assert answer["case"]["verdict"] == "legitimate" and answer["sar"]["file"] is False
    pending = json.loads((tmp_path / "answers" / "_pending_graph_write" / "SMP-001.json").read_text())
    assert pending["evidence_requests"][0]["assumed_response"] == "no_reply"
    assert pending["next_best_actions"]["initial"] != pending["next_best_actions"]["final"]


def test_decision_paths_choose_the_most_informative_request(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-001"))
    paths = {path["request_type"]: path for path in state["decision_paths"]}
    assert paths["customer_validation"]["chosen"] and not paths["step_up_auth"]["chosen"]
    assert paths["customer_validation"]["distinct_decisions"] > paths["step_up_auth"]["distinct_decisions"]
    outcomes = {outcome["answer"]: outcome for outcome in paths["customer_validation"]["outcomes"]}
    assert outcomes["denied"]["verdict"] == "fraud" and outcomes["confirmed"]["verdict"] == "legitimate"
    assert "highest decision value" in state["evidence_requests"][0]["reason"]
    # Simulating answers must not change the real investigation.
    assert state["evidence_responses"] == [] and state["case"]["verdict"] == "uncertain"


def test_score_breakdown_adds_up_and_finds_decisive_signals(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-002"))
    breakdown = state["score_breakdown"]
    assert abs(sum(row["points"] for row in breakdown["contributions"]) - breakdown["probability"]) < 1e-6
    assert any(row["decisive"] for row in breakdown["contributions"])  # 0.852 sits just above the 0.85 line


def test_blast_radius_lists_other_cards_on_the_shared_device(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-002"))
    blast = state["blast_radius"]
    assert {row["card_id"] for row in blast["cards"]} == {"SMP-C301-K1", "SMP-C302-K1"}
    assert blast["recent_spend_usd"] == 2010.0 and blast["confirmed_cases"] == ["SMP-CC-501"]
    assert engine.start_investigation(provider.get("SMP-005"))["blast_radius"] is None


def test_graphrag_retrieval_is_traced_and_cited(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-004"))
    step = next(step for step in state["agent_trace"] if step["tool"] == "graphrag_retrieve")
    assert step["source"] == "graphrag:tfidf" and step["ok"]
    assert any(item["source"].startswith("graphrag") for item in state["policy_grounding"])
    assert any(item["reason_for_match"].startswith("Narrative similarity") for item in state["similar_cases"])
    assert set(state["case"]["similar_prior_cases"]) == {item["case_id"] for item in state["similar_cases"]}


def test_llm_planner_steers_and_falls_back_safely():
    import json as _json
    from backend.planner import LLMPlanner

    source = CsvSource(str(SAMPLE / "transactions.csv"), None, str(SAMPLE / "closed_cases_history.csv"))
    replies = iter([_json.dumps({"tool": "get_device_activity", "reason": "New device behind a proxy."}),
                    _json.dumps({"tool": "drop_graph", "reason": "not allowed"}),
                    _json.dumps({"tool": "finish", "reason": "Enough evidence."})])
    engine = LocalInvestigationEngine(source, memory=CaseMemory(), planner=LLMPlanner(lambda system, prompt: next(replies)))
    state = engine.start_investigation(CasePackProvider(str(SAMPLE / "case_pack.csv")).get("SMP-004"))
    planners = {step["tool"]: step.get("planner") for step in state["agent_trace"]}
    assert planners["get_device_activity"] == "llm"
    assert planners["get_customer_activity"] == "llm-fallback"  # the invalid tool name was refused
    assert "finish_investigation" in planners and "drop_graph" not in planners
    assert state["case"]["verdict"] in {"fraud", "uncertain", "legitimate"}


def test_planner_failure_never_breaks_the_case():
    from backend.planner import LLMPlanner

    def broken(system, prompt):
        raise RuntimeError("provider down")

    source = CsvSource(str(SAMPLE / "transactions.csv"), None, str(SAMPLE / "closed_cases_history.csv"))
    engine = LocalInvestigationEngine(source, memory=CaseMemory(), planner=LLMPlanner(broken))
    state = engine.start_investigation(CasePackProvider(str(SAMPLE / "case_pack.csv")).get("SMP-002"))
    assert state["case"]["verdict"] == "fraud"
    assert all(step.get("planner") in {None, "rules", "llm-fallback"} for step in state["agent_trace"])


def test_auto_actions_execute_and_protected_ones_wait_for_approval(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-006"))
    executed = {item["action"]: item for item in state["executions"]}
    assert executed["CREATE_CASE"]["status"] == "executed" and executed["CREATE_CASE"]["receipt_id"].startswith("MOCK-")
    assert "BLOCK_CARD" not in executed  # L2: waits for a human
    state = engine.resume_with_approval("SMP-006", {"action": "BLOCK_CARD", "approved": True})
    state = engine.resume_with_approval("SMP-006", {"action": "FILE_REPORT", "approved": False})
    outcome = {item["action"]: item["status"] for item in state["executions"]}
    assert outcome["BLOCK_CARD"] == "executed" and outcome["FILE_REPORT"] == "rejected"
    assert sum(1 for event in state["audit"] if event["type"] in {"action_executed", "action_not_executed"}) == len(state["executions"])


def test_undocumented_coordinated_ring_is_detected(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-007"))
    assert state["case"]["pattern"] == "undocumented" and state["case"]["pattern_description"]
    assert "ESCALATE_TO_ANALYST" in {item["action"] for item in state["next_best_actions"]["final"]}


def test_memory_recalls_an_earlier_case_on_the_same_device(agent):
    provider, engine = agent
    before = engine.start_investigation(provider.get("SMP-008"))
    assert not any(item["ref"] == "case_memory" for item in before["case"]["evidence"])
    state = engine.start_investigation(provider.get("SMP-002"))
    for item in list(state["approval_requests"]):
        state = engine.resume_with_approval("SMP-002", {"action": item["action"], "approved": True})
    after = engine.start_investigation(provider.get("SMP-008"))
    assert any(item["ref"] == "case_memory" and "SMP-002" in item["claim"] for item in after["case"]["evidence"])


def test_communities_and_discovery_label_known_and_undocumented_rings():
    from backend.discovery import discover

    source = CsvSource(str(SAMPLE / "transactions.csv"), None, str(SAMPLE / "closed_cases_history.csv"))
    rings = {tuple(ring["benchmark_cases"]): ring for ring in discover(source, CasePackProvider(str(SAMPLE / "case_pack.csv")).list(), min_customers=3)}
    assert rings[("SMP-002", "SMP-008")]["label"] == "known_ring"
    assert rings[("SMP-007",)]["label"] == "candidate_undocumented" and rings[("SMP-007",)]["customers"] == 3


def test_card_mapping_check_passes_on_sample():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_card_mapping.py"), "--transactions", str(SAMPLE / "transactions.csv"),
                             "--case-pack", str(SAMPLE / "case_pack.csv"), "--closed-cases", str(SAMPLE / "closed_cases_history.csv")], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "Mismatched: 0" in result.stdout


def test_rings_endpoint_returns_labelled_rings():
    from fastapi.testclient import TestClient
    from backend.main import create_app

    source = CsvSource(str(SAMPLE / "transactions.csv"), None, str(SAMPLE / "closed_cases_history.csv"))
    app = create_app(workflow=LocalInvestigationEngine(source, memory=CaseMemory()), case_provider=CasePackProvider(str(SAMPLE / "case_pack.csv")))
    rings = TestClient(app).get("/network/rings").json()
    assert {ring["label"] for ring in rings} == {"known_ring", "candidate_undocumented"}


def test_generic_fingerprint_is_not_sharing_evidence_but_a_burst_is():
    from backend.sources.base import generic_device

    assert generic_device(158, 34, "Windows")          # many customers spread over months
    assert not generic_device(52, 24, "SM-G935F Build/NRD90M")   # one phone build, half its customers in the alert week
    assert generic_device(171, 126, "")      # a new desktop browser release: bursty but names no device
    assert generic_device(300, 20, "SM-G935F Build/NRD90M")    # a popular phone spread over months
    assert not generic_device(6, 1)         # a handful of customers is always specific


def test_ring_membership_links_a_card_whose_own_device_is_common(agent):
    provider, engine = agent
    state = engine.start_investigation(provider.get("SMP-007"))
    assert any(step["tool"] == "find_ring_membership" and "ring of 3 customers" in step["result"] for step in state["agent_trace"])
    assert any(item["claim"].startswith("Graph-wide ring:") for item in state["case"]["evidence"])


def test_graph_memory_recalls_only_earlier_investigations_and_counts_fraud(agent):
    provider, engine = agent
    asked = {}

    class GraphMemorySource(CsvSource):
        def prior_investigations(self, customer_id, card_ids, device_ids, before, exclude_case):
            asked.update(customer_id=customer_id, cards=list(card_ids), before=before, exclude=exclude_case)
            return [{"case_id": "INV-SMP-900", "verdict": "fraud", "pattern": "card_testing", "opened_at": "2026-09-01 10:00:00", "reasons": ["card SMP-C302-K1"]}]

    source = GraphMemorySource(str(SAMPLE / "transactions.csv"), None, str(SAMPLE / "closed_cases_history.csv"))
    engine = LocalInvestigationEngine(source, memory=CaseMemory())
    state = engine.start_investigation(provider.get("SMP-002"))
    assert asked["exclude"] == "INV-SMP-002" and "SMP-C202-K1" in asked["cards"]
    assert any(step["tool"] == "recall_graph_memory" and "1 concluded fraud" in step["result"] for step in state["agent_trace"])
    claim = next(item for item in state["case"]["evidence"] if "SMP-900" in item["claim"])
    assert claim["ref"] == "tigergraph:InvestigationCase" and "its card is in this card's ring: SMP-C302-K1" in claim["claim"]

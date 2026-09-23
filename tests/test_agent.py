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

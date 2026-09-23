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

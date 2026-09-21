from __future__ import annotations
import json
from pathlib import Path
from backend.evidence_requests.models import RequestType
from backend.evidence_requests.models import EvidenceResponse, ResponseSource
from backend.evidence_requests.service import EvidenceRequestService, policy_effects
from backend.models.answer import FraudPattern, Verdict
from backend.policy.rules import PolicyContext, recommend_actions

def test_fixture_simulation_records_assumption(tmp_path: Path) -> None:
    (tmp_path / "case-x.json").write_text(json.dumps({"responses":[{"type":"customer_validation","result":"denied","assumption":"Demonstration only."}]}))
    service = EvidenceRequestService(tmp_path)
    request = service.create(case_id="case-x", request_type=RequestType.CUSTOMER_VALIDATION, question="Did you make this?", reason="R1", ordinal=0)
    response = service.simulate(request)
    assert response.simulated and response.assumption == "Demonstration only." and response.result == "denied"
    assert any(item.action.value == "BLOCK_CARD" for item in recommend_actions(PolicyContext(customer_response=policy_effects(response)["customer_response"])))

def test_customer_confirmed_reaches_r3() -> None:
    response = EvidenceRequestService(default_results={"customer_validation": ("confirmed",)}).simulate(EvidenceRequestService().create(case_id="c", request_type=RequestType.CUSTOMER_VALIDATION, question="q", reason="r", ordinal=0))
    assert [item.action.value for item in recommend_actions(PolicyContext(customer_response=policy_effects(response)["customer_response"]))] == ["CLOSE_NO_FRAUD"]

def test_no_reply_and_analyst_conflict_reach_r4_and_r8() -> None:
    service = EvidenceRequestService(default_results={"customer_validation": ("no_reply",), "analyst_info": ("unknown",)})
    request = service.create(case_id="c", request_type=RequestType.CUSTOMER_VALIDATION, question="q", reason="r", ordinal=0)
    no_reply = policy_effects(service.simulate(request))
    assert "DECLINE_TRANSACTION" in [item.action.value for item in recommend_actions(PolicyContext(**no_reply))]
    analyst = service.simulate(service.create(case_id="c", request_type=RequestType.ANALYST_INFO, question="q", reason="r", ordinal=1))
    assert policy_effects(analyst)["conflicting_evidence"] is False
    conflict = EvidenceResponse(request_id="r", case_id="c", type=RequestType.ANALYST_INFO, result="unknown", source=ResponseSource.SIMULATION, simulated=True, assumption="Demonstration only.", details={"finding":"Conflicting graph facts.", "supporting_entity_ids":[], "confidence":0.8, "notes":"Synthetic analyst note."})
    assert "ESCALATE_TO_ANALYST" in [item.action.value for item in recommend_actions(PolicyContext(verdict=Verdict.UNCERTAIN, **policy_effects(conflict)))]

def test_step_up_results_are_evidence_not_actions() -> None:
    service = EvidenceRequestService(default_results={"step_up_auth": ("passed", "failed")})
    first = service.simulate(service.create(case_id="case-one", request_type=RequestType.STEP_UP_AUTH, question="q", reason="r", ordinal=0))
    second = service.simulate(service.create(case_id="case-two", request_type=RequestType.STEP_UP_AUTH, question="q", reason="r", ordinal=0))
    assert first.simulated and second.simulated
    assert policy_effects(first)["step_up_authentication_evidence"] in {0.0, 1.0}
    assert policy_effects(second)["step_up_authentication_evidence"] in {0.0, 1.0}

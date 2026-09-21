import pytest
from pydantic import ValidationError

from backend.models.answer import (
    Action,
    Answer,
    ApprovalRoute,
    Case,
    CaseStatus,
    Evidence,
    EvidenceRequest,
    EvidenceRequestType,
    EvidenceSource,
    FraudPattern,
    NextBestActions,
    PolicyAction,
    SAR,
    Verdict,
)


def valid_answer(**overrides):
    payload = {
        "case_id": "HHG-001",
        "case": {
            "status": "open",
            "verdict": "uncertain",
            "fraud_probability": 0.61,
            "pattern": "none",
            "pattern_description": "",
            "affected_txn_ids": [],
            "first_suspicious_txn_id": "",
            "connected_card_ids": [],
            "connected_device_profiles": [],
            "exposure_usd": 0,
            "evidence": [
                {
                    "claim": "The flagged transaction has risk score 0.61.",
                    "source": "graph",
                    "ref": "query:transaction_context",
                    "entity_ids": ["3514030"],
                }
            ],
            "similar_prior_cases": [],
            "summary": "More evidence is required.",
            "written_to_graph": False,
            "graph_case_id": "",
        },
        "evidence_requests": [],
        "next_best_actions": {
            "initial": [
                {
                    "action": "VERIFY_WITH_CUSTOMER",
                    "route": "auto",
                    "reason": "R1: verify a weak signal before blocking.",
                }
            ],
            "final": [
                {
                    "action": "VERIFY_WITH_CUSTOMER",
                    "route": "auto",
                    "reason": "R1: verify a weak signal before blocking.",
                }
            ],
            "what_changed": "nothing",
        },
        "sar": {
            "file": False,
            "reason": "No report criteria has been established.",
            "narrative": "",
            "subjects": [],
            "total_amount_usd": 0,
            "activity_dates": [],
        },
        "stop_reason": "Waiting for customer validation.",
        "tool_calls": 8,
        "tokens": 0,
        "latency_s": 1.25,
    }
    for key, value in overrides.items():
        payload[key] = value
    return payload


def test_valid_answer_parses():
    answer = Answer.model_validate(valid_answer())
    assert answer.case_id == "HHG-001"
    assert answer.case.fraud_probability == 0.61
    assert answer.next_best_actions.initial[0].route is ApprovalRoute.AUTO


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("case.status", "pending"),
        ("case.verdict", "maybe"),
        ("case.pattern", "kaggle_label"),
        ("evidence_requests.0.type", "email_check"),
        ("case.evidence.0.source", "llm"),
        ("next_best_actions.initial.0.route", "L3"),
        ("next_best_actions.initial.0.action", "BLOCK_EVERYTHING"),
    ],
)
def test_invalid_enum_values_fail(field, value):
    payload = valid_answer()
    if field.startswith("case."):
        payload["case"][field.split(".")[1]] = value
    elif field.startswith("evidence_requests."):
        payload["evidence_requests"] = [
            {"type": value, "asked_after_step": 1, "assumed_response": "No response"}
        ]
    elif field.startswith("next_best_actions.initial."):
        payload["next_best_actions"]["initial"][0][field.split(".")[-1]] = value
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)


def test_extra_fields_are_forbidden():
    payload = valid_answer()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)


def test_strict_numeric_validation():
    payload = valid_answer()
    payload["case"]["fraud_probability"] = "0.61"
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)


def test_probability_and_counts_are_bounded():
    payload = valid_answer()
    payload["case"]["fraud_probability"] = 1.01
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)
    payload = valid_answer()
    payload["tool_calls"] = -1
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)


def test_undocumented_requires_description():
    payload = valid_answer()
    payload["case"]["pattern"] = "undocumented"
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)


def test_legitimate_case_invariants():
    payload = valid_answer()
    payload["case"]["verdict"] = "legitimate"
    payload["case"]["affected_txn_ids"] = ["3514030"]
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)


def test_sar_shape_and_action_must_agree():
    payload = valid_answer()
    payload["next_best_actions"]["final"].append(
        {
            "action": "FILE_REPORT",
            "route": "L2",
            "reason": "R2: report criteria met.",
        }
    )
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)

    payload = valid_answer()
    payload["next_best_actions"]["final"].append(
        {
            "action": "FILE_REPORT",
            "route": "L2",
            "reason": "R2: report criteria met.",
        }
    )
    payload["sar"] = {
        "file": True,
        "reason": "R2: report criteria met.",
        "narrative": "Customer activity is suspicious.",
        "subjects": ["C12382", "C12382-K1"],
        "total_amount_usd": 77.07,
        "activity_dates": ["2016-12-04", "2016-12-04"],
    }
    parsed = Answer.model_validate(payload)
    assert parsed.sar.file is True


def test_sar_false_requires_empty_report_fields():
    payload = valid_answer()
    payload["sar"]["narrative"] = "Should be empty."
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)


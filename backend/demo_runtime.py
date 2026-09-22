"""Honest local reference runtime for UI/API demos.

It exposes benchmark triggers from case_pack.csv and never fabricates outcomes.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CasePackProvider:
    def __init__(self, path: str) -> None:
        with Path(path).open(newline="", encoding="utf-8") as handle:
            self._cases = {row["case_id"]: row for row in csv.DictReader(handle)}

    def list(self) -> list[dict[str, Any]]:
        return [{"case_id": row["case_id"], "trigger_type": row.get("trigger_type", ""), "opened_at": row.get("opened_at", "")} for row in self._cases.values()]

    def get(self, case_id: str) -> dict[str, Any]:
        if case_id not in self._cases:
            raise KeyError(case_id)
        return dict(self._cases[case_id])


class PreviewCaseProvider:
    """A clearly labeled synthetic case keeps the local product demonstrable.

    It is never a substitute for benchmark input and is intentionally scoped
    to the no-case-pack local preview experience.
    """
    _case = {
        "case_id": "DEMO-001", "trigger_type": "simulated_risk_signal",
        "trigger_text": "SIMULATED DEMO: unusual device and merchant velocity signal.",
        "opened_at": "2026-09-22T10:42:00Z", "customer_id": "DEMO-CUSTOMER-41",
        "card_id": "DEMO-CARD-41", "flagged_txn_id": "DEMO-TXN-9031", "risk_score": 0.82,
    }

    def list(self) -> list[dict[str, Any]]:
        return [{"case_id": self._case["case_id"], "trigger_type": "SIMULATED · risk signal", "opened_at": self._case["opened_at"]}]

    def get(self, case_id: str) -> dict[str, Any]:
        if case_id != self._case["case_id"]:
            raise KeyError(case_id)
        return dict(self._case)


class ReferenceWorkflow:
    """Local, evidence-only runtime for validating API/UI wiring."""
    def __init__(self, transactions_path: str | None = None) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._transactions: dict[str, dict[str, str]] = {}
        if transactions_path and Path(transactions_path).exists():
            with Path(transactions_path).open(newline="", encoding="utf-8-sig") as handle:
                self._transactions = {row["TransactionID"]: row for row in csv.DictReader(handle) if row.get("TransactionID")}

    @staticmethod
    def _seal(state: dict[str, Any], event: dict[str, Any]) -> None:
        """Append an auditable, deterministic hash-chain entry for a case event."""
        ledger = list(state.get("integrity_ledger", []))
        previous_hash = ledger[-1]["hash"] if ledger else "GENESIS"
        material = json.dumps(
            {"case_id": state["case_id"], "previous_hash": previous_hash, "event": event},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        ledger.append({
            "sequence": len(ledger) + 1,
            "event_type": str(event.get("type", "case_event")),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "previous_hash": previous_hash,
            "hash": digest,
        })
        state["integrity_ledger"] = ledger
        state["integrity"] = {
            "status": "sealed",
            "event_count": len(ledger),
            "latest_hash": digest,
            "chain_root": ledger[0]["hash"],
        }

    def start_investigation(self, case_input: dict[str, Any]) -> dict[str, Any]:
        case_id = case_input["case_id"]
        flagged_id = case_input.get("flagged_txn_id", "")
        transaction = self._transactions.get(flagged_id)
        nodes = [{"data": {"id": f"transaction:{flagged_id}", "label": f"Transaction {flagged_id}", "entity_type": "Transaction"}}]
        edges: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        if transaction:
            customer_id = transaction.get("customer_id") or case_input.get("customer_id", "")
            nodes.extend([
                {"data": {"id": f"customer:{customer_id}", "label": f"Customer {customer_id}", "entity_type": "Customer"}},
                {"data": {"id": f"card:{case_input.get('card_id', '')}", "label": f"Card {case_input.get('card_id', '')}", "entity_type": "Card"}},
            ])
            edges.extend([
                {"data": {"id": "edge:customer-card", "source": f"customer:{customer_id}", "target": f"card:{case_input.get('card_id', '')}", "label": "OWNS"}},
                {"data": {"id": "edge:card-transaction", "source": f"card:{case_input.get('card_id', '')}", "target": f"transaction:{flagged_id}", "label": "MADE"}},
            ])
            timeline.append({"transaction_id": flagged_id, "ts": transaction.get("ts", ""), "transaction_amt": transaction.get("TransactionAmt", ""), "channel": transaction.get("channel", ""), "risk_score": transaction.get("risk_score", ""), "billing_region": transaction.get("addr1", "")})
            evidence.append({"claim": f"Transaction {flagged_id} is present in the supplied transaction dataset with customer {customer_id} and timestamp {transaction.get('ts', '')}.", "source": "graph", "ref": "local.transactions.csv", "entity_ids": [flagged_id, customer_id]})
        audit_event = {"type": "local_transaction_lookup", "reference": flagged_id, "grounded": bool(transaction)}
        state = {**case_input, "case_id": case_id, "trigger": case_input, "status": "evidence_available", "message": "Grounded local transaction context loaded. Fraud assessment remains unavailable until the configured investigation workflow runs.", "graph": {"nodes": nodes, "edges": edges}, "timeline": timeline, "case": {"evidence": evidence}, "audit": [audit_event]}
        self._seal(state, audit_event)
        self._states[case_id] = state
        return state

    def resume_with_approval(self, case_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        state = self._states[case_id]
        state["approval_events"] = [*state.get("approval_events", []), decision]
        event = {"type": "approval_recorded", "action": decision.get("action", ""), "approved": bool(decision.get("approved"))}
        state["audit"] = [*state.get("audit", []), event]
        self._seal(state, event)
        state["message"] = "Approval event recorded by the reference runtime; no fraud decision was inferred."
        return state

    def resume_with_evidence(self, case_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        state = self._states[case_id]
        state["evidence_responses"] = [*state.get("evidence_responses", []), evidence]
        event = {"type": "evidence_response_recorded", "request_id": evidence.get("request_id", ""), "result": evidence.get("result", "unknown")}
        state["audit"] = [*state.get("audit", []), event]
        self._seal(state, event)
        state["message"] = "Evidence response recorded as supplied; no fraud decision was inferred."
        return state

    def get_investigation_state(self, case_id: str) -> dict[str, Any]:
        return self._states[case_id]


class PreviewWorkflow:
    """Interactive synthetic preview with prominent simulation provenance."""
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}

    def start_investigation(self, case_input: dict[str, Any]) -> dict[str, Any]:
        case_id = case_input["case_id"]
        evidence = [
            {"claim": "SIMULATED: a new device initiated an online purchase materially above the card's recent activity.", "source": "simulated", "ref": "preview:device-velocity", "entity_ids": ["DEMO-TXN-9031", "DEMO-DEVICE-77"], "simulated": True, "assumption": "Synthetic preview data; not a benchmark finding."},
            {"claim": "SIMULATED: two cards share the same device fingerprint within a short review window.", "source": "simulated", "ref": "preview:shared-device", "entity_ids": ["DEMO-CARD-41", "DEMO-CARD-88", "DEMO-DEVICE-77"], "simulated": True, "assumption": "Synthetic preview data; not a benchmark finding."},
        ]
        state = {**case_input, "status": "awaiting_evidence", "simulation_mode": True,
            "message": "Interactive synthetic preview. Load case_pack.csv to investigate benchmark triggers.",
            "case": {"status": "escalated", "verdict": "uncertain", "fraud_probability": 0.74, "pattern": "account_takeover", "exposure_usd": 1840.0, "summary": "SIMULATED preview: device reuse and an abnormal online purchase warrant controlled verification before a block.", "evidence": evidence, "similar_prior_cases": ["SIM-CASE-018"]},
            "graph": {"nodes": [
                {"data": {"id": "transaction:DEMO-TXN-9031", "label": "Flagged payment", "entity_type": "Transaction"}},
                {"data": {"id": "customer:DEMO-CUSTOMER-41", "label": "Customer 41", "entity_type": "Customer"}},
                {"data": {"id": "card:DEMO-CARD-41", "label": "Card 41", "entity_type": "Card"}},
                {"data": {"id": "device:DEMO-DEVICE-77", "label": "New device", "entity_type": "DeviceProfile"}},
                {"data": {"id": "card:DEMO-CARD-88", "label": "Connected card", "entity_type": "Card"}},
            ], "edges": [
                {"data": {"id": "owns", "source": "customer:DEMO-CUSTOMER-41", "target": "card:DEMO-CARD-41", "label": "OWNS"}},
                {"data": {"id": "made", "source": "card:DEMO-CARD-41", "target": "transaction:DEMO-TXN-9031", "label": "MADE"}},
                {"data": {"id": "used", "source": "transaction:DEMO-TXN-9031", "target": "device:DEMO-DEVICE-77", "label": "USED"}},
                {"data": {"id": "shared", "source": "card:DEMO-CARD-88", "target": "device:DEMO-DEVICE-77", "label": "SHARES"}},
            ]},
            "timeline": [
                {"transaction_id": "DEMO-TXN-9029", "ts": "2026-09-22T10:21:00Z", "transaction_amt": "19.25", "channel": "online", "risk_score": "0.31", "device_profile_id": "DEMO-DEVICE-77", "billing_region": "CA"},
                {"transaction_id": "DEMO-TXN-9030", "ts": "2026-09-22T10:33:00Z", "transaction_amt": "42.00", "channel": "online", "risk_score": "0.48", "device_profile_id": "DEMO-DEVICE-77", "billing_region": "CA"},
                {"transaction_id": "DEMO-TXN-9031", "ts": "2026-09-22T10:42:00Z", "transaction_amt": "1840.00", "channel": "online", "risk_score": "0.82", "device_profile_id": "DEMO-DEVICE-77", "billing_region": "CA", "suspicious": True},
            ], "similar_cases": [{"case_id": "SIM-CASE-018", "pattern": "account_takeover", "outcome": "confirmed after customer denial", "similarity_score": "0.81", "reason_for_match": "SIMULATED: new device and abrupt online amount change."}],
            "evidence_requests": [{"request_id": "DEMO-VERIFY-01", "case_id": case_id, "type": "customer_validation", "question": "Did you authorize the $1,840.00 online purchase?", "reason": "SIMULATED preview: customer confirmation resolves the highest-impact uncertainty.", "status": "pending"}],
            "next_best_actions": {"initial": [{"action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "SIMULATED preview: evidence is concerning but customer validation is still required."}, {"action": "MONITOR_CARD", "route": "auto", "reason": "SIMULATED preview: monitor while verification is pending."}], "final": [], "what_changed": "Awaiting a controlled customer-validation response."},
            "approval_requests": [], "sar": {"file": False, "reason": "SIMULATED preview: report threshold is not met until evidence is resolved.", "narrative": "", "subjects": [], "total_amount_usd": 0, "activity_dates": []},
            "audit": [{"type": "synthetic_preview_started", "reference": "DEMO-001", "grounded": False, "simulated": True}]}
        ReferenceWorkflow._seal(state, state["audit"][0])
        self._states[case_id] = state
        return state

    def resume_with_evidence(self, case_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        state = self._states[case_id]
        state["evidence_responses"] = [*state.get("evidence_responses", []), {**evidence, "simulated": True, "assumption": "Synthetic preview response; not customer-provided evidence."}]
        result = evidence.get("result", "unknown")
        state["status"] = "evidence_reviewed"
        state["next_best_actions"]["final"] = [{"action": "ESCALATE_TO_ANALYST", "route": "L1", "reason": f"SIMULATED preview: customer validation result is {result}; analyst review is required before protected actions."}]
        state["next_best_actions"]["what_changed"] = "A simulated evidence response was recorded and the controlled escalation route was updated."
        state["approval_requests"] = [{"action": "ESCALATE_TO_ANALYST", "route": "L1", "reason": "SIMULATED preview: analyst must approve the escalation route.", "approval_status": "pending"}]
        event = {"type": "synthetic_evidence_response", "result": result, "simulated": True}
        state["audit"] = [*state["audit"], event]
        ReferenceWorkflow._seal(state, event)
        return state

    def resume_with_approval(self, case_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        state = self._states[case_id]
        event = {"type": "synthetic_approval_recorded", "action": decision.get("action"), "approved": bool(decision.get("approved")), "simulated": True}
        state["audit"] = [*state["audit"], event]
        state["approval_requests"] = [{**item, "approval_status": "approved" if decision.get("approved") else "rejected"} for item in state.get("approval_requests", [])]
        state["message"] = "SIMULATED preview: approval decision recorded. Load case_pack.csv for real benchmark investigation."
        ReferenceWorkflow._seal(state, event)
        return state

    def get_investigation_state(self, case_id: str) -> dict[str, Any]:
        return self._states[case_id]


def build_reference_runtime(path: str) -> tuple[CasePackProvider, ReferenceWorkflow]:
    transaction_path = os.getenv("TRANSACTIONS_PATH")
    return CasePackProvider(path), ReferenceWorkflow(transaction_path)


def build_preview_runtime() -> tuple[PreviewCaseProvider, PreviewWorkflow]:
    return PreviewCaseProvider(), PreviewWorkflow()

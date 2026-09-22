"""Honest local reference runtime for UI/API demos.

It exposes benchmark triggers from case_pack.csv and never fabricates outcomes.
"""
from __future__ import annotations

import csv
import os
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


class ReferenceWorkflow:
    """Local, evidence-only runtime for validating API/UI wiring."""
    def __init__(self, transactions_path: str | None = None) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._transactions: dict[str, dict[str, str]] = {}
        if transactions_path and Path(transactions_path).exists():
            with Path(transactions_path).open(newline="", encoding="utf-8-sig") as handle:
                self._transactions = {row["TransactionID"]: row for row in csv.DictReader(handle) if row.get("TransactionID")}

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
        state = {"case_id": case_id, "trigger": case_input, "status": "evidence_available", "message": "Grounded local transaction context loaded. Fraud assessment remains unavailable until the configured investigation workflow runs.", "graph": {"nodes": nodes, "edges": edges}, "timeline": timeline, "case": {"evidence": evidence}, "audit": [{"type": "local_transaction_lookup", "reference": flagged_id, "grounded": bool(transaction)}]}
        self._states[case_id] = state
        return state

    def resume_with_approval(self, case_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        state = self._states[case_id]
        state["approval_events"] = [*state.get("approval_events", []), decision]
        state["message"] = "Approval event recorded by the reference runtime; no fraud decision was inferred."
        return state

    def resume_with_evidence(self, case_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        state = self._states[case_id]
        state["evidence_responses"] = [*state.get("evidence_responses", []), evidence]
        state["message"] = "Evidence response recorded as supplied; no fraud decision was inferred."
        return state

    def get_investigation_state(self, case_id: str) -> dict[str, Any]:
        return self._states[case_id]


def build_reference_runtime(path: str) -> tuple[CasePackProvider, ReferenceWorkflow]:
    transaction_path = os.getenv("TRANSACTIONS_PATH")
    return CasePackProvider(path), ReferenceWorkflow(transaction_path)

"""Honest local reference runtime for UI/API demos.

It exposes benchmark triggers from case_pack.csv and never fabricates outcomes.
"""
from __future__ import annotations

import csv
import hashlib
import json
import mmap
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CasePackProvider:
    def __init__(self, path: str, transactions_path: str | None = None) -> None:
        with Path(path).open(newline="", encoding="utf-8") as handle:
            self._cases = {row["case_id"]: row for row in csv.DictReader(handle)}
        self._risk_scores: dict[str, str] = {}
        if transactions_path and Path(transactions_path).exists():
            targets = {str(row.get("flagged_txn_id") or "") for row in self._cases.values() if not row.get("risk_score")}
            with Path(transactions_path).open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                header = next(csv.reader([mapped.readline().decode("utf-8", "replace")]))
                risk_index = header.index("risk_score") if "risk_score" in header else -1
                while risk_index >= 0 and targets:
                    line = mapped.readline()
                    if not line:
                        break
                    transaction_id = line.split(b",", 1)[0].decode("utf-8", "replace")
                    if transaction_id not in targets:
                        continue
                    fields = next(csv.reader([line.decode("utf-8", "replace")]))
                    if risk_index < len(fields) and fields[risk_index]:
                        self._risk_scores[transaction_id] = fields[risk_index]
                        targets.remove(transaction_id)

    def _with_risk_score(self, row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        if not result.get("risk_score"):
            result["risk_score"] = self._risk_scores.get(str(result.get("flagged_txn_id") or ""), "")
        return result

    def list(self) -> list[dict[str, Any]]:
        fields = ("case_id", "trigger_type", "trigger_text", "opened_at", "flagged_txn_id", "customer_id", "card_id", "risk_score")
        return [{field: self._with_risk_score(row).get(field, "") for field in fields} for row in self._cases.values()]

    def get(self, case_id: str) -> dict[str, Any]:
        if case_id not in self._cases:
            raise KeyError(case_id)
        return self._with_risk_score(self._cases[case_id])


# Only these transaction columns are read; the rest of the wide source table is ignored.
_TRANSACTION_FIELDS = ("TransactionID", "customer_id", "card_id", "ts", "TransactionAmt", "channel", "risk_score", "addr1", "P_emaildomain", "ProductCD", "card4", "card6", "device_profile_id", "id_15", "id_23", "id_34")


class ReferenceWorkflow:
    """Local, evidence-only runtime for validating API/UI wiring."""
    def __init__(self, transactions_path: str | None = None) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._transactions: dict[str, dict[str, str]] = {}
        self._by_customer: dict[str, list[str]] = {}
        if transactions_path and Path(transactions_path).exists():
            with Path(transactions_path).open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    txn_id = row.get("TransactionID")
                    if not txn_id:
                        continue
                    self._transactions[txn_id] = {key: row[key] for key in _TRANSACTION_FIELDS if row.get(key)}
                    if row.get("customer_id"):
                        self._by_customer.setdefault(row["customer_id"], []).append(txn_id)

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

    @staticmethod
    def _timeline_row(txn_id: str, row: dict[str, str], flagged: bool) -> dict[str, Any]:
        return {"transaction_id": txn_id, "ts": row.get("ts", ""), "transaction_amt": row.get("TransactionAmt", ""), "channel": row.get("channel", ""), "risk_score": row.get("risk_score", ""), "billing_region": row.get("addr1", ""), "email_domain": row.get("P_emaildomain", ""), "suspicious": flagged}

    def start_investigation(self, case_input: dict[str, Any]) -> dict[str, Any]:
        case_id = case_input["case_id"]
        flagged_id = case_input.get("flagged_txn_id", "")
        transaction = self._transactions.get(flagged_id)
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []

        def node(entity_type: str, key: str, label: str, **extra: Any) -> str:
            node_id = f"{entity_type.lower()}:{key}"
            nodes.setdefault(node_id, {"data": {"id": node_id, "label": label, "entity_type": entity_type, "entity_id": key, **extra}})
            return node_id

        def edge(source: str, target: str, label: str) -> None:
            edges.append({"data": {"id": f"edge:{source}->{target}", "source": source, "target": target, "label": label}})

        if flagged_id:
            txn_node = node("Transaction", flagged_id, flagged_id, flagged=True)
        customer_id = (transaction or {}).get("customer_id") or case_input.get("customer_id", "")
        card_id = case_input.get("card_id", "")
        if customer_id:
            customer_node = node("Customer", customer_id, customer_id)
        if card_id:
            card_node = node("Card", card_id, card_id)
            if customer_id:
                edge(customer_node, card_node, "OWNS")
            if flagged_id:
                edge(card_node, txn_node, "MADE")
        elif customer_id and flagged_id:
            edge(customer_node, txn_node, "MADE")
        if transaction:
            if transaction.get("P_emaildomain"):
                edge(txn_node, node("EmailDomain", transaction["P_emaildomain"], transaction["P_emaildomain"]), "USED_EMAIL")
            if transaction.get("addr1"):
                edge(txn_node, node("BillingRegion", transaction["addr1"], f"Region {transaction['addr1']}"), "BILLED_TO")
            history = sorted(self._by_customer.get(customer_id, [flagged_id]), key=lambda txn: self._transactions[txn].get("ts", ""))
            timeline = [self._timeline_row(txn, self._transactions[txn], txn == flagged_id) for txn in history]
            evidence.append({"claim": f"Transaction {flagged_id} is present in the supplied transaction dataset with customer {customer_id} and timestamp {transaction.get('ts', '')}.", "source": "graph", "ref": "local.transactions.csv", "entity_ids": [flagged_id, customer_id]})
            if len(history) > 1:
                evidence.append({"claim": f"Customer {customer_id} has {len(history)} transactions in the supplied dataset.", "source": "graph", "ref": "local.transactions.csv", "entity_ids": [customer_id]})
        audit_event = {"type": "local_transaction_lookup", "reference": flagged_id, "grounded": bool(transaction)}
        message = "Grounded local transaction context loaded. Fraud assessment remains unavailable until the configured investigation workflow runs." if transaction else "The flagged transaction was not found in the configured transactions file. Set TRANSACTIONS_PATH to load transaction context."
        state = {**case_input, "case_id": case_id, "trigger": case_input, "status": "evidence_available", "message": message, "graph": {"nodes": list(nodes.values()), "edges": edges}, "timeline": timeline, "case": {"evidence": evidence}, "audit": [audit_event]}
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

    def overview(self, case_input: dict[str, Any]) -> dict[str, Any] | None:
        """Lookup-only runtime has no assessment to summarise."""
        return None


def build_reference_runtime(path: str, transactions_path: str | None = None, closed_cases_path: str | None = None) -> tuple[CasePackProvider, ReferenceWorkflow]:
    """Case pack plus the investigation agent over the configured graph source.

    ``DATA_SOURCE=tigergraph`` answers the agent's tools with installed GSQL
    queries over TigerGraph MCP; otherwise the supplied CSV files are used.
    """
    from backend.local_engine import LocalInvestigationEngine
    from backend.sources.tigergraph_source import MCPGraphWriter, open_source
    from backend.cases.service import InvestigationCaseService

    transactions = transactions_path or os.getenv("TRANSACTIONS_PATH")
    closed_cases = closed_cases_path or os.getenv("CLOSED_CASES_PATH")
    identity = os.getenv("IDENTITY_PATH")
    kind = "csv" if transactions_path is not None else os.getenv("DATA_SOURCE", "csv")
    source = open_source(kind, transactions=transactions, identity=identity, closed_cases=closed_cases) if (kind.lower().startswith("tiger") or transactions) else None
    case_service = InvestigationCaseService(MCPGraphWriter(source)) if source is not None and source.name == "tigergraph-mcp" else None
    return CasePackProvider(path, transactions), LocalInvestigationEngine(source, case_service=case_service)

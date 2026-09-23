"""Simulated execution of the agent's actions through mock bank systems.

The challenge allows actions to be "simulated, stubbed, or represented through
mock APIs". This module is that layer: each action goes to the system that
would carry it out (card platform, customer messaging, case management,
regulatory filing, transaction monitoring) and comes back with a receipt.

Rules the agent follows:

* ``auto`` actions execute as soon as the policy recommends them.
* ``L1``/``L2`` actions execute only after a human approves them; a rejected
  action gets a "not executed" receipt.
* Every receipt is sealed into the case's hash chain and clearly labelled
  simulated. Nothing here touches a real system.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

SYSTEMS: dict[str, tuple[str, str]] = {
    "ALLOW_TRANSACTION": ("payments", "Transaction released for settlement"),
    "DECLINE_TRANSACTION": ("payments", "Pending authorisation declined"),
    "MONITOR_CARD": ("transaction-monitoring", "Card added to enhanced monitoring for 30 days"),
    "MONITOR_CONNECTED_CARDS": ("transaction-monitoring", "Connected cards added to enhanced monitoring"),
    "WARN_CUSTOMER": ("customer-messaging", "Fraud-awareness warning sent to the customer"),
    "VERIFY_WITH_CUSTOMER": ("customer-messaging", "Verification request sent to the customer's registered phone"),
    "STEP_UP_AUTH": ("identity", "Step-up authentication challenge issued on next use"),
    "BLOCK_CARD": ("card-platform", "Card blocked; replacement order created"),
    "BLOCK_ALL_CARDS": ("card-platform", "All of the customer's cards blocked"),
    "GENERATE_REPORT": ("case-management", "Investigation report generated"),
    "CREATE_CASE": ("case-management", "Fraud case opened in case management"),
    "FILE_REPORT": ("regulatory-filing", "Suspicious activity report queued for filing"),
    "ESCALATE_TO_ANALYST": ("case-management", "Case routed to the analyst review queue"),
    "CLOSE_NO_FRAUD": ("case-management", "Alert closed as no fraud"),
}


class MockActionService:
    """Carries out actions against simulated systems and returns receipts."""

    def execute(self, case_id: str, action: dict[str, Any], *, sequence: int, approved_by: str = "") -> dict[str, Any]:
        system, detail = SYSTEMS.get(action["action"], ("case-management", "Action recorded"))
        receipt = "MOCK-" + hashlib.sha256(f"{case_id}|{action['action']}|{sequence}".encode()).hexdigest()[:8].upper()
        return {"receipt_id": receipt, "action": action["action"], "route": action["route"], "status": "executed", "system": system,
                "detail": detail, "approved_by": approved_by or ("policy (auto)" if action["route"] == "auto" else ""),
                "executed_at": datetime.now(timezone.utc).isoformat(), "simulated": True}

    def reject(self, case_id: str, action: dict[str, Any], *, sequence: int) -> dict[str, Any]:
        system, _ = SYSTEMS.get(action["action"], ("case-management", ""))
        return {"receipt_id": "", "action": action["action"], "route": action["route"], "status": "rejected", "system": system,
                "detail": f"Not executed: {action['route']} approver rejected it", "approved_by": "", "executed_at": datetime.now(timezone.utc).isoformat(), "simulated": True}

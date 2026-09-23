"""Local investigation engine over CSV inputs.

It runs the repository's deterministic investigation modules (pattern
detection, fraud probability, stopping, policy R1-R10, approval routing and
SAR generation) against transactions and closed cases read from CSV files, so
the full analyst workflow can be exercised without a TigerGraph instance.

Every claim is derived from a supplied row. Nothing here invents a fact: when
the flagged transaction is missing, the engine falls back to lookup only.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from backend.demo_runtime import ReferenceWorkflow
from backend.evidence_requests.models import CustomerResult, StepUpResult
from backend.investigation.exposure import episode_exposure_usd
from backend.investigation.fraud_probability import ScoringInputs, deterministic_fraud_probability
from backend.investigation.patterns import PatternContext, TransactionEvidence, classify_pattern
from backend.investigation.scoring_config import DEFAULT_STOPPING_CONFIG
from backend.investigation.stopping import EvidenceDirection, IndependentEvidence, VerificationResponse, evaluate_stopping
from backend.models.answer import FraudPattern, PolicyAction, Verdict
from backend.policy.approvals import get_approval_route
from backend.policy.rules import CustomerResponse, PolicyContext, recommend_actions
from backend.policy.sar import build_sar, evaluate_sar, generate_grounded_sar

TRANSACTIONS_REF = "transactions.csv"
CLOSED_CASES_REF = "closed_cases_history.csv"
CONFIRMED_OUTCOMES = {"confirmed_fraud", "fraud", "fraud_confirmed"}
PATTERN_WINDOW = timedelta(hours=48)
NETWORK_WINDOW = timedelta(days=7)


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value: float) -> str:
    return f"${value:,.2f}"


class LocalInvestigationEngine(ReferenceWorkflow):
    def __init__(self, transactions_path: str | None = None, closed_cases_path: str | None = None) -> None:
        super().__init__(transactions_path)
        self._closed: list[dict[str, str]] = []
        if closed_cases_path and Path(closed_cases_path).exists():
            with Path(closed_cases_path).open(newline="", encoding="utf-8-sig") as handle:
                self._closed = [row for row in csv.DictReader(handle) if row.get("case_id")]
        self._contexts: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ data

    def _card_of(self, row: dict[str, str], case_input: dict[str, Any]) -> str:
        if row.get("card_id"):
            return row["card_id"]
        return case_input.get("card_id", "") if row.get("customer_id") == case_input.get("customer_id") else ""

    def _evidence_row(self, txn_id: str, case_input: dict[str, Any]) -> TransactionEvidence | None:
        row = self._transactions.get(txn_id)
        stamp = _time(row.get("ts")) if row else None
        amount = _float(row.get("TransactionAmt")) if row else None
        if not row or stamp is None or amount is None:
            return None
        return TransactionEvidence(
            transaction_id=txn_id, card_id=self._card_of(row, case_input), customer_id=row.get("customer_id", ""),
            timestamp=stamp, amount_usd=amount, channel=row.get("channel", ""), billing_region=row.get("addr1") or None,
            product_code=row.get("ProductCD") or None, purchaser_email_domain=row.get("P_emaildomain") or None,
            device_profile_id=row.get("device_profile_id") or None, device_status=row.get("id_15") or None,
            proxy_type=row.get("id_23") or None, match_status=row.get("id_34") or None,
        )

    def _context(self, case_input: dict[str, Any]) -> dict[str, Any] | None:
        target = self._evidence_row(case_input.get("flagged_txn_id", ""), case_input)
        if target is None:
            return None
        customer_ids = self._by_customer.get(target.customer_id, [])
        customer_history = [item for item in (self._evidence_row(txn, case_input) for txn in customer_ids) if item]
        card_history = [item for item in customer_history if item.card_id == target.card_id] if target.card_id else customer_history
        network: list[TransactionEvidence] = []
        if target.device_profile_id:
            for txn_id, row in self._transactions.items():
                if row.get("device_profile_id") != target.device_profile_id or row.get("customer_id") == target.customer_id:
                    continue
                item = self._evidence_row(txn_id, {})
                if item and abs(item.timestamp - target.timestamp) <= NETWORK_WINDOW:
                    network.append(item)
        return {"target": target, "card_history": card_history, "customer_history": customer_history, "network": network}

    # ------------------------------------------------------------ assessment

    def _linked_closed_cases(self, context: dict[str, Any]) -> list[tuple[dict[str, str], list[str]]]:
        """Closed cases sharing an entity with this case, with the entities they share."""
        target: TransactionEvidence = context["target"]
        network_customers = {item.customer_id for item in context["network"]}
        network_txns = {item.transaction_id for item in context["network"]}
        linked = []
        for row in self._closed:
            reasons = []
            txn_ids = set(filter(None, row.get("txn_ids", "").split("|")))
            connected = set(filter(None, row.get("connected_card_ids", "").split("|")))
            if row.get("customer_id") == target.customer_id:
                reasons.append(f"same customer {target.customer_id}")
            if target.card_id and (row.get("card_id") == target.card_id or target.card_id in connected):
                reasons.append(f"same card {target.card_id}")
            if txn_ids & network_txns or row.get("customer_id") in network_customers:
                reasons.append(f"customer who shared device {target.device_profile_id}")
            devices = {self._transactions.get(txn, {}).get("device_profile_id") for txn in txn_ids}
            if target.device_profile_id and target.device_profile_id in devices and not any("device" in reason for reason in reasons):
                reasons.append(f"same device {target.device_profile_id}")
            if reasons:
                linked.append((row, reasons))
        return linked

    def _assess(self, case_input: dict[str, Any], context: dict[str, Any], responses: list[dict[str, Any]]) -> dict[str, Any]:
        target: TransactionEvidence = context["target"]
        card_history: list[TransactionEvidence] = context["card_history"]
        network: list[TransactionEvidence] = context["network"]
        prior = [item for item in card_history if item.timestamp < target.timestamp]
        evidence: list[dict[str, Any]] = []
        independent: list[IndependentEvidence] = []

        def fact(claim: str, entities: list[str], key: str | None = None, direction: EvidenceDirection = EvidenceDirection.FRAUD, source: str = "graph", ref: str = TRANSACTIONS_REF) -> None:
            evidence.append({"claim": claim, "source": source, "ref": ref, "entity_ids": [entity for entity in entities if entity]})
            if key:
                independent.append(IndependentEvidence(claim, direction, key))

        # Pattern detection runs the documented detectors unchanged.
        other_cards = sorted({item.card_id for item in network if item.card_id})
        linked = self._linked_closed_cases(context)
        confirmed_links = [(row, reasons) for row, reasons in linked if row.get("outcome", "").lower() in CONFIRMED_OUTCOMES]
        pattern = classify_pattern(PatternContext(
            target=target, card_history=tuple(card_history), customer_history=tuple(context["customer_history"]),
            network_transactions=tuple(network), connected_card_ids=tuple(other_cards),
            confirmed_related_case_ids=tuple(row["case_id"] for row, _ in confirmed_links),
        ))
        if pattern.pattern is not FraudPattern.NONE:
            fact(f"Pattern {pattern.pattern.value.replace('_', ' ')} detected: {'; '.join(pattern.supporting_evidence)}.", [target.transaction_id, target.card_id], "pattern")
        elif prior:
            fact(f"No documented fraud pattern matched: {'; '.join(pattern.contradicting_evidence[:2])}.", [target.transaction_id], "pattern_absent", EvidenceDirection.LEGITIMATE)

        unusual = 0.0
        if prior:
            typical = median(item.amount_usd for item in prior)
            if target.amount_usd >= max(2 * typical, typical + 50):
                unusual = 1.0
                fact(f"Flagged amount {_money(target.amount_usd)} is {target.amount_usd / typical:.1f}× the card's prior median of {_money(typical)} across {len(prior)} transactions.", [target.transaction_id, target.card_id], "amount")
            else:
                fact(f"Flagged amount {_money(target.amount_usd)} is in line with the card's prior median of {_money(typical)}.", [target.transaction_id], "amount_consistent", EvidenceDirection.LEGITIMATE)

        shared = 0.0
        other_customers = sorted({item.customer_id for item in network})
        prior_devices = {item.device_profile_id for item in prior if item.device_profile_id}
        if target.device_profile_id and other_customers:
            shared = 1.0
            fact(f"Device {target.device_profile_id} was also used by {len(other_customers)} other customer(s) ({', '.join(other_customers)}) within seven days.", [target.device_profile_id, *other_customers], "device")
        elif (target.device_status or "").lower() == "new" or (target.device_profile_id and prior_devices and target.device_profile_id not in prior_devices):
            shared = 0.5
            fact(f"Device {target.device_profile_id or 'on the flagged transaction'} is new for this card{' (identity marks it New)' if (target.device_status or '').lower() == 'new' else ''}.", [target.transaction_id, target.device_profile_id or ""], "device")
        elif target.device_profile_id and target.device_profile_id in prior_devices:
            fact(f"Device {target.device_profile_id} has been used on this card before.", [target.device_profile_id], "device_known", EvidenceDirection.LEGITIMATE)

        region = 0.0
        prior_regions = {item.billing_region for item in prior if item.billing_region}
        if target.billing_region and prior_regions and target.billing_region not in prior_regions:
            region = 1.0
            fact(f"Billing region {target.billing_region} is new for this card; prior regions: {', '.join(sorted(prior_regions))}.", [target.transaction_id], "region")

        history = 0.0
        for row, reasons in confirmed_links[:3]:
            history = 1.0
            fact(f"Closed case {row['case_id']} ({row.get('outcome', '').replace('_', ' ')}, {row.get('pattern', 'unknown').replace('_', ' ')}) involved the {', '.join(reasons)}.", [row["case_id"], *filter(None, [row.get("customer_id"), row.get("card_id")])], "history", ref=CLOSED_CASES_REF)

        # Customer and step-up evidence, from the trigger or recorded responses.
        customer: CustomerResponse | None = None
        no_reply = False
        step_up = 0.0
        conflicting = 0.0
        verification: VerificationResponse | None = None
        if case_input.get("trigger_type") == "customer_report":
            customer = CustomerResponse.DENIED
            fact(f"The customer reported the transaction as not made by them: “{case_input.get('trigger_text', '').strip()}”", [target.customer_id, target.transaction_id], "customer", source="customer", ref="case_pack.trigger_text")
            verification = VerificationResponse(True, EvidenceDirection.FRAUD, "case_pack.trigger_text")
        for response in responses:
            result = response.get("result")
            if response.get("type") == "customer_validation":
                if result == "denied":
                    customer = CustomerResponse.DENIED
                    fact("The customer denied making the transaction.", [target.customer_id, target.transaction_id], "customer", source="customer", ref=response["request_id"])
                    verification = VerificationResponse(True, EvidenceDirection.FRAUD, response["request_id"])
                elif result == "confirmed":
                    customer = CustomerResponse.CONFIRMED
                    conflicting = 1.0
                    fact("The customer confirmed they made the transaction.", [target.customer_id, target.transaction_id], "customer", EvidenceDirection.LEGITIMATE, "customer", response["request_id"])
                    verification = VerificationResponse(True, EvidenceDirection.LEGITIMATE, response["request_id"])
                elif result == "no_reply":
                    no_reply = True
                    fact("The customer did not reply to the verification request.", [target.customer_id], source="customer", ref=response["request_id"])
            elif response.get("type") == "step_up_auth":
                if result == "failed":
                    step_up = 1.0
                    fact("Step-up authentication failed.", [target.customer_id], "step_up", source="external", ref=response["request_id"])
                elif result == "passed":
                    conflicting = max(conflicting, 0.5)
                    fact("Step-up authentication passed.", [target.customer_id], "step_up", EvidenceDirection.LEGITIMATE, "external", response["request_id"])
            elif response.get("details"):
                fact(f"Analyst note: {response['details']}", [target.transaction_id], source="document", ref=response["request_id"])

        risk = min(1.0, max(0.0, _float(case_input.get("risk_score")) or _float(self._transactions[target.transaction_id].get("risk_score")) or 0.0))
        probability = deterministic_fraud_probability(ScoringInputs(
            risk_score=risk, pattern_strength=pattern.strength, unusual_transaction_behavior=unusual,
            shared_device_evidence=shared, region_evidence=region, prior_confirmed_fraud_cases=history,
            customer_evidence=1.0 if customer is CustomerResponse.DENIED else 0.0,
            step_up_authentication_evidence=step_up, conflicting_evidence=conflicting,
        ))
        config = DEFAULT_STOPPING_CONFIG
        if customer is CustomerResponse.CONFIRMED:
            verdict = Verdict.LEGITIMATE
        elif customer is CustomerResponse.DENIED or probability >= config.strong_fraud_threshold:
            verdict = Verdict.FRAUD
        elif probability <= config.strong_legitimate_threshold:
            verdict = Verdict.LEGITIMATE
        else:
            verdict = Verdict.UNCERTAIN

        # Episode: the card's transactions that the detected pattern covers.
        if pattern.pattern is FraudPattern.NONE:
            episode = [target]
        elif pattern.pattern is FraudPattern.OUT_OF_REGION_USE:
            episode = [item for item in card_history if item.billing_region == target.billing_region and abs(item.timestamp - target.timestamp) <= timedelta(days=7)]
        else:
            channels = {"online"} if pattern.pattern in {FraudPattern.CARD_TESTING, FraudPattern.CARD_NOT_PRESENT_FRAUD, FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE} else {"online", "in_person"}
            episode = [item for item in card_history if item.channel.lower() in channels and abs(item.timestamp - target.timestamp) <= PATTERN_WINDOW and item.timestamp <= target.timestamp]
        episode = sorted({item.transaction_id: item for item in [*episode, target]}.values(), key=lambda item: item.timestamp)
        episode_rows = [{"TransactionID": item.transaction_id, "TransactionAmt": item.amount_usd, "ts": item.timestamp.isoformat()} for item in episode]
        exposure = episode_exposure_usd(episode_rows)

        asked = {response.get("type") for response in responses}
        stop = evaluate_stopping(
            fraud_probability=probability, evidence=independent, verification=verification,
            further_investigation_unlikely={"customer_validation", "step_up_auth"} <= asked,
        )
        shared_origin = len(other_customers) >= 2 or (bool(other_customers) and bool(confirmed_links))
        confirmed_cards = {row.get("card_id") for row, _ in confirmed_links if row.get("customer_id") == target.customer_id and row.get("card_id")}
        independent_count = len({item.independence_key for item in independent if item.direction is EvidenceDirection.FRAUD})
        actions = recommend_actions(PolicyContext(
            verdict=verdict, fraud_probability=probability, exposure_usd=exposure, pattern=pattern.pattern,
            independent_evidence_count=independent_count, customer_response=customer, no_reply_within_24h=no_reply,
            shared_fraud_origin=shared_origin, conflicting_evidence=conflicting > 0 and verdict is not Verdict.LEGITIMATE,
            confirmed_fraud_cards_for_customer=len(confirmed_cards),
        ))
        sar_decision = evaluate_sar(verdict=verdict, fraud_probability=probability, exposure_usd=exposure, shared_fraud_origin=shared_origin, connected_to_other_card_fraud=bool(confirmed_links) and bool(other_customers))
        sar = None if sar_decision.file else build_sar(sar_decision)
        if sar_decision.file:
            generated = generate_grounded_sar(
                decision=sar_decision, customer_id=target.customer_id, card_id=target.card_id or target.customer_id,
                connected_card_ids=other_cards, episode_transactions=episode_rows, pattern=pattern.pattern,
                linkage_claims=[item["claim"] for item in evidence if item["ref"] == CLOSED_CASES_REF],
                evidence_response="; ".join(f"{item.get('type', '').replace('_', ' ')}: {item.get('result')}" for item in responses),
                known_subject_ids=[target.customer_id, target.card_id or target.customer_id, *other_cards], investigation_case_created=True,
            )
            sar = generated.sar
        assert sar is not None
        return {
            "target": target, "pattern": pattern, "probability": probability, "verdict": verdict, "exposure": exposure,
            "episode": episode, "evidence": evidence, "stop": stop, "actions": [item.model_dump(mode="json") for item in actions],
            "sar": sar.model_dump(mode="json"), "linked": linked, "other_customers": other_customers, "other_cards": other_cards,
            "customer": customer,
        }

    # ----------------------------------------------------------- rendering

    def _next_request(self, case_id: str, assessment: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
        if assessment["stop"].should_stop:
            return None
        asked = {item["type"] for item in state.get("evidence_requests", [])}
        target: TransactionEvidence = assessment["target"]
        if "customer_validation" not in asked and assessment["customer"] is None:
            return {"request_id": f"{case_id}-customer-validation", "case_id": case_id, "type": "customer_validation",
                    "question": f"Did you make the {_money(target.amount_usd)} {target.channel.replace('_', ' ')} purchase on {target.timestamp:%d %b %Y at %H:%M} (transaction {target.transaction_id})?",
                    "reason": assessment["stop"].stop_reason + " Customer confirmation is the strongest way to settle it.", "status": "pending"}
        if "step_up_auth" not in asked:
            return {"request_id": f"{case_id}-step-up", "case_id": case_id, "type": "step_up_auth",
                    "question": f"Ask the cardholder of {target.card_id or target.customer_id} to complete step-up authentication.",
                    "reason": assessment["stop"].stop_reason + " A step-up result adds an independent signal.", "status": "pending"}
        return None

    def _render(self, state: dict[str, Any], assessment: dict[str, Any]) -> None:
        target: TransactionEvidence = assessment["target"]
        pattern = assessment["pattern"]
        previous = {item["action"]: item for item in state.get("approval_requests", [])}
        approvals = []
        for action in assessment["actions"]:
            if action["route"] in {"L1", "L2"}:
                prior = previous.get(action["action"])
                approvals.append({**action, "approval_status": prior["approval_status"] if prior else "pending"})
        if assessment["sar"]["file"] and "FILE_REPORT" not in {item["action"] for item in approvals}:
            prior = previous.get("FILE_REPORT")
            approvals.append({"action": PolicyAction.FILE_REPORT.value, "route": get_approval_route(PolicyAction.FILE_REPORT, assessment["exposure"]).value,
                              "reason": assessment["sar"]["reason"], "approval_status": prior["approval_status"] if prior else "pending"})
        state["approval_requests"] = approvals
        open_requests = [item for item in state.get("evidence_requests", []) if item.get("status") != "resolved"]
        pending = [item for item in approvals if item["approval_status"] == "pending"]
        verdict: Verdict = assessment["verdict"]
        if open_requests:
            status = "awaiting_evidence"
        elif pending:
            status = "awaiting_approval"
        else:
            status = "completed"
        case_status = ("escalated" if pending or any(item["action"] == "ESCALATE_TO_ANALYST" for item in assessment["actions"]) else
                       "closed_fraud" if verdict is Verdict.FRAUD else "closed_legitimate" if verdict is Verdict.LEGITIMATE else "open")
        pattern_text = pattern.pattern.value.replace("_", " ")
        summary = (f"{pattern_text.capitalize()} pattern on {target.card_id or target.customer_id}" if pattern.pattern is not FraudPattern.NONE else f"No documented fraud pattern on {target.card_id or target.customer_id}")
        summary += f": fraud probability {assessment['probability']:.2f}, exposure {_money(assessment['exposure'])} across {len(assessment['episode'])} transaction(s). {assessment['stop'].stop_reason}"
        similar = []
        for row, reasons in assessment["linked"]:
            similar.append((len(reasons) + (1 if row.get("pattern") == pattern.pattern.value else 0), row, reasons))
        for row in self._closed:
            if pattern.pattern is not FraudPattern.NONE and row.get("pattern") == pattern.pattern.value and all(row is not item for _, item, _ in similar):
                similar.append((1, row, []))
        similar.sort(key=lambda item: -item[0])
        state["similar_cases"] = [{
            "case_id": row["case_id"], "pattern": row.get("pattern", ""), "outcome": row.get("outcome", ""),
            "similarity_score": round(min(1.0, score / 4), 2),
            "reason_for_match": "Shares the " + ", ".join(reasons) + ("; same pattern" if row.get("pattern") == pattern.pattern.value else "") + "." if reasons else f"Same pattern ({pattern_text}); {row.get('analyst_notes', '').strip() or 'no analyst note'}",
        } for score, row, reasons in similar[:6]]
        state["case"] = {"status": case_status, "verdict": verdict.value, "fraud_probability": assessment["probability"], "pattern": pattern.pattern.value,
                         "exposure_usd": assessment["exposure"], "summary": summary, "evidence": assessment["evidence"],
                         "similar_prior_cases": [item["case_id"] for item in state["similar_cases"]],
                         "affected_txn_ids": [item.transaction_id for item in assessment["episode"]]}
        state["stop_reason"] = assessment["stop"].stop_reason
        state["sar"] = assessment["sar"]
        state["status"] = status
        state["message"] = summary
        self._render_graph(state, assessment)

    def _render_graph(self, state: dict[str, Any], assessment: dict[str, Any]) -> None:
        target: TransactionEvidence = assessment["target"]
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}

        def node(kind: str, key: str, **extra: Any) -> str:
            node_id = f"{kind.lower()}:{key}"
            nodes.setdefault(node_id, {"data": {"id": node_id, "label": key, "entity_type": kind, "entity_id": key, **extra}})
            return node_id

        def edge(source: str, target_id: str, label: str) -> None:
            edges.setdefault(f"{source}->{target_id}", {"data": {"id": f"edge:{source}->{target_id}", "source": source, "target": target_id, "label": label}})

        customer = node("Customer", target.customer_id)
        card = node("Card", target.card_id) if target.card_id else customer
        if card != customer:
            edge(customer, card, "OWNS")
        episode_ids = {item.transaction_id for item in assessment["episode"]}
        for item in assessment["episode"]:
            txn = node("Transaction", item.transaction_id, flagged=item.transaction_id == target.transaction_id, amount_usd=item.amount_usd, channel=item.channel, ts=item.timestamp.isoformat())
            edge(card, txn, "MADE")
        flagged = f"transaction:{target.transaction_id}"
        if target.device_profile_id:
            device = node("DeviceProfile", target.device_profile_id, status=target.device_status or "")
            edge(flagged, device, "USED_DEVICE")
            for other in assessment["other_customers"]:
                edge(node("Customer", other, shares_device=True), device, "SHARES_DEVICE")
        if target.purchaser_email_domain:
            edge(flagged, node("EmailDomain", target.purchaser_email_domain), "USED_EMAIL")
        if target.billing_region:
            edge(flagged, node("BillingRegion", target.billing_region), "BILLED_TO")
        for row, reasons in assessment["linked"][:4]:
            closed = node("ClosedCase", row["case_id"], outcome=row.get("outcome", ""), pattern=row.get("pattern", ""))
            anchor = customer if any("customer " + target.customer_id in reason for reason in reasons) else f"deviceprofile:{target.device_profile_id}" if target.device_profile_id else customer
            if row.get("customer_id") in assessment["other_customers"]:
                anchor = f"customer:{row['customer_id']}"
            edge(closed, anchor, "INVOLVED")
        state["graph"] = {"nodes": list(nodes.values()), "edges": list(edges.values())}
        state["timeline"] = [{**row, "suspicious": row["transaction_id"] == target.transaction_id, "in_episode": row["transaction_id"] in episode_ids,
                              "device_profile_id": self._transactions.get(row["transaction_id"], {}).get("device_profile_id", "")} for row in state.get("timeline", [])]

    def _record(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        state["audit"] = [*state.get("audit", []), event]
        self._seal(state, event)

    def _step(self, state: dict[str, Any], assessment: dict[str, Any], label: str) -> None:
        pattern = assessment["pattern"]
        self._record(state, {"type": f"{label}pattern_detection", "pattern": pattern.pattern.value, "strength": f"{pattern.strength:.2f}"})
        self._record(state, {"type": f"{label}fraud_probability", "fraud_probability": f"{assessment['probability']:.4f}", "verdict": assessment["verdict"].value, "evidence_items": len(assessment["evidence"])})
        self._record(state, {"type": f"{label}stopping_evaluation", "stop": assessment["stop"].should_stop, "reason_code": assessment["stop"].reason_code.value})
        self._record(state, {"type": f"{label}policy_applied", "actions": ",".join(item["action"] for item in assessment["actions"]), "exposure_usd": f"{assessment['exposure']:.2f}"})

    # -------------------------------------------------------- workflow API

    def start_investigation(self, case_input: dict[str, Any]) -> dict[str, Any]:
        state = super().start_investigation(case_input)
        context = self._context(case_input)
        if context is None:
            return state
        case_id = case_input["case_id"]
        self._contexts[case_id] = {"input": dict(case_input), **context}
        state["evidence_requests"], state["evidence_responses"], state["approval_requests"] = [], [], []
        assessment = self._assess(case_input, context, [])
        self._step(state, assessment, "")
        request = self._next_request(case_id, assessment, state)
        if request:
            state["evidence_requests"] = [request]
            self._record(state, {"type": "evidence_requested", "request_id": request["request_id"], "request_type": request["type"]})
        state["next_best_actions"] = {"initial": assessment["actions"], "final": assessment["actions"], "what_changed": "nothing"}
        self._render(state, assessment)
        if state["approval_requests"]:
            self._record(state, {"type": "approvals_routed", "pending": ",".join(item["action"] for item in state["approval_requests"])})
        return state

    def resume_with_evidence(self, case_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        if case_id not in self._contexts:
            return super().resume_with_evidence(case_id, evidence)
        state = self._states[case_id]
        request = next((item for item in state.get("evidence_requests", []) if item["request_id"] == evidence.get("request_id")), None)
        if request is None:
            raise KeyError(evidence.get("request_id", ""))
        allowed = {"customer_validation": set(CustomerResult._value2member_map_), "step_up_auth": set(StepUpResult._value2member_map_)}.get(request["type"])
        result = str(evidence.get("result", "unknown"))
        if allowed is not None and result not in allowed:
            raise ValueError(f"{result!r} is not a valid {request['type']} result")
        details = evidence.get("details") or ""
        label = {"customer_validation": "Customer", "step_up_auth": "Step-up authentication", "analyst_info": "Analyst"}[request["type"]]
        response = {"request_id": request["request_id"], "type": request["type"], "result": result, "details": details if isinstance(details, str) else str(details),
                    "claim": f"{label} response: {result.replace('_', ' ')}" + (f". {details}" if details else "."), "source": evidence.get("source", "analyst"),
                    "ref": request["request_id"], "entity_ids": [self._contexts[case_id]["target"].customer_id], "simulated": False}
        request["status"] = "resolved"
        state["evidence_responses"] = [*state.get("evidence_responses", []), response]
        self._record(state, {"type": "evidence_response_recorded", "request_id": request["request_id"], "result": result})
        context = self._contexts[case_id]
        assessment = self._assess(context["input"], context, state["evidence_responses"])
        self._step(state, assessment, "reassessed_")
        follow_up = self._next_request(case_id, assessment, state)
        if follow_up:
            state["evidence_requests"] = [*state["evidence_requests"], follow_up]
            self._record(state, {"type": "evidence_requested", "request_id": follow_up["request_id"], "request_type": follow_up["type"]})
        initial = state["next_best_actions"]["initial"]
        changed = [item["action"] for item in assessment["actions"] if item["action"] not in {entry["action"] for entry in initial}]
        dropped = [item["action"] for item in initial if item["action"] not in {entry["action"] for entry in assessment["actions"]}]
        what_changed = f"{label} evidence ({result.replace('_', ' ')}) moved fraud probability to {assessment['probability']:.2f}."
        if changed:
            what_changed += " Added: " + ", ".join(action.replace("_", " ").lower() for action in changed) + "."
        if dropped:
            what_changed += " No longer recommended: " + ", ".join(action.replace("_", " ").lower() for action in dropped) + "."
        state["next_best_actions"] = {"initial": initial, "final": assessment["actions"], "what_changed": what_changed}
        self._render(state, assessment)
        return state

    def resume_with_approval(self, case_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        if case_id not in self._contexts:
            return super().resume_with_approval(case_id, decision)
        state = self._states[case_id]
        item = next((entry for entry in state.get("approval_requests", []) if entry["action"] == decision.get("action")), None)
        if item is None:
            raise KeyError(decision.get("action", ""))
        approved = bool(decision.get("approved"))
        item["approval_status"] = "approved" if approved else "rejected"
        self._record(state, {"type": "approval_recorded", "action": item["action"], "route": item["route"], "approved": approved})
        pending = [entry for entry in state["approval_requests"] if entry["approval_status"] == "pending"]
        if not pending and not [entry for entry in state.get("evidence_requests", []) if entry.get("status") != "resolved"]:
            state["status"] = "completed"
            verdict = state["case"]["verdict"]
            state["case"]["status"] = "closed_fraud" if verdict == "fraud" else "closed_legitimate" if verdict == "legitimate" else "escalated"
            self._record(state, {"type": "case_closed", "case_status": state["case"]["status"]})
        state["message"] = f"{item['action'].replace('_', ' ').capitalize()} {'approved' if approved else 'rejected'} at {item['route']}" + (f"; {len(pending)} approval(s) still pending." if pending else "; no approvals pending.")
        return state

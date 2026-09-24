"""The investigation agent.

An explicit, auditable agent loop over graph tools:

1. **Investigate**: call graph tools (TigerGraph MCP or CSV) to load the flagged
   transaction, the customer's baseline, who else used the device, the fraud
   ring around it and prior cases on the same entities. Every call is a
   recorded tool step with the reason it was made.
2. **Assess**: run the repository's deterministic pattern detectors and
   weighted fraud probability over what the tools returned.
3. **Decide whether to stop**: apply the stopping rules. If the evidence is not
   enough, request customer validation or step-up authentication and pause.
4. **Recommend**: apply policy R1-R10 and approval routing; ground every action
   in the policy text that produced it.
5. **Remember**: completed investigations become case memory so later
   investigations start from them.

Nothing here invents a fact: every claim cites the tool and entities it came
from. When the flagged transaction cannot be found, the agent falls back to a
lookup-only record instead of guessing.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Callable

from backend.actions_executor import MockActionService
from backend.demo_runtime import ReferenceWorkflow
from backend.evidence_requests.models import CustomerResult, StepUpResult
from backend.investigation.exposure import episode_exposure_usd
from backend.investigation.fraud_probability import ScoringInputs, deterministic_fraud_probability
from backend.investigation.patterns import PatternContext, TransactionEvidence, classify_pattern
from backend.investigation.scoring_config import DEFAULT_SCORING_CONFIG, DEFAULT_STOPPING_CONFIG
from backend.investigation.stopping import EvidenceDirection, IndependentEvidence, VerificationResponse, evaluate_stopping
from backend.graphrag import open_graphrag
from backend.memory import CaseMemory
from backend.planner import FINISH, RulePlanner, ToolOption, open_planner
from backend.models.answer import FraudPattern, PolicyAction, Verdict
from backend.policy.approvals import get_approval_route
from backend.policy.knowledge import PolicyKnowledge
from backend.policy.rules import CustomerResponse, PolicyContext, recommend_actions
from backend.policy.sar import build_sar, evaluate_sar, generate_grounded_sar
from backend.sources.base import CaseDataSource, ClosedCaseRecord, RingResult, Txn

PATTERN_WINDOW = timedelta(hours=48)
NETWORK_WINDOW = timedelta(days=7)
RING_HOPS = 2


# Every input to the weighted fraud probability, with the weight that scales it.
SIGNALS = (
    ("risk_score", "Bank risk score", "risk_score_weight"),
    ("pattern_strength", "Fraud pattern", "pattern_strength_weight"),
    ("unusual_transaction_behavior", "Unusual amount", "unusual_behavior_weight"),
    ("shared_device_evidence", "Shared or new device", "shared_device_weight"),
    ("region_evidence", "New billing region", "region_evidence_weight"),
    ("prior_confirmed_fraud_cases", "Linked confirmed fraud", "prior_confirmed_case_weight"),
    ("customer_evidence", "Customer denial", "customer_evidence_weight"),
    ("step_up_authentication_evidence", "Failed step-up", "step_up_weight"),
    ("conflicting_evidence", "Conflicting evidence", "conflicting_evidence_weight"),
)


def _verdict_for(probability: float, customer: CustomerResponse | None) -> Verdict:
    config = DEFAULT_STOPPING_CONFIG
    if customer is CustomerResponse.CONFIRMED:
        return Verdict.LEGITIMATE
    if customer is CustomerResponse.DENIED or probability >= config.strong_fraud_threshold:
        return Verdict.FRAUD
    if probability <= config.strong_legitimate_threshold:
        return Verdict.LEGITIMATE
    return Verdict.UNCERTAIN


def _contributions(inputs: ScoringInputs, probability: float, customer: CustomerResponse | None) -> list[dict[str, Any]]:
    """How many points each signal added, and whether removing it alone would change the verdict."""
    rows = []
    for field, label, weight_name in SIGNALS:
        value = getattr(inputs, field)
        if not value:
            continue
        weight = getattr(DEFAULT_SCORING_CONFIG, weight_name)
        points = -value * weight if field == "conflicting_evidence" else value * weight
        without = round(max(0.0, min(1.0, probability - points)), 4)
        rows.append({"signal": field, "label": label, "value": round(value, 4), "weight": weight, "points": round(points, 4),
                     "without": without, "decisive": _verdict_for(without, customer) is not _verdict_for(probability, customer)})
    return sorted(rows, key=lambda row: -abs(row["points"]))


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _evidence(txn: Txn) -> TransactionEvidence:
    return TransactionEvidence(
        transaction_id=txn.transaction_id, card_id=txn.card_id, customer_id=txn.customer_id, timestamp=txn.ts,
        amount_usd=txn.amount, channel=txn.channel, billing_region=txn.region, product_code=txn.product_code,
        purchaser_email_domain=txn.email, device_profile_id=txn.device_profile_id, device_status=txn.device_status,
        proxy_type=txn.proxy_type, match_status=txn.match_status,
    )


def _timeline_row(txn: Txn, flagged: str, episode: set[str]) -> dict[str, Any]:
    return {"transaction_id": txn.transaction_id, "ts": txn.ts.isoformat(), "transaction_amt": f"{txn.amount:.2f}", "channel": txn.channel,
            "risk_score": "" if txn.risk_score is None else f"{txn.risk_score:.2f}", "billing_region": txn.region or "", "email_domain": txn.email or "",
            "device_profile_id": txn.device_profile_id or "", "suspicious": txn.transaction_id == flagged, "in_episode": txn.transaction_id in episode}


class ToolTrace:
    """Records each tool the agent calls: what, why, what came back, how long."""

    def __init__(self, source_name: str) -> None:
        self.source_name = source_name
        self.steps: list[dict[str, Any]] = []

    def call(self, tool: str, args: dict[str, Any], reason: str, run: Callable[[], Any], summarise: Callable[[Any], str], *, planner: str = "rules", source: str | None = None) -> Any:
        started = time.perf_counter()
        error = ""
        try:
            result = run()
        except Exception as caught:  # noqa: BLE001 - the trace records the failure; the agent continues with less evidence
            result, error = None, f"{type(caught).__name__}: {caught}"
        self.steps.append({"step": len(self.steps) + 1, "tool": tool, "source": source or self.source_name, "args": args, "reason": reason, "planner": planner,
                           "result": error or summarise(result), "ok": not error, "ms": round((time.perf_counter() - started) * 1000, 1)})
        return result

    def note(self, tool: str, source: str, args: dict[str, Any], reason: str, result: str) -> None:
        self.steps.append({"step": len(self.steps) + 1, "tool": tool, "source": source, "args": args, "reason": reason, "result": result, "ok": True, "ms": 0.0})


class LocalInvestigationEngine(ReferenceWorkflow):
    """The investigation agent (kept under its original name for compatibility)."""

    def __init__(self, source: CaseDataSource | None = None, *, memory: CaseMemory | None = None, knowledge: PolicyKnowledge | None = None, planner: Any = None, compute_decision_paths: bool = True) -> None:
        super().__init__(None)
        self.source = source
        self.memory = memory or CaseMemory(os.getenv("CASE_MEMORY_PATH") or None)
        self.knowledge = knowledge or PolicyKnowledge(os.getenv("POLICY_DOCS_PATH") or None)
        self._contexts: dict[str, dict[str, Any]] = {}
        self._previews: dict[str, dict[str, Any]] = {}
        self.planner = planner or open_planner()
        self.executor = MockActionService()
        self.compute_decision_paths = compute_decision_paths
        self._rag: Any = None
        self._closed_index = {case.case_id: case for case in getattr(source, "_closed", ())}

    @property
    def rag(self) -> Any:
        if self._rag is None and self.source is not None:
            self._rag = open_graphrag(self.source, self.knowledge)
        return self._rag

    @property
    def source_name(self) -> str:
        return getattr(self.source, "name", "none")

    # ------------------------------------------------------------ investigate

    MAX_TOOL_STEPS = 6

    def _tool_options(self, gathered: dict[str, Any]) -> list[ToolOption]:
        """The graph tools that make sense right now, in the investigator's default order."""
        target: Txn = gathered["target"]
        done = gathered["done"]
        device = target.device_profile_id
        options = []
        if "get_customer_activity" not in done:
            options.append(ToolOption("get_customer_activity", f"All transactions of customer {target.customer_id} across their cards: the behavioural baseline.", "Build the customer's baseline across every card they hold."))
        if device and "get_device_activity" not in done:
            options.append(ToolOption("get_device_activity", f"Every transaction seen on device {device}, whoever made it.", f"Check who else has used device {device}."))
        if device and "get_device_activity" in done and "detect_device_ring" not in done and (gathered["network"] or (target.device_status or "").lower() == "new"):
            options.append(ToolOption("detect_device_ring", f"Graph algorithm: bounded connected component around device {device} to find a fraud ring.", "The device is shared or new: expand the connected component around it to look for a fraud ring."))
        if "get_linked_closed_cases" not in done:
            options.append(ToolOption("get_linked_closed_cases", "Closed investigations on this customer, card or the customers sharing its device, with outcomes.", "Case memory: find prior investigations on this customer, card or the customers sharing its device."))
        return options

    @staticmethod
    def _observations(gathered: dict[str, Any]) -> str:
        target: Txn = gathered["target"]
        lines = [f"Flagged transaction {target.transaction_id}: {_money(target.amount)} {target.channel} on card {target.card_id or 'unknown'}, region {target.region or 'unknown'}, "
                 f"device {target.device_profile_id or 'none'} (status {target.device_status or 'unknown'}, proxy {target.proxy_type or 'none'})."]
        if "get_customer_activity" in gathered["done"]:
            prior = [item for item in gathered["history"] if item.ts < target.ts]
            typical = median(item.amount for item in prior) if prior else 0
            lines.append(f"Customer history: {len(gathered['history'])} transactions; prior median {_money(typical)}.")
        if "get_device_activity" in gathered["done"]:
            lines.append(f"Device shared with {len({item.customer_id for item in gathered['network']})} other customers within seven days.")
        if gathered["ring"]:
            ring = gathered["ring"]
            lines.append(f"Ring: {len(ring.customers)} customers, {len(ring.cards)} cards, {len(ring.confirmed_cases)} confirmed fraud cases.")
        if "get_linked_closed_cases" in gathered["done"]:
            lines.append(f"Linked closed cases: {len(gathered['linked'])} ({sum(1 for case in gathered['linked'] if case.confirmed_fraud)} confirmed fraud).")
        return "\n".join(lines)

    def _run_tool(self, name: str, reason: str, planner: str, gathered: dict[str, Any], trace: ToolTrace) -> None:
        source, target = self.source, gathered["target"]
        gathered["done"].add(name)
        if name == "get_customer_activity":
            history = trace.call(name, {"customer_id": target.customer_id}, reason, lambda: source.customer_transactions(target.customer_id), lambda rows: f"{len(rows)} transactions", planner=planner) or [target]
            if all(item.transaction_id != target.transaction_id for item in history):
                history = sorted([*history, target], key=lambda item: item.ts)
            gathered["history"] = history
        elif name == "get_device_activity":
            device = target.device_profile_id
            on_device = trace.call(name, {"device_profile_id": device}, reason, lambda: source.device_transactions(device),
                                   lambda rows: f"{len(rows)} transactions from {len({row.customer_id for row in rows})} customers", planner=planner) or []
            gathered["network"] = [item for item in on_device if item.customer_id != target.customer_id and abs(item.ts - target.ts) <= NETWORK_WINDOW]
        elif name == "detect_device_ring":
            device = target.device_profile_id
            gathered["ring"] = trace.call(name, {"device_profile_id": device, "max_hops": RING_HOPS}, reason, lambda: source.device_ring(device, RING_HOPS),
                                          lambda result: f"{len(result.customers)} customers, {len(result.cards)} cards, {len(result.devices)} devices, {len(result.confirmed_cases)} confirmed cases" if result else "no ring", planner=planner)
        elif name == "get_linked_closed_cases":
            network = gathered["network"]
            gathered["linked"] = trace.call(name, {"customer_id": target.customer_id, "card_id": target.card_id}, reason,
                                            lambda: source.linked_closed_cases(target.customer_id, target.card_id, {item.customer_id for item in network}, {item.transaction_id for item in network}),
                                            lambda rows: f"{len(rows)} closed cases", planner=planner) or []

    def _gather(self, case_input: dict[str, Any], trace: ToolTrace, planner: Any = None) -> dict[str, Any] | None:
        """Investigate: the planner picks each next graph tool until the evidence is enough or the budget runs out."""
        if self.source is None:
            return None
        source = self.source
        flagged = case_input.get("flagged_txn_id", "")
        target = trace.call("get_transaction", {"transaction_id": flagged}, "Load the flagged transaction with its card, device and identity signals.",
                            lambda: source.transaction(flagged), lambda txn: f"{_money(txn.amount)} {txn.channel} on {txn.card_id or 'unknown card'}" if txn else "not found")
        if target is None:
            return None
        if not target.card_id and case_input.get("card_id") and target.customer_id == case_input.get("customer_id"):
            target = Txn(**{**target.__dict__, "card_id": case_input["card_id"]})
        gathered: dict[str, Any] = {"target": target, "history": [target], "network": [], "ring": None, "linked": [], "done": set()}
        budget = self.MAX_TOOL_STEPS
        while budget > 0:
            options = self._tool_options(gathered)
            choice = (planner or self.planner).choose(self._observations(gathered), options, budget)
            if choice.tool == FINISH:
                if options:
                    trace.note("finish_investigation", f"planner:{choice.planner}", {"skipped": [option.name for option in options]}, choice.reason, "stopped gathering evidence")
                break
            self._run_tool(choice.tool, choice.reason, choice.planner, gathered, trace)
            budget -= 1
        if "get_customer_activity" not in gathered["done"]:
            self._run_tool("get_customer_activity", "Required: no assessment runs without the customer's baseline.", "required", gathered, trace)
        history = gathered["history"]
        devices = {item.device_profile_id for item in history if item.device_profile_id}
        remembered = self.memory.related(case_id=case_input["case_id"], customer_id=target.customer_id, card_id=target.card_id, devices=devices)
        if len(self.memory):
            trace.note("recall_case_memory", "case-memory", {"customer_id": target.customer_id}, "Check this agent's own earlier investigations on the same entities.", f"{len(remembered)} related investigations")
        card_history = [item for item in history if item.card_id == target.card_id] if target.card_id else history
        return {"input": dict(case_input), "target": target, "history": history, "card_history": card_history, "network": gathered["network"], "ring": gathered["ring"],
                "linked": gathered["linked"], "remembered": remembered, "trace": trace}

    def _retrieve_grounding(self, context: dict[str, Any], assessment: dict[str, Any]) -> None:
        """GraphRAG: retrieve the policy passages and prior-case narratives relevant to this assessment."""
        rag = self.rag
        if rag is None:
            return
        pattern = assessment["pattern"].pattern.value.replace("_", " ")
        query = " ".join([pattern, assessment["target"].channel, *(item["claim"] for item in assessment["evidence"][:4]),
                          *(item["action"].replace("_", " ").lower() for item in assessment["actions"])])
        method = getattr(rag, "method", "rag")

        def run() -> dict[str, Any]:
            if hasattr(rag, "retrieve_all"):
                return rag.retrieve_all(query)
            return {"policy": rag.retrieve(query, "policy", 3), "patterns": rag.retrieve(query, "pattern_document", 2), "cases": rag.retrieve(query, "closed_case", 3)}

        context["rag"] = context["trace"].call("graphrag_retrieve", {"query": query[:80] + ("…" if len(query) > 80 else ""), "method": method},
                                               "Ground the explanation: retrieve the policy passages and prior-case narratives closest to this case.", run,
                                               lambda found: f"{len(found['policy']) + len(found['patterns'])} policy passages, {len(found['cases'])} case narratives ({method})" if found else "nothing retrieved",
                                               source=f"graphrag:{method}") or {"policy": [], "patterns": [], "cases": []}

    @staticmethod
    def _link_reasons(case: ClosedCaseRecord, target: Txn, network: list[Txn]) -> list[str]:
        reasons = []
        if case.customer_id == target.customer_id:
            reasons.append(f"same customer {target.customer_id}")
        if target.card_id and (case.card_id == target.card_id or target.card_id in case.connected_card_ids):
            reasons.append(f"same card {target.card_id}")
        if case.customer_id in {item.customer_id for item in network} or set(case.txn_ids) & {item.transaction_id for item in network}:
            reasons.append(f"customer who shared device {target.device_profile_id}")
        return reasons or ["linked by the graph"]

    # ----------------------------------------------------------------- assess

    def _assess(self, case_input: dict[str, Any], context: dict[str, Any], responses: list[dict[str, Any]], trace: ToolTrace | None = None) -> dict[str, Any]:
        target: Txn = context["target"]
        card_history: list[Txn] = context["card_history"]
        network: list[Txn] = context["network"]
        ring: RingResult | None = context["ring"]
        prior = [item for item in card_history if item.ts < target.ts]
        evidence: list[dict[str, Any]] = []
        independent: list[IndependentEvidence] = []
        graph_ref = "tigergraph" if self.source_name == "tigergraph-mcp" else "transactions.csv"
        cases_ref = "tigergraph:ClosedCase" if self.source_name == "tigergraph-mcp" else "closed_cases_history.csv"

        def fact(claim: str, entities: list[str], key: str | None = None, direction: EvidenceDirection = EvidenceDirection.FRAUD, source: str = "graph", ref: str = graph_ref) -> None:
            evidence.append({"claim": claim, "source": source, "ref": ref, "entity_ids": [entity for entity in entities if entity]})
            if key:
                independent.append(IndependentEvidence(claim, direction, key))

        linked = [(case, self._link_reasons(case, target, network)) for case in context["linked"]]
        confirmed_links = [(case, reasons) for case, reasons in linked if case.confirmed_fraud]
        other_customers = sorted({item.customer_id for item in network})
        other_cards = sorted({item.card_id for item in network if item.card_id and item.card_id != target.card_id})
        ring_cards = sorted(set(ring.cards) - {target.card_id}) if ring else []

        pattern = classify_pattern(PatternContext(
            target=_evidence(target), card_history=tuple(map(_evidence, card_history)), customer_history=tuple(map(_evidence, context["history"])),
            network_transactions=tuple(map(_evidence, network)), connected_card_ids=tuple(sorted(set(other_cards) | set(ring_cards))),
            confirmed_related_case_ids=tuple(sorted({case.case_id for case, _ in confirmed_links} | set(ring.confirmed_cases if ring else ()))),
        ))
        if pattern.pattern is not FraudPattern.NONE:
            fact(f"Pattern {pattern.pattern.value.replace('_', ' ')} detected: {'; '.join(pattern.supporting_evidence)}.", [target.transaction_id, target.card_id], "pattern")
        elif prior:
            fact(f"No documented fraud pattern matched: {'; '.join(pattern.contradicting_evidence[:2])}.", [target.transaction_id], "pattern_absent", EvidenceDirection.LEGITIMATE)

        unusual = 0.0
        if prior:
            typical = median(item.amount for item in prior)
            if target.amount >= max(2 * typical, typical + 50):
                unusual = 1.0
                fact(f"Flagged amount {_money(target.amount)} is {target.amount / max(typical, 0.01):.1f}× the card's prior median of {_money(typical)} across {len(prior)} transactions.", [target.transaction_id, target.card_id], "amount")
            else:
                fact(f"Flagged amount {_money(target.amount)} is in line with the card's prior median of {_money(typical)}.", [target.transaction_id], "amount_consistent", EvidenceDirection.LEGITIMATE)

        shared = 0.0
        prior_devices = {item.device_profile_id for item in prior if item.device_profile_id}
        device_new = (target.device_status or "").lower() == "new"
        if target.device_profile_id and other_customers:
            shared = 1.0
            fact(f"Device {target.device_profile_id} was also used by {len(other_customers)} other customer(s) ({', '.join(other_customers[:6])}) within seven days.", [target.device_profile_id, *other_customers[:6]], "device")
        elif device_new or (target.device_profile_id and prior_devices and target.device_profile_id not in prior_devices):
            shared = 0.5
            fact(f"Device {target.device_profile_id or 'on the flagged transaction'} is new for this card{' (identity marks it New)' if device_new else ''}.", [target.transaction_id, target.device_profile_id or ""], "device")
        elif target.device_profile_id and target.device_profile_id in prior_devices:
            fact(f"Device {target.device_profile_id} has been used on this card before.", [target.device_profile_id], "device_known", EvidenceDirection.LEGITIMATE)
        if ring and (len(ring.customers) >= 3 or ring.confirmed_cases):
            touching = f", touching confirmed fraud case(s) {', '.join(ring.confirmed_cases[:4])}" if ring.confirmed_cases else ""
            fact(f"Fraud-ring analysis: device {ring.seed_device} sits in a connected component of {len(ring.customers)} customers, {len(ring.cards)} cards and {len(ring.devices)} devices within {ring.hops} hops{touching}.",
                 [ring.seed_device, *ring.cards[:6]], "ring")

        region = 0.0
        prior_regions = {item.region for item in prior if item.region}
        if target.region and prior_regions and target.region not in prior_regions:
            region = 1.0
            fact(f"Billing region {target.region} is new for this card; prior regions: {', '.join(sorted(prior_regions))}.", [target.transaction_id], "region")

        history_signal = 0.0
        for case, reasons in confirmed_links[:3]:
            history_signal = 1.0
            fact(f"Closed case {case.case_id} ({case.outcome.replace('_', ' ')}, {(case.pattern or 'unknown').replace('_', ' ')}) involved the {', '.join(reasons)}.", [case.case_id, case.customer_id, case.card_id], "history", ref=cases_ref)
        for record, reasons in context["remembered"][:2]:
            fact(f"This agent's earlier investigation {record['case_id']} ({record.get('verdict')}, {str(record.get('pattern', 'none')).replace('_', ' ')}) shares the {', '.join(reasons)}.", [record["case_id"]], ref="case_memory")
            if record.get("verdict") == "fraud":
                history_signal = 1.0

        customer: CustomerResponse | None = None
        no_reply = False
        step_up = 0.0
        conflicting = 0.0
        verification: VerificationResponse | None = None
        if case_input.get("trigger_type") == "customer_report":
            customer = CustomerResponse.DENIED
            fact(f"The customer reported the transaction as not made by them: “{str(case_input.get('trigger_text', '')).strip()}”", [target.customer_id, target.transaction_id], "customer", source="customer", ref="case_pack.trigger_text")
            verification = VerificationResponse(True, EvidenceDirection.FRAUD, "case_pack.trigger_text")
        for response in responses:
            result = response.get("result")
            simulated = " (simulated response)" if response.get("simulated") else ""
            if response.get("type") == "customer_validation":
                if result == "denied":
                    customer = CustomerResponse.DENIED
                    fact(f"The customer denied making the transaction{simulated}.", [target.customer_id, target.transaction_id], "customer", source="customer", ref=response["request_id"])
                    verification = VerificationResponse(True, EvidenceDirection.FRAUD, response["request_id"])
                elif result == "confirmed":
                    customer = CustomerResponse.CONFIRMED
                    conflicting = 1.0
                    fact(f"The customer confirmed they made the transaction{simulated}.", [target.customer_id, target.transaction_id], "customer", EvidenceDirection.LEGITIMATE, "customer", response["request_id"])
                    verification = VerificationResponse(True, EvidenceDirection.LEGITIMATE, response["request_id"])
                elif result == "no_reply":
                    no_reply = True
                    fact(f"The customer did not reply to the verification request{simulated}.", [target.customer_id], source="customer", ref=response["request_id"])
            elif response.get("type") == "step_up_auth":
                if result == "failed":
                    step_up = 1.0
                    fact(f"Step-up authentication failed{simulated}.", [target.customer_id], "step_up", source="external", ref=response["request_id"])
                elif result == "passed":
                    conflicting = max(conflicting, 0.5)
                    fact(f"Step-up authentication passed{simulated}.", [target.customer_id], "step_up", EvidenceDirection.LEGITIMATE, "external", response["request_id"])
            elif response.get("details"):
                fact(f"Analyst note: {response['details']}", [target.transaction_id], source="document", ref=response["request_id"])

        risk_value = case_input.get("risk_score")
        risk = float(risk_value) if risk_value not in (None, "") else (target.risk_score or 0.0)
        inputs = ScoringInputs(
            risk_score=min(1.0, max(0.0, risk)), pattern_strength=pattern.strength, unusual_transaction_behavior=unusual,
            shared_device_evidence=shared, region_evidence=region, prior_confirmed_fraud_cases=history_signal,
            customer_evidence=1.0 if customer is CustomerResponse.DENIED else 0.0, step_up_authentication_evidence=step_up, conflicting_evidence=conflicting,
        )
        probability = deterministic_fraud_probability(inputs)
        verdict = _verdict_for(probability, customer)
        contributions = _contributions(inputs, probability, customer)

        if pattern.pattern is FraudPattern.NONE:
            episode = [target]
        elif pattern.pattern is FraudPattern.OUT_OF_REGION_USE:
            episode = [item for item in card_history if item.region == target.region and abs(item.ts - target.ts) <= timedelta(days=7)]
        else:
            channels = {"online"} if pattern.pattern in {FraudPattern.CARD_TESTING, FraudPattern.CARD_NOT_PRESENT_FRAUD, FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE} else {"online", "in_person"}
            episode = [item for item in card_history if item.channel.lower() in channels and abs(item.ts - target.ts) <= PATTERN_WINDOW and item.ts <= target.ts]
        episode = sorted({item.transaction_id: item for item in [*episode, target]}.values(), key=lambda item: item.ts)
        if verdict is Verdict.LEGITIMATE:
            episode = []  # answer format: a legitimate case has no affected transactions and no exposure
        episode_rows = [{"TransactionID": item.transaction_id, "TransactionAmt": item.amount, "ts": item.ts.isoformat()} for item in episode]
        exposure = episode_exposure_usd(episode_rows) if episode_rows else 0.0

        asked = {response.get("type") for response in responses}
        further_unlikely = {"customer_validation", "step_up_auth"} <= asked
        stop = evaluate_stopping(fraud_probability=probability, evidence=independent, verification=verification, further_investigation_unlikely=further_unlikely)
        shared_origin = len(other_customers) >= 2 or (bool(other_customers) and bool(confirmed_links)) or bool(ring and ring.confirmed_cases and len(ring.customers) >= 3)
        coordinated = pattern.pattern is FraudPattern.UNDOCUMENTED
        confirmed_cards = {case.card_id for case, _ in confirmed_links if case.customer_id == target.customer_id and case.card_id}
        independent_count = len({item.independence_key for item in independent if item.direction is EvidenceDirection.FRAUD})
        actions = recommend_actions(PolicyContext(
            verdict=verdict, fraud_probability=probability, exposure_usd=exposure, pattern=pattern.pattern,
            independent_evidence_count=independent_count, customer_response=customer, no_reply_within_24h=no_reply,
            shared_fraud_origin=shared_origin, conflicting_evidence=conflicting > 0 and verdict is not Verdict.LEGITIMATE,
            coordinated_undocumented_abuse=coordinated, confirmed_fraud_cards_for_customer=len(confirmed_cards),
        ))
        connected_cards = sorted(set(other_cards) | set(ring_cards))
        sar_decision = evaluate_sar(verdict=verdict, fraud_probability=probability, exposure_usd=exposure, shared_fraud_origin=shared_origin,
                                    connected_to_other_card_fraud=bool(confirmed_links) and bool(other_customers), coordinated_undocumented_abuse=coordinated)
        if sar_decision.file:
            subject_card = target.card_id or target.customer_id
            sar = generate_grounded_sar(
                decision=sar_decision, customer_id=target.customer_id, card_id=subject_card, connected_card_ids=connected_cards[:10],
                episode_transactions=episode_rows, pattern=pattern.pattern,
                linkage_claims=[item["claim"] for item in evidence if item["ref"] in {cases_ref, "case_memory"}],
                evidence_response="; ".join(f"{item.get('type', '').replace('_', ' ')}: {item.get('result')}" for item in responses),
                known_subject_ids=[target.customer_id, subject_card, *connected_cards[:10]], investigation_case_created=True,
            ).sar
        else:
            sar = build_sar(sar_decision)

        similar: list[tuple[ClosedCaseRecord, list[str]]] = list(linked)
        if pattern.pattern is not FraudPattern.NONE:
            if trace is not None and self.source is not None and context.get("pattern_cases_for") != pattern.pattern.value:
                source = self.source
                context["pattern_cases"] = trace.call("get_closed_cases_by_pattern", {"pattern": pattern.pattern.value, "k": 5},
                                                      f"Retrieve closed cases with the same {pattern.pattern.value.replace('_', ' ')} pattern and their outcomes.",
                                                      lambda: source.closed_cases_by_pattern(pattern.pattern.value, 5), lambda rows: f"{len(rows)} closed cases") or []
                context["pattern_cases_for"] = pattern.pattern.value
            known = {case.case_id for case, _ in similar}
            similar += [(case, []) for case in context.get("pattern_cases", []) if case.case_id not in known]

        return {"contributions": contributions, "target": target, "pattern": pattern, "probability": probability, "verdict": verdict, "exposure": exposure, "episode": episode,
                "evidence": evidence, "stop": stop, "actions": [item.model_dump(mode="json") for item in actions], "sar": sar.model_dump(mode="json"),
                "linked": linked, "similar": similar, "other_customers": other_customers, "connected_cards": connected_cards, "customer": customer,
                "ring": ring, "independent_count": independent_count, "verification_settled": verification is not None,
                "further_unlikely": further_unlikely, "customer_disputed": customer is CustomerResponse.DENIED}

    # -------------------------------------------------------------- explain

    def _grounding(self, assessment: dict[str, Any]) -> list[dict[str, Any]]:
        """The policy text behind each recommended action, plus relevant policy documents."""
        cited: dict[str, dict[str, Any]] = {}
        for action in assessment["actions"]:
            for rule in {part.split(":")[0].strip() for part in action["reason"].split(";")}:
                chunk = self.knowledge.rule(rule)
                if chunk:
                    entry = cited.setdefault(chunk.ref, {"ref": chunk.ref, "title": chunk.title, "text": chunk.text, "source": chunk.source, "supports": []})
                    entry["supports"].append(action["action"])
        if any(action["route"] in {"L1", "L2"} for action in assessment["actions"]):
            chunk = self.knowledge.rule("approval_routes")
            if chunk:
                cited.setdefault(chunk.ref, {"ref": chunk.ref, "title": chunk.title, "text": chunk.text, "source": chunk.source, "supports": [a["action"] for a in assessment["actions"] if a["route"] != "auto"]})
        rag = context_rag = assessment.get("rag") or {}
        for passage in [*context_rag.get("policy", []), *context_rag.get("patterns", [])]:
            if passage.ref not in cited:
                cited[passage.ref] = {"ref": passage.ref, "title": passage.title, "text": passage.text, "source": f"graphrag:{passage.method}", "supports": [], "score": passage.score}
        if not rag and self.knowledge.has_documents:
            query = " ".join([assessment["pattern"].pattern.value.replace("_", " "), *(action["action"].replace("_", " ").lower() for action in assessment["actions"])])
            for chunk in self.knowledge.search(query, 3, documents_only=True):
                cited.setdefault(chunk.ref, {"ref": chunk.ref, "title": chunk.title, "text": chunk.text, "source": chunk.source, "supports": []})
        return list(cited.values())

    @staticmethod
    def _explanation(assessment: dict[str, Any], request: dict[str, Any] | None) -> dict[str, str]:
        """Plain-language reasoning built only from the assessment's own facts."""
        stop = assessment["stop"]
        claims = [item["claim"] for item in assessment["evidence"]]
        verdict = assessment["verdict"].value
        uncertainty = stop.stop_reason
        if request:
            uncertainty += f" The agent asked for {request['type'].replace('_', ' ')} because it is the cheapest evidence that can settle the question."
        elif verdict == "uncertain":
            uncertainty += " No further evidence request is available, so the case is escalated rather than decided."
        return {
            "verdict": f"Verdict {verdict} at fraud probability {assessment['probability']:.2f}, backed by {assessment['independent_count']} independent fraud-supporting evidence source(s).",
            "evidence": " ".join(claims[:3]) or "The trigger was the only signal available.",
            "uncertainty": uncertainty,
            "actions": "; ".join(f"{item['action'].replace('_', ' ').lower()} ({item['route']}), {item['reason']}" for item in assessment["actions"]) or "Policy recommends no action for this evidence.",
        }

    # -------------------------------------------------------------- render

    POSSIBLE_ANSWERS = {"customer_validation": ("denied", "confirmed", "no_reply"), "step_up_auth": ("failed", "passed", "not_completed")}

    def _decision_paths(self, case_input: dict[str, Any], context: dict[str, Any], responses: list[dict[str, Any]], assessment: dict[str, Any], asked: set[str]) -> list[dict[str, Any]]:
        """Value of information: simulate every answer to every evidence request still available.

        For each request the agent could make, it re-runs the full deterministic
        assessment once per possible answer and records the verdict, probability,
        actions and routes that answer would lead to. The request whose answers
        lead to the most different decisions (and most often settle the case) is
        the one worth asking first.
        """
        if assessment["stop"].should_stop:
            return []
        current = tuple(sorted(item["action"] for item in assessment["actions"]))
        paths = []
        for request_type, answers in self.POSSIBLE_ANSWERS.items():
            if request_type in asked or (request_type == "customer_validation" and assessment["customer"] is not None):
                continue
            outcomes = []
            for answer in answers:
                what_if = self._assess(case_input, context, [*responses, {"request_id": f"what-if:{request_type}", "type": request_type, "result": answer}])
                outcomes.append({"answer": answer, "verdict": what_if["verdict"].value, "probability": round(what_if["probability"], 4), "settles": what_if["stop"].should_stop,
                                 "sar": bool(what_if["sar"]["file"]), "actions": [{"action": item["action"], "route": item["route"]} for item in what_if["actions"]]})
            decisions = {tuple(sorted(item["action"] for item in outcome["actions"])) for outcome in outcomes}
            paths.append({"request_type": request_type, "outcomes": outcomes, "distinct_decisions": len(decisions),
                          "changes_decision": sum(1 for outcome in outcomes if tuple(sorted(item["action"] for item in outcome["actions"])) != current),
                          "settling_answers": sum(1 for outcome in outcomes if outcome["settles"]), "chosen": False})
        paths.sort(key=lambda path: (-path["distinct_decisions"], -path["settling_answers"], path["request_type"] != "customer_validation"))
        if paths:
            paths[0]["chosen"] = True
        return paths

    def _next_request(self, case_id: str, assessment: dict[str, Any], state: dict[str, Any], paths: list[dict[str, Any]]) -> dict[str, Any] | None:
        if assessment["stop"].should_stop or not paths:
            return None
        best = paths[0]
        target: Txn = assessment["target"]
        plural = lambda count, word: f"{count} {word}{'' if count == 1 else 's'}"  # noqa: E731
        why = (f"{best['request_type'].replace('_', ' ').capitalize()} has the highest decision value: its {len(best['outcomes'])} possible answers lead to "
               f"{plural(best['distinct_decisions'], 'different decision')}, and {best['settling_answers']} of them settle the case")
        if len(paths) > 1:
            other = paths[1]
            why += f", versus {plural(other['distinct_decisions'], 'decision')} for {other['request_type'].replace('_', ' ')}"
        reason = f"{assessment['stop'].stop_reason} {why}."
        if best["request_type"] == "customer_validation":
            return {"request_id": f"{case_id}-customer-validation", "case_id": case_id, "type": "customer_validation",
                    "question": f"Did you make the {_money(target.amount)} {target.channel.replace('_', ' ')} purchase on {target.ts:%d %b %Y at %H:%M} (transaction {target.transaction_id})?",
                    "reason": reason, "status": "pending"}
        return {"request_id": f"{case_id}-step-up", "case_id": case_id, "type": "step_up_auth",
                "question": f"Ask the cardholder of {target.card_id or target.customer_id} to complete step-up authentication.",
                "reason": reason, "status": "pending"}

    @staticmethod
    def _blast_radius(context: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any] | None:
        """Other cards the same device or ring reaches, with their recent spend on that device."""
        if assessment["verdict"] is Verdict.LEGITIMATE:
            return None
        target: Txn = assessment["target"]
        ring: RingResult | None = context["ring"]
        cards: dict[str, dict[str, Any]] = {}
        for item in context["network"]:
            key = item.card_id or item.customer_id
            entry = cards.setdefault(key, {"card_id": item.card_id, "customer_id": item.customer_id, "transactions": 0, "spend_usd": 0.0, "first_seen": item.ts.isoformat(), "last_seen": "", "link": f"shared device {target.device_profile_id}"})
            entry["transactions"] += 1
            entry["spend_usd"] = round(entry["spend_usd"] + item.amount, 2)
            entry["first_seen"] = min(entry["first_seen"], item.ts.isoformat())
            entry["last_seen"] = max(entry["last_seen"], item.ts.isoformat())
        for card in (ring.cards if ring else ()):
            if card != target.card_id and card not in cards:
                cards[card] = {"card_id": card, "customer_id": "", "transactions": 0, "spend_usd": 0.0, "first_seen": "", "last_seen": "", "link": f"fraud ring within {ring.hops} hops"}
        if not cards:
            return None
        rows = sorted(cards.values(), key=lambda row: (-row["spend_usd"], row["card_id"]))
        return {"target": {"card_id": target.card_id, "first_seen": target.ts.isoformat(), "spend_usd": target.amount}, "cards": rows[:12], "card_count": len(rows), "customers": len({row["customer_id"] for row in rows if row["customer_id"]}),
                "recent_spend_usd": round(sum(row["spend_usd"] for row in rows), 2), "confirmed_cases": list(ring.confirmed_cases) if ring else []}

    def _render(self, state: dict[str, Any], assessment: dict[str, Any], *, narrate: bool = True) -> None:
        context = self._contexts[state["case_id"]]
        context["last"] = assessment
        target: Txn = assessment["target"]
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
        status = "awaiting_evidence" if open_requests else "awaiting_approval" if pending else "completed"
        case_status = ("escalated" if pending or any(item["action"] == "ESCALATE_TO_ANALYST" for item in assessment["actions"]) else
                       "closed_fraud" if verdict is Verdict.FRAUD else "closed_legitimate" if verdict is Verdict.LEGITIMATE else "open")
        pattern_text = pattern.pattern.value.replace("_", " ")
        summary = (f"{pattern_text.capitalize()} pattern on {target.card_id or target.customer_id}" if pattern.pattern is not FraudPattern.NONE else f"No documented fraud pattern on {target.card_id or target.customer_id}")
        summary += f": fraud probability {assessment['probability']:.2f}, exposure {_money(assessment['exposure'])} across {len(assessment['episode'])} transaction(s). {assessment['stop'].stop_reason}"
        scored = []
        for case, reasons in assessment["similar"]:
            same = case.pattern == pattern.pattern.value and pattern.pattern is not FraudPattern.NONE
            scored.append((len(reasons) + (1 if same else 0), case, reasons, same))
        scored.sort(key=lambda item: -item[0])
        state["similar_cases"] = [{
            "case_id": case.case_id, "pattern": case.pattern, "outcome": case.outcome, "similarity_score": round(min(1.0, score / 4), 2),
            "reason_for_match": ("Shares the " + ", ".join(reasons) + ("; same pattern" if same else "") + ".") if reasons else f"Same pattern ({pattern_text}). {case.analyst_notes or 'No analyst note.'}",
        } for score, case, reasons, same in scored[:6]]
        episode_devices = {item.device_profile_id for item in assessment["episode"] if item.device_profile_id}
        state["case"] = {"status": case_status, "verdict": verdict.value, "fraud_probability": assessment["probability"], "pattern": pattern.pattern.value,
                         "pattern_description": "; ".join(pattern.supporting_evidence) if pattern.pattern is FraudPattern.UNDOCUMENTED else "",
                         "exposure_usd": assessment["exposure"], "summary": summary, "evidence": assessment["evidence"],
                         "similar_prior_cases": [item["case_id"] for item in state["similar_cases"]], "affected_txn_ids": [item.transaction_id for item in assessment["episode"]],
                         "first_suspicious_txn_id": assessment["episode"][0].transaction_id if assessment["episode"] else "",
                         "connected_card_ids": assessment["connected_cards"], "connected_device_profiles": sorted(episode_devices)}
        state["stop_reason"] = assessment["stop"].stop_reason
        state["stop_context"] = {"independent_evidence_count": assessment["stop"].independent_evidence_count, "verification_settled": assessment["verification_settled"],
                                 "further_investigation_unlikely": assessment["further_unlikely"], "customer_disputed": assessment["customer_disputed"]}
        state["sar"] = assessment["sar"]
        state["status"] = status
        state["message"] = summary
        state["explanation"] = self._explanation(assessment, open_requests[0] if open_requests else None)
        assessment["rag"] = context.get("rag")
        state["policy_grounding"] = self._grounding(assessment)
        known = {item["case_id"] for item in state["similar_cases"]}
        for passage in (context.get("rag") or {}).get("cases", []):
            case_id = passage.source_id
            if case_id in known:
                continue
            record = self._closed_index.get(case_id)
            state["similar_cases"].append({"case_id": case_id, "pattern": record.pattern if record else "", "outcome": record.outcome if record else "",
                                           "similarity_score": passage.score, "reason_for_match": f"Narrative similarity {passage.score:.2f} ({passage.method}): {passage.text[:160]}"})
            known.add(case_id)
        state["case"]["similar_prior_cases"] = [item["case_id"] for item in state["similar_cases"]]
        state["score_breakdown"] = {"probability": assessment["probability"], "contributions": assessment["contributions"],
                                    "fraud_threshold": DEFAULT_STOPPING_CONFIG.strong_fraud_threshold, "legitimate_threshold": DEFAULT_STOPPING_CONFIG.strong_legitimate_threshold}
        state["blast_radius"] = self._blast_radius(context, assessment)
        state["agent_trace"] = context["trace"].steps
        state["data_source"] = self.source_name
        self._render_graph(state, assessment)
        if narrate:
            self._narrate(state, assessment)

    def _narrate_in_background(self, state: dict[str, Any], assessment: dict[str, Any]) -> None:
        try:
            self._narrate(state, assessment)
        finally:
            state["llm_pending"] = False

    def _narrate(self, state: dict[str, Any], assessment: dict[str, Any]) -> None:
        """Optional LLM narrative, grounded: every claim must cite supplied evidence or policy.

        The model only writes prose. Probability, verdict, actions and routes stay
        deterministic, and a narrative that cites anything unsupported is discarded.
        """
        if os.getenv("LLM_PROVIDER", "disabled").strip().lower() in {"", "disabled"}:
            return
        from backend.app.llm.synthesis import GroundedSynthesisService

        evidence = state["case"]["evidence"]
        entity_ids = {state["case_id"], *(entity for item in evidence for entity in item["entity_ids"]), *state["case"]["affected_txn_ids"],
                      *state["case"]["similar_prior_cases"], *state["case"]["connected_card_ids"]}
        context = {
            "case_id": state["case_id"], "graph_evidence": evidence,
            "retrieved_policy": [{"ref": item["ref"], "text": item["text"], "entity_ids": []} for item in state["policy_grounding"]],
            "citation_reference_allowlist": sorted({item["ref"] for item in evidence} | {item["ref"] for item in state["policy_grounding"]}),
            "entity_ids": sorted(entity_ids), "detected_pattern": state["case"]["pattern"], "pattern_description": state["case"]["pattern_description"],
            "verdict": state["case"]["verdict"], "fraud_probability": state["case"]["fraud_probability"], "stop_reason": state["stop_reason"],
            "recommended_actions": state["next_best_actions"]["final"], "evidence_requests": state.get("evidence_requests", []),
        }
        step = {"step": len(state["agent_trace"]) + 1, "tool": "synthesize_explanation", "source": "llm", "args": {"model": os.getenv("LLM_MODEL", "")},
                "reason": "Write the case narrative from the cited evidence and policy only.", "ok": True, "ms": 0.0}
        started = time.perf_counter()
        try:
            synthesis, usage = GroundedSynthesisService().synthesize(context)
        except Exception as caught:  # noqa: BLE001 - grounding failures keep the deterministic explanation
            step.update(ok=False, result=f"discarded: {type(caught).__name__}")
        else:
            if usage.fallback:
                step.update(ok=False, result="LLM unavailable; deterministic explanation kept")
            else:
                state["explanation"] = {**state["explanation"], "narrative": synthesis.case_summary, "evidence": synthesis.evidence_explanation,
                                        "uncertainty": synthesis.uncertainty_explanation, "actions": synthesis.action_explanation, "citations": synthesis.citations.model_dump()}
                state["llm_usage"] = {"model": usage.model, "total_tokens": usage.total_tokens}
                step["result"] = f"grounded narrative, {usage.total_tokens} tokens"
        step["ms"] = round((time.perf_counter() - started) * 1000, 1)
        state["agent_trace"] = [*state["agent_trace"], step]

    def _render_graph(self, state: dict[str, Any], assessment: dict[str, Any]) -> None:
        target: Txn = assessment["target"]
        context = self._contexts[state["case_id"]]
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
        flagged = node("Transaction", target.transaction_id, flagged=True, amount_usd=target.amount, channel=target.channel, ts=target.ts.isoformat())
        for item in assessment["episode"] or [target]:
            edge(card, node("Transaction", item.transaction_id, flagged=item.transaction_id == target.transaction_id, amount_usd=item.amount, channel=item.channel, ts=item.ts.isoformat()), "MADE")
        if target.device_profile_id:
            device = node("DeviceProfile", target.device_profile_id, status=target.device_status or "", proxy=target.proxy_type or "")
            edge(flagged, device, "USED_DEVICE")
            for other in assessment["other_customers"][:8]:
                edge(node("Customer", other, shares_device=True), device, "SHARES_DEVICE")
        if target.email:
            edge(flagged, node("EmailDomain", target.email), "USED_EMAIL")
        if target.region:
            edge(flagged, node("BillingRegion", target.region), "BILLED_TO")
        for case, _ in assessment["linked"][:4]:
            closed = node("ClosedCase", case.case_id, outcome=case.outcome, pattern=case.pattern)
            anchor = f"customer:{case.customer_id}" if f"customer:{case.customer_id}" in nodes else customer
            edge(closed, anchor, "INVOLVED")
        state["graph"] = {"nodes": list(nodes.values()), "edges": list(edges.values())}
        episode_ids = {item.transaction_id for item in assessment["episode"]}
        state["timeline"] = [_timeline_row(item, target.transaction_id, episode_ids) for item in context["history"]]

    def _record(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        state["audit"] = [*state.get("audit", []), event]
        self._seal(state, event)

    def _seal_steps(self, state: dict[str, Any], assessment: dict[str, Any], label: str, trace: ToolTrace, from_step: int) -> None:
        for step in trace.steps[from_step:]:
            self._record(state, {"type": "tool_call", "tool": step["tool"], "source": step["source"], "ok": step["ok"], "result": step["result"]})
        pattern = assessment["pattern"]
        self._record(state, {"type": f"{label}pattern_detection", "pattern": pattern.pattern.value, "strength": f"{pattern.strength:.2f}"})
        self._record(state, {"type": f"{label}fraud_probability", "fraud_probability": f"{assessment['probability']:.4f}", "verdict": assessment["verdict"].value, "evidence_items": len(assessment["evidence"])})
        self._record(state, {"type": f"{label}stopping_evaluation", "stop": assessment["stop"].should_stop, "reason_code": assessment["stop"].reason_code.value})
        self._record(state, {"type": f"{label}policy_applied", "actions": ",".join(item["action"] for item in assessment["actions"]), "exposure_usd": f"{assessment['exposure']:.2f}"})

    # ---------------------------------------------------------- queue view

    @staticmethod
    def _finding(assessment: dict[str, Any]) -> str:
        pattern = assessment["pattern"]
        if pattern.pattern is not FraudPattern.NONE:
            return pattern.reason
        claims = [item["claim"] for item in assessment["evidence"]]
        return claims[0] if claims else "No grounded signal beyond the trigger."

    def overview(self, case_input: dict[str, Any]) -> dict[str, Any] | None:
        """Summarise a case for the queue without starting or changing its investigation."""
        case_id = case_input["case_id"]
        state = self._states.get(case_id)
        stored = self._contexts.get(case_id)
        if self.source_name == "tigergraph-mcp" and not stored:
            customer_id = str(case_input.get("customer_id") or "")
            card_id = str(case_input.get("card_id") or "")
            return {
                "verdict": "none", "pattern": "none", "fraud_probability": None, "exposure_usd": None,
                "finding": "Awaiting investigation", "flagged_amount": None, "channel": "", "status": "not_started",
                "pending_approvals": [], "open_requests": 0, "sar_required": False,
                "entities": {"customers": [customer_id] if customer_id else [], "cards": [card_id] if card_id else [],
                              "devices": [], "shared_devices": [], "transactions": [], "closed_cases": []},
            }
        if stored and "last" in stored and state:
            assessment, context = stored["last"], stored
            status = state["status"]
            approvals = [item for item in state.get("approval_requests", []) if item["approval_status"] == "pending"]
            open_requests = len([item for item in state.get("evidence_requests", []) if item.get("status") != "resolved"])
        else:
            context = self._previews.get(case_id)
            if context is None:
                # Queue previews use the rule planner: no model calls just to list cases.
                context = self._gather(case_input, ToolTrace(self.source_name), planner=RulePlanner())
                if context is None:
                    return None
                self._previews[case_id] = context
            assessment = self._assess(case_input, context, [])
            status = "not_started"
            approvals = [item for item in assessment["actions"] if item["route"] in {"L1", "L2"}]
            open_requests = 0 if assessment["stop"].should_stop else 1
        target: Txn = assessment["target"]
        history = context["history"]
        return {
            "verdict": assessment["verdict"].value, "pattern": assessment["pattern"].pattern.value, "fraud_probability": assessment["probability"],
            "exposure_usd": assessment["exposure"], "finding": self._finding(assessment), "flagged_amount": target.amount, "channel": target.channel,
            "status": status, "pending_approvals": [{"action": item["action"], "route": item["route"]} for item in approvals],
            "open_requests": open_requests, "sar_required": bool(assessment["sar"]["file"]),
            "entities": {
                "customers": sorted({target.customer_id, *assessment["other_customers"]}),
                "cards": sorted({item.card_id for item in history if item.card_id} | set(assessment["connected_cards"])),
                "devices": sorted({item.device_profile_id for item in history if item.device_profile_id}),
                "shared_devices": [target.device_profile_id] if target.device_profile_id and assessment["other_customers"] else [],
                "transactions": sorted({item.transaction_id for item in history} | {item.transaction_id for item in context["network"]}),
                "closed_cases": [case.case_id for case, _ in assessment["linked"]],
            },
        }

    # ------------------------------------------------------ workflow API

    def start_investigation(self, case_input: dict[str, Any]) -> dict[str, Any]:
        case_id = case_input["case_id"]
        trace = ToolTrace(self.source_name)
        context = self._gather(case_input, trace)
        if context is None:
            state = super().start_investigation(case_input)
            state["agent_trace"] = trace.steps
            state["data_source"] = self.source_name
            return state
        self._contexts[case_id] = context
        self._previews.pop(case_id, None)
        state: dict[str, Any] = {**case_input, "case_id": case_id, "trigger": dict(case_input), "evidence_requests": [], "evidence_responses": [], "approval_requests": [], "audit": []}
        self._states[case_id] = state
        self._record(state, {"type": "case_opened", "trigger_type": str(case_input.get("trigger_type", "")), "flagged_txn_id": str(case_input.get("flagged_txn_id", ""))})
        assessment = self._assess(case_input, context, [], trace)
        async_narrative = self.source_name == "tigergraph-mcp" and os.getenv("LLM_PROVIDER", "disabled").strip().lower() == "openai"
        self._retrieve_grounding(context, assessment)
        self._seal_steps(state, assessment, "", trace, 0)
        state["decision_paths"] = self._decision_paths(case_input, context, [], assessment, set()) if self.compute_decision_paths else []
        request = self._next_request(case_id, assessment, state, state["decision_paths"])
        if request:
            state["evidence_requests"] = [request]
            self._record(state, {"type": "evidence_requested", "request_id": request["request_id"], "request_type": request["type"]})
        state["next_best_actions"] = {"initial": assessment["actions"], "final": assessment["actions"], "what_changed": "nothing"}
        self._render(state, assessment, narrate=not async_narrative)
        if async_narrative:
            state["llm_pending"] = True
            threading.Thread(target=self._narrate_in_background, args=(state, assessment), daemon=True, name=f"llm-narrative-{case_id}").start()
        if state["approval_requests"]:
            self._record(state, {"type": "approvals_routed", "pending": ",".join(item["action"] for item in state["approval_requests"])})
        self._execute_auto(state, assessment)
        self._remember_if_done(state)
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
        simulated = bool(evidence.get("simulated"))
        response = {"request_id": request["request_id"], "type": request["type"], "result": result, "details": details if isinstance(details, str) else str(details),
                    "claim": f"{label} response: {result.replace('_', ' ')}" + (f". {details}" if details else "."), "source": evidence.get("source", "analyst"),
                    "ref": request["request_id"], "entity_ids": [self._contexts[case_id]["target"].customer_id], "simulated": simulated}
        if simulated:
            response["assumption"] = str(evidence.get("assumption") or "Simulated response; not customer-provided evidence.")
        request["status"] = "resolved"
        state["evidence_responses"] = [*state.get("evidence_responses", []), response]
        self._record(state, {"type": "evidence_response_recorded", "request_id": request["request_id"], "result": result, "simulated": simulated})
        context = self._contexts[case_id]
        trace: ToolTrace = context["trace"]
        steps_before = len(trace.steps)
        assessment = self._assess(context["input"], context, state["evidence_responses"], trace)
        self._retrieve_grounding(context, assessment)
        self._seal_steps(state, assessment, "reassessed_", trace, steps_before)
        asked = {item["type"] for item in state.get("evidence_requests", [])}
        state["decision_paths"] = self._decision_paths(context["input"], context, state["evidence_responses"], assessment, asked)
        follow_up = self._next_request(case_id, assessment, state, state["decision_paths"])
        if follow_up:
            state["evidence_requests"] = [*state["evidence_requests"], follow_up]
            self._record(state, {"type": "evidence_requested", "request_id": follow_up["request_id"], "request_type": follow_up["type"]})
        initial = state["next_best_actions"]["initial"]
        added = [item["action"] for item in assessment["actions"] if item["action"] not in {entry["action"] for entry in initial}]
        dropped = [item["action"] for item in initial if item["action"] not in {entry["action"] for entry in assessment["actions"]}]
        what_changed = f"{label} evidence ({result.replace('_', ' ')}) moved fraud probability to {assessment['probability']:.2f}."
        if added:
            what_changed += " Added: " + ", ".join(action.replace("_", " ").lower() for action in added) + "."
        if dropped:
            what_changed += " No longer recommended: " + ", ".join(action.replace("_", " ").lower() for action in dropped) + "."
        if not added and not dropped:
            what_changed += " The recommended actions did not change."
        state["next_best_actions"] = {"initial": initial, "final": assessment["actions"], "what_changed": what_changed}
        self._render(state, assessment)
        self._execute_auto(state, assessment)
        self._remember_if_done(state)
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
        self._execute(state, item, approved_by=f"{item['route']} approver", rejected=not approved)
        pending = [entry for entry in state["approval_requests"] if entry["approval_status"] == "pending"]
        if not pending and not [entry for entry in state.get("evidence_requests", []) if entry.get("status") != "resolved"]:
            state["status"] = "completed"
            verdict = state["case"]["verdict"]
            state["case"]["status"] = "closed_fraud" if verdict == "fraud" else "closed_legitimate" if verdict == "legitimate" else "escalated"
            self._record(state, {"type": "case_closed", "case_status": state["case"]["status"]})
            self._remember_if_done(state)
        state["message"] = f"{item['action'].replace('_', ' ').capitalize()} {'approved' if approved else 'rejected'} at {item['route']}" + (f"; {len(pending)} approval(s) still pending." if pending else "; no approvals pending.")
        return state

    def _execute(self, state: dict[str, Any], action: dict[str, Any], *, approved_by: str = "", rejected: bool = False) -> dict[str, Any]:
        executions = state.setdefault("executions", [])
        receipt = (self.executor.reject if rejected else self.executor.execute)(state["case_id"], action, sequence=len(executions) + 1, **({} if rejected else {"approved_by": approved_by}))
        executions.append(receipt)
        self._record(state, {"type": "action_executed" if not rejected else "action_not_executed", "action": receipt["action"], "system": receipt["system"],
                             "receipt_id": receipt["receipt_id"], "simulated": True})
        return receipt

    def _execute_auto(self, state: dict[str, Any], assessment: dict[str, Any]) -> None:
        """Automatic actions run as soon as policy recommends them; each runs once per case."""
        done = {item["action"] for item in state.get("executions", []) if item["status"] == "executed"}
        for action in assessment["actions"]:
            if action["route"] == "auto" and action["action"] not in done:
                self._execute(state, action)

    def _remember_if_done(self, state: dict[str, Any]) -> None:
        """Completed investigations become case memory for later ones."""
        if state.get("status") != "completed" or state.get("remembered"):
            return
        context = self._contexts[state["case_id"]]
        target: Txn = context["target"]
        self.memory.remember({"case_id": state["case_id"], "customer_id": target.customer_id, "card_id": target.card_id,
                              "devices": sorted({item.device_profile_id for item in context["history"] if item.device_profile_id}),
                              "verdict": state["case"]["verdict"], "pattern": state["case"]["pattern"], "fraud_probability": state["case"]["fraud_probability"],
                              "status": state["case"]["status"], "summary": state["case"]["summary"], "recorded_at": datetime.now(timezone.utc).isoformat()})
        state["remembered"] = True
        self._record(state, {"type": "case_memory_updated", "case_id": state["case_id"]})

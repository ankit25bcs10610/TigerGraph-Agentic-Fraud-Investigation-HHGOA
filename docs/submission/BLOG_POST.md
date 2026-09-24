# Sentinel: From an uncertain alert to a defensible fraud decision

*An agentic fraud investigation system built on TigerGraph for the HHGOA Hacker House Goa challenge.*

Fraud investigation is not a single classification problem. An analyst must connect a payment to a customer, card, device and region; compare it with normal behaviour; search for related accounts; read policy; decide whether more evidence is needed; route protected actions for approval; and leave a record that another person can verify.

We built **Sentinel** to make that workflow faster without making it less accountable. Sentinel is graph-native, evidence-first and explicit about uncertainty. It investigates the activity, recommends the next best action, pauses when the evidence is insufficient, and records every decision with its supporting evidence and approval route.

## The one-line idea

**Graph evidence finds the relationships. Deterministic controls make the decision. A human approves protected actions. The audit chain proves what happened.**

## What Sentinel does

Sentinel starts from a risk signal, customer report or analyst request and runs a complete investigation:

1. **Load the trigger.** Validate the case, transaction, customer and card references before analysis begins.
2. **Build context in TigerGraph.** Retrieve the transaction profile, the card and customer baselines, device neighbours, regional activity, linked cards and prior cases.
3. **Detect patterns.** Evaluate card testing, card-not-present fraud, card-not-present fraud from a new device, out-of-region use, account takeover and coordinated activity that does not fit a documented pattern.
4. **Grade the evidence.** Combine independent signals into a transparent fraud probability, preserving both supporting and contradicting evidence.
5. **Choose whether to continue.** If the evidence is not sufficient, select a controlled evidence request such as customer validation or step-up authentication.
6. **Recommend and route actions.** Apply bank policy R1–R10. Automatic actions can run; card blocks, declines and reports are routed to the required L1 or L2 approval.
7. **Explain and remember.** Produce a grounded narrative, persist the formal case, retain before-and-after recommendations, and extend the tamper-evident audit chain.

The analyst sees this as one workbench: queue health, exposure, risk waterfall, relationship graph, ring timeline, evidence requests, policy citations, approval state and the complete agent trace.

## What the analyst sees

The command center puts operational risk and the investigation queue first. The case view then moves from the relationship graph to evidence, score waterfall, decisions and audit without hiding the underlying records.

![Sentinel investigation workbench](../../docs/screenshots/investigation.png)

![Sentinel policy decisions and approvals](../../docs/screenshots/decisions.png)

The relationship view makes shared devices and linked cases visible, while the audit view lets the browser verify the event chain rather than asking the analyst to trust a status label.

## Why TigerGraph is central

Fraud signals become more valuable when connected. A new device is one signal. The same device used by four customers, touching a previously confirmed case, is a different investigation.

Sentinel stores and retrieves the investigation context in TigerGraph:

- Customers, cards, transactions, devices, email domains, billing regions and closed cases are graph entities.
- Deterministic identity construction ensures the same source device or card is represented consistently across records.
- Read-only GSQL queries expose focused agent tools such as transaction context, customer activity, card windows, device neighbours, connected cards and prior cases.
- The official TigerGraph MCP server exposes those graph capabilities to the agent. Each tool call records what was called, why it was called and what it returned.
- A bounded device-ring traversal expands device → transaction → card → customer relationships without allowing an unbounded graph search to overwhelm the investigation.
- Every formal benchmark investigation is written back as an `InvestigationCase` and linked to the entities and evidence that produced it.

The graph is not just a storage layer. It changes the investigation questions Sentinel can ask: *Who else touched this device? Which cards are in the blast radius? Has this relationship appeared in a confirmed case? Is the activity coordinated in the same episode?*

## The agent architecture

```text
Trigger / case pack
        │
        ▼
Validation and case creation
        │
        ▼
TigerGraph MCP → GSQL evidence tools
        │
        ▼
Pattern detectors → evidence grading → fraud probability
        │                         │
        │                         └─ GraphRAG policy and prior-case context
        ▼
Stopping decision
        │
        ├─ enough evidence → policy → approval route → action receipt
        │
        └─ uncertainty → value-of-information evidence request → re-assess
                                      │
                                      ▼
                         InvestigationCase + memory + audit chain
```

The backend is Python and FastAPI. The workflow is orchestrated as a state machine. The analyst UI is Next.js, React, TypeScript and Cytoscape.js.

## Agentic where it helps, deterministic where it matters

The LLM is optional and deliberately constrained. It may plan the next graph tool and write a narrative from retrieved citations. It cannot change the fraud probability, invent evidence, choose an approval route, execute a protected action or override policy.

The deterministic layer owns:

- pattern detection and supporting/contradicting evidence;
- fraud probability and exposure calculation;
- stopping criteria and uncertainty handling;
- policy recommendations and SAR eligibility;
- AUTO, L1 and L2 approval routing;
- graph persistence and output validation.

If the LLM is unavailable, the rule-based planner continues the workflow and the deterministic explanation remains available. If an LLM narrative contains unsupported references, validation rejects it rather than allowing an attractive but ungrounded explanation into the case record.

## Next-best action is a real workflow, not a button label

When Sentinel is uncertain, it does not simply display “review.” It evaluates the evidence requests available to the case and selects one that can change the decision.

For example, a customer validation response can move an uncertain case to confirmed fraud or confirmed legitimate activity. A step-up response may add confidence without settling the case. The agent records:

- the recommendation before the request;
- why the request was selected;
- the simulated or real response, clearly labelled;
- the updated probability and verdict;
- the changed action set and approval route.

This makes the agent’s behaviour inspectable before and after new evidence arrives.

## Policy, permissions and receipts

Sentinel treats a recommendation and an execution as different events. Every action is mapped to its policy rule and approval route. Automatic actions receive a simulated bank-system receipt. Protected actions remain pending until an authorized analyst approves or rejects them.

The case record includes the evidence, recommendation, required role, approval decision, execution result and receipt. This prevents the common failure mode where a UI says “block card” but the system cannot show whether anyone was authorized to perform it.

## GraphRAG and grounded explanations

Graph evidence answers *what is connected*. GraphRAG supplies the policy and prior-case context needed to answer *why this matters*.

Sentinel indexes policy passages, documented pattern descriptions and closed-case narratives as `KnowledgeChunk` vertices. Retrieval is performed through the graph integration and returned alongside structural evidence. The narrative layer can only cite records in its allow-list, and the UI exposes those citations next to the explanation.

The result is a useful separation:

- graph queries provide facts and relationships;
- deterministic detectors assess those facts;
- policy documents explain permitted actions;
- the LLM, when available, turns cited records into readable prose.

## The audit trail is part of the product

Every graph call, detector result, evidence request, response, approval and action extends a SHA-256 hash chain. The browser recomputes the chain and reports whether the record is verified. Secrets and credentials are filtered before events reach the UI.

That gives an analyst and a reviewer answers to four practical questions:

1. What did the agent know?
2. Which tools did it call and why?
3. Which policy produced the recommendation?
4. What was actually approved and executed?

## Accuracy work and honest calibration

We replayed 49 closed investigations, sampled evenly across the seven analyst labels. The case under test and every case opened after it were hidden from the agent to avoid label leakage. This is a blindfolded evidence-only calibration, not a claim that analyst notes are available at trigger time.

The latest calibration report is stored in [`outputs/CALIBRATION_REAL.md`](../../outputs/CALIBRATION_REAL.md):

| Analyst pattern | Recall |
|---|---:|
| Account takeover | 57% |
| Card-not-present fraud | 29% |
| Card-not-present, new device | 29% |
| Card testing | 71% |
| Out-of-region use | 43% |
| Undocumented activity | 29% |
| Legitimate / none | 14% |

The most important engineering result was not fitting labels. It was removing evidence leaks and false positives:

- the target transaction is excluded from its own device baseline;
- historical shared-device activity outside the active episode does not suppress account-takeover detection;
- coordinated undocumented activity requires temporally relevant cross-customer evidence or a repeated authorization pattern;
- regression tests protect each of these boundaries.

The current benchmark run produced **20/20 valid answer files**, with all 20 formal cases written to TigerGraph and no review failures. The repository currently has **166 passing automated tests** in the local suite; live integration tests additionally require the active Savanna workspace to resolve and remain available.

We also keep the limitations visible. The closed-case notes often contain customer reports that are not available in a blindfolded trigger-only replay. Therefore several confirmed cases correctly remain uncertain until the workflow gathers more evidence. That is a calibration limitation we expose rather than hide behind a hard-coded answer.

## What we learned

### A graph makes the second question cheap

The first question is “is this transaction unusual?” The more valuable question is often “what else is connected to it?” TigerGraph makes device, card, customer and prior-case relationships available in a bounded investigation instead of forcing a sequence of expensive joins.

### Uncertainty is a product capability

A fraud system that must always answer fraud or not-fraud will overstate weak evidence. Sentinel has an explicit uncertain state, evidence requests, stopping criteria and a before/after decision record.

### Grounding is a systems problem

Good prompts are not enough. Grounding requires an evidence allow-list, policy attribution, output validation, and a fallback when the model is unavailable. Those controls are implemented outside the LLM.

### Accuracy improves when relationships are time-aware

A historical relationship is not automatically evidence for the current episode. Scoping network signals to the investigation window improved precision without adding case-specific rules.

## What we would build next

- Run a larger, time-split evaluation with separate trigger-only and post-customer-report metrics.
- Tune pattern thresholds from documented policy and training-period distributions, with precision/recall plots and confidence intervals.
- Add more real-time customer and step-up integrations instead of simulated evidence responses.
- Expand graph-wide ring analytics and monitor how rings evolve across cases.
- Add analyst feedback loops so resolved cases improve retrieval and detector calibration without leaking future labels into historical evaluations.

## Try it

- **Repository:** [TigerGraph-Agentic-Fraud-Investigation-HHGOA](https://github.com/ankit25bcs10610/TigerGraph-Agentic-Fraud-Investigation-HHGOA)
- **Benchmark answers:** [`outputs/benchmark_final/answers/`](../../outputs/benchmark_final/answers/)
- **Calibration:** [`outputs/CALIBRATION_REAL.md`](../../outputs/CALIBRATION_REAL.md)
- **Architecture:** [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)
- **Demo video:** *add the final recording link here before submission*

Sentinel is built on TigerGraph Savanna for the TigerGraph Hacker House Goa challenge.

**Team:** Kartikeya Yadav and Ankit Pandey

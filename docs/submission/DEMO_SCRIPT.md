# Demo video script (4 min 30 s)

One story, told end to end: an uncertain alert becomes a defensible, approved, remembered decision. Record at 1600×1000 in the light theme, with the API running on TigerGraph (`DATA_SOURCE=tigergraph`).

The cases below are from the live run on TigerGraph (`outputs/benchmark_final/REPORT.md`):

- **Case A: HHG-010.** A $1,000.03 risk-score alert the agent cannot settle on graph evidence: it simulates each possible answer and asks the customer.
- **Case B: HHG-014.** The analyst's "same unusual device profile" request. One phone build (`SM-G935F Build/NRD90M`) served 24 of its 52 customers in the alert week, the ring expands to 38 cards, and no documented pattern explains it: the agent labels it *undocumented*.
- **The ring: HHG-011 and HHG-016.** Two separate alerts (card testing, and a customer's dispute) whose cards sit in the same 36-customer ring of burst devices, found by `agent_fraud_communities` across the whole graph.

Restart the API first so every case starts as *New*.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:20 | Command center | "Fraud analysts get alerts faster than they can investigate them. Sentinel is an agent that investigates each one on TigerGraph, decides whether it has enough evidence, and recommends the next best action under bank policy, with a human approving anything that matters." |
| 0:20–0:50 | Operational risk, priority brief, queue, Fraud rings tab | "The queue is already assessed: exposure, verdict mix, what needs a decision. Across all 590,000 transactions, community detection found eight rings of devices serving several customers in a burst, and each one is described: the biggest is 36 cards on 16 shared phones, all online, almost all product C. No documented pattern looks like that. Two of today's alerts, a card-testing case and a customer dispute, are in it." |
| 0:50–1:40 | Open **HHG-014** → Agent reasoning panel | "An analyst asked about an unusual device. Each step is a GSQL query through TigerGraph MCP, with the reason it ran. The device has 52 customers, which usually means a generic browser fingerprint, so the agent checks: it's one specific phone build, a Galaxy S7 edge, and 24 of those customers used it this week. That's one device serving many cards, so it expands the ring." Point to the source chip: *TigerGraph MCP*. |
| 1:40–2:10 | Relationship map → Blast radius | "The ring holds 38 cards on 12 devices within seven days, and no documented pattern explains it, so the agent calls it undocumented and lists every card it reaches. For a common fingerprint it does the opposite and says why: open HHG-016 and it skips the device, then finds the card in the graph-wide ring anyway." |
| 2:10–2:40 | Why the agent decided this, then Decisions → Policy grounding | "The agent explains its verdict, what is still uncertain and why each action was chosen, and every action is cited to the policy rule that produced it. Filing a report needs L2 sign-off, so it waits for a human." |
| 2:40–3:05 | Open **HHG-010** → How the score was built, Decision paths | "This one is uncertain: the waterfall shows it's 0.25 short of the fraud line. So which question should it ask? The agent simulated every possible answer. Asking the customer can lead to three different decisions and settle the case; step-up authentication can't settle it. So it asks the customer, and we can see what each answer will do before it arrives." |
| 3:05–3:30 | Evidence → record the customer's answer | "The customer denies it…" Record *Denied*. "…exactly the branch we saw: the verdict moves to fraud, the recommendation changes to block the card, and the approval route follows the exposure." Show Decisions: before and after. |
| 3:30–3:55 | Approve → toast → Audit | "Approved and sealed. Every event, including every graph query, is in a SHA-256 hash chain, and your browser recomputes each hash: case record verified." |
| 3:55–4:15 | Decisions → Actions taken; then open **HHG-011** → Agent reasoning, `recall_graph_memory` | "Approved actions are carried out through the bank's systems, here simulated, each with a receipt in the audit chain. And every case becomes memory in the graph: HHG-011, two weeks later, recalls the agent's own fraud finding on HHG-016, a different customer whose card is in the same ring." |
| 4:15–4:30 | README hero / repo | "Deterministic where it must be, agentic where it helps, grounded everywhere. The benchmark answers, calibration and code are in the repo." |

## Recording tips

- Hide the browser bookmarks bar; zoom to 100%.
- Pre-open the dev tools *closed*; start each shot on the command center.
- Record the voice separately if the room is noisy, then lay it over the screen capture.
- Keep it under 5 minutes; judges stop watching at the limit.

# Demo video script (4 min 30 s)

One story, told end to end: an uncertain alert becomes a defensible, approved, remembered decision. Record at 1600×1000 in the light theme, with the API running on TigerGraph (`DATA_SOURCE=tigergraph`).

Before recording, pick two benchmark cases from `outputs/REPORT.md`:

- **Case A**: a case where the agent asked for evidence. Its final actions differ from its initial ones.
- **Case B**: a case the agent settled on graph evidence alone, ideally with a shared device or linked closed case.

Restart the API first so every case starts as *New*.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:20 | Command center | "Fraud analysts get alerts faster than they can investigate them. Sentinel is an agent that investigates each one on TigerGraph, decides whether it has enough evidence, and recommends the next best action under bank policy, with a human approving anything that matters." |
| 0:20–0:50 | Operational risk, priority brief, queue, Fraud rings tab | "The queue is already assessed: exposure, verdict mix, what needs a decision. And across the whole graph, community detection found these rings, one of which matches no documented pattern." |
| 0:50–1:40 | Open **Case B** → Agent reasoning panel | "Here's what the agent actually did. Each step is a GSQL query called through TigerGraph MCP, with the reason it ran: load the transaction, build the customer's baseline, check who else used the device, then a fraud-ring expansion around it, then prior cases on the same entities." Point to the source chip: *TigerGraph MCP*. |
| 1:40–2:10 | Relationship map → Blast radius | "The ring analysis found three customers on one device, one of them in a confirmed fraud case, and the blast radius lists the other cards the same device reaches, with their recent spend. One alert protects the whole ring." |
| 2:10–2:40 | Why the agent decided this, then Decisions → Policy grounding | "The agent explains its verdict, what is still uncertain and why each action was chosen, and every action is cited to the policy rule that produced it. Filing a report needs L2 sign-off, so it waits for a human." |
| 2:40–3:05 | Open **Case A** → How the score was built, Decision paths | "This one is uncertain: the waterfall shows it's 0.25 short of the fraud line. So which question should it ask? The agent simulated every possible answer. Asking the customer can lead to three different decisions and settle the case; step-up authentication can't settle it. So it asks the customer, and we can see what each answer will do before it arrives." |
| 3:05–3:30 | Evidence → record the customer's answer | "The customer denies it…" Record *Denied*. "…exactly the branch we saw: the verdict moves to fraud, the recommendation changes to block the card, and the approval route follows the exposure." Show Decisions: before and after. |
| 3:30–3:55 | Approve → toast → Audit | "Approved and sealed. Every event, including every graph query, is in a SHA-256 hash chain, and your browser recomputes each hash: case record verified." |
| 3:55–4:15 | Decisions → Actions taken; then open a case on the same device | "Approved actions are carried out through the bank's systems, here simulated, each with a receipt in the audit chain. And the case is now memory: this next alert on the same device opens with 'the agent's earlier investigation concluded fraud.'" |
| 4:15–4:30 | README hero / repo | "Deterministic where it must be, agentic where it helps, grounded everywhere. The benchmark answers, calibration and code are in the repo." |

## Recording tips

- Hide the browser bookmarks bar; zoom to 100%.
- Pre-open the dev tools *closed*; start each shot on the command center.
- Record the voice separately if the room is noisy, then lay it over the screen capture.
- Keep it under 5 minutes; judges stop watching at the limit.

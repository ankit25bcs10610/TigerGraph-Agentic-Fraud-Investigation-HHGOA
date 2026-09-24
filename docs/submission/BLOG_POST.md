# Sentinel: an agent that investigates fraud on TigerGraph, and knows when it doesn't know enough

*Built for the TigerGraph Hacker House Goa challenge by Kartikeya Yadav and Ankit Pandey.*

Fraud teams don't lack alerts. They lack time. For every flagged payment, an analyst traces the customer's history, checks the device, looks for linked accounts, reads prior cases and policy, and only then decides what to do, often after the money has gone. We set out to build an agent that does that investigation, and that is honest about uncertainty: it asks for more evidence when it needs to, acts when the evidence is enough, and leaves a record anyone can audit.

## What we built

Sentinel takes a trigger (a risk score, a customer report or an analyst request) and turns it into an evidence-backed case:

1. **Investigate.** The agent calls graph tools on TigerGraph: the flagged transaction with its card and device, the customer's baseline across every card, everyone else who used the same device, a fraud-ring expansion around that device, and prior cases on the same entities.
2. **Assess.** Deterministic detectors look for five documented patterns (card testing, card-not-present fraud with or without a new device, out-of-region use, account takeover) and for coordinated activity none of them explains. A transparent weighted score turns the evidence into a fraud probability.
3. **Decide whether to stop.** Stopping rules check whether the evidence is strong and independent enough. If not, the agent asks the customer to validate the transaction, or requests step-up authentication, and pauses.
4. **Recommend.** Policy rules R1–R10 produce the next best actions. Automatic actions run; declines, card blocks and report filings are routed to L1 or L2 approval, and the route follows the exposure.
5. **Explain and remember.** Every action is cited to the policy text that produced it. The case is written back to TigerGraph as an `InvestigationCase`, and into case memory, so the next investigation on the same customer, card or device starts from it.

The analyst sees all of this in a command center: exposure and verdict mix across the queue, a priority brief, the relationship map, the agent's reasoning step by step, and the approvals waiting for them.

## Architecture

```
case_pack trigger
      │
      ▼
 Agent loop ──tools──► TigerGraph MCP ──► installed GSQL queries
      │                    (agent_txn_profile, agent_customer_activity,
      │                     agent_device_activity, agent_device_ring,
      │                     agent_fraud_communities, agent_ring_profile,
      │                     agent_linked_closed_cases, agent_prior_investigations)
      ▼
 Deterministic assessment: patterns → fraud probability → stopping rules
      │            │
      │            └─ not enough evidence → evidence request → resume
      ▼
 Policy R1–R10 → approval routing (auto / L1 / L2) → SAR rules
      │
      ├─► grounding: rule text + policy documents (GraphRAG)
      ├─► optional LLM narrative, rejected if any claim is uncited
      ├─► InvestigationCase written to TigerGraph + case memory
      └─► SHA-256 hash chain of every event, verified in the browser
```

The backend is Python (FastAPI); the workbench is Next.js, React and Cytoscape.js.

## How TigerGraph is used

- **The graph** holds customers, cards, transactions, device profiles, email domains, billing regions, the bank's closed cases and the agent's own investigation cases. Card and device identities are derived deterministically from the raw fields, so the same device seen by two customers is one vertex.
- **GSQL queries are the agent's tools.** Each is a small, read-only question with a clear answer. The agent calls them through the **official TigerGraph MCP server**, and every call is recorded with the reason it was made.
- **A graph algorithm finds rings.** `agent_device_ring` runs a seeded, bounded connected-component expansion: device → transactions → cards → their other transactions → other devices, for two rounds, only within seven days of the alert. It returns the ring's customers, cards and devices, and any confirmed-fraud cases touching it. That feeds both the "coordinated, undocumented abuse" detector and the shared-origin reporting rule.
- **It knows when a device means nothing.** Device profiles here are fingerprints (model, browser, screen), and some are shared by hundreds of customers. Our first version expanded rings through them and found "rings" of 6,000 customers for ordinary alerts. Our second version flagged bursts, and promptly mistook a Chrome release for a fraud ring: a new browser version packs hundreds of customers into its first weeks. The agent now asks three questions of every device: how many customers ever used it, how many used it in the week of the alert, and whether the profile names an actual device model or only "Windows". A generic desktop profile is never ring evidence, however busy. A specific phone build serving many cards in one week is, and that is exactly what the benchmark's analyst request HHG-014 describes: one Samsung Galaxy S7 edge build (`SM-G935F Build/NRD90M`) used by 24 of its 52 customers in the alert week, a 38-card ring, and no documented pattern that explains it.
- **Case memory lives in the graph.** Each formal case becomes an `InvestigationCase` vertex linked to the flagged transaction, the customer, the card, connected cards, devices and similar closed cases, and later investigations read those links back.
- **GraphRAG** grounds the explanation: after assessing, the agent runs vector search over `KnowledgeChunk` vertices (policy passages, pattern documents, closed-case narratives) through MCP, cites what it retrieved, and the LLM may only write from that.

## The agentic part, and where we kept it deterministic

We drew a hard line. The LLM never computes the probability, never picks an action and never approves anything. It can write the narrative, and our validator throws the narrative away if it cites anything that wasn't retrieved.

What *is* agentic:

- **An LLM chooses the next tool.** An LLM planner picks each next graph query from the tools that make sense at that moment, within a step budget, and must say why. It can only choose from an allow-list; an invalid choice or a provider failure hands control to a rule planner, and the trace records it. The planner decides what to look at, never the verdict.
- **Knowing when to stop.** The agent keeps investigating until a stopping rule is met: strong fraud or strong legitimacy with enough independent evidence, a settled customer answer, or no useful next step.
- **Gathering evidence under control.** When uncertain, the agent requests customer validation or step-up authentication, choosing between them by value of information (below). Each request pauses the case until the answer is recorded.
- **Updating its recommendation.** We record the next best actions **before** any evidence and **after** it, with a sentence on what changed.
- **Memory, in the graph.** Every investigation is written back to TigerGraph as an `InvestigationCase` linked to the customer, cards and devices it touched. A later investigation walks those edges (`agent_prior_investigations`), only to cases opened before it. When the agent reached HHG-011 on December 29, it recalled its own fraud finding on HHG-016 from December 12: a different customer, but a card in the same ring.
- **Controls and audit.** L1/L2 actions wait for a human. Every event (each graph call, assessment, request, response and approval) extends a SHA-256 hash chain, and the UI recomputes every hash to prove nothing was edited.

## Five ideas we haven't seen elsewhere

**1. The agent chooses its questions by value of information.** When the evidence isn't enough, most agents ask a fixed next question. Ours simulates every possible answer to every request it could make, running each through the full deterministic assessment, and asks for the evidence whose answers lead to the most different decisions. For a card-testing case, asking the customer can end in *block the card*, *close as legitimate* or *monitor*: three decisions, two of which settle the case. Step-up authentication can't settle it either way. So the agent asks the customer, says why, and shows the analyst every branch before the answer arrives.

**2. Every verdict comes with its counterfactual.** A waterfall shows exactly how many points each signal added to the fraud probability and how far the result sits from each threshold. Signals whose removal alone would flip the verdict are marked *decisive*. When a probability sits just past a threshold, every signal is decisive, and the analyst can see that the call is close rather than being handed a confident label.

**3. It finds, and describes, the pattern nobody documented.** The brief warns that not every fraud pattern in the data is documented. A weakly-connected-components query runs across all 590,000 transactions, over cards and *burst devices* (3–10 customers on one device within 72 hours), and found eight rings. Finding a ring is not the same as explaining it, so `agent_ring_profile` summarises what each ring's cards did on their shared devices. The largest: 73 transactions by 36 cards on 16 shared devices, 15 of them different Android phone builds, 100% online, 99% product C, median $31.70. None of the five documented patterns describes that, so it is labelled *undocumented*. Two separate benchmark alerts, a card-testing case (HHG-011) and a customer's dispute (HHG-016), turned out to sit inside it, and each investigation cites the ring.

**4. It acts, with receipts.** Automatic actions run through simulated bank systems as soon as policy recommends them, and protected actions only after approval. Each returns a receipt sealed into the audit chain, so "what did the agent actually do" has an answer.

**5. One alert protects the whole ring.** Once a case looks like fraud, the agent uses the shared device and the ring expansion to list every *other* card the same fraudster can reach, with its recent spend. It's the question a graph answers in one hop and a table-based system rarely asks.

## How accurate is it?

We measured it two ways, and we'll be straight about both.

**Against the bank's history.** We replayed 49 closed cases, sampled evenly across the seven analyst labels, hiding the case under test and every case opened after it. Pattern recall was 71% for card testing (with 100% precision in the sample), 43% for out-of-region use, 29% for card-not-present from a new device, 14% for account takeover and for undocumented activity, and 0% for plain card-not-present fraud. The agent settled only four cases without asking for more evidence; the rest it kept uncertain. That is a modest number, and it told us where to work: detector tuning, and the device evidence below.

**On the 20 benchmark cases, live on TigerGraph.** Every answer was produced through TigerGraph MCP and written back to the graph as an `InvestigationCase`; all 20 pass our validator. Our first live run labelled 13 of the 20 cases "undocumented" and produced answer files of 8,000 lines, because generic browser fingerprints were chaining unrelated customers into giant "rings". Fixing that, by asking whether a device names a real model and whether its customers are concentrated around the alert, brought it to three undocumented cases, each tied to evidence an analyst can check: one phone build used by 24 customers in a week (HHG-014), a card inside the 36-card ring (HHG-016), and a 33-customer ring around a rare device (HHG-019).

The number we care most about isn't raw agreement: it's how often the agent stays *uncertain* instead of guessing wrong. Uncertain cases go to the evidence-request branch, not straight to a block.

## What we learned

- **Graphs make the second question cheap.** "Who else used this device?" is one hop in TigerGraph and a painful self-join anywhere else. Most of our best evidence came from the second and third hop.
- **A graph needs to know which edges mean something.** A device vertex shared by 250 people is not evidence of anything. The most valuable code we wrote decides, for each device, whether it is one physical device or a fingerprint, and it changed more answers than any other fix.
- **Uncertainty is a feature.** Designing the "not enough evidence yet" path first made the whole agent more trustworthy than tuning for a confident verdict.
- **Separate facts from prose.** Letting the LLM only narrate cited facts kept explanations readable without letting them drift from the evidence.

## What we'd do with more time

- Load the identity signals (new-device flags, proxy and match status) onto every transaction in the live graph, so the new-device and account-takeover detectors see what our CSV replay sees, then re-run the calibration.
- Run Louvain from the TigerGraph GDS library alongside our connected components, and track how rings grow over time.
- Integrate real customer messaging and step-up providers instead of labelled simulated responses.

---

Code and benchmark answers: https://github.com/ankit25bcs10610/TigerGraph-Agentic-Fraud-Investigation-HHGOA · Demo video: *(add link)* · Built on TigerGraph Savanna with @TigerGraphDB.

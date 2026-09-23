# Social posts

Pick one per platform. Replace the links before posting and tag **@TigerGraphDB**.

## LinkedIn

We built Sentinel for the TigerGraph Hacker House Goa challenge: an AI agent that investigates fraud alerts on a graph, and knows when it doesn't have enough evidence yet.

For each alert it:
🔎 queries TigerGraph through MCP (customer baseline, shared devices, a fraud-ring expansion, prior cases)
⚖️ scores the evidence deterministically and checks whether it's enough to act
🙋 asks the customer or requests step-up authentication when it isn't
✅ recommends the next best action under policy, with L1/L2 human approval for anything protected
🔏 seals every step in a hash chain your browser can verify

The LLM only writes the explanation, and only from cited evidence.

Blog: <link> · Demo: <link> · Code: <link>

@TigerGraphDB #TigerGraph #GraphDatabase #FraudDetection #AIAgents #HackerHouseGoa

## X (single post)

Built Sentinel for #HackerHouseGoa: a fraud-investigation agent on @TigerGraphDB. It queries the graph through MCP, finds device rings, asks for evidence when it's unsure, and routes blocks to human approval. Every step is hash-sealed. Demo: <link>

## X (thread)

1/ Fraud analysts don't lack alerts, they lack time. We built Sentinel, an agent that investigates each alert on @TigerGraphDB and knows when it doesn't know enough. 🧵

2/ Every graph question is a GSQL query called through TigerGraph MCP, with a recorded reason: the customer's baseline, who else used the device, and a bounded connected-component search for fraud rings.

3/ When the evidence isn't enough, it doesn't guess. It asks the customer or requests step-up auth, then updates its recommendation, and we record the before and the after.

4/ Blocks and report filings wait for L1/L2 approval. Every event lands in a SHA-256 chain the UI re-verifies. The LLM only narrates cited facts.

5/ Blog: <link> · Demo: <link> · Code: <link> #HackerHouseGoa

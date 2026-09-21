# Core GSQL investigation queries

These queries are deterministic graph retrieval primitives. They are intended to be installed in the FraudInvestigation graph and called by the investigation workflow. An LLM may interpret returned evidence, but it must not replace these queries or infer their graph joins.

## Installation

Install the schema and loading job first, then load sample data as described in DATA_LOADING.md. Install each query:

    for q in tigergraph/queries/*.gsql; do
      gsql -g FraudInvestigation "$q"
    done

In an interactive GSQL shell, the equivalent is:

    USE GRAPH FraudInvestigation
    @tigergraph/queries/transaction_context.gsql

Run a saved query with:

    RUN QUERY query_name("argument", ...)

The query files use GSQL Syntax v2 for explicit multi-hop paths and reverse traversals.

## Query reference

### 1. transaction_context

File: tigergraph/queries/transaction_context.gsql

Purpose: retrieve the target transaction and its directly connected customer/card/device/email/billing context.

Parameters:

- transaction_id: Transaction.transaction_id.

Returned result sets:

- target: the transaction, including amount, timestamp, channel, risk_score, card fields, address fields, and retained source feature fields.
- cards: Card vertices reached through the incoming MADE edge.
- customers: Customer vertices reached through OWNS.
- devices: DeviceProfile vertices reached through FROM_DEVICE.
- email_domains: EmailDomain vertices reached through PURCHASER_EMAIL.
- regions: BillingRegion vertices reached through BILLED_IN.

Sample call:

    RUN QUERY transaction_context("3000001")

Limitation: a transaction without a supplied identity row, email domain, or valid addr1 naturally has an empty corresponding result set. risk_score is returned as evidence, never as a verdict.

### 2. card_history

File: tigergraph/queries/card_history.gsql

Purpose: return the complete transaction history for one Card in chronological order.

Parameter:

- card_id: Card.card_id.

Returned result sets:

- card: the requested Card.
- history: all transactions reached through MADE, ordered by Transaction.ts ascending.

Sample call:

    RUN QUERY card_history("C06075-K1")

Limitation: transaction history follows the deterministic card construction used by the loader. The source dataset does not provide a direct case-card-to-transaction mapping.

### 3. customer_history

File: tigergraph/queries/customer_history.gsql

Purpose: retrieve a customer's cards and all transactions reached through those cards.

Parameter:

- customer_id: Customer.customer_id.

Returned result sets:

- customer: the requested Customer.
- cards: all cards connected through OWNS.
- history: all card transactions, ordered by ts.

Sample call:

    RUN QUERY customer_history("C06075")

Limitation: if card mapping is unresolved, history is complete for constructed transaction cards but may not align perfectly with historical case card labels.

### 4. card_window

File: tigergraph/queries/card_window.gsql

Purpose: return transactions on the same card within a time window around a target transaction. This is the primitive for burst and card-testing detection.

Parameters:

- card_id: Card.card_id.
- transaction_id: target Transaction.transaction_id.
- hours: unsigned number of hours on either side of the target.

Returned result sets:

- target: the target transaction only if it belongs to the supplied card.
- window: same-card transactions whose TransactionDT difference is within hours, ordered by ts.

Sample call:

    RUN QUERY card_window("C06075-K1", "3000001", 1)

Limitation: the query uses TransactionDT seconds because it is numeric and present on every transaction. It does not decide whether a sequence is card testing; it only returns the evidence window.

### 5. device_neighbors

File: tigergraph/queries/device_neighbors.gsql

Purpose: find activity sharing one DeviceProfile and identify associated cards, customers, and confirmed historical fraud cases.

Parameter:

- device_profile_id: DeviceProfile.device_profile_id.

Returned result sets:

- device
- transactions, ordered by ts
- cards
- customers
- related_fraud_cases, restricted to ClosedCase.outcome = confirmed_fraud

Sample call:

    RUN QUERY device_neighbors("DP-6dbb02081c9e89be16f48df47f0136ae")

Limitation: only identity rows with at least one usable device/identity field produce FROM_DEVICE edges. A missing device edge is not evidence that transactions used different devices.

### 6. region_history

File: tigergraph/queries/region_history.gsql

Purpose: retrieve a card's billing-region vertices and the card's transaction activity over time.

Parameter:

- card_id: Card.card_id.

Returned result sets:

- card
- regions: distinct BillingRegion vertices reached by the card's transactions
- activity: transactions with billing-region joins, ordered by ts

Sample call:

    RUN QUERY region_history("C06075-K1")

Limitation: addr1 and addr2 are anonymized source codes. The query does not translate them into geography or infer travel/fraud.

### 7. email_neighbors

File: tigergraph/queries/email_neighbors.gsql

Purpose: find transactions, cards, and customers sharing an EmailDomain.

Parameter:

- email_domain: EmailDomain.email_domain.

Returned result sets:

- domain
- transactions, ordered by ts
- cards
- customers

Sample call:

    RUN QUERY email_neighbors("yahoo.com")

Limitation: the schema edge is named PURCHASER_EMAIL but the loader retains both P_emaildomain and R_emaildomain with an email_role edge attribute. Consumers should inspect that attribute before treating a match as purchaser-domain evidence.

### 8. connected_cards

File: tigergraph/queries/connected_cards.gsql

Purpose: find other cards connected to a starting card through shared devices, billing regions, purchaser/recipient email domains, or historical closed-case links.

Parameter:

- card_id: starting Card.card_id.

Returned result sets:

- start
- device_cards
- region_cards
- email_cards
- closed_primary_cards
- closed_connected_cards
- closed_peer_cards

Sample call:

    RUN QUERY connected_cards("C06075-K1")

Limitation: each result set represents one defensible relationship and is intentionally not collapsed into an unexplained single score. The caller can union/deduplicate sets while preserving relationship provenance.

### 9. prior_cases

File: tigergraph/queries/prior_cases.gsql

Purpose: retrieve historical ClosedCases relevant to a customer or card, plus their involved transactions and card links.

Parameters:

- customer_id: customer identifier.
- card_id: card identifier. Matching either parameter is sufficient.

Returned result sets:

- cases
- transactions
- primary_cards
- connected_cards

Sample call:

    RUN QUERY prior_cases("C00259", "C00259-K1")

Limitation: this retrieves explicit customer/card matches only. Similarity based on patterns, devices, regions, or notes belongs in a separate retrieval layer and is not fabricated by this query.

### 10. fraud_episode_candidates

File: tigergraph/queries/fraud_episode_candidates.gsql

Purpose: return potentially related transactions around a target through independently interpretable graph paths.

Parameter:

- transaction_id: target Transaction.transaction_id.

Returned result sets:

- target
- card_candidates: same constructed card within a fixed 48-hour window
- device_candidates: shared DeviceProfile
- region_candidates: shared BillingRegion
- email_candidates: shared EmailDomain
- closed_case_candidates: transactions co-involved in a historical ClosedCase

Sample call:

    RUN QUERY fraud_episode_candidates("3000001")

Limitation: 48 hours is an explicit retrieval window, not a fraud rule. The result sets can overlap and are intentionally kept separate so downstream evidence can preserve why each candidate was returned. No query output is a fraud verdict.

## Sample-data test coverage

The sample preparation used the first 1,000 transactions and produced:

- 1,000 Transaction vertices
- 277 Customer vertices
- 286 transaction-derived card fingerprints
- 124 DeviceProfile vertices
- 26 EmailDomain vertices
- 53 BillingRegion vertices
- 17 related ClosedCase vertices
- 714 NEXT edges

The sample IDs used above were checked against the prepared TSV data:

- transaction: 3000001
- customer: C06075
- card: C06075-K1
- device: DP-6dbb02081c9e89be16f48df47f0136ae
- email: yahoo.com
- historical case example: C00259 / C00259-K1

The repository environment does not include the TigerGraph gsql runtime or a running TigerGraph server, so the queries could not be installed/executed against a live graph here. Static validation checked all ten query declarations, graph/vertex/edge names, sample parameter IDs, and required traversal coverage. Live installation should be run with the commands above after loading the sample graph.


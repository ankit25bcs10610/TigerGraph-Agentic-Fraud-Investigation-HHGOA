# Manual case investigation: HHG-001

## Scope and method

This is a manual investigation of one benchmark case only. No agent, LangGraph workflow, LLM reasoning, or hidden answer-key guess was used.

The workspace has no live TigerGraph gsql runtime or server. I therefore executed the same read-only traversals against the validated full prepared graph data and recorded the exact saved GSQL queries and parameters that would be installed and run on TigerGraph. The graph data used was prepared from the supplied transactions, identity, and closed-case files.

## Trigger

Case: HHG-001

- Opened at: 2016-12-05 01:55:28
- Trigger type: risk_score
- Trigger text: Real-time model scored transaction 3514030 ($77.07, in billing region 444.0) at 0.61. Review and decide.
- Flagged transaction: 3514030
- Customer: C12382
- Case card label: C12382-K1
- Trigger risk score: 0.61

The risk score is treated only as an input signal.

## GSQL query record

These are the graph queries used for the manual investigation:

1. transaction_context("3514030")
2. card_history("C12382-K1")
3. customer_history("C12382")
4. card_window("C12382-K1", "3514030", 48)
5. region_history("C12382-K1")
6. connected_cards("C12382-K1")
7. prior_cases("C12382", "C12382-K1")
8. fraud_episode_candidates("3514030")

The saved query email_neighbors was not run for the flagged transaction because its purchaser email value is empty. The saved device_neighbors query was not run for the flagged transaction because it is in-person and has no FROM_DEVICE edge. Those absences are themselves part of the evidence.

## Facts discovered

### Flagged transaction

Transaction 3514030 has:

| Field | Value |
|---|---|
| Amount | 77.07 USD |
| Timestamp | 2016-12-04 19:55:28 |
| ProductCD | W |
| Channel | in_person |
| Risk score | 0.61 |
| addr1 | 444.0 |
| addr2 | 87.0 |
| P_emaildomain | empty |
| R_emaildomain | empty |
| card4 | visa |
| card6 | debit |

Because ProductCD is W and channel is in_person, no identity row or device profile is attached to this transaction.

### Card history

The deterministic graph card label for the transaction is C12382-K1. Its history contains 422 transactions from 2016-07-06 through 2016-12-31.

The card has activity in 40 distinct observed addr1 billing-region values. Region 444.0 appears 15 times on this card:

- 10 occurrences precede the flagged transaction.
- The flagged transaction is one occurrence.
- 4 occurrences follow it.

Therefore, region 444.0 is not a new region for this card at the time of HHG-001.

### Customer history

The customer history contains:

- Customer C12382
- One constructed card: C12382-K1
- 422 transactions through that card

The visible history is mixed in amount and region and is mostly in-person for this customer/card. The card-label construction is deterministic but remains a dataset limitation because the source does not publish a direct transaction-to-case-card mapping.

### Device profile

No device profile is present for flagged transaction 3514030. This is expected for an in-person W transaction.

The card has historical online activity and therefore participates in device-based relationships through other transactions. The connected-cards query returned 189 other cards through shared device profiles across the card's full history. That is network evidence, not proof about this specific in-person transaction.

### Billing region

The flagged transaction is billed in anonymized region 444.0, country code 87.

Across the entire dataset, region 444.0 is shared by approximately 321 constructed cards and 296 customers. This makes it a high-connectivity region and weak evidence by itself. Across this card's own history, region 444.0 was already observed 10 times before HHG-001.

The card's broader region history contains 40 regions, not a single isolated region change.

### Purchaser email

The flagged transaction has no P_emaildomain or R_emaildomain value. No purchaser-email neighborhood can be attributed directly to the flagged transaction.

The card's historical transactions do contain several email domains, including gmail.com and yahoo.com, but those historical values do not establish an email relationship for transaction 3514030.

### Transaction sequence

The 48-hour card window around transaction 3514030 contains 15 transactions:

| Transaction | Timestamp | Amount | Region | Risk score |
|---|---|---:|---|---:|
| 3510115 | 2016-12-03 15:53:45 | 23.99 | 433.0 | 0.04 |
| 3510225 | 2016-12-03 16:32:25 | 35.92 | 204.0 | 0.08 |
| 3510464 | 2016-12-03 17:47:05 | 107.96 | 191.0 | 0.30 |
| 3510612 | 2016-12-03 18:24:53 | 34.52 | 204.0 | 0.06 |
| 3511596 | 2016-12-03 23:03:54 | 59.06 | 433.0 | 0.15 |
| 3512936 | 2016-12-04 14:28:34 | 160.00 | 485.0 | 0.08 |
| 3513814 | 2016-12-04 18:51:28 | 116.97 | 203.0 | 0.09 |
| 3514030 | 2016-12-04 19:55:28 | 77.07 | 444.0 | 0.61 |
| 3514461 | 2016-12-04 22:08:43 | 38.92 | 203.0 | 0.11 |
| 3515241 | 2016-12-05 02:45:13 | 29.07 | 498.0 | 0.02 |
| 3517969 | 2016-12-06 01:13:55 | 226.08 | 225.0 | 0.03 |
| 3519088 | 2016-12-06 15:39:17 | 38.99 | 203.0 | 0.12 |
| 3519140 | 2016-12-06 15:56:33 | 34.49 | 203.0 | 0.07 |
| 3519301 | 2016-12-06 16:48:13 | 76.99 | 330.0 | 0.05 |
| 3519548 | 2016-12-06 18:01:08 | 107.93 | 264.0 | 0.16 |

The candidate-window sum is 1,167.96 USD, but this is candidate activity, not assessed fraud exposure.

This sequence does not match the documented card-testing shape: it contains no online authorizations and is not a sequence of three or more tiny online authorizations followed by a larger purchase.

### Connected cards

For C12382-K1, connected_cards returned:

| Relationship | Other cards |
|---|---:|
| Shared device profiles across the card's full history | 189 |
| Shared billing regions across the card's full history | 12,042 |
| Shared email domains across the card's full history | 13,846 |
| Closed-case primary/connected-card relationships | 0 |

The region and email sets are extremely broad because common anonymized values are shared across many customers. They should not be treated as a specific fraud ring without stronger temporal and behavioral evidence.

### Relevant closed cases

Four historical cases directly match customer C12382 and card C12382-K1. All were confirmed fraud:

| Case | Pattern | Transaction | Amount | Region / context |
|---|---|---|---:|---|
| CC-1066 | out_of_region_use | 3090135 | 170.98 | in-person, addr1 205.0 |
| CC-1673 | card_not_present_new_device | 3140508 | 199.98 | online, addr1 264.0, id_15 New |
| CC-2964 | out_of_region_use | 3226855 | 171.08 | in-person, addr1 205.0 |
| CC-3587 | out_of_region_use | 3271314 | 49.09 | in-person, addr1 205.0 |

The historical cases have no connected-card references for this card. They establish that this customer/card has prior confirmed fraud history, including repeated out-of-region activity and one new-device online incident, but they do not prove that HHG-001 is fraudulent.

## Potentially relevant fraud patterns

- Out-of-region use: possible but weak at this point. HHG-001 is in-person and region 444.0, but the card had already used region 444.0 ten times before the flagged transaction. The graph does not show this region as new for the card.
- Card-not-present fraud: not supported by the flagged transaction because it is in-person.
- Card-not-present from a new device: not supported because the flagged transaction has no device record.
- Card testing: not supported by the 48-hour sequence; the candidate transactions are in-person and not a small-online-authorization sequence.
- Account takeover: not established. There is no device or email evidence on the flagged transaction and no mixed-channel anomaly identified from this manual pass.
- Undocumented/coordinated pattern: not established. Shared region/email results are too broad and there are no closed-case connected-card links for this card.

## Uncertainties

1. There is no customer response confirming or denying the $77.07 transaction.
2. Merchant, terminal, authorization, and card-present verification details are not supplied.
3. The risk score of 0.61 is not a fraud label.
4. Region codes are anonymized; region 444.0 cannot be interpreted geographically from this data alone.
5. The target has no purchaser email or device profile.
6. The candidate 48-hour amount sum should not be treated as fraud exposure without episode attribution.
7. The deterministic C12382-K1 construction is consistent for graph loading but is not a source-published transaction-to-case-card mapping.
8. Shared-region and shared-email neighborhoods are high-cardinality and therefore have weak specificity.

## Additional evidence that would help

- Customer confirmation or denial of transaction 3514030.
- Merchant/terminal identity, authorization outcome, and card-present verification signals.
- Confirmation of whether the customer was physically in billing region 444.0.
- A verified mapping between case card labels and raw transaction card fingerprints.
- More precise device, merchant, or terminal linkage for the surrounding transactions.
- Analyst review of the prior confirmed cases and whether the current activity matches their operational circumstances.

## Relevant policy rules

The rules that appear relevant to the next investigation step are:

- R1: verify before blocking on a weak signal. The current trigger is one risk signal plus a non-new billing region, so verification or step-up authentication is the defensible next evidence request.
- R2: if the customer denies the transaction, recommend blocking the card and creating a case; report filing depends on the resulting exposure and qualifying connections.
- R3: if the customer confirms it, close as no fraud and record the confirmation.
- R4: if there is no reply within 24 hours, monitoring and pending-authorization handling become relevant. The candidate window exceeds $500, but it is not yet established fraud exposure.
- R6: shared-origin handling should be considered only if a specific shared device, region cluster, or email relationship is shown to be meaningful; the current region/email neighborhoods are too broad on their own.
- R8: analyst escalation may become relevant if the case remains uncertain and the assessed exposure is above $500 or evidence conflicts.
- R5, R7, R9, and R10 are not directly supported by the evidence found in this manual pass.

This investigation intentionally stops at evidence gathering and policy relevance. It does not assign a final hidden answer, fraud probability, verdict, or executed action.


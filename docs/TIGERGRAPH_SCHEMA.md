# TigerGraph schema design

This schema is based on the actual headers and relationships documented in DATASET_ANALYSIS.md and the README. It defines graph structure only; no loading jobs or queries are included.

## Design principles

- TransactionID is the transaction key and customer_id is the customer key.
- risk_score is stored as a transaction input signal. It is not a verdict or outcome.
- The opaque C*, D*, M*, and V* source fields are retained as raw transaction properties. Their meanings are not invented.
- Empty source values should remain missing during loading.
- The graph has no public fraud label. Historical outcomes come from ClosedCase.outcome; system conclusions belong on InvestigationCase.

## Vertices

| Vertex | ID | Important attributes | Why it exists |
|---|---|---|---|
| Customer | customer_id (STRING) | customer_id | Groups a customer's cards and activity. |
| Card | card_id (STRING) | customer_id, raw card1-card6 fields | Represents the card referenced by cases and the card-to-transaction path. The supplied transaction files do not contain a literal card_id; later loading must validate how case labels map to raw card fields before creating MADE edges. |
| Transaction | transaction_id (STRING) | transaction_dt, transaction_amt, product_cd, customer_id, ts, channel, risk_score, card/address/email fields, C1-C14, D1-D15, M1-M9, V1-V339 | The primary investigative event and source of amount, timing, channel, risk, and feature evidence. |
| DeviceProfile | device_profile_id (STRING) | device_info, device_type, os, browser, screen, device_status, proxy_type, match_status | Connects online transactions that share a constructed device profile. The loading process should construct the ID from available identity fields only. |
| EmailDomain | email_domain (STRING) | email_domain | Supports purchaser-domain neighborhood analysis. |
| BillingRegion | billing_region_id (STRING) | addr1, addr2 | Represents anonymized billing-region codes, not resolved geographic locations. |
| ClosedCase | case_id (STRING) | outcome, pattern, dates, transaction references, exposure, actions, notes | Stores historical investigations and their confirmed/cleared outcomes for retrieval and comparison. |
| InvestigationCase | investigation_case_id (STRING) | status, verdict, pattern, fraud probability, exposure, trigger, evidence, actions, approval, SAR narrative | Stores cases produced by this system, including iterative evidence and the final recommendation. |

The transaction schema includes every actual transaction header group. card1-card6 are raw properties rather than independently meaningful entities. DeviceProfile uses only fields that actually exist in identity.csv: DeviceInfo, DeviceType, id_30 to os, id_31 to browser, id_33 to screen, id_15 to device_status, id_23 to proxy_type, and id_34 to match_status. OS, browser, and screen are schema property names, not invented source columns.

## Edges and directions

| Edge | Direction | Purpose |
|---|---|---|
| OWNS | Customer -> Card | Associates a customer with a card. |
| MADE | Card -> Transaction | Links a card to transactions made with it. |
| FROM_DEVICE | Transaction -> DeviceProfile | Links online transactions to the constructed identity/device profile. In-person transactions normally have no identity row. |
| PURCHASER_EMAIL | Transaction -> EmailDomain | Links a transaction to P_emaildomain. The email_role attribute preserves purchaser/recipient role if both source domains are represented. |
| BILLED_IN | Transaction -> BillingRegion | Links the transaction to anonymized addr1/addr2 billing context. |
| NEXT | Transaction -> Transaction | Orders transactions in a validated card scope; the edge carries ts. It should not be generated until the card key is resolved. |
| INVOLVES | ClosedCase -> Transaction | Connects a historical case to every transaction in txn_ids. relation can distinguish general involvement from first_fraud_txn_id. |
| ON_CARD | ClosedCase -> Card | Links the historical case to its primary card_id. |
| CONNECTED_TO | ClosedCase -> Card | Links historical cases to connected_card_ids. |
| FLAGGED_TRANSACTION | InvestigationCase -> Transaction | Identifies the transaction that triggered the investigation. |
| FOR_CUSTOMER | InvestigationCase -> Customer | Identifies the investigated customer. |
| FOR_CARD | InvestigationCase -> Card | Identifies the primary card under investigation. |
| AFFECTS | InvestigationCase -> Transaction | Links all transactions included in the assessed episode beyond the flagged transaction. |
| CONNECTED_CARD | InvestigationCase -> Card | Links other cards implicated by shared infrastructure or activity. |
| CONNECTED_DEVICE | InvestigationCase -> DeviceProfile | Links device profiles used as cross-card evidence. |
| SIMILAR_TO_CLOSED_CASE | InvestigationCase -> ClosedCase | Links a system case to retrieved historical cases judged similar. similarity_reason records why retrieval was relevant. |

No additional InvestigationCase edges are included. The seven listed relationships are limited to the flagged transaction, customer, primary card, affected transactions, connected cards/devices, and similar historical cases requested for system memory.

## ClosedCase versus InvestigationCase

ClosedCase is imported historical evidence from the July-October history. It contains analyst-produced outcomes such as confirmed_fraud and cleared. Its notes are evidence for retrieval, not system conclusions.

InvestigationCase is the system's own investigation record. It starts from a trigger, can be updated after evidence requests or human approval, stores the system's independent fraud_probability, and records the recommendation and approval route. Its verdict is distinct from transaction risk_score. A completed system case can later become historical memory, but it is not the same source type as an imported ClosedCase.

## Validation performed

The schema was checked against the inspected files and README:

- TransactionID, customer_id, case IDs, and required case transaction references are represented.
- The transaction schema preserves C1-C14, D1-D15, M1-M9, and V1-V339 without assigning invented meanings.
- Identity-derived device properties use only actual identity fields: DeviceInfo, DeviceType, id_30, id_31, id_33, id_15, id_23, and id_34.
- All required README edges and the minimal InvestigationCase relationships are present with the requested directions.
- No loading job, query, application code, or data file was created or changed.
- The unresolved card_id mapping is explicitly represented as a design constraint; the schema does not claim that card1-card6 already equal case card_id.


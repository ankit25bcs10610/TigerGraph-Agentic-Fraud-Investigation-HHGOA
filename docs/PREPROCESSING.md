# TigerGraph preprocessing

This preprocessing layer preserves the TigerGraph Savanna schema already created manually. It does not connect to TigerGraph and does not load `case_pack.csv` as historical truth.

## Source files

- `transactions.csv`: the 590,742-row transaction table. The graph transaction vertex receives `TransactionID`, `TransactionAmt`, `TransactionDT`, `ts`, `channel`, `risk_score`, and `ProductCD` under the requested output names.
- `identity.csv`: 144,432 identity rows joined by `TransactionID`. Only the actual device fields needed by the schema are used: `DeviceInfo`, `DeviceType`, `id_30`, `id_31`, and `id_33`.
- `closed_cases_history.csv`: 5,565 historical cases. Its `txn_ids` and `connected_card_ids` pipe-separated fields are expanded into edge files.
- `case_pack.csv`: the 20 benchmark triggers. It is used only to make the development sample internally relevant; it is not emitted as historical case data and contains no benchmark outcome.

## Card ID mapping discovered

The transaction and identity headers contain no literal `card_id`. The case files contain labels such as `C12382-K1`. The mapping that matches every closed-case transaction reference checked (14,955 references) and all 20 benchmark flagged transactions is:

1. Use the customer-scoped `(card1, card4, card6)` fingerprint. These are actual source columns; the README identifies `card4` as the network and `card6` as the card type.
2. Collect distinct fingerprints for each `customer_id`.
3. Sort those fingerprints deterministically.
4. Assign the one-based ordinal as `customer_id-K1`, `customer_id-K2`, and so on.

`card2`, `card3`, and `card5` remain available in the raw transaction data but are not used to distinguish the case card labels. In particular, `card5` can vary within one case card. The script fails on a case-pack mapping mismatch instead of silently inventing a label.

## DeviceProfile IDs

For each identity row with at least one usable device field, the script concatenates these values in this fixed order:

```text
DeviceInfo, DeviceType, id_30, id_31, id_33
```

It hashes the UTF-8 value joined with a unit separator using SHA-256 and uses the first 32 hexadecimal characters with a `DP-` prefix. The same five source values always produce the same `device_profile_id`. Empty fields remain empty; an identity row with all five fields empty creates no device vertex or edge.

## NEXT edges

Transactions are grouped by their derived `card_id`, sorted by `ts` and then `TransactionID` for a deterministic tie-break, and each adjacent pair produces one row in `next_transaction.csv`. No transaction from one card is connected to another card. The full output contains 576,424 NEXT edges for 590,742 transactions.

## Closed-case expansion

`closed_cases_graph.csv` keeps the structured case fields requested by the schema and deliberately omits the serialized `txn_ids` and `connected_card_ids` fields. The script parses those fields on `|`, then emits:

- `closed_case_involves.csv`: one `case_id,transaction_id` row per transaction reference.
- `closed_case_on_card.csv`: one row for the main case card.
- `closed_case_connected_to.csv`: one row per connected card reference.

The full output resolves all 14,955 transaction references and all 92 connected-card references.

## Null handling

Empty source values are written as empty CSV fields. They are not converted into semantic categories. Missing identity values therefore remain missing in `device_profiles.csv`; no device edge is created when all device fields are absent. Empty `P_emaildomain` and `addr1` values create no corresponding vertex or edge. Optional historical fields such as `first_fraud_txn_id` can be empty for cleared cases.

## Generated files

Vertices:

```text
data/processed/customers.csv
data/processed/cards.csv
data/processed/transactions_graph.csv
data/processed/device_profiles.csv
data/processed/email_domains.csv
data/processed/billing_regions.csv
data/processed/closed_cases_graph.csv
```

Edges:

```text
data/processed/owns.csv
data/processed/made.csv
data/processed/from_device.csv
data/processed/purchaser_email.csv
data/processed/billed_in.csv
data/processed/next_transaction.csv
data/processed/closed_case_involves.csv
data/processed/closed_case_on_card.csv
data/processed/closed_case_connected_to.csv
```

## Commands

From the repository root, using the supplied files in Downloads:

```bash
python3 scripts/prepare_tigergraph_data.py \
  --data-dir /Users/ankitpandey/Downloads \
  --output-dir data/processed \
  --sample

python3 scripts/validate_processed_data.py \
  --data-dir /Users/ankitpandey/Downloads \
  --processed-dir data/processed
```

For the complete dataset:

```bash
python3 scripts/prepare_tigergraph_data.py \
  --data-dir /Users/ankitpandey/Downloads \
  --output-dir data/processed \
  --full

python3 scripts/validate_processed_data.py \
  --data-dir /Users/ankitpandey/Downloads \
  --processed-dir data/processed
```

The sample is closed over all transactions for the 20 benchmark customers, their derived cards, and the relevant historical cases. It is not a raw first-N slice. The full mode makes a complete graph-ready export.

## Validation results

The complete export was generated and validated successfully. Row counts include data rows, excluding headers:

| File | Rows |
|---|---:|
| `customers.csv` | 13,553 |
| `cards.csv` | 14,318 |
| `transactions_graph.csv` | 590,742 |
| `device_profiles.csv` | 9,776 |
| `email_domains.csv` | 59 |
| `billing_regions.csv` | 332 |
| `closed_cases_graph.csv` | 5,565 |
| `owns.csv` | 14,318 |
| `made.csv` | 590,742 |
| `from_device.csv` | 141,055 |
| `purchaser_email.csv` | 496,262 |
| `billed_in.csv` | 525,003 |
| `next_transaction.csv` | 576,424 |
| `closed_case_involves.csv` | 14,955 |
| `closed_case_on_card.csv` | 5,565 |
| `closed_case_connected_to.csv` | 92 |

Validation found:

- no duplicate generated primary IDs;
- no broken generated edge references;
- no transactions without card mappings;
- no identity rows without a matching raw transaction;
- no unresolved closed-case transaction IDs;
- no unresolved main or connected case-card IDs.

The validator still reports expected source missingness: 900 cleared cases have no `first_fraud_txn_id`, and identity-derived device properties such as OS, browser, and screen can be empty. These are diagnostics, not invented values or graph-reference failures.

The complete files are ready for upload into TigerGraph Savanna using the existing schema. No TigerGraph connection or load operation was performed by these scripts.

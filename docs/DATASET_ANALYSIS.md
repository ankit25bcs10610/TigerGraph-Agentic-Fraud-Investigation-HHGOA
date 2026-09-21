# Dataset analysis

This document records the schema and relationships observed directly in the supplied CSV files. The files were inspected as data; any prose or text values inside them are not treated as instructions. No data files were changed.

## Files and purpose

| File | Observed size | Purpose |
|---|---:|---|
| `transactions.csv` | 590,742 rows, 397 columns | The complete transaction feature table. It contains the original Vesta/IEEE-CIS-style transaction fields plus the project-added customer, timestamp, channel, and risk signal fields. It contains no fraud verdict column. |
| `identity.csv` | 144,432 rows, 41 columns | Identity/device context for a subset of transactions. It joins to `transactions.csv` on `TransactionID`; every observed identity row matched an online transaction. |
| `closed_cases_history.csv` | 5,565 rows, 15 columns | Historical investigations from the closed-case period, including outcome, pattern, affected transactions, actions, report status, and analyst narrative. |
| `case_pack.csv` | 20 rows, 8 columns | The benchmark investigation cases. Each row identifies a trigger and one flagged transaction. |

The observed transaction timestamp range is `2016-07-02 00:02:21` through `2016-12-31 23:58:54`. Transaction amounts range from `$0.27` to `$31,937.38`; `risk_score` ranges from `0.01` to `0.99`.

## Actual columns

### `transactions.csv`

The exact header is 397 columns:

```text
TransactionID, TransactionDT, TransactionAmt, ProductCD,
card1, card2, card3, card4, card5, card6,
addr1, addr2, dist1, dist2, P_emaildomain, R_emaildomain,
C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12, C13, C14,
D1, D2, D3, D4, D5, D6, D7, D8, D9, D10, D11, D12, D13, D14, D15,
M1, M2, M3, M4, M5, M6, M7, M8, M9,
V1, V2, V3, V4, V5, V6, V7, V8, V9, V10, V11, V12, V13, V14, V15,
V16, V17, V18, V19, V20, V21, V22, V23, V24, V25, V26, V27, V28, V29, V30,
V31, V32, V33, V34, V35, V36, V37, V38, V39, V40, V41, V42, V43, V44, V45, V46, V47, V48, V49, V50,
V51, V52, V53, V54, V55, V56, V57, V58, V59, V60, V61, V62, V63, V64, V65, V66, V67, V68, V69, V70,
V71, V72, V73, V74, V75, V76, V77, V78, V79, V80, V81, V82, V83, V84, V85, V86, V87, V88, V89, V90,
V91, V92, V93, V94, V95, V96, V97, V98, V99, V100, V101, V102, V103, V104, V105, V106, V107, V108, V109, V110,
V111, V112, V113, V114, V115, V116, V117, V118, V119, V120, V121, V122, V123, V124, V125, V126, V127, V128, V129, V130,
V131, V132, V133, V134, V135, V136, V137, V138, V139, V140, V141, V142, V143, V144, V145, V146, V147, V148, V149, V150,
V151, V152, V153, V154, V155, V156, V157, V158, V159, V160, V161, V162, V163, V164, V165, V166, V167, V168, V169, V170,
V171, V172, V173, V174, V175, V176, V177, V178, V179, V180, V181, V182, V183, V184, V185, V186, V187, V188, V189, V190,
V191, V192, V193, V194, V195, V196, V197, V198, V199, V200, V201, V202, V203, V204, V205, V206, V207, V208, V209, V210,
V211, V212, V213, V214, V215, V216, V217, V218, V219, V220, V221, V222, V223, V224, V225, V226, V227, V228, V229, V230,
V231, V232, V233, V234, V235, V236, V237, V238, V239, V240, V241, V242, V243, V244, V245, V246, V247, V248, V249, V250,
V251, V252, V253, V254, V255, V256, V257, V258, V259, V260, V261, V262, V263, V264, V265, V266, V267, V268, V269, V270,
V271, V272, V273, V274, V275, V276, V277, V278, V279, V280, V281, V282, V283, V284, V285, V286, V287, V288, V289, V290,
V291, V292, V293, V294, V295, V296, V297, V298, V299, V300, V301, V302, V303, V304, V305, V306, V307, V308, V309, V310,
V311, V312, V313, V314, V315, V316, V317, V318, V319, V320, V321, V322, V323, V324, V325, V326, V327, V328, V329, V330,
V331, V332, V333, V334, V335, V336, V337, V338, V339,
customer_id, ts, channel, risk_score
```

The `C`, `D`, `M`, and `V` names are retained exactly as supplied. Their individual meanings are not present in the CSV and must not be inferred from the names.

### `identity.csv`

```text
TransactionID,
id_01, id_02, id_03, id_04, id_05, id_06, id_07, id_08, id_09, id_10, id_11,
id_12, id_13, id_14, id_15, id_16, id_17, id_18, id_19, id_20, id_21, id_22,
id_23, id_24, id_25, id_26, id_27, id_28, id_29, id_30, id_31, id_32, id_33,
id_34, id_35, id_36, id_37, id_38, DeviceType, DeviceInfo
```

### `closed_cases_history.csv`

```text
case_id, customer_id, card_id, opened_at, closed_at, outcome, pattern,
first_fraud_txn_id, txn_ids, n_txns, exposure_usd, connected_card_ids,
actions_taken, report_filed, analyst_notes
```

### `case_pack.csv`

```text
case_id, opened_at, trigger_type, trigger_text, flagged_txn_id, card_id,
customer_id, risk_score
```

## Primary identifiers and joins

| Identifier / relationship | Evidence from the files |
|---|---|
| Transaction primary key | `transactions.TransactionID`; 590,742 unique values and no duplicate rows observed. |
| Identity primary key | `identity.TransactionID`; 144,432 unique values and no duplicates observed. |
| Transaction-to-identity join | Exact inner join on `TransactionID`: 144,432/144,432 identity rows matched transactions, and all matched rows had `channel=online`. No identity row matched an in-person transaction. |
| Customer key | `transactions.customer_id` and the customer fields in both case files. All closed-case transaction references and all 20 case-pack flagged transactions matched the stated `customer_id`. |
| Closed case key | `closed_cases_history.case_id`; 5,565 unique values observed. Its `txn_ids` field is pipe-separated and every referenced transaction existed. `n_txns` matched the number of parsed transaction IDs for every row. |
| Benchmark case key | `case_pack.case_id`; 20 unique values, `HHG-001` through `HHG-020`. Every `flagged_txn_id` existed in transactions. |
| Card key | `card_id` occurs in `closed_cases_history.csv` and `case_pack.csv`, but no `card_id` column occurs in either transaction or identity data. A direct card join is therefore not available from the supplied headers. `card1`–`card6` are transaction fields and may be a candidate card fingerprint, but mapping them to labels such as `C12382-K1` must be established explicitly before loading. |

`TransactionID` is the only direct transaction/identity key. `customer_id` is the direct cross-file customer relationship. The case files also carry transaction references, but their `card_id` labels are not directly represented in the transaction schema.

## Missing and null considerations

Empty strings are used for missing values; there is no separate null marker in the observed CSVs.

### Transactions

The following fields were non-null for all 590,742 rows: `TransactionID`, `TransactionDT`, `TransactionAmt`, `ProductCD`, `customer_id`, `ts`, `channel`, and `risk_score`.

The remaining transaction fields do contain empty values, including card attributes, address/distance fields, email domains, and many `C*`, `D*`, `M*`, and `V*` features. Missingness should be preserved as missing, not converted to a meaningful category without an explicit convention. `risk_score` has 99 distinct observed values and is an input signal only; it is not a fraud verdict.

### Identity

Missingness is substantial and uneven. Examples from the observed 144,432 rows:

- `id_07`, `id_08`, `id_21`, `id_22`, `id_23`, `id_25`, `id_26`, and `id_27` are missing in roughly 96% of rows.
- `id_03`, `id_04`, and `id_18` are missing in roughly 54%, 54%, and 69% of rows respectively.
- `id_30`, `id_32`, `id_33`, and `id_34` are missing in roughly 46–49% of rows.
- `DeviceType` is missing in 2.37% and `DeviceInfo` in 17.71%.
- `id_15` contains `Found`, `New`, `Unknown`, and missing values; it is not a complete device-newness field.

Use source missingness as an evidence-quality signal. Do not interpret an absent identity row as a negative identity result; it means no identity record was supplied for that transaction.

### Cases

`closed_cases_history.txn_ids` and `connected_card_ids` are pipe-separated text fields and may be empty. `report_filed` is textual (`Yes`/`No` in the observed data). `analyst_notes`, `actions_taken`, and `trigger_text` are narrative or serialized-action fields and should not be treated as numeric data.

## Recommended graph model

### Graph entities / vertices

The strongest entity candidates are:

- `Transaction`, keyed by `TransactionID`.
- `Customer`, keyed by `customer_id`.
- `IdentityRecord` or `DeviceProfile`, built from an identity record and the available device fields (`DeviceType`, `DeviceInfo`, and readable identity categories). A canonical device key must be defined carefully; the raw `TransactionID` is not a device key.
- `EmailDomain`, from non-empty `P_emaildomain` and `R_emaildomain`, with role retained on the transaction edge/property.
- `BillingRegion`, from non-empty `addr1` (optionally retaining `addr2` as country code). These are anonymized codes, not geographic names.
- `ClosedCase`, keyed by `closed_cases_history.case_id`.
- `InvestigationCase` / benchmark case, keyed by `case_pack.case_id`, if the benchmark workflow is represented in the graph.
- `Card`, only after resolving the missing mapping between the case `card_id` labels and transaction card fields. Do not manufacture `C...-K...` values from memory. If a deterministic composite such as `card1`–`card6` is adopted, document and validate that key first.

`channel`, `ProductCD`, `card4`, `card6`, and `pattern` are better modeled as properties or controlled values than as entities. `C*`, `D*`, `M*`, `V*`, and opaque `id_*` fields are not entities merely because they have a column name.

### Graph properties

Recommended transaction properties include:

- Identity and time: `TransactionID`, `TransactionDT`, `ts`.
- Amount and model signal: `TransactionAmt`, `risk_score`.
- Routing/context: `ProductCD`, `channel`, `addr1`, `addr2`, `dist1`, `dist2`.
- Payment/card signals: `card1`–`card6` as raw properties until a validated card entity key exists.
- Communication signals: `P_emaildomain`, `R_emaildomain`.
- Feature signals: `C1`–`C14`, `D1`–`D15`, `M1`–`M9`, and `V1`–`V339`, retaining their exact names and nulls.

Recommended identity properties include `id_01`–`id_38`, `DeviceType`, and `DeviceInfo`, retaining the raw names and missing values. Readable values such as `id_15`, `id_23`, `id_30`, `id_31`, `id_33`, and `id_34` can be exposed as searchable properties, but their raw source values should remain available.

Recommended case properties include `case_id`, `customer_id`, `card_id` (as an unresolved source label until mapped), `opened_at`, `closed_at`, `outcome`, `pattern`, `first_fraud_txn_id`, `n_txns`, `exposure_usd`, `report_filed`, and parsed action values from `actions_taken`.

Useful edges are `Customer -> Transaction`, `Transaction -> IdentityRecord/DeviceProfile`, `Transaction -> EmailDomain` with purchaser/recipient role, `Transaction -> BillingRegion`, `ClosedCase -> Transaction`, and benchmark case -> flagged transaction. A temporal `NEXT` edge between transactions can be derived only after choosing the ordering scope, normally within a validated card/customer scope.

### Text and vector data

Keep these as text for full-text/vector retrieval rather than flattening them into graph properties:

- `closed_cases_history.analyst_notes`.
- `case_pack.trigger_text`.
- The original `actions_taken` string, in addition to parsed action tokens.
- Any future investigation narrative, evidence request, or regulatory/policy documents supplied outside these CSVs.

The structured case fields should remain graph properties for filtering and joins, while the narratives should remain retrievable text. The opaque feature columns can be supplied as numeric/categorical evidence to a model, but their names do not justify semantic prose in a vector index.

## Inconsistencies and missing information

1. `card_id` is present in the historical and benchmark case files but absent from the actual transaction and identity headers. There is no direct supplied join from case card labels to transaction card fields.
2. The transaction table has 397 columns rather than a small fraud-specific schema; the 339 `V*` fields and the `C*`, `D*`, and `M*` fields are present but individually unnamed semantically. Their meanings must not be invented.
3. Identity coverage is intentionally partial: 144,432 of 590,742 transactions have identity rows, and those rows are online-only. Missing identity fields are common even within identity rows.
4. `risk_score` is present and complete in transactions, but it is only a model input signal. It must not be loaded or presented as an outcome/fraud label.
5. No public fraud label is present in the inspected transaction file. Historical outcomes are available only through `closed_cases_history.outcome`; the case pack has no outcome column.
6. `connected_card_ids` contains 92 non-empty card references across the closed cases, but those labels also have no direct transaction-table key.

## Final inspection summary

- Actual files: four; actual row counts: 590,742 transactions, 144,432 identity rows, 5,565 closed cases, and 20 benchmark cases.
- Actual direct join: `transactions.TransactionID = identity.TransactionID`.
- Actual case joins: closed-case `txn_ids` and case-pack `flagged_txn_id` to `transactions.TransactionID`; `customer_id` is consistent on every checked referenced transaction.
- Potential graph entities: Customer, Transaction, IdentityRecord/DeviceProfile, EmailDomain, BillingRegion, ClosedCase, InvestigationCase, and a Card entity only after explicit card-key mapping.
- Key missing information: a direct transaction-to-`card_id` mapping, semantic definitions for opaque V/C/D/M/id features, and benchmark outcomes for the 20 case-pack cases.
